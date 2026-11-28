"""独立版路径、发布标签、冻结版本信息和启动自检的纯逻辑测试。"""

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stroop_efficacy import runtime, session_data  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_standalone", ROOT / "packaging" / "build_standalone.py"
)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def check_release_versions():
    assert builder.release_version("standalone-v1.2.3") == "1.2.3"
    assert builder.release_version("standalone-v1.2.3-rc.1") == "1.2.3-rc.1"
    for invalid in (
        "v1.2.3",
        "standalone-v1.2",
        "standalone-v1.2.3+local",
        "main",
        "standalone-v1.2.3/extra",
    ):
        try:
            builder.release_version(invalid)
        except ValueError:
            continue
        raise AssertionError(f"接受了无有效发布版本的标签：{invalid}")


def check_archive_paths(root):
    source = runtime.default_archive_root(
        environ={runtime.DATA_DIR_ENV: str(root / "override")},
        frozen=False,
        source_root=root / "source",
    )
    assert source == root / "source" / "data"
    override = runtime.default_archive_root(
        environ={runtime.DATA_DIR_ENV: str(root / "override")},
        frozen=True,
        platform="win32",
        home=root / "home",
    )
    assert override == (root / "override").resolve()
    windows = runtime.default_archive_root(
        environ={"LOCALAPPDATA": str(root / "local-app-data")},
        frozen=True,
        platform="win32",
        home=root / "home",
    )
    assert windows == (
        root / "local-app-data" / "EVC-Lab" / "StroopEfficacyLearning" / "data"
    )
    mac = runtime.default_archive_root(
        environ={}, frozen=True, platform="darwin", home=root / "home"
    )
    assert mac == (
        root
        / "home"
        / "Library"
        / "Application Support"
        / "EVC-Lab"
        / "StroopEfficacyLearning"
        / "data"
    )
    linux = runtime.default_archive_root(
        environ={"XDG_DATA_HOME": str(root / "xdg")},
        frozen=True,
        platform="linux",
        home=root / "home",
    )
    assert linux == root / "xdg" / "EVC-Lab" / "stroop-efficacy-learning" / "data"


def check_macos_bundle_boundary(root):
    app = root / "StroopEfficacyLearning.app"
    executable = app / "Contents" / "MacOS" / "StroopEfficacyLearning"
    patches = frozen(app / "Contents" / "Frameworks", executable)
    with (
        patches[0],
        patches[1],
        patches[2],
        patch.object(runtime.sys, "platform", "darwin"),
    ):
        assert runtime.executable_root() == app.resolve()
        for subfolder in ("MacOS", "Resources", "Frameworks"):
            try:
                runtime.default_archive_root(
                    environ={
                        runtime.DATA_DIR_ENV: str(
                            app / "Contents" / subfolder / "sessions"
                        )
                    }
                )
            except RuntimeError:
                continue
            raise AssertionError(f"允许在 app 内保存数据：{subfolder}")


def write_build_info(directory, version="1.2.3"):
    info = {
        "bundle_version": version,
        "source_commit": "a" * 40,
        "entrypoint_sha256": "b" * 64,
        "module_sha256": {"stroop_efficacy/runtime.py": "c" * 64},
        "psychopy_version": "2026.2.5",
    }
    directory.mkdir(parents=True, exist_ok=True)
    (directory / runtime.BUILD_INFO_NAME).write_text(json.dumps(info), encoding="utf-8")
    return info


def frozen(bundle, executable):
    return (
        patch.object(runtime.sys, "frozen", True, create=True),
        patch.object(runtime.sys, "_MEIPASS", str(bundle), create=True),
        patch.object(runtime.sys, "executable", str(executable)),
    )


def check_frozen_metadata(root):
    bundle = root / "bundle"
    info = write_build_info(bundle)
    patches = frozen(bundle, root / "program" / "StroopEfficacyLearning.exe")
    with patches[0], patches[1], patches[2]:
        assert runtime.bundled_build_info(required=True) == info
        assert session_data.code_version(root / "missing.py") == (
            info["source_commit"],
            info["entrypoint_sha256"],
            info["module_sha256"],
        )
        version = runtime.display_version(root / "missing.py")
        assert "1.2.3" in version and info["source_commit"][:12] in version


def check_smoke_test(root):
    bundle = root / "bundle"
    info = write_build_info(bundle, version="2.0.0-rc.1")
    report = root / "reports" / "smoke.json"
    data = root / "persistent" / "sessions"
    executable = root / "program" / "StroopEfficacyLearning"
    executable.parent.mkdir()
    payload = b"frozen executable fixture"
    executable.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()
    patches = frozen(bundle, executable)
    env = {
        runtime.DATA_DIR_ENV: str(data),
        runtime.SMOKE_REPORT_ENV: str(report),
    }
    with patches[0], patches[1], patches[2], patch.dict(os.environ, env, clear=False):
        result = runtime.standalone_smoke_test()
        builder.validate_smoke_report(result, info, expected)
        executable.write_bytes(payload + b"modified")
        tampered = runtime.standalone_smoke_test(
            report_path=report.parent / "tampered.json"
        )
        try:
            builder.validate_smoke_report(tampered, info, expected)
        except RuntimeError as exc:
            assert "SHA-256" in str(exc)
        else:
            raise AssertionError("可执行文件内容不匹配时仍通过构建自检。")
    assert result["status"] == "ok"
    assert result["bundle_version"] == "2.0.0-rc.1"
    assert Path(result["archive_root"]) == data.resolve()
    assert json.loads(report.read_text(encoding="utf-8")) == result
    assert data.is_dir()


def check_missing_info(root):
    patches = frozen(root / "empty", root / "program" / "app")
    with patches[0], patches[1], patches[2]:
        try:
            runtime.bundled_build_info(required=True)
        except RuntimeError:
            return
    raise AssertionError("独立包缺少构建信息时没有报错。")


def check_invalid_platform(root):
    output = root / "output"
    try:
        builder.build("1.2.3", "unsupported-platform", root=root, output_root=output)
    except ValueError:
        assert not output.exists()
        return
    raise AssertionError("未经支持的平台可以创建构建输出。")


def main():
    check_release_versions()
    with TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        check_archive_paths(root)
        check_macos_bundle_boundary(root)
        check_invalid_platform(root)
        check_frozen_metadata(root)
        check_smoke_test(root)
        check_missing_info(root)
    print("Standalone release metadata, paths, and smoke checks passed.")


if __name__ == "__main__":
    main()
