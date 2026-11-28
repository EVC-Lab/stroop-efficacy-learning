"""按明确发布版本构建、启动自检并归档跨平台 PyInstaller 包。"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


APP_NAME = "StroopEfficacyLearning"
RELEASE_PATTERN = re.compile(
    r"standalone-v(?P<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)"
)
ROOT = Path(__file__).resolve().parents[1]


def release_version(tag):
    """只接受独立版发布标签，返回不带标签前缀的版本号。"""
    match = RELEASE_PATTERN.fullmatch(tag)
    if match is None:
        raise ValueError(
            f"发布标签必须是 standalone-vX.Y.Z 或 standalone-vX.Y.Z-rc.N：{tag}"
        )
    return match["version"]


def executable_path(dist_root):
    if sys.platform == "darwin":
        return dist_root / f"{APP_NAME}.app" / "Contents" / "MacOS" / APP_NAME
    suffix = ".exe" if sys.platform == "win32" else ""
    return dist_root / APP_NAME / f"{APP_NAME}{suffix}"


def build_info(root, version):
    sys.path.insert(0, str(root))
    from stroop_efficacy.session_data import code_version

    commit, entry_hash, module_hashes = code_version(root / "run.py")
    if commit == "unknown" or commit.endswith("-dirty"):
        raise RuntimeError("发布构建必须来自干净且可识别的 Git 提交。")
    return {
        "schema_version": 1,
        "bundle_version": version,
        "source_commit": commit,
        "entrypoint_sha256": entry_hash,
        "module_sha256": module_hashes,
        "python_version": platform.python_version(),
        "psychopy_version": importlib.metadata.version("psychopy"),
        "pyinstaller_version": importlib.metadata.version("pyinstaller"),
        "target_platform": sys.platform,
        "target_machine": platform.machine(),
        "built_at": datetime.now(timezone.utc).isoformat(),
    }


def run_pyinstaller(root, work, dist, info_path):
    import PyInstaller.__main__

    PyInstaller.__main__.run(
        [
            str(root / "run.py"),
            "--name",
            APP_NAME,
            "--onedir",
            "--windowed",
            "--clean",
            "--noconfirm",
            "--distpath",
            str(dist),
            "--workpath",
            str(work / "pyinstaller"),
            "--specpath",
            str(work),
            "--add-data",
            f"{info_path}{os.pathsep}.",
            "--collect-all",
            "psychopy",
            "--collect-all",
            "psychtoolbox",
            "--copy-metadata",
            "psychopy",
            "--copy-metadata",
            "psychtoolbox",
        ]
    )


def smoke_test(executable, version, work):
    report = work / "smoke-report.json"
    with tempfile.TemporaryDirectory(prefix="standalone-data-", dir=work) as data:
        env = os.environ.copy()
        env.update(
            STROOP_EFFICACY_DATA_DIR=str(Path(data) / "sessions"),
            STROOP_EFFICACY_SMOKE_REPORT=str(report),
        )
        if sys.platform.startswith("linux"):
            env["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [str(executable), "--standalone-smoke-test"],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )
    if completed.returncode != 0:
        raise RuntimeError(
            "独立包启动自检失败。\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    result = json.loads(report.read_text(encoding="utf-8"))
    if result.get("status") != "ok" or result.get("bundle_version") != version:
        raise RuntimeError(f"独立包启动自检报告无效：{result}")
    return result


def copy_readme(root, staging, version):
    template = (root / "packaging" / "standalone-README.txt").read_text(
        encoding="utf-8"
    )
    (staging / "START-HERE.txt").write_text(
        template.replace("{{VERSION}}", version), encoding="utf-8"
    )


def archive_package(staging, output, platform_tag):
    output.parent.mkdir(parents=True, exist_ok=True)
    if platform_tag.startswith("linux"):
        with tarfile.open(output, "w:gz") as archive:
            archive.add(staging, arcname=staging.name)
    else:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(staging.parent))
    return output


def build(version, platform_tag, root=ROOT, output_root=None):
    output_root = root / "dist" if output_root is None else Path(output_root)
    work = output_root / "work" / platform_tag
    dist = output_root / "pyinstaller" / platform_tag
    package = output_root / "package"
    if output_root.exists():
        shutil.rmtree(output_root)
    work.mkdir(parents=True)
    dist.mkdir(parents=True)

    info = build_info(root, version)
    info_path = work / "build-info.json"
    info_path.write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    run_pyinstaller(root, work, dist, info_path)
    executable = executable_path(dist)
    if not executable.is_file():
        raise RuntimeError(f"PyInstaller 未生成预期程序：{executable}")
    smoke = smoke_test(executable, version, work)

    staging = package / APP_NAME
    staging.mkdir(parents=True)
    if sys.platform == "darwin":
        shutil.copytree(dist / f"{APP_NAME}.app", staging / f"{APP_NAME}.app")
    else:
        shutil.copytree(dist / APP_NAME, staging / APP_NAME)
    copy_readme(root, staging, version)
    shutil.copy2(info_path, staging / "build-info.json")
    (staging / "smoke-test.json").write_text(
        json.dumps(smoke, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    suffix = ".tar.gz" if platform_tag.startswith("linux") else ".zip"
    artifact = package / f"{APP_NAME}-{version}-{platform_tag}{suffix}"
    archive_package(staging, artifact, platform_tag)
    digest = __import__("hashlib").sha256(artifact.read_bytes()).hexdigest()
    checksum = artifact.with_name(artifact.name + ".sha256")
    checksum.write_text(f"{digest}  {artifact.name}\n", encoding="ascii")
    print(json.dumps({"artifact": str(artifact), "sha256": digest}, ensure_ascii=False))
    return artifact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="standalone-vX.Y.Z 形式的发布标签")
    parser.add_argument("--version", help="已确定的 X.Y.Z 发布版本号")
    parser.add_argument("--platform-tag", help="例如 windows-x64、macos-arm64")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument(
        "--validate-tag", action="store_true", help="只验证标签，不安装或构建"
    )
    args = parser.parse_args()
    if args.tag:
        version = release_version(args.tag)
        if args.version and args.version != version:
            parser.error("--version 与 --tag 中的版本不一致。")
    elif args.version:
        version = release_version(f"standalone-v{args.version}")
    else:
        parser.error("必须提供 --tag 或 --version，拒绝构建无版本程序包。")
    if args.validate_tag:
        print(version)
        return
    if not args.platform_tag:
        parser.error("实际构建必须提供 --platform-tag。")
    build(version, args.platform_tag, output_root=args.output_root)


if __name__ == "__main__":
    main()
