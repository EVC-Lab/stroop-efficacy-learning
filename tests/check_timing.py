
"""Check interval timing with a virtual clock or a real PsychoPy Studio window.

Usage: python tests/check_timing.py [--studio | --ptb-keyboard] [--fullscreen] [--isi 0.25]
Simulated keypresses use the task's normal event and timing logic. With --studio,
flip times come from PsychoPy; the test does not measure physical display latency.
"""

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stroop_efficacy_learning as task
from stroop_efficacy import session_data


class VirtualClock:
    frame_period = 1 / 60

    def __init__(self):
        self.now = 0.0

    def getTime(self):
        return self.now

    def wait(self, seconds, **_):
        self.now += seconds

    def flip(self):
        # Compare against the frame timestamp as division can round down at a boundary.
        frame = math.floor(self.now / self.frame_period)
        timestamp = frame * self.frame_period
        while timestamp <= self.now:
            frame += 1
            timestamp = frame * self.frame_period
        self.now = timestamp
        return timestamp


class VirtualStim:
    def __init__(self, _window, text="", **settings):
        self.text = text
        self.__dict__.update(settings)

    def draw(self):
        pass

    def setColor(self, color):
        self.color = color


class ScriptedKeyboard:
    def __init__(self, now):
        self.now = now
        self.pending = []

    def getBackend(self):
        return "ptb"

    def start(self):
        pass

    def stop(self):
        pass

    def clearEvents(self):
        self.pending.clear()

    def getKeys(self, keyList=None, waitRelease=False):
        ready = [
            key for key, available_at in self.pending
            if available_at <= self.now() and (not keyList or key.name in keyList)
            and key.released == waitRelease
        ]
        self.pending = [(key, at) for key, at in self.pending if key not in ready]
        return ready

    def queue(self, name, timestamp, available_at=None, released=False):
        if available_at is None:
            available_at = timestamp
        self.pending.append((SimpleNamespace(name=name, tDown=timestamp, released=released), available_at))


def check_virtual_flips():
    clock = VirtualClock()
    for frame in range(1, 601):
        last_flip = clock.getTime()
        assert clock.flip() > last_flip
        assert clock.getTime() == frame * clock.frame_period
    clock.wait(0.010)
    assert clock.flip() == 601 * clock.frame_period


def check_deadline_poll():
    """An on-time press can be retrieved after cutoff. A press at cutoff is excluded."""
    clock = VirtualClock()
    response_keys = ["d", "f", "escape"]
    timed_input = task.TimedInput(ScriptedKeyboard(clock.getTime))
    with patch.object(task.psylog, "defaultClock", clock):
        clock.now = 2.01
        timed_input.keyboard.queue("f", 2.003)
        timed_input.keyboard.queue("d", 1.999, available_at=2.005, released=True)
        assert timed_input.wait_for_response(response_keys, 1.0, 2.0) == ("d", 1.999, None)
        timed_input.keyboard.queue("d", 0.999)
        timed_input.keyboard.queue("d", 2.0)
        timed_input.keyboard.queue("d", 2.001)
        assert timed_input.wait_for_response(response_keys, 1.0, 2.0) == ("", None, None)
        timed_input.keyboard.queue("space", 2.005)
        assert [key.name for key in timed_input.poll_keys(["space"])] == ["space"]
        timed_input.keyboard.queue("space", 2.005, released=True)
        assert timed_input.poll_keys(["space"]) == []
        timed_input.keyboard.queue("d", 2.006)
        timed_input.keyboard.queue("escape", 2.007)
        timed_input.keyboard.queue("f", 2.008)
        assert timed_input.wait_for_response(response_keys, 2.0, 3.0) == ("d", 2.006, 2.007)


def check_refresh_rate():
    assert task.resolve_frame_timing(60.0, None) == (60.0, 1 / 60)
    assert task.resolve_frame_timing(360.0, None) == (360.0, 1 / 360)
    for measured in (None, 0.0, 1.0, 5000.0, math.nan, math.inf):
        assert task.resolve_frame_timing(measured, 1 / 144) == (None, 1 / 144)
    assert task.resolve_frame_timing(math.nan, math.inf) == (None, 1 / 60)


