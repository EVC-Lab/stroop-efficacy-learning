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
            getActualFrameRate=lambda **_: 1 / clock.frame_period,
            setMouseVisible=mouse_visible,
            close=lambda: closed_windows.append(True),
        )

    visual = SimpleNamespace(
        Window=window_factory,
        TextStim=VirtualStim,
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
        patch.object(task.core, "quit", side_effect=SystemExit),
        patch.object(task, "MouseClass", return_value=mouse),
        patch.object(launcher, "show_session_result") as result,
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
            launcher.run_registered(INFO, "quick", root, keyboard)
        with patch.object(task.StroopEfficacyExp, "wait_space", interrupted):
            launcher.run_registered(INFO, "pilot", root, keyboard)
            launcher.run_registered(INFO, "pilot", root, keyboard)
        with patch.object(
            task.StroopEfficacyExp,
            "wait_space",
            side_effect=RuntimeError("control failure"),
        ):
            try:
                launcher.run_registered(INFO, "formal", root, keyboard)
            except RuntimeError as exc:
                assert str(exc) == "control failure"
            else:
                raise AssertionError("Run exception was swallowed")
        with patch.object(task.StroopEfficacyExp, "wait_space", fail_on_end):
            try:
                launcher.run_registered(
                    {**INFO, "被试编号": end_failure_code}, "quick", root, keyboard
                )
            except RuntimeError as exc:
                assert str(exc) == "final screen failure"
            else:
                raise AssertionError("Final screen exception was swallowed")
        with patch.object(task.StroopEfficacyExp, "run", fail_in_interval):
            for code in partial_codes:
                try:
                    launcher.run_registered(
                        {**INFO, "被试编号": code}, "formal", root, keyboard
                    )
                except KeyboardInterrupt as exc:
                    assert str(exc) == "response wait interrupted"
                else:
                    raise AssertionError("Interval exception was swallowed")
        with (
            patch.object(
                visual, "TextStim", side_effect=RuntimeError("window setup failed")
            ),
            patch.object(keyboard, "stop") as stop_keyboard,
        ):
            try:
                launcher.run_registered(INFO, "pilot", root, keyboard)
            except RuntimeError as exc:
                assert str(exc) == "window setup failed"
            else:
                raise AssertionError("Startup failure was swallowed")
            stop_keyboard.assert_called_once()
            result.assert_called_with(None, CODE, "pilot", False)
    assert window_sizes == [False, False, True, True, True, False, True, True, True]
    assert result.call_count == 8 and len(closed_windows) == 9
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


def verify_studio_dialogs(root):
    """通过本机 Qt 事件循环操作真实登记对话框，无需实验参与者。"""
    from PyQt6 import QtCore, QtWidgets

    operator_ui.ensureQtApp()
    app = QtWidgets.QApplication.instance()
    actions = iter(
        [
            ("实验员登记", "invalid"),
            ("请核对参与者编码", "OK"),
            ("实验员登记", "valid"),
            ("查找场次", "返回登记"),
            ("实验员登记", "核对并启动"),
            ("确认启动", "返回修改"),
            ("实验员登记", "核对并启动"),
            ("确认启动", "确认重跑"),
        ]
    )
    pending = next(actions)
    error = []
    checks = []

    def tick():
        nonlocal pending
        widget = app.activeModalWidget()
        if widget is None or pending[0] not in widget.windowTitle():
            QtCore.QTimer.singleShot(50, tick)
            return
        action = pending[1]
        try:
            if action in ("invalid", "valid"):
                field = widget.findChild(QtWidgets.QLineEdit, "participant_code")
                field.setText("A/B" if action == "invalid" else CODE.lower())
                if action == "valid":
                    mode = widget.findChild(QtWidgets.QComboBox, "run_mode")
                    mode.setCurrentIndex(mode.findData("quick"))
                    path = widget.findChild(QtWidgets.QLabel, "archive_path")
                    assert str(root / "quick" / CODE) == path.text()
                action = "核对并启动" if action == "invalid" else "查找场次"
            if widget.windowTitle() == "查找场次":
                table = widget.findChild(QtWidgets.QTableWidget, "archive_sessions")
                assert table.rowCount() == 5
            if widget.windowTitle() == "确认启动":
                assert "效能序列 B" in widget.text()
                assert "已有 5 场" in widget.informativeText()
            button = next(
                child
                for child in widget.findChildren(QtWidgets.QPushButton)
                if child.text().replace("&", "") == action
            )
            checks.append(action)
            pending = next(actions, None)
            if pending:
                QtCore.QTimer.singleShot(50, tick)
            button.click()
        except Exception as exc:
            error.append(exc)
            for dialog in app.topLevelWidgets():
                dialog.close()

    def close_stalled_dialogs():
        if pending is not None:
            error.append(RuntimeError(f"Timed out waiting for {pending}"))
            for dialog in app.topLevelWidgets():
                dialog.close()

    watchdog = QtCore.QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(close_stalled_dialogs)
    watchdog.start(10000)
    QtCore.QTimer.singleShot(50, tick)
    result = operator_ui.ask_registration(root)
    watchdog.stop()
    assert not error, error
    assert result == (INFO, "quick") and len(checks) == 8

    completed = next(
        entry for entry in archive.list_sessions(root, CODE) if entry.mode == "quick"
    )

    def inspect_result():
        dialog = app.activeModalWidget()
        try:
            assert dialog.windowTitle() == "本场保存结果"
            assert "已完成" in dialog.text()
            assert "完整区段数  12" in dialog.informativeText()
            assert str(completed.path) in dialog.informativeText()
            folder = next(
                button for button in dialog.buttons() if button.text() == "打开场次目录"
            )
            folder.click()
        except Exception as exc:
            error.append(exc)
        finally:
            if dialog:
                dialog.close()

    with patch.object(operator_ui, "open_folder") as open_folder:
        QtCore.QTimer.singleShot(50, inspect_result)
        operator_ui.show_session_result(completed.path, CODE, "quick")
        assert not error, error
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
        if arguments.studio_ui:
            verify_studio_dialogs(root)
    print("Operator checks passed.")
