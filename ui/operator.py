"""常驻实验员登记与场次结果界面。"""

from PyQt6 import QtCore, QtWidgets
from psychopy.gui.qtgui import ensureQtApp

from stroop_efficacy.archive import (
    MODES,
    SNAPSHOT_STATUS,
    STATUS,
    describe_session,
    list_sessions,
    participant_code,
    performance_first,
)

from .common import open_folder, plain_label
from .session_browser import browse_sessions


class OperatorDialog(QtWidgets.QDialog):
    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_Escape:
            event.accept()
            return
        super().keyPressEvent(event)


def run_operator_panel(root, *, start_session, check_devices, version):
    ensureQtApp()
    dialog = OperatorDialog()
    dialog.setWindowTitle("色词 Stroop · 实验员登记")
    dialog.setMinimumWidth(520)
    layout = QtWidgets.QVBoxLayout(dialog)
    form = QtWidgets.QFormLayout()
    code_field = QtWidgets.QLineEdit()
    code_field.setObjectName("participant_code")
    code_field.setPlaceholderText("例如 S012，使用编号")
    mode_field = QtWidgets.QComboBox()
    mode_field.setObjectName("run_mode")
    mode_field.addItem("请选择运行模式", "")
    for mode, label in MODES.items():
        mode_field.addItem(label, mode)
    direction_field = QtWidgets.QComboBox()
    direction_field.setObjectName("sequence_assignment")
    direction_field.addItem("自动（按编号最后一个数字）", "自动")
    direction_field.addItem("手动指定 A", "正向")
    direction_field.addItem("手动指定 B", "反向")
    detail = plain_label("")
    path = plain_label(str(root))
    path.setObjectName("archive_path")
    form.addRow("参与者编码", code_field)
    form.addRow("运行模式", mode_field)
    form.addRow("序列分配", direction_field)
    form.addRow("保存位置", path)
    form.addRow("任务版本", plain_label(version))
    layout.addLayout(form)
    layout.addWidget(detail)
    buttons = QtWidgets.QHBoxLayout()
    history = QtWidgets.QPushButton("查找场次")
    devices = QtWidgets.QPushButton("设备检查")
    start = QtWidgets.QPushButton("核对并启动")
    buttons.addWidget(history)
    buttons.addWidget(devices)
    buttons.addStretch()
    buttons.addWidget(start)
    layout.addLayout(buttons)
    notice = plain_label("")
    layout.addWidget(notice)
    latest = QtWidgets.QGroupBox("最近一场")
    latest_layout = QtWidgets.QVBoxLayout(latest)
    result_label = plain_label("")
    result_label.setObjectName("session_result")
    result_label.setTextInteractionFlags(
        QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
    )
    latest_layout.addWidget(result_label)
    folder = QtWidgets.QPushButton("打开场次目录")
    latest_layout.addWidget(folder, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
    layout.addWidget(latest)
    latest.hide()
    last_path = None

    def run_in_task_window(action, *args):
        dialog.setEnabled(False)
        dialog.showMinimized()
        try:
            return action(*args)
        finally:
            dialog.setEnabled(True)
            dialog.showNormal()
            dialog.raise_()
            dialog.activateWindow()

    def show_device_check():
        try:
            notice.setText(run_in_task_window(check_devices))
        except (Exception, KeyboardInterrupt) as exc:
            notice.setText(f"设备检查未能完成。请检查显示和 PTB 键盘后重试。{exc}")

    def show_result(result, code, mode):
        nonlocal last_path
        last_path = result.path
        outcome = (
            "启动失败" if result.status == "startup_failed" else STATUS[result.status]
        )
        lines = [f"{code} · {MODES[mode]} · {outcome}"]
        if last_path is None:
            lines.append("本场没有可校验的存档。")
        else:
            entry = describe_session(last_path, code, mode)
            lines += [
                f"会话编号  {entry.session_id}",
                f"完整区段数  {entry.completed}",
                f"保存状态  {SNAPSHOT_STATUS[entry.snapshot]}",
                f"保存位置  {last_path}",
            ]
            if result.save_failed:
                lines.append("结束时的保存失败。上方状态仅反映当前可读取的记录。")
            if result.status == "completed" and entry.snapshot == "current":
                code_field.clear()
                direction_field.setCurrentIndex(0)
        if result.detail:
            lines.append(result.detail)
        result_label.setText("\n".join(lines))
        folder.setVisible(last_path is not None)
        latest.show()
        code_field.setFocus()
        code_field.selectAll()

    def update_preview():
        mode = mode_field.currentData()
        try:
            code = participant_code(code_field.text())
        except ValueError:
            code = None
        destination = root / mode if mode else root
        path.setText(str(destination / code if code and mode else destination))
        instructions = ""
        if mode:
            instructions = (
                "窗口模式，12 个区段，仅供检查流程。"
                if mode == "quick"
                else "完整流程，288 个区段，全屏运行。"
            )
        if code:
            direction = direction_field.currentData()
            sequence = "B" if performance_first(code, direction) else "A"
            instructions += f" 效能序列 {sequence}。"
        detail.setText(instructions.strip())

    def confirm():
        try:
            code = participant_code(code_field.text())
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(dialog, "请核对参与者编码", str(exc))
            code_field.setFocus()
            return
        mode = mode_field.currentData()
        if not mode:
            QtWidgets.QMessageBox.warning(
                dialog, "请选择运行模式", "请选择正式采集、预测试或快跑。"
            )
            mode_field.setFocus()
            return
        direction = direction_field.currentData()
        sequence = "B" if performance_first(code, direction) else "A"
        try:
            previous = list_sessions(root, code)
        except OSError as exc:
            QtWidgets.QMessageBox.warning(dialog, "无法读取场次目录", str(exc))
            return
        message = QtWidgets.QMessageBox(dialog)
        message.setWindowTitle("确认启动")
        message.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        message.setText(f"{code} · {MODES[mode]} · 效能序列 {sequence}")
        summary = [f"保存位置  {root / mode / code}"]
        if previous:
            summary.append(f"该编码已有 {len(previous)} 场。本次将创建新会话。")
            for entry in previous[:4]:
                label = MODES.get(entry.mode, "旧版")
                status = STATUS.get(entry.status, "需核对")
                summary.append(
                    f"{entry.started_at or '时间未记录'}  {label}  {status}  {entry.completed} 段"
                )
            if len(previous) > 4:
                summary.append("可在「查找场次」查看其余记录。")
        message.setInformativeText("\n".join(summary))
        back = message.addButton(
            "返回修改", QtWidgets.QMessageBox.ButtonRole.RejectRole
        )
        begin = message.addButton(
            "确认重跑" if previous else "确认启动",
            QtWidgets.QMessageBox.ButtonRole.AcceptRole,
        )
        message.setDefaultButton(back)
        message.exec()
        if message.clickedButton() == begin:
            info = {"被试编号": code, "漂移方向": direction}
            result = run_in_task_window(start_session, info, mode)
            show_result(result, code, mode)

    code_field.textChanged.connect(update_preview)
    mode_field.currentIndexChanged.connect(update_preview)
    direction_field.currentIndexChanged.connect(update_preview)
    history.clicked.connect(
        lambda: browse_sessions(root, code_field.text().strip(), dialog)
    )
    devices.clicked.connect(show_device_check)
    folder.clicked.connect(lambda: open_folder(last_path, dialog))
    start.clicked.connect(confirm)
    start.setDefault(True)
    code_field.setFocus()
    dialog.exec()
