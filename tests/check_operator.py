"""用合成场次核查登记、模式隔离、场次查询和保存结果。"""

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run as launcher  # noqa: E402
from check_timing import ScriptedKeyboard, VirtualClock, VirtualStim  # noqa: E402
from stroop_efficacy import archive  # noqa: E402
from stroop_efficacy import experiment as task  # noqa: E402
from stroop_efficacy.design import run_settings  # noqa: E402
from stroop_efficacy.session_data import (  # noqa: E402
    TABLE_FIELDS,
    read_session_snapshot,
    write_snapshot,
)
from ui import operator as operator_ui  # noqa: E402


CODE = "QA-SESSION-02"
INFO = {"被试编号": CODE, "漂移方向": "自动"}


def verify_archive(root):
    for invalid in ("", "A/B", "..", "NUL", "姓名", "A" * 33):
        try:
            archive.participant_code(invalid)
        except ValueError:
            continue
        raise AssertionError(f"Accepted invalid code {invalid!r}")
    assert archive.participant_code(f"  {CODE.lower()}  ") == CODE
    assert archive.performance_first(CODE) and not archive.performance_first("S001")
    assert run_settings("formal") == run_settings("pilot")
    fast = run_settings("quick")
    assert fast["DEBUG_FAST"] and not fast["FULLSCR"] and fast["N_INTERVALS"] == 12
    assert not task.CFG["DEBUG_FAST"] and task.CFG["N_INTERVALS"] == 288

    clock = VirtualClock()
    keyboard = ScriptedKeyboard(clock.getTime)
    window_sizes = []
    closed_windows = []
    startup_messages = []

    def make_text(window, text="", **settings):
        stim = VirtualStim(window, text, **settings)
        if settings.get("autoDraw"):
            startup_messages.append(stim)
        return stim

    def measure_frame_rate(*, infoMsg):
        assert infoMsg == ""
        splash = startup_messages[-1]
        assert splash.text == "正在测量显示器刷新率，请稍候"
        assert splash.font == task.CFG["FONT"] and splash.autoDraw
        return 1 / clock.frame_period

    def window_factory(**settings):
        window_sizes.append(settings["fullscr"])
        probe = False

        def mouse_visible(visible):
            nonlocal probe
            probe = visible

        def flip():
            nonlocal probe
            when = clock.flip()
            assert when < 420, "Synthetic operator run did not exit"
            if probe:
                probe = False
                keyboard.queue("right", clock.getTime() + 0.04)
                keyboard.queue("space", clock.getTime() + 0.06)
            return when

        return SimpleNamespace(
            flip=flip,
            monitorFramePeriod=clock.frame_period,
            getActualFrameRate=measure_frame_rate,
            setMouseVisible=mouse_visible,
            close=lambda: closed_windows.append(True),
        )

    visual = SimpleNamespace(
        Window=window_factory,
        TextStim=make_text,
        Rect=VirtualStim,
        Line=VirtualStim,
        Circle=VirtualStim,
    )
    mouse = SimpleNamespace(getPressed=lambda: [False])

    def interrupted(exp, *_args, **_kwargs):
        exp.abort()

    def fail_on_end(_exp, message, **_kwargs):
        if message.startswith("实验结束"):
            raise RuntimeError("final screen failure")

    def fail_in_interval(exp):
        exp.save()
        phase = "prac3" if exp.subj.endswith("-PRACTICE") else "main"

        def respond(*_args):
            if exp.rows_trials:
                raise KeyboardInterrupt("response wait interrupted")
            clock.wait(0.10)
            return "d", clock.getTime(), None

        with patch.object(exp.timed_input, "wait_for_response", respond):
            exp.run_interval(0, 2.0, "performance", phase=phase)

    end_failure_code = "QA-END-FAIL"
    partial_codes = ("QA-PARTIAL-MAIN", "QA-PARTIAL-PRACTICE")
    with (
        patch.object(task, "visual", visual),
        patch.object(task.psylog, "defaultClock", clock),
        patch.object(task.core, "getTime", clock.getTime),
        patch.object(task.core, "wait", clock.wait),
        patch.object(task, "MouseClass", return_value=mouse),
    ):
        with patch.dict(task.CFG, {"DEBUG_FAST": True}):
            inferred = task.StroopEfficacyExp(
                INFO,
                keyboard=keyboard,
                entrypoint=launcher.ENTRYPOINT,
                archive_root=root,
            )
        assert (
            inferred.mode == "quick" and inferred.main_schedule.windows == (1.0,) * 12
        )
        inferred.win.close()
        with patch.object(inferred, "save", side_effect=KeyboardInterrupt):
            try:
                inferred.finish("completed")
            except KeyboardInterrupt:
                assert inferred.session_status == "running" and not inferred.finished_at
            else:
                raise AssertionError("Terminal save interrupt was swallowed")
        with patch.object(task.StroopEfficacyExp, "wait_space", return_value=None):
            result = launcher.run_registered(INFO, "quick", root, keyboard)
            assert result.status == "completed" and result.path
        with patch.object(task.StroopEfficacyExp, "wait_space", interrupted):
            for _ in range(2):
                result = launcher.run_registered(INFO, "pilot", root, keyboard)
                assert result.status == "interrupted" and result.path
        with patch.object(
            task.StroopEfficacyExp,
            "wait_space",
            side_effect=RuntimeError("control failure"),
        ):
            result = launcher.run_registered(INFO, "formal", root, keyboard)
            assert result.status == "error" and "control failure" in result.detail
        with patch.object(task.StroopEfficacyExp, "wait_space", fail_on_end):
            result = launcher.run_registered(
                {**INFO, "被试编号": end_failure_code}, "quick", root, keyboard
            )
            assert result.status == "error" and "final screen failure" in result.detail
        with patch.object(task.StroopEfficacyExp, "run", fail_in_interval):
            for code in partial_codes:
                result = launcher.run_registered(
                    {**INFO, "被试编号": code}, "formal", root, keyboard
                )
                assert (
                    result.status == "error"
                    and "response wait interrupted" in result.detail
                )
        with (
            patch.object(
                visual, "TextStim", side_effect=RuntimeError("window setup failed")
            ),
            patch.object(keyboard, "stop") as stop_keyboard,
        ):
            result = launcher.run_registered(INFO, "pilot", root, keyboard)
            assert result.status == "startup_failed" and result.path is None
            assert "window setup failed" in result.detail
            stop_keyboard.assert_called_once()
    assert window_sizes == [False, False, True, True, True, False, True, True, True]
    assert len(closed_windows) == 9
    assert all(not stim.autoDraw for stim in startup_messages)
    (end_failure,) = archive.list_sessions(root, end_failure_code)
    assert end_failure.status == "error" and end_failure.completed == 12
    for code, phase in zip(partial_codes, ("main", "prac3")):
        (entry,) = archive.list_sessions(root, code)
        meta, recovered = read_session_snapshot(entry.path)
        assert not recovered and entry.status == "error" and entry.completed == 0
        assert meta["数据表"]["trials.csv"]["行数"] == 0
        assert meta["数据表"]["intervals.csv"]["行数"] == 0
        (unlinked,) = meta["异常未关联试次"]
        assert unlinked["阶段"] == phase and unlinked["区段"] == 1
        assert unlinked["反应键"] == "d" and unlinked["会话编号"] == entry.session_id
        for key in ("正式刺激呈现计数", "正式刺激作答计数"):
            assert sum(sum(words.values()) for words in meta[key].values()) == int(
                phase == "main"
            )
    entries = archive.list_sessions(root, CODE.lower())
    assert len({entry.session_id for entry in entries}) == 4
    assert archive.list_sessions(root, "QA-OTHER") == []
    assert sorted((entry.mode, entry.status, entry.completed) for entry in entries) == [
        ("formal", "error", 0),
        ("pilot", "interrupted", 0),
        ("pilot", "interrupted", 0),
        ("quick", "completed", 12),
    ]
    for entry in entries:
        assert entry.path == root / entry.mode / CODE / entry.session_id
        assert entry.started_at and entry.finished_at
        meta, recovered = read_session_snapshot(entry.path)
        assert not recovered and meta["会话编号"] == entry.session_id
        assert meta["序列分配方式"] == "auto"
        assert meta["正式调度"]["来源序列"] == "B"
        assert meta["运行参数"]["DEBUG_FAST"] == (entry.mode == "quick")
        assert not {"姓名", "性别", "年龄"} & meta.keys()
        assert (entry.path / "error.log").exists() == (entry.mode == "formal")

    legacy = root / "legacy-local-record"
    legacy.mkdir()
    (legacy / "meta.json").write_text(
        json.dumps({"被试编号": CODE, "导出版本": 1, "完整区段数": 2}),
        encoding="utf-8",
    )
    prior = archive.list_sessions(root, CODE)[-1]
    assert (prior.mode, prior.status, prior.completed) == ("legacy", "legacy", 2)
    assert prior.snapshot == "legacy" and not prior.version

    other = "QA-TIMEZONE"
    for session_id, start in (
        ("1", "2026-11-01T01:59:00-04:00"),
        ("2", "2026-11-01T01:00:00-05:00"),
    ):
        entry = root / "pilot" / other / session_id
        entry.mkdir(parents=True)
        write_snapshot(
            entry,
            [(name, []) for name in TABLE_FIELDS],
            dict(
                会话编号=session_id,
                被试编号=other,
                运行模式="pilot",
                会话开始时间=start,
            ),
        )
    assert [entry.session_id for entry in archive.list_sessions(root, other)] == [
        "2",
        "1",
    ]