def check_interface_keys(exp):
    """Exercise confirmation, instructions, the probe and abort saving through the PTB input path."""
    original_flip = exp.win.flip

    def on_flip(*events):
        queued = list(events)

        def flip():
            timestamp = float(original_flip())
            if queued:
                for key, delay in queued:
                    exp.timed_input.keyboard.queue(key, timestamp + delay, released=True)
                queued.clear()
            return timestamp

        return patch.object(exp.win, "flip", flip)

    with on_flip(("r", 0.020)):
        assert exp.confirm_info() is False
    with on_flip(("space", 0.020)):
        assert exp.confirm_info() is True
    with on_flip(("space", 0.020)):
        exp.wait_space("用空格继续")

    mouse = SimpleNamespace(getPressed=lambda: [False])
    with patch.object(task, "MouseClass", lambda **_: mouse), on_flip(("right", 0.010), ("space", 0.030)):
        exp.run_probe("efficacy", after_interval=0)
    assert exp.rows_probes[-1]["评价值"] > 50

    for pressed in (False, True):
        assert task.mouse_left_pressed(SimpleNamespace(getPressed=lambda: [pressed])) is pressed
        assert task.mouse_left_pressed(SimpleNamespace(getLeftButtonPressed=lambda: pressed)) is pressed


def check_interval_interruptions(exp):
    original_flip = exp.win.flip
    original_draw = exp.fb_source.draw
    original_target = exp._present_target

    stages = ("注视中", "作答中", "题间空屏", "反馈前", "反馈中")
    for index, stage in enumerate(stages):
        n_flips = 0
        n_targets = 0
        pending_feedback = False

        def present_with_response(ink, word):
            nonlocal n_targets
            onset = original_target(ink, word)
            n_targets += 1
            if stage == "作答中" and n_targets == 2:
                exp.timed_input.keyboard.queue("escape", onset + 0.075, released=True)
            else:
                exp.timed_input.keyboard.queue(task.CFG["KEYS"][ink], onset + 0.12)
            return onset

        def feedback_draw():
            nonlocal pending_feedback
            original_draw()
            if stage == "反馈中":
                pending_feedback = True
            elif stage == "反馈前":
                stop_at = float(task.psylog.defaultClock.getTime()) + 0.075
                exp.timed_input.keyboard.queue("escape", stop_at, released=True)

        def flip():
            nonlocal n_flips, pending_feedback
            timestamp = float(original_flip())
            n_flips += 1
            if pending_feedback or (stage == "注视中" and n_flips == 1) or (stage == "题间空屏" and n_flips == 3):
                stop_delay = 0.025 if stage == "注视中" else 0.075
                exp.timed_input.keyboard.queue("escape", timestamp + stop_delay, released=True)
                pending_feedback = False
            return timestamp

        before_total = exp.total_score
        before_history = list(exp.yoke.buf)
        before_intervals = len(exp.rows_intervals)
        before_trials = len(exp.rows_trials)
        duration = 1.4 if stage in ("作答中", "题间空屏") else 0.6
        with TemporaryDirectory() as directory:
            exp.outdir = directory
            with (patch.object(exp.fb_source, "draw", feedback_draw),
                  patch.object(exp, "_present_target", present_with_response),
                  patch.object(exp.win, "flip", flip),
                  patch.object(exp.win, "close") as close,
                  patch.object(task.core, "quit", side_effect=SystemExit),
                  patch.dict(task.CFG, {"ISI_BETWEEN": 0.25})):
                try:
                    exp.run_interval(900 + index, duration, "performance")
                except SystemExit:
                    close.assert_called_once()
                else:
                    raise AssertionError(f"Esc did not interrupt during {stage}")

            assert len(exp.rows_intervals) == before_intervals + 1
            row = exp.rows_intervals[-1]
            with (Path(directory) / "intervals.csv").open(encoding="utf-8-sig", newline="") as stream:
                intervals = list(csv.DictReader(stream))
            saved = intervals[-1]
            with (Path(directory) / "trials.csv").open(encoding="utf-8-sig", newline="") as stream:
                trials = list(csv.DictReader(stream))
            meta = json.loads((Path(directory) / "meta.json").read_text(encoding="utf-8"))
            assert len(trials) == before_trials + row["试次数"]
            assert all(r["区段"] == saved["区段"] for r in trials[before_trials:])
            assert saved["中断阶段"] == stage
            assert float(saved["中断时刻s"]) >= float(saved["注视翻屏时刻s"])
            assert row["反馈中断"] == int(stage == "反馈中")
            assert meta["实测刷新率Hz"] == exp.refresh_hz
            assert meta["出题估计帧长s"] == exp.frame_period
            assert meta["总分"] == float(saved["累计得分"])
            assert meta["总分"] == sum(float(r["区段得分"]) for r in intervals
                                       if r["阶段"] == "main" and r["区段得分"] != "")
            assert meta["中断区段数"] == sum(bool(r["中断阶段"]) for r in intervals if r["阶段"] == "main")
            if stage == "注视中":
                assert row["试次数"] == row["正确数"] == 0
                assert saved["区段开始时刻s"] == saved["区段截止时刻s"] == saved["作答窗用时s"] == ""
            else:
                assert row["试次数"] == (2 if stage == "作答中" else 1)
                assert row["正确数"] == 1 and row["正确率"] == 1
                assert row["作答窗用时s"] > 0
            if stage == "作答中":
                assert trials[-1]["试次中断"] == "1"
                assert trials[-1]["正确"] == trials[-1]["按键时刻s"] == ""
            if stage == "反馈中":
                assert 0.075 <= row["反馈时长s"] < 0.250
                assert row["反馈延迟s"] >= 0
                assert saved["反馈结束时刻s"] == f"{row['反馈结束时刻s']:.6f}"
                assert row["作答窗用时s"] == duration
                assert exp.total_score == before_total + 10
                assert exp.yoke.buf[-1] == 10
            else:
                assert saved["反馈翻屏时刻s"] == saved["区段得分"] == ""
                assert exp.total_score == before_total
                assert list(exp.yoke.buf) == before_history
    print("UI input, both mouse APIs, and abort saving in all five interval stages passed.")


