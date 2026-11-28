"""实验员界面共用的标签和目录入口。"""

from PyQt6 import QtCore, QtGui, QtWidgets


def open_folder(path, parent):
    if not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path))):
        QtWidgets.QMessageBox.warning(parent, "无法打开目录", str(path))


def plain_label(value):
    label = QtWidgets.QLabel(value)
    label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label
