
"""Check interval timing with a virtual clock or a real PsychoPy Studio window.

Usage: python tests/check_timing.py [--studio] [--fullscreen] [--isi 0.25]
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


class VirtualClock:
    frame_period = 1 / 60

    def __init__(self):
        self.now = 0.0

    def getTime(self):
        return self.now

    def wait(self, seconds):
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
    exp = task.StroopEfficacyExp.__new__(task.StroopEfficacyExp)
    clock = VirtualClock()
    exp.response_keys = ["d", "f", "escape"]
    exp.last_key_down = {}
    exp.keyboard = ScriptedKeyboard(clock.getTime)
    with patch.object(task.logging, "defaultClock", clock):
        clock.now = 2.01
        exp.keyboard.queue("f", 2.003)
        exp.keyboard.queue("d", 1.999, available_at=2.005, released=True)
        assert exp._wait_for_response(1.0, 2.0) == ("d", 1.999)
        exp.keyboard.queue("d", 0.999)
        exp.keyboard.queue("d", 2.0)
        exp.keyboard.queue("d", 2.001)
        assert exp._wait_for_response(1.0, 2.0) == ("", None)
        exp.keyboard.queue("space", 2.005)
        assert [key.name for key in exp._poll_keys(["space"])] == ["space"]
        exp.keyboard.queue("space", 2.005, released=True)
        assert exp._poll_keys(["space"]) == []


def check_interface_keys(exp):
    """Exercise confirmation, instructions, the probe and abort saving through the PTB input path."""
    original_flip = exp.win.flip

    def on_flip(*events):
        queued = list(events)

        def flip():
            timestamp = float(original_flip())
            if queued:
                for key, delay in queued:
                    exp.keyboard.queue(key, timestamp + delay, released=True)
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

    original_draw = exp.fb_source.draw
    show_feedback = False
    aborted = False

    def feedback_draw():
        nonlocal show_feedback
        original_draw()
        show_feedback = True

    def feedback_flip():
        nonlocal show_feedback
        timestamp = float(original_flip())
        if show_feedback:
            exp.keyboard.queue("escape", timestamp + 0.075, released=True)
            show_feedback = False
        return timestamp

    with TemporaryDirectory() as directory:
        exp.outdir = directory
        with (patch.object(exp.fb_source, "draw", feedback_draw),
              patch.object(exp.win, "flip", feedback_flip),
              patch.object(exp.win, "close") as close,
              patch.object(task.core, "quit", side_effect=SystemExit)):
            try:
                exp.run_interval(0, 0.6, "random")
            except SystemExit:
                aborted = True
            assert aborted
            close.assert_called_once()
        row = exp.rows_intervals[-1]
        assert row["反馈中断"] == 1
        feedback_duration = row["反馈结束时刻s"] - row["反馈翻屏时刻s"]
        assert 0.075 <= feedback_duration < 0.250
        with (Path(directory) / "intervals.csv").open(encoding="utf-8-sig", newline="") as stream:
            saved = list(csv.DictReader(stream))[-1]
        assert saved["反馈中断"] == "1"
        assert saved["反馈结束时刻s"] == f"{row['反馈结束时刻s']:.6f}"
        meta = json.loads((Path(directory) / "meta.json").read_text(encoding="utf-8"))
        assert meta["实测刷新率Hz"] == exp.refresh_hz
        assert meta["出题估计帧长s"] == exp.frame_period
    print(
        f"UI input and feedback interruption checks passed. "
        f"Esc ended feedback after {1000 * feedback_duration:.1f} ms. "
        f"Measured refresh rate: {exp.refresh_hz!r} Hz."
    )

def run_intervals(args):
    if args.studio:
        exp = task.StroopEfficacyExp({"被试编号": "QA-TIMING", "漂移方向": "正向"})
        assert exp.keyboard.getBackend() == "ptb"
        window = exp.win
    else:
        clock = task.logging.defaultClock
        window = SimpleNamespace(
            flip=clock.flip, monitorFramePeriod=clock.frame_period,
            getActualFrameRate=lambda **_: 1 / clock.frame_period,
            setMouseVisible=lambda _visible: None, close=lambda: None,
        )
        virtual_visual = SimpleNamespace(
            Window=lambda **_settings: window, TextStim=VirtualStim, Rect=VirtualStim,
            Line=VirtualStim, Circle=VirtualStim,
        )
        with patch.multiple(task, visual=virtual_visual, Keyboard=lambda **_: ScriptedKeyboard(clock.getTime)):
            exp = task.StroopEfficacyExp({"被试编号": "QA-TIMING", "漂移方向": "正向"})

    exp.keyboard = ScriptedKeyboard(task.logging.defaultClock.getTime)
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
            exp.keyboard.queue(key, timestamp + 0.27)
        elif target_count == 1:
            if scenario == "before":
                exp.keyboard.queue(key, end - 0.005, available_at=end)
            elif scenario == "at":
                exp.keyboard.queue(key, end)
            elif scenario == "after":
                exp.keyboard.queue(key, end + 0.002)
        return timestamp

    def time_feedback(score, eff_type, deadline, practice=False):
        nonlocal feedback_entered
        assert deadline == end
        assert practice == (scenario == "practice_timeout")
        feedback_entered = task.logging.defaultClock.getTime()
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
    finally:
        window.close()

    return reports


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--studio", action="store_true", help="Use real flips in a Studio window.")
    parser.add_argument("--fullscreen", action="store_true", help="Use the full-screen acquisition mode.")
    parser.add_argument("--isi", type=float, default=0.25, help="Blank interval in seconds.")
    args = parser.parse_args()
    if not __debug__:
        parser.error("Run without Python optimization so timing assertions remain enabled")
    if args.fullscreen and not args.studio:
        parser.error("--fullscreen requires --studio")
    if not math.isfinite(args.isi) or args.isi < 0:
        parser.error("--isi must be a finite, non-negative duration")
    check_virtual_flips()
    check_deadline_poll()

    settings = {"FULLSCR": args.fullscreen, "FIX_CHOICES": (0.08,), "ISI_BETWEEN": args.isi}
    with patch.dict(task.CFG, settings):
        if args.studio:
            results = run_intervals(args)
        else:
            virtual = VirtualClock()
            # Keep getTime, waits and flips on the same clock in the simulated run.
            with patch.object(task.logging, "defaultClock", virtual), patch.object(task.core, "wait", virtual.wait):
                results = run_intervals(args)
    print(json.dumps({"studio": args.studio, "fullscreen": args.fullscreen,
                      "isi_s": args.isi, "intervals": results}, indent=2), flush=True)
    if not all(row["within_flip_tolerance"] for row in results):
        sys.exit("Feedback timing exceeded the tolerance of two refresh periods.")


if __name__ == "__main__":
    main()
