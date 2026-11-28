"""PTB 键盘队列、共用时钟上的作答判定与显示帧长估计。"""

import math

from psychopy import core
from psychopy import logging as psylog
from psychopy.hardware.keyboard import Keyboard


def open_timed_keyboard():
    # 实验窗口就绪后再启动队列。区段内持续监听。
    keyboard = Keyboard(backend="ptb", waitForStart=True)
    if keyboard.getBackend() != "ptb":
        raise RuntimeError(
            "请用 PsychoPy Studio 的 Python 环境运行，并确认 Psychtoolbox 键盘后端可用。"
        )
    return keyboard


def resolve_frame_timing(measured_hz, monitor_period):
    """过滤明显异常的测量值，避免把异常帧长用于末题判断。"""
    min_hz, max_hz = 30.0, 1000.0
    if measured_hz is not None and min_hz <= measured_hz <= max_hz:
        hz = float(measured_hz)
        return hz, 1.0 / hz
    if monitor_period is not None and 1.0 / max_hz <= monitor_period <= 1.0 / min_hz:
        return None, float(monitor_period)
    return None, 1.0 / 60.0


class TimedInput:
    def __init__(self, keyboard):
        self.keyboard = keyboard
        self.last_key_down = {}

    def poll_keys(self, key_list):
        # PTB 的按下和已释放事件都要读取。一次按键只处理一次。
        presses = self.keyboard.getKeys(keyList=key_list, waitRelease=False)
        presses += self.keyboard.getKeys(keyList=key_list, waitRelease=True)
        keys = []
        for key in sorted(presses, key=lambda press: press.tDown):
            if key.tDown > self.last_key_down.get(key.name, -math.inf):
                self.last_key_down[key.name] = key.tDown
                keys.append(key)
        return keys

    def wait_for_ui_key(self, onset, names):
        key_list = [*names, "escape"]
        while True:
            keys = self.poll_keys(key_list)
            if any(key.name == "escape" for key in keys):
                return "escape"
            for key in keys:
                if key.tDown >= onset:
                    return key.name
            core.wait(0.010, hogCPUperiod=0.001)

    def wait_until_or_escape(self, timestamp):
        """等到指定时刻，期间收到 Esc 时返回其按下时间。"""
        while True:
            # 清掉非作答阶段的普通按键，并保留 Esc 的时刻。
            for press in self.poll_keys(None):
                if press.name == "escape":
                    return press.tDown
            remaining = timestamp - psylog.defaultClock.getTime()
            if remaining <= 0:
                return None
            core.wait(min(remaining, 0.010), hogCPUperiod=0.001)

    def wait_for_response(self, key_list, onset, deadline):
        """返回响应键、按下时刻和 Esc 时刻。判分使用 PTB 时间戳。"""
        while True:
            poll_time = psylog.defaultClock.getTime()
            keys = self.poll_keys(key_list)
            escape_at = next(
                (press.tDown for press in keys if press.name == "escape"), None
            )
            response_end = deadline if escape_at is None else min(deadline, escape_at)
            for press in keys:
                if press.name != "escape" and onset <= press.tDown < response_end:
                    return press.name, press.tDown, escape_at
            if escape_at is not None or poll_time >= deadline:
                return "", None, escape_at
            # 截止后再读一次队列。短等待留出休眠时间，保持翻屏与按键时钟一致。
            remaining = min(poll_time + 0.005, deadline) - psylog.defaultClock.getTime()
            if remaining > 0:
                core.wait(remaining, hogCPUperiod=0.001)
