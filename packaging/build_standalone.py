"""按明确发布版本构建、启动自检并归档跨平台 PyInstaller 包。"""

from __future__ import annotations

import argparse
import hashlib
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
PLATFORM_TAGS = {
    "windows-x64": ("win32", "x64"),
    "linux-x64": ("linux", "x64"),
    "macos-x64": ("darwin", "x64"),
    "macos-arm64": ("darwin", "arm64"),
}
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
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=normal"], cwd=root
    )
    if dirty or commit == "unknown" or commit.endswith("-dirty"):
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


def sha256(path):
    with path.open("rb") as contents:
        return hashlib.file_digest(contents, "sha256").hexdigest()


def validate_smoke_report(result, info, executable_sha256):
    if result.get("status") != "ok":
        raise RuntimeError(f"独立包启动自检报告无效：{result}")
    for field in (
        "bundle_version",
        "source_commit",
        "entrypoint_sha256",
        "module_sha256",
    ):
        if result.get(field) != info[field]:
            raise RuntimeError(f"独立包启动自检的 {field} 与构建记录不一致。")
    if result.get("executable_sha256") != executable_sha256:
        raise RuntimeError("独立包实际运行的可执行文件与构建产物的 SHA-256 不一致。")


def smoke_test(executable, info, executable_sha256, work):
    with tempfile.TemporaryDirectory(prefix="smoke-", dir=work) as directory:
        report = Path(directory) / "smoke-report.json"
        env = os.environ.copy()
        env.update(
            STROOP_EFFICACY_DATA_DIR=str(Path(directory) / "sessions"),
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
        if completed.returncode != 0 or not report.is_file():
            raise RuntimeError(
                "独立包启动自检失败。\n"
                f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )
        result = json.loads(report.read_text(encoding="utf-8"))
    validate_smoke_report(result, info, executable_sha256)
    return result


def copy_readme(root, staging, version):
    template = (root / "packaging" / "standalone-README.txt").read_text(
        encoding="utf-8"
    )
    (staging / "START-HERE.txt").write_text(
        template.replace("{{VERSION}}", version), encoding="utf-8"
    )


def archive_package(staging, output, platform_tag):
    if platform_tag.startswith("linux"):
        with tarfile.open(output, "w:gz") as archive:
            archive.add(staging, arcname=staging.name)
    elif platform_tag.startswith("macos"):
        subprocess.run(
            ["zip", "-qry", str(output), staging.name],
            cwd=staging.parent,
            check=True,
        )
    else:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(staging.parent))


def extract_package(artifact, destination, platform_tag):
    if platform_tag.startswith("linux"):
        with tarfile.open(artifact, "r:gz") as archive:
            archive.extractall(destination, filter="data")
    elif platform_tag.startswith("macos"):
        subprocess.run(
            ["unzip", "-q", str(artifact), "-d", str(destination)], check=True
        )
    else:
        with zipfile.ZipFile(artifact) as archive:
            archive.extractall(destination)


def symlink_targets(directory):
    return {
        path.relative_to(directory): path.readlink()
        for path in directory.rglob("*")
        if path.is_symlink()
    }


def build(version, platform_tag, root=ROOT, output_root=None):
    version = release_version(f"standalone-v{version}")
    if platform_tag not in PLATFORM_TAGS:
        raise ValueError(f"不支持的目标平台：{platform_tag}")
    machine = platform.machine().lower()
    arch = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(machine, machine)
    if (sys.platform, arch) != PLATFORM_TAGS[platform_tag]:
        raise ValueError(
            f"{platform_tag} 需要对应平台的构建环境，当前为 {sys.platform}/{machine}。"
        )

    root = Path(root).resolve()
    output_root = (
        root / "dist" if output_root is None else Path(output_root)
    ).resolve()
    package = (output_root / "package").resolve()
    if not package.is_relative_to(output_root):
        raise ValueError(f"发布文件目录超出构建输出目录：{package}")
    info = build_info(root, version)
    suffix = ".tar.gz" if platform_tag.startswith("linux") else ".zip"
    artifact = package / f"{APP_NAME}-{version}-{platform_tag}{suffix}"

    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="standalone-", dir=output_root
    ) as directory:
        work = Path(directory)
        dist = work / "pyinstaller-dist"
        dist.mkdir()
        info_path = work / "build-info.json"
        info_path.write_text(
            json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        run_pyinstaller(root, work, dist, info_path)
        executable = executable_path(dist)
        if not executable.is_file():
            raise RuntimeError(f"PyInstaller 未生成预期程序：{executable}")
        executable_sha256 = sha256(executable)
        smoke = smoke_test(executable, info, executable_sha256, work)

        staging = work / "staging" / APP_NAME
        bundle = f"{APP_NAME}.app" if sys.platform == "darwin" else APP_NAME
        shutil.copytree(dist / bundle, staging / bundle, symlinks=True)
        copy_readme(root, staging, version)
        shutil.copy2(info_path, staging / "build-info.json")
        (staging / "smoke-test.json").write_text(
            json.dumps(smoke, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        candidate = work / artifact.name
        archive_package(staging, candidate, platform_tag)
        restored = work / "extracted"
        extract_package(candidate, restored, platform_tag)
        extracted = restored / APP_NAME
        if symlink_targets(dist / bundle) != symlink_targets(extracted / bundle):
            raise RuntimeError("解压后的程序包与构建产物的符号链接不一致。")
        smoke_test(executable_path(extracted), info, executable_sha256, work)

        digest = sha256(candidate)
        checksum = candidate.with_name(candidate.name + ".sha256")
        checksum.write_text(f"{digest}  {artifact.name}\n", encoding="ascii")
        package.mkdir(parents=True, exist_ok=True)
        candidate.replace(artifact)
        checksum.replace(package / checksum.name)

    print(json.dumps({"artifact": str(artifact), "sha256": digest}, ensure_ascii=False))
    return artifact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="standalone-vX.Y.Z 形式的发布标签")
    parser.add_argument("--version", help="已确定的 X.Y.Z 发布版本号")
    parser.add_argument("--platform-tag", choices=PLATFORM_TAGS)
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
