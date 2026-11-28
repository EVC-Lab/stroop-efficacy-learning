"""从 PsychoPy Studio 启动色词 Stroop 行为任务。"""

import traceback
from contextlib import ExitStack
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from tempfile import TemporaryFile

from stroop_efficacy.device_check import check_devices
from stroop_efficacy.experiment import SessionInterrupted, StroopEfficacyExp
from stroop_efficacy.timing import open_timed_keyboard
from ui.operator import run_operator_panel

ENTRYPOINT = Path(__file__).resolve()


@dataclass(frozen=True)
class SessionResult:
    status: str
    path: Path | None = None
    detail: str = ""
    save_failed: bool = False


def run_registered(info, mode, archive_root, keyboard):
    """运行一场实验，收回设备并返回任务结果。"""
    exp = None
    detail = ""
    save_failed = False
    try:
        with ExitStack() as cleanup:
            cleanup.callback(keyboard.stop)
            exp = StroopEfficacyExp(
                info,
                keyboard=keyboard,
                entrypoint=ENTRYPOINT,
                mode=mode,
                archive_root=archive_root,
            )
            cleanup.callback(exp.win.close)
            exp.run()
    except SessionInterrupted:
        pass
    except (Exception, KeyboardInterrupt) as exc:
        traceback.print_exc()
        detail = f"{type(exc).__name__}：{exc}"
        if exp is None:
            return SessionResult("startup_failed", detail=f"无法启动实验窗口。{detail}")
        try:
            exp.finish("error")
        except (Exception, KeyboardInterrupt):
            save_failed = True
            traceback.print_exc()
        if exp.outdir is not None:
            try:
                log = "".join(traceback.format_exception(exc))
                (exp.outdir / "error.log").write_text(log, encoding="utf-8")
            except OSError:
                traceback.print_exc()
    return SessionResult(
        "error" if detail else exp.session_status, exp.outdir, detail, save_failed
    )


def start_session(info, mode, archive_root):
    destination = archive_root / mode / info["被试编号"]
    try:
        destination.mkdir(parents=True, exist_ok=True)
        with TemporaryFile(dir=destination) as probe:
            probe.write(b"ok")
            probe.flush()
    except OSError as exc:
        return SessionResult(
            "startup_failed",
            detail=f"保存位置不可写。请检查磁盘空间和目录权限后重试。\n{destination}\n{exc}",
        )
    try:
        keyboard = open_timed_keyboard()
    except (ImportError, OSError, RuntimeError) as exc:
        return SessionResult(
            "startup_failed",
            detail=f"无法初始化 PTB 键盘。请检查 PsychoPy Studio 环境后重试。\n{exc}",
        )
    return run_registered(info, mode, archive_root, keyboard)


def launch_experiment():
    """保持实验员窗口开启，直至实验员关闭。"""
    from stroop_efficacy.runtime import default_archive_root, display_version

    root = default_archive_root()
    run_operator_panel(
        root,
        start_session=partial(start_session, archive_root=root),
        check_devices=check_devices,
        version=display_version(ENTRYPOINT),
    )


def main():
    import sys

    if "--standalone-smoke-test" in sys.argv:
        from stroop_efficacy.runtime import standalone_smoke_test

        standalone_smoke_test()
        return
    launch_experiment()


if __name__ == "__main__":
    main()
