"""PsychoPy Studio 启动登记、场次查询及保存结果。"""

from PyQt6 import QtCore, QtGui, QtWidgets
from psychopy.gui.qtgui import ensureQtApp

from .archive import (
    MODES,
    STATUS,
    describe_session,
    list_sessions,
    participant_code,
    performance_first,
)


def open_folder(path, parent):
    if not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path))):
        QtWidgets.QMessageBox.warning(parent, "无法打开目录", str(path))


def plain_label(value):
    label = QtWidgets.QLabel(value)
    label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


def browse_sessions(root, initial_code, parent):
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle("查找场次")
    dialog.resize(860, 420)
    layout = QtWidgets.QVBoxLayout(dialog)
    search = QtWidgets.QHBoxLayout()
    label = QtWidgets.QLabel("参与者编码")
    field = QtWidgets.QLineEdit(initial_code)
    field.setObjectName("archive_code")
    label.setBuddy(field)
    search_button = QtWidgets.QPushButton("查找")
    search.addWidget(label)
    search.addWidget(field, 1)
    search.addWidget(search_button)
    layout.addLayout(search)
    table = QtWidgets.QTableWidget(0, 5)
    table.setObjectName("archive_sessions")
    table.setHorizontalHeaderLabels(
        ["参与者编码", "模式", "状态", "完整区段", "开始时间"]
    )
    table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
    table.horizontalHeader().setStretchLastSection(True)
    layout.addWidget(table)
    location = plain_label("")
    layout.addWidget(location)
    buttons = QtWidgets.QHBoxLayout()
    folder = QtWidgets.QPushButton("打开场次目录")
    close = QtWidgets.QPushButton("返回登记")
    buttons.addStretch()
    buttons.addWidget(folder)
    buttons.addWidget(close)
    layout.addLayout(buttons)
    entries = []

    def select():
        row = table.currentRow()
        folder.setEnabled(row >= 0)
        location.setText(str(entries[row].path) if row >= 0 else "没有匹配场次")

    def refresh():
        nonlocal entries
        try:
            entries = list_sessions(root, field.text().strip())
        except OSError as exc:
            QtWidgets.QMessageBox.warning(dialog, "无法读取场次目录", str(exc))
            return
        with QtCore.QSignalBlocker(table):
            table.setRowCount(len(entries))
            for row, entry in enumerate(entries):
                values = (
                    entry.code,
                    MODES.get(entry.mode, "旧版"),
                    STATUS.get(entry.status, "需核对"),
                    str(entry.completed),
                    entry.started_at or "—",
                )
                for column, value in enumerate(values):
                    table.setItem(row, column, QtWidgets.QTableWidgetItem(value))
            if entries:
                table.selectRow(0)
            else:
                table.setCurrentCell(-1, -1)
        table.resizeColumnsToContents()
        select()

    table.itemSelectionChanged.connect(select)
    folder.clicked.connect(
        lambda: open_folder(entries[table.currentRow()].path, dialog)
    )
    close.clicked.connect(dialog.accept)
    search_button.clicked.connect(refresh)
    field.returnPressed.connect(refresh)
    refresh()
    dialog.exec()


def ask_registration(root):
    ensureQtApp()
    dialog = QtWidgets.QDialog()
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
    layout.addLayout(form)
    layout.addWidget(detail)
    buttons = QtWidgets.QHBoxLayout()
    history = QtWidgets.QPushButton("查找场次")
    cancel = QtWidgets.QPushButton("取消")
    start = QtWidgets.QPushButton("核对并启动")
    buttons.addWidget(history)
    buttons.addStretch()
    buttons.addWidget(cancel)
    buttons.addWidget(start)
    layout.addLayout(buttons)
    registration = None

    def update_preview():
        mode = mode_field.currentData()
        try:
            code = participant_code(code_field.text())
        except ValueError:
            code = None
        destination = root / mode if mode else root
        path.setText(str(destination / code if code and mode else destination))
        detail.setText(
            "窗口模式，12 个区段，仅供检查流程。"
            if mode == "quick"
            else ("完整流程，288 个区段，全屏运行。" if mode else "")
        )

    def confirm():
        nonlocal registration
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
            registration = ({"被试编号": code, "漂移方向": direction}, mode)
            dialog.accept()

    code_field.textChanged.connect(update_preview)
    mode_field.currentIndexChanged.connect(update_preview)
    history.clicked.connect(
        lambda: browse_sessions(root, code_field.text().strip(), dialog)
    )
    cancel.clicked.connect(dialog.reject)
    start.clicked.connect(confirm)
    start.setDefault(True)
    code_field.setFocus()
    dialog.exec()
    return registration


def show_session_result(path, code, mode, save_failed=False):
    ensureQtApp()
    message = QtWidgets.QMessageBox()
    message.setWindowTitle("本场保存结果")
    message.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    if path is None:
        message.setText("本场未创建数据目录。")
    else:
        entry = describe_session(path, code, mode)
        status = STATUS.get(entry.status, "需核对")
        message.setText(f"{code} · {MODES[mode]} · {status}")
        summary = f"完整区段数  {entry.completed}\n保存位置  {path}"
        if entry.status == "recovery":
            summary += "\n上一份可核对的记录在 .previous.zip。"
        if save_failed:
            summary += "\n本次结束时未能保存，请核对场次文件。"
        message.setInformativeText(summary)
        folder = message.addButton(
            "打开场次目录", QtWidgets.QMessageBox.ButtonRole.ActionRole
        )
        folder.clicked.connect(lambda: open_folder(path, message))
    message.addButton("关闭", QtWidgets.QMessageBox.ButtonRole.RejectRole)
    message.exec()
