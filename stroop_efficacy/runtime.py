"""独立程序包的数据目录、构建信息和启动自检。"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryFile


DATA_DIR_ENV = "STROOP_EFFICACY_DATA_DIR"
SMOKE_REPORT_ENV = "STROOP_EFFICACY_SMOKE_REPORT"
BUILD_INFO_NAME = "build-info.json"
SOURCE_ROOT = Path(__file__).resolve().parent.parent


def is_frozen():
    """区分 PyInstaller 独立包与源码／Studio 运行。"""
    return bool(getattr(sys, "frozen", False))


def bundle_root():
    """PyInstaller 解包资源目录；源码模式返回仓库根目录。"""
    return Path(getattr(sys, "_MEIPASS", SOURCE_ROOT)).resolve()


def executable_root():
    """程序所在目录，不用来保存独立版的会话数据。"""
    if not is_frozen():
        return SOURCE_ROOT
    executable = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        for directory in executable.parents:
            if directory.suffix.lower() == ".app":
                return directory
    return executable.parent


def bundled_build_info(required=False):
    """读取构建时嵌入的版本记录，源码模式没有该记录。"""
    if not is_frozen():
        return None
    path = bundle_root() / BUILD_INFO_NAME
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
        for key in (
            "bundle_version",
            "source_commit",
            "entrypoint_sha256",
            "module_sha256",
        ):
            if not info[key]:
                raise ValueError(f"构建信息缺少 {key}")
        if not isinstance(info["module_sha256"], dict):
            raise TypeError("module_sha256 必须是对象")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        if required:
            raise RuntimeError(f"独立版构建信息无效：{path}\n{exc}") from exc
        return None
    return info


def default_archive_root(
    *, environ=None, frozen=None, platform=None, home=None, source_root=None
):
    """返回持久数据目录；显式环境变量优先，便于采集机统一管理。"""
    frozen = is_frozen() if frozen is None else frozen
    if not frozen:
        root = SOURCE_ROOT if source_root is None else Path(source_root)
        return root / "data"

    env = os.environ if environ is None else environ
    override = env.get(DATA_DIR_ENV, "").strip()
    platform = sys.platform if platform is None else platform
    home = Path.home() if home is None else Path(home)
    if override:
        root = Path(override).expanduser()
    elif platform == "win32":
        base = (
            Path(env["LOCALAPPDATA"])
            if env.get("LOCALAPPDATA")
            else home / "AppData" / "Local"
        )
        root = base / "EVC-Lab" / "StroopEfficacyLearning" / "data"
    elif platform == "darwin":
        root = (
            home
            / "Library"
            / "Application Support"
            / "EVC-Lab"
            / "StroopEfficacyLearning"
            / "data"
        )
    else:
        base = (
            Path(env["XDG_DATA_HOME"])
            if env.get("XDG_DATA_HOME")
            else home / ".local" / "share"
        )
        root = base / "EVC-Lab" / "stroop-efficacy-learning" / "data"

    root = root.resolve()
    if root.is_relative_to(executable_root()):
        raise RuntimeError(f"数据目录不能位于程序目录内：{root}")
    return root


def display_version(entrypoint):
    """登记页同时显示发布版本和源码提交，Studio 仍沿用源码摘要。"""
    info = bundled_build_info()
    if info is not None:
        return f"独立版 {info['bundle_version']} · {info['source_commit'][:12]}"
    from .session_data import code_version

    commit, entry_hash, _ = code_version(entrypoint)
    return commit if commit != "unknown" else f"入口 SHA-256 {entry_hash[:12]}"


def standalone_smoke_test(report_path=None):
    """在不打开实验窗口的情况下验证独立包、版本记录和数据目录。"""
    result = {"status": "failed"}
    try:
        if not is_frozen():
            raise RuntimeError("启动自检只适用于 PyInstaller 独立包。")
        info = bundled_build_info(required=True)
        with Path(sys.executable).open("rb") as executable:
            executable_sha256 = hashlib.file_digest(executable, "sha256").hexdigest()
        root = default_archive_root()
        root.mkdir(parents=True, exist_ok=True)
        with TemporaryFile(dir=root) as probe:
            probe.write(b"standalone-smoke-test")
            probe.flush()
        result = {
            "status": "ok",
            "bundle_version": info["bundle_version"],
            "source_commit": info["source_commit"],
            "entrypoint_sha256": info["entrypoint_sha256"],
            "module_sha256": info["module_sha256"],
            "executable_sha256": executable_sha256,
            "archive_root": str(root),
            "psychopy_version": info.get("psychopy_version", "unknown"),
        }
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    destination = report_path or os.environ.get(SMOKE_REPORT_ENV)
    if destination:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if result["status"] != "ok":
        raise RuntimeError(result["error"])
    return result
