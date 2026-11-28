"""从 PsychoPy Studio 启动色词 Stroop 行为任务。"""

import traceback
from pathlib import Path

from psychopy import gui

from stroop_efficacy.experiment import StroopEfficacyExp
from stroop_efficacy.timing import open_timed_keyboard
from ui.operator import ask_registration, show_session_result

ENTRYPOINT = Path(__file__).resolve()


def run_registered(info, mode, archive_root, keyboard):
    """从已确认的登记运行一场，退出全屏后显示保存结果。"""
    exp = None
    save_failed = False
    error = None
    try:
        exp = StroopEfficacyExp(
            info,
            keyboard=keyboard,
            entrypoint=ENTRYPOINT,
            mode=mode,
            archive_root=archive_root,
        )
        exp.run()
    except SystemExit:
        pass
    except (Exception, KeyboardInterrupt) as exc:
        error = exc
        if exp is not None:
            try:
                exp.finish("error")
            except (Exception, KeyboardInterrupt):
                save_failed = True
                traceback.print_exc()
        if exp is not None and exp.outdir is not None:
            try:
                log = "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                )
                (exp.outdir / "error.log").write_text(log, encoding="utf-8")
            except OSError:
                traceback.print_exc()
    finally:
        keyboard.stop()
        if exp is not None:
            exp.win.close()
    show_session_result(
        exp.outdir if exp is not None else None,
        exp.subj if exp is not None else info["被试编号"],
        mode,
        save_failed,
    )
    if error is not None:
        raise error


def launch_experiment():
    """打开实验员登记页并启动已确认的场次。"""
    root = ENTRYPOINT.parent / "data"
    registration = ask_registration(root)
    if registration is None:
        return
    try:
        keyboard = open_timed_keyboard()
    except (ImportError, OSError, RuntimeError) as exc:
        dialog = gui.Dlg(title="无法初始化实验键盘")
        dialog.addText("请在 PsychoPy Studio 中检查 Psychtoolbox 键盘后端。")
        dialog.addText(str(exc))
        dialog.show()
        return
    info, mode = registration
    run_registered(info, mode, root, keyboard)


if __name__ == "__main__":
    launch_experiment()
