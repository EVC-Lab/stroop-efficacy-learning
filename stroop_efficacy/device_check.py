"""在不创建场次的情况下检查全屏中文和响应键。"""

from contextlib import ExitStack

from psychopy import core, visual

from .design import run_settings
from .experiment import open_task_window
from .timing import TimedInput, open_timed_keyboard


def check_devices():
    settings = run_settings("formal")
    keys = tuple(settings["KEYS"].values())
    seen = set()
    with ExitStack() as cleanup:
        keyboard = open_timed_keyboard()
        cleanup.callback(keyboard.stop)
        window = open_task_window(settings)
        cleanup.callback(window.close)
        window.setMouseVisible(False)
        keyboard.start()
        keyboard.clearEvents()
        timed_input = TimedInput(keyboard)
        message = visual.TextStim(
            window, font=settings["FONT"], height=0.043, wrapWidth=1.15, autoLog=False
        )
        deadline = core.getTime() + 60
        while core.getTime() < deadline:
            missing = "  ".join(key.upper() for key in keys if key not in seen)
            if missing:
                instructions = f"请按以下响应键  {missing}"
            else:
                instructions = "响应键均已收到。中文清晰时按空格确认。"
            text = (
                f"设备检查\n\n中文样字  红  绿  蓝  黄\n\n{instructions}\n\n按 Esc 返回"
            )
            if message.text != text:
                message.text = text
            message.draw()
            window.flip()

            for press in timed_input.poll_keys([*keys, "space", "escape"]):
                if press.name == "escape":
                    return "设备检查已取消。"
                if press.name == "space" and not missing:
                    return "设备检查通过。四个响应键已收到，中文显示已确认。"
                if press.name in keys:
                    seen.add(press.name)
        return "设备检查已超时。请检查显示和键盘后重试。"