def verify_snapshot_states(root):
    code = "QA-SNAPSHOT-STATES"
    path = root / "pilot" / code / "qa-snapshot"
    path.mkdir(parents=True)
    meta = {
        "会话编号": path.name,
        "被试编号": code,
        "运行模式": "pilot",
        "会话状态": "running",
        "完整区段数": 0,
        "代码版本": "qa-code-version",
        "会话开始时间": "2026-11-28T12:00:00+08:00",
    }
    tables = [(name, []) for name in TABLE_FIELDS]
    write_snapshot(path, tables, meta)
    write_snapshot(
        path,
        tables,
        {**meta, "会话状态": "completed", "会话结束时间": "2026-11-28T12:30:00+08:00"},
    )
    current = archive.describe_session(path, code, "pilot")
    assert current.snapshot == "current" and current.status == "completed"
    assert current.version == "qa-code-version" and current.finished_at
    (path / "trials.csv").write_text("damaged", encoding="utf-8")
    previous = archive.describe_session(path, code, "pilot")
    assert previous.snapshot == "previous" and previous.status == "recovery"
    assert not previous.finished_at and previous.version == current.version
    (path / ".previous.zip").unlink()
    unreadable = archive.describe_session(path, code, "pilot")
    assert unreadable.snapshot == "unreadable" and not unreadable.version