def check_failed_save(exp):
    """A partial write in staging cannot damage the previously published files."""
    def fail_after_partial_write(_meta, stream, **_):
        stream.write("{")
        raise OSError("simulated write failure")

    with TemporaryDirectory() as directory, patch.object(exp, "outdir", directory):
        exp.save()
        before = {path.name: path.read_bytes() for path in Path(directory).iterdir()}
        assert set(before) == {"trials.csv", "intervals.csv", "probes.csv", "meta.json"}
        with (patch.object(exp, "rows_intervals", exp.rows_intervals[:-1]),
              patch.object(session_data.json, "dump", fail_after_partial_write)):
            try:
                exp.save()
            except OSError as exc:
                assert str(exc) == "simulated write failure"
            else:
                raise AssertionError("The simulated write failure did not reach save()")
        assert {path.name: path.read_bytes() for path in Path(directory).iterdir()} == before
    print("A failed staged save left all four previous files intact.")


def check_ptb_clock(keyboard):
    """Check the Studio PTB conversion using its native clock and a constructed event."""
    from psychopy.hardware.keyboard import keyNames
    from psychtoolbox import GetSecs

    code = next(code for code, name in keyNames.items() if name == "d")
    device = keyboard.device
    before = task.psylog.defaultClock.getTime()
    ptb_time = GetSecs()
    down = device.parseMessage({"down": True, "keycode": code, "time": ptb_time})
    after = task.psylog.defaultClock.getTime()
    device.parseMessage({"down": False, "keycode": code, "time": ptb_time + 0.05})
    assert before - 0.001 <= down.tDown <= after + 0.001, (before, down.tDown, after)
    assert down.name == "d" and math.isclose(down.duration, 0.05, abs_tol=0.000001)
    timed_input = task.TimedInput(keyboard)
    device.responses.append(down)
    assert timed_input.poll_keys(["d"]) == [down]
    assert timed_input.poll_keys(["d"]) == []

    ptb_time = GetSecs()
    held = device.parseMessage({"down": True, "keycode": code, "time": ptb_time})
    device.responses.append(held)
    assert timed_input.poll_keys(["d"]) == [held]
    released = device.parseMessage({"down": False, "keycode": code, "time": ptb_time + 0.05})
    assert released is held
    device.responses.append(released)
    assert timed_input.poll_keys(["d"]) == []
    print("Native PTB clock conversion and de-duplication passed with constructed device events.")


def check_native_keyboard():
    """Observe a live PTB press and one tap released before either poll."""
    exp = task.StroopEfficacyExp({"被试编号": "QA-PTB", "漂移方向": "正向"})
    view = task.visual.TextStim(exp.win, font=task.CFG["FONT"], height=0.04)
    exp.win.winHandle.set_caption("PsychoPy Studio PTB test")
    try:
        exp.timed_input.keyboard.clearEvents()
        view.text = "PTB 键盘检查 1 / 2\n\n请轻按一次 D 并松开。"
        view.draw()
        onset = float(exp.win.flip())
        key, t_down, escape_at = exp.timed_input.wait_for_response(exp.response_keys, onset, onset + 60)
        assert key == "d" and escape_at is None, "PTB did not capture the first D press"
        observed = task.psylog.defaultClock.getTime()
        tolerance = max(2 * exp.frame_period, 0.025)
        assert onset <= t_down <= observed and observed - t_down < tolerance
        task.core.wait(0.3, hogCPUperiod=0.001)
        assert exp.timed_input.poll_keys(["d"]) == [], "D release counted as a second press"
        print(f"PTB first D poll lag: {(observed - t_down) * 1000:.2f} ms.", flush=True)

        exp.timed_input.keyboard.clearEvents()
        view.text = "PTB 键盘检查 2 / 2\n\n请在 30 秒内轻按一次 J 并松开。"
        view.draw()
        onset = float(exp.win.flip())
        task.core.wait(30.0, hogCPUperiod=0.001)
        keys = exp.timed_input.poll_keys(["j"])
        assert len(keys) == 1, f"Expected one completed J press, got {len(keys)}"
        assert onset <= keys[0].tDown < onset + 30.0
        assert keys[0].duration is not None and keys[0].duration > 0
        assert exp.timed_input.poll_keys(["j"]) == [], "Completed J press was returned twice"
        print("Live PTB press and completed tap, timestamps and de-duplication passed.", flush=True)
    finally:
        exp.timed_input.keyboard.stop()
        exp.win.close()


