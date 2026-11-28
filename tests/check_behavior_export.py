"""验证 PsychoPy 任务用合成输入写出的数据契约。"""

import csv
import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from contextlib import ExitStack
from datetime import datetime
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from check_timing import ScriptedKeyboard, VirtualClock, VirtualStim, task
from stroop_efficacy import session_data


def read_snapshot(directory):
    path = Path(directory)
    meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
    assert set(meta["数据表"]) == {"trials.csv", "intervals.csv", "probes.csv"}
    tables = {}
    for name, spec in meta["数据表"].items():
        raw = (path / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == spec["SHA256"]
        reader = csv.DictReader(StringIO(raw.decode("utf-8-sig"), newline=""))
        assert "会话编号" in reader.fieldnames
        rows = list(reader)
        assert len(rows) == spec["行数"]
        assert all(row["会话编号"] == meta["会话编号"] for row in rows)
        tables[name] = rows
    return meta, tables


def check_joins(meta, tables):
    def interval_key(row):
        return row["会话编号"], row["阶段"], row["区段"]

    intervals = {interval_key(row): row for row in tables["intervals.csv"]}
    assert len(intervals) == len(tables["intervals.csv"])
    trials_by_interval = defaultdict(list)
    for i, row in enumerate(tables["trials.csv"], start=1):
        assert int(row["试次编号"]) == i
        if row["阶段"] in {"main", "prac3"}:
            key = interval_key(row)
            assert row["组块"] == intervals[key]["组块"]
            trials_by_interval[key].append(row)
        else:
            assert row["阶段"] in {"prac1", "prac2"} and row["区段"] == ""
        if row["作答状态"] == "responded":
            rt = float(row["反应时"])
            assert 0 <= rt < float(row["可作答时长s"])
            assert row["反应键"] and row["按键时刻s"]
            assert int(row["过快"]) == int(rt < 0.25)
        else:
            assert row["反应键"] == row["反应时"] == row["过快"] == ""
            assert row["正确"] == ("0" if row["作答状态"] == "timeout" else "")
    for key, interval in intervals.items():
        trials = trials_by_interval[key]
        statuses = Counter(row["作答状态"] for row in trials)
        assert len(trials) == int(interval["试次数"])
        assert sum(row["正确"] == "1" for row in trials) == int(interval["正确数"])
        assert statuses["responded"] == int(interval["作答数"])
        assert statuses["timeout"] == int(interval["截止未答数"])
    for i, probe in enumerate(tables["probes.csv"], start=1):
        interval = intervals[interval_key(probe)]
        assert probe["区段"] == probe["插入位置"] and probe["组块"] == interval["组块"]
        assert int(probe["探测编号"]) == i
    assert meta["参数SHA256"] == session_data.parameter_hash(meta["运行参数"])


def verify_export(tmpdir):
    clock = VirtualClock()
    window = SimpleNamespace(
        flip=clock.flip,
        monitorFramePeriod=clock.frame_period,
        getActualFrameRate=lambda **_: 1 / clock.frame_period,
        setMouseVisible=lambda _state: None,
        close=lambda: None,
    )
    visual = SimpleNamespace(
        Window=lambda **_: window,
        TextStim=VirtualStim,
        Rect=VirtualStim,
        Line=VirtualStim,
        Circle=VirtualStim,
    )
    keyboard = ScriptedKeyboard(clock.getTime)
    info = {"被试编号": "QA-EXPORT-01", "姓名": "合成"}
    with ExitStack() as mocks:
        mocks.enter_context(patch.object(task, "visual", visual))
        mocks.enter_context(patch.object(task.psylog, "defaultClock", clock))
        mocks.enter_context(patch.object(task.core, "wait", clock.wait))
        mocks.enter_context(
            patch.dict(
                task.CFG,
                {
                    "DEBUG_FAST": False,
                    "N_INTERVALS": 288,
                    "BREAK_EVERY": 36,
                    "WINDOW_CHOICES": (2.0, 3.0, 4.0),
                    "FIX_CHOICES": (0.08,),
                },
            )
        )
        fixed_time = datetime(2026, 1, 1)
        mocks.enter_context(
            patch.object(task, "datetime", SimpleNamespace(now=lambda: fixed_time))
        )
        root = tmpdir / "data"
        exp = task.StroopEfficacyExp(
            info, keyboard=keyboard, mode="pilot", archive_root=root
        )
        rerun = task.StroopEfficacyExp(
            info,
            keyboard=ScriptedKeyboard(clock.getTime),
            mode="pilot",
            archive_root=root,
        )
        exp.save()
        rerun.save()
        first_meta, empty = read_snapshot(exp.outdir)
        rerun_meta, _ = read_snapshot(rerun.outdir)
        assert not any(empty.values())
        assert (
            exp.outdir != rerun.outdir
            and first_meta["会话编号"] != rerun_meta["会话编号"]
        )
        assert first_meta["导出版本"] == 2 and first_meta["RT单位"] == "s"
        assert first_meta["会话开始时间"] == rerun_meta["会话开始时间"]
        assert "姓名" not in first_meta and "合成" not in str(exp.outdir)
        assert (
            exp.outdir.parent == rerun.outdir.parent == root / "pilot" / "QA-EXPORT-01"
        )
        assert len(first_meta["脚本SHA256"]) == 64 and first_meta["正式调度"]["版本"]

        present = exp._present_target

        def scripted_targets(*presses):
            pending = iter(presses)

            def show(ink, word):
                onset = present(ink, word)
                if press := next(pending, None):
                    key, delay = press
                    keyboard.queue(key, onset + delay)
                return onset

            return patch.object(exp, "_present_target", show)

        with scripted_targets(("d", 0.3123456789)):
            exp._practice_trial("red", "", with_fb=False, phase="prac1")
        with scripted_targets(("f", 0.32)):
            exp._practice_trial("red", "绿", with_fb=False, phase="prac2")
        with (
            scripted_targets(),
            patch.object(
                exp, "make_trial_content", return_value=("red", "绿", "incongruent")
            ),
        ):
            exp.run_interval(
                0,
                1.0,
                "performance",
                phase="prac3",
                practice_yoke=task.YokeWindow(init=[]),
            )
        with (
            scripted_targets(("d", 0.3123456789), ("f", 0.26)),
            patch.object(
                exp,
                "make_trial_content",
                return_value=("red", "绿", "incongruent"),
            ),
        ):
            exp.run_interval(0, 2.0, "performance")
        played_probe = False

        def flip_probe():
            nonlocal played_probe
            onset = clock.flip()
            if not played_probe:
                keyboard.queue("right", onset + 0.01)
                keyboard.queue("space", onset + 0.03)
                played_probe = True
            return onset

        mouse = SimpleNamespace(getPressed=lambda: [False])
        with (
            patch.object(window, "flip", flip_probe),
            patch.object(task, "MouseClass", return_value=mouse),
        ):
            exp.run_probe("efficacy", after_interval=0)
        previous_manifest = (Path(exp.outdir) / "meta.json").read_bytes()
        replace = os.replace

        def stop_mid_publish(src, dst):
            if Path(dst).name == "trials.csv":
                raise OSError("simulated interrupted publication")
            replace(src, dst)

        with patch.object(session_data.os, "replace", stop_mid_publish):
            try:
                exp.save()
            except OSError as exc:
                assert str(exc) == "simulated interrupted publication"
            else:
                raise AssertionError("Simulated failure did not interrupt publication")
        assert (Path(exp.outdir) / "meta.json").read_bytes() == previous_manifest
        interval_bytes = (Path(exp.outdir) / "intervals.csv").read_bytes()
        assert (
            hashlib.sha256(interval_bytes).hexdigest()
            != first_meta["数据表"]["intervals.csv"]["SHA256"]
        )
        assert session_data.read_session_snapshot(Path(exp.outdir)) == (
            first_meta,
            True,
        )
        exp.save()
        check_joins(*read_snapshot(exp.outdir))

        with (
            scripted_targets(("escape", 0.30)),
            patch.object(task.core, "quit", side_effect=SystemExit),
        ):
            try:
                exp.run_interval(36, exp.main_schedule.windows[36], "performance")
            except SystemExit:
                pass
            else:
                raise AssertionError(
                    "Synthetic Escape did not interrupt the main interval"
                )
        meta, tables = read_snapshot(exp.outdir)
        check_joins(meta, tables)
        assert (
            meta["会话编号"] == first_meta["会话编号"]
            and meta["完整区段数"] == meta["中断区段数"] == 1
        )
        assert [row["区段状态"] for row in tables["intervals.csv"]] == [
            "completed",
            "completed",
            "interrupted",
        ]
        assert [row["组块"] for row in tables["intervals.csv"]] == ["", "1", "2"]
        assert tables["trials.csv"][-1]["作答状态"] == "interrupted"
        formal_first = next(
            row for row in tables["trials.csv"] if row["阶段"] == "main"
        )
        assert math.isclose(
            float(formal_first["反应时"]), 0.3123456789, rel_tol=0, abs_tol=1e-10
        )
        assert tables["intervals.csv"][1]["作答数"] == "2"
        assert tables["intervals.csv"][1]["截止未答数"] == "1"
        assert tables["probes.csv"][0]["探针类型"] == "efficacy"


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError(
            "Run without Python optimization so export assertions remain enabled."
        )
    with TemporaryDirectory() as directory:
        verify_export(Path(directory))
    print(
        "Behavior exports passed: reruns, joins, missing responses, and interrupted publication."
    )