def verify_startup_checks(root):
    blocked = root / "blocked"
    blocked.write_text("This is a file.", encoding="utf-8")
    with patch.object(launcher, "open_timed_keyboard") as open_keyboard:
        result = launcher.start_session(INFO, "quick", blocked)
        assert result.status == "startup_failed" and "保存位置不可写" in result.detail
        open_keyboard.assert_not_called()
    path = root / "preflight"
    with patch.object(
        launcher, "open_timed_keyboard", side_effect=RuntimeError("PTB unavailable")
    ):
        result = launcher.start_session(INFO, "quick", path)
        assert result.status == "startup_failed" and "PTB unavailable" in result.detail
        assert not list((path / "quick" / CODE).iterdir())


def verify_studio_dialogs(root):
    """在真实 Qt 事件循环中验证同一窗口连续开场、失败后重试与关闭。"""
    from PyQt6 import QtCore, QtTest, QtWidgets

    operator_ui.ensureQtApp()
    app = QtWidgets.QApplication.instance()
    entries = archive.list_sessions(root, CODE)
    completed = next(entry for entry in entries if entry.status == "completed")
    interrupted = next(entry for entry in entries if entry.status == "interrupted")
    cases = iter(
        [
            launcher.SessionResult("startup_failed", detail="PTB unavailable"),
            launcher.SessionResult("interrupted", interrupted.path),
            launcher.SessionResult("completed", completed.path),
            launcher.SessionResult("completed", completed.path),
        ]
    )
    actions = iter(
        [
            ("实验员登记", "invalid"),
            ("请核对参与者编码", "OK"),
            ("实验员登记", "device"),
            ("实验员登记", "history"),
            ("查找场次", "filter"),
            ("实验员登记", "核对并启动"),
            ("确认启动", "返回修改"),
            ("实验员登记", "核对并启动"),
            ("确认启动", "确认重跑"),
            ("实验员登记", "failed"),
            ("确认启动", "确认重跑"),
            ("实验员登记", "interrupted"),
            ("确认启动", "确认重跑"),
            ("实验员登记", "next"),
            ("确认启动", "确认重跑"),
            ("实验员登记", "close"),
        ]
    )
    pending = next(actions)
    errors = []
    launches = []
    panel = None

    def start_session(info, mode):
        launches.append((info, mode))
        return next(cases)

    def button(widget, text):
        return next(
            child
            for child in widget.findChildren(QtWidgets.QPushButton)
            if child.text().replace("&", "") == text
        )

    def close_all():
        for dialog in app.topLevelWidgets():
            dialog.close()

    def tick():
        nonlocal pending, panel
        title, action = pending
        widget = app.activeModalWidget()
        if widget is None or title not in widget.windowTitle():
            QtCore.QTimer.singleShot(40, tick)
            return
        try:
            if title == "实验员登记":
                if panel is None:
                    panel = widget
                assert widget is panel and not widget.isMinimized()
                field = widget.findChild(QtWidgets.QLineEdit, "participant_code")
                mode = widget.findChild(QtWidgets.QComboBox, "run_mode")
                result = widget.findChild(QtWidgets.QLabel, "session_result")
                if action == "invalid":
                    field.setText("A/B")
                    action = "核对并启动"
                elif action == "device":
                    action = "设备检查"
                elif action == "history":
                    field.setText(CODE.lower())
                    mode.setCurrentIndex(mode.findData("quick"))
                    path = widget.findChild(QtWidgets.QLabel, "archive_path")
                    assert path.text() == str(root / "quick" / CODE)
                    action = "查找场次"
                elif action == "failed":
                    assert (
                        "启动失败" in result.text()
                        and "PTB unavailable" in result.text()
                    )
                    assert field.text() == CODE.lower()
                    mode.setCurrentIndex(mode.findData("pilot"))
                    action = "核对并启动"
                elif action == "interrupted":
                    assert "已中断" in result.text() and field.text() == CODE.lower()
                    assert "当前快照已校验" in result.text()
                    mode.setCurrentIndex(mode.findData("quick"))
                    action = "核对并启动"
                elif action in {"next", "close"}:
                    assert (
                        "已完成" in result.text() and "当前快照已校验" in result.text()
                    )
                    assert "完整区段数  12" in result.text() and not field.text()
                    assert str(completed.path) in result.text()
                    if action == "next":
                        button(widget, "打开场次目录").click()
                        field.setText(CODE)
                        action = "核对并启动"
                    else:
                        QtTest.QTest.keyClick(widget, QtCore.Qt.Key.Key_Escape)
                        assert widget.isVisible()
            if title == "查找场次":
                table = widget.findChild(QtWidgets.QTableWidget, "archive_sessions")
                assert table.rowCount() == 5
                mode = widget.findChild(QtWidgets.QComboBox, "archive_mode_filter")
                mode.setCurrentIndex(mode.findData("quick"))
                saved = widget.findChild(QtWidgets.QComboBox, "archive_snapshot_filter")
                saved.setCurrentIndex(saved.findData("current"))
                date = widget.findChild(QtWidgets.QDateEdit, "archive_date")
                widget.findChild(QtWidgets.QCheckBox, "archive_use_date").setChecked(
                    True
                )
                date.setDate(
                    QtCore.QDate.fromString(completed.started_at[:10], "yyyy-MM-dd")
                )
                button(widget, "查找").click()
                assert table.rowCount() == 1 and table.item(0, 1).text() == "快跑"
                saved.setCurrentIndex(saved.findData("unreadable"))
                button(widget, "查找").click()
                assert table.rowCount() == 0
                action = "返回登记"
            if title == "确认启动":
                assert "效能序列 B" in widget.text()
                assert "已有 5 场" in widget.informativeText()
            pending = next(actions, None)
            if pending:
                QtCore.QTimer.singleShot(40, tick)
            if action == "close":
                widget.close()
            else:
                button(widget, action).click()
        except Exception as exc:
            errors.append(exc)
            close_all()

    def close_stalled_dialogs():
        errors.append(RuntimeError(f"Timed out waiting for {pending}"))
        close_all()

    watchdog = QtCore.QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(close_stalled_dialogs)
    watchdog.start(10000)
    QtCore.QTimer.singleShot(40, tick)
    with (
        patch.object(operator_ui, "open_folder") as open_folder,
        patch.object(launcher, "check_devices", return_value="设备检查通过。") as check,
    ):
        operator_ui.run_operator_panel(
            root, start_session=start_session, check_devices=check, version="QA-version"
        )
        watchdog.stop()
        assert not errors, errors
        assert pending is None
        assert launches == [
            (INFO, mode) for mode in ("quick", "pilot", "quick", "quick")
        ]
        check.assert_called_once()
        assert open_folder.call_args.args[0] == completed.path


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("Run without Python optimization.")
    parser = argparse.ArgumentParser()
    parser.add_argument("--studio-ui", action="store_true")
    arguments = parser.parse_args()
    with TemporaryDirectory() as directory:
        root = Path(directory)
        verify_archive(root)
        verify_snapshot_states(root)
        verify_startup_checks(root)
        if arguments.studio_ui:
            verify_studio_dialogs(root)
    print("Operator checks passed.")