def run_intervals(args):
    if args.studio:
        exp = task.StroopEfficacyExp({"被试编号": "QA-TIMING", "漂移方向": "正向"})
        assert exp.timed_input.keyboard.getBackend() == "ptb"
        check_ptb_clock(exp.timed_input.keyboard)
        exp.timed_input.keyboard.stop()
        window = exp.win
    else:
        clock = task.psylog.defaultClock
        window = SimpleNamespace(
            flip=clock.flip, monitorFramePeriod=clock.frame_period,
            getActualFrameRate=lambda **_: 1 / clock.frame_period,
            setMouseVisible=lambda _visible: None, close=lambda: None,
        )
        virtual_visual = SimpleNamespace(
            Window=lambda **_settings: window, TextStim=VirtualStim, Rect=VirtualStim,
            Line=VirtualStim, Circle=VirtualStim,
        )
        with patch.object(task, "visual", virtual_visual):
            exp = task.StroopEfficacyExp({"被试编号": "QA-TIMING", "漂移方向": "正向"},
                                        keyboard=ScriptedKeyboard(clock.getTime))

    exp.timed_input.keyboard = ScriptedKeyboard(task.psylog.defaultClock.getTime)
    real_flip = window.flip
    real_draw = exp.word.draw
    real_feedback = exp._fb_interval
    color_keys = {tuple(task.CFG["COLOR_RGB"][ink]): k for ink, k in task.CFG["KEYS"].items()}
    pending_target = False
    first_on = None
    end = None
    duration = None
    scenario = None
    target_count = 0
    reports = []
    feedback_entered = None

    def draw():
        nonlocal pending_target
        real_draw()
        pending_target = True

    def flip():
        nonlocal pending_target, first_on, end, target_count
        timestamp = float(real_flip())
        if not pending_target:
            return timestamp
        pending_target = False
        target_count += 1
        if first_on is None:
            first_on = timestamp
            end = first_on + duration
        color = tuple(float(channel) for channel in exp.word.color)
        key = next(
            (key for rgb, key in color_keys.items()
             if len(color) == len(rgb) and all(math.isclose(a, b, abs_tol=1e-5) for a, b in zip(color, rgb))),
            None,
        )
        if key is None:
            raise AssertionError(f"Unexpected stimulus color {color!r}")
        if scenario == "normal" and timestamp + 0.27 < end:
            exp.timed_input.keyboard.queue(key, timestamp + 0.27)
        elif target_count == 1:
            if scenario == "before":
                exp.timed_input.keyboard.queue(key, end - 0.005, available_at=end)
            elif scenario == "at":
                exp.timed_input.keyboard.queue(key, end)
            elif scenario == "after":
                exp.timed_input.keyboard.queue(key, end + 0.002)
        return timestamp

    def time_feedback(score, eff_type, deadline, practice=False):
        nonlocal feedback_entered
        assert deadline == end
        assert practice == (scenario == "practice_timeout")
        feedback_entered = task.psylog.defaultClock.getTime()
        return real_feedback(score, eff_type, deadline, practice=practice)

    exp._fb_interval = time_feedback
    exp.word.draw = draw
    window.flip = flip
    try:
        for duration in (2.0, 3.0, 4.0):
            scenarios = ("normal", "before", "at", "after", "none")
            if duration == 2.0:
                scenarios += ("practice_timeout",)
            for scenario in scenarios:
                first_on = end = None
                target_count = 0
                n = len(exp.rows_trials)
                practice = scenario == "practice_timeout"
                previous_total = exp.total_score
                if practice:
                    interval = exp.run_interval(None, duration, "random", phase="prac3",
                                                practice_yoke=task.YokeWindow(init=[30]))
                else:
                    interval = exp.run_interval(len(reports), duration, "performance")
                trials = exp.rows_trials[n:]
                feedback_delay = interval["反馈翻屏时刻s"] - end
                feedback_duration = interval["反馈结束时刻s"] - interval["反馈翻屏时刻s"]
                assert interval["区段开始时刻s"] == first_on
                assert interval["区段截止时刻s"] == end
                assert interval["作答窗用时s"] == duration
                assert math.isclose(interval["反馈延迟s"], feedback_delay, abs_tol=0.00000051)
                assert math.isclose(interval["反馈时长s"], feedback_duration, abs_tol=0.00000051)
                assert math.isclose(end - first_on, duration, abs_tol=1e-9)
                tolerance = max(2 * exp.frame_period, 0.025)
                within_tolerance = (
                    -1e-9 <= feedback_delay <= tolerance
                    and task.CFG["FB_DUR"] - 1e-9 <= feedback_duration <= task.CFG["FB_DUR"] + tolerance
                )
                if practice:
                    assert interval["区段得分"] == 30 and exp.total_score == previous_total
                else:
                    assert interval["区段得分"] == 10 * sum(r["正确"] for r in trials)
                for row in trials:
                    assert row["作答截止时刻s"] == end
                    assert row["目标翻屏时刻s"] < end
                    if row["反应键"]:
                        onset = row["目标翻屏时刻s"]
                        press = row["按键时刻s"]
                        assert onset <= press < end
                        assert abs(row["反应时"] - (press - onset)) <= 0.000051
                    else:
                        assert row["反应时"] == row["按键时刻s"] == ""
                if scenario == "normal":
                    assert interval["正确数"] >= 2
                    for earlier, following in zip(trials, trials[1:]):
                        assert following["目标翻屏时刻s"] - earlier["按键时刻s"] >= args.isi - 1e-9
                else:
                    assert len(trials) == 1
                    assert bool(trials[0]["反应键"]) == (scenario == "before")
                reports.append({
                    "window_s": duration, "case": scenario,
                    "feedback_delay_ms": round(1000 * feedback_delay, 2),
                    "feedback_duration_s": round(feedback_duration, 4),
                    "finalization_ms_from_cutoff": round(1000 * (feedback_entered - end), 2),
                    "within_flip_tolerance": within_tolerance,
                    "trials": len(trials), "points": interval["区段得分"],
                })
        window.flip = real_flip
        exp.word.draw = real_draw
        exp._fb_interval = real_feedback
        text_stim = task.visual.TextStim if args.studio else VirtualStim
        with patch.object(task.visual, "TextStim", text_stim):
            check_interface_keys(exp)
        check_interval_interruptions(exp)
        check_failed_save(exp)
    finally:
        window.close()

    return reports


