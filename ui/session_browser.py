"""按参与者编码、模式、日期和保存状态查找本地场次。"""

from PyQt6 import QtCore, QtWidgets

from stroop_efficacy.archive import MODES, SNAPSHOT_STATUS, STATUS, list_sessions

from .common import open_folder, plain_label


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
    filters = QtWidgets.QHBoxLayout()
    mode = QtWidgets.QComboBox()
    mode.setObjectName("archive_mode_filter")
    mode.addItem("全部模式", "")
    for key, name in {**MODES, "legacy": "旧版"}.items():
        mode.addItem(name, key)
    saved = QtWidgets.QComboBox()
    saved.setObjectName("archive_snapshot_filter")
    saved.addItem("全部保存状态", "")
    for key, name in SNAPSHOT_STATUS.items():
        saved.addItem(name, key)
    use_date = QtWidgets.QCheckBox("按开始日期")
    use_date.setObjectName("archive_use_date")
    day = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
    day.setObjectName("archive_date")
    day.setDisplayFormat("yyyy-MM-dd")
    day.setCalendarPopup(True)
    day.setEnabled(False)
    use_date.toggled.connect(day.setEnabled)
    filters.addWidget(mode)
    filters.addWidget(saved)
    filters.addWidget(use_date)
    filters.addWidget(day)
    filters.addStretch()
    layout.addLayout(filters)
    table = QtWidgets.QTableWidget(0, 6)
    table.setObjectName("archive_sessions")
    table.setHorizontalHeaderLabels(
        ["参与者编码", "模式", "任务状态", "保存状态", "完整区段", "开始时间"]
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
        if row < 0:
            location.setText("没有匹配场次")
            return
        entry = entries[row]
        location.setText(
            f"会话编号  {entry.session_id}\n"
            f"任务版本  {entry.version or '未记录'}\n"
            f"结束时间  {entry.finished_at or '未记录'}\n"
            f"保存位置  {entry.path}"
        )

    def refresh():
        nonlocal entries
        try:
            matches = list_sessions(root, field.text().strip())
        except OSError as exc:
            QtWidgets.QMessageBox.warning(dialog, "无法读取场次目录", str(exc))
            return
        mode_filter = mode.currentData()
        snapshot_filter = saved.currentData()
        date_filter = day.date().toString("yyyy-MM-dd") if use_date.isChecked() else ""
        entries = [
            entry
            for entry in matches
            if (not mode_filter or entry.mode == mode_filter)
            and (not snapshot_filter or entry.snapshot == snapshot_filter)
            and (not date_filter or entry.started_at[:10] == date_filter)
        ]
        with QtCore.QSignalBlocker(table):
            table.setRowCount(len(entries))
            for row, entry in enumerate(entries):
                values = (
                    entry.code,
                    MODES.get(entry.mode, "旧版"),
                    "待核对" if entry.status == "recovery" else STATUS[entry.status],
                    SNAPSHOT_STATUS[entry.snapshot],
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