def main():
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--studio", action="store_true", help="Use real flips in a Studio window.")
    modes.add_argument("--ptb-keyboard", action="store_true", help="Check the native PTB queue with two live keypresses.")
    parser.add_argument("--fullscreen", action="store_true", help="Use the full-screen acquisition mode.")
    parser.add_argument("--isi", type=float, default=0.25, help="Blank interval in seconds.")
    args = parser.parse_args()
    if not __debug__:
        parser.error("Run without Python optimization so timing assertions remain enabled")
    if args.fullscreen and not (args.studio or args.ptb_keyboard):
        parser.error("--fullscreen requires --studio or --ptb-keyboard")
    if args.ptb_keyboard:
        with patch.dict(task.CFG, {"FULLSCR": args.fullscreen}):
            check_native_keyboard()
        return
    if not math.isfinite(args.isi) or args.isi < 0:
        parser.error("--isi must be a finite, non-negative duration")
    check_virtual_flips()
    check_deadline_poll()
    check_refresh_rate()

    settings = {"FULLSCR": args.fullscreen, "FIX_CHOICES": (0.08,), "ISI_BETWEEN": args.isi}
    with patch.dict(task.CFG, settings):
        if args.studio:
            results = run_intervals(args)
        else:
            virtual = VirtualClock()
            # Keep getTime, waits and flips on the same clock in the simulated run.
            with patch.object(task.psylog, "defaultClock", virtual), patch.object(task.core, "wait", virtual.wait):
                results = run_intervals(args)
    print(json.dumps({"studio": args.studio, "fullscreen": args.fullscreen,
                      "isi_s": args.isi, "intervals": results}, indent=2), flush=True)
    if not all(row["within_flip_tolerance"] for row in results):
        sys.exit("Feedback timing exceeded the tolerance of two refresh periods.")


if __name__ == "__main__":
    main()
