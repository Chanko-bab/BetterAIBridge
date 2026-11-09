"""仓库查看器：使用者能看到智能体收着的东西，也能删。"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from app.services import warehouse


def _size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


def _when(ts) -> str:
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%m-%d %H:%M")
    except (OSError, ValueError, TypeError):
        return ""


class WarehouseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("仓库")
        self.resize(820, 560)
        self._rows: list[dict] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(QLabel("仓库", objectName="CardTitle"))
        self.lbl = QLabel("", objectName="Muted")
        head.addWidget(self.lbl, 1)
        self.cb_lib = QComboBox()
        self.cb_lib.setMinimumWidth(180)
        self.cb_lib.currentIndexChanged.connect(self.reload)
        head.addWidget(self.cb_lib)
        outer.addLayout(head)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["文件", "类型", "来源", "说明", "大小 / 时间"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 240)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 300)
        self.table.doubleClicked.connect(lambda _i: self.open_item())
        outer.addWidget(self.table, 1)

        row = QHBoxLayout()
        self.btn_open = QPushButton("打开", objectName="Ghost")
        self.btn_open.clicked.connect(self.open_item)
        self.btn_del = QPushButton("删除", objectName="Danger")
        self.btn_del.clicked.connect(self.delete_item)
        btn_refresh = QPushButton("刷新", objectName="Ghost")
        btn_refresh.clicked.connect(self.reload)
        btn_close = QPushButton("关闭", objectName="Ghost")
        btn_close.clicked.connect(self.accept)
        row.addWidget(self.btn_open)
        row.addWidget(self.btn_del)
        row.addStretch(1)
        row.addWidget(btn_refresh)
        row.addWidget(btn_close)
        outer.addLayout(row)

        self.reload()

    def _lib(self) -> str:
        return str(self.cb_lib.currentData() or "")

    def reload(self) -> None:
        keep = self._lib()
        self.cb_lib.blockSignals(True)
        self.cb_lib.clear()
        self.cb_lib.addItem("全部库", "")
        for lib in warehouse.libraries():
            title = str(lib.get("title") or lib.get("id"))
            self.cb_lib.addItem(f"{title}（{lib.get('count', 0)}）", lib.get("id"))
        idx = self.cb_lib.findData(keep)
        self.cb_lib.setCurrentIndex(max(0, idx))
        self.cb_lib.blockSignals(False)

        try:
            self._rows = warehouse.list_items(library=self._lib() or None)
        except (OSError, ValueError):
            self._rows = []
        self.table.setRowCount(len(self._rows))
        for i, row in enumerate(self._rows):
            self.table.setItem(i, 0, QTableWidgetItem(str(row.get("title") or row.get("name") or "")))
            self.table.setItem(i, 1, QTableWidgetItem(str(row.get("kind") or "")))
            self.table.setItem(i, 2, QTableWidgetItem(str(row.get("library") or row.get("source") or "")))
            desc = str(row.get("desc") or "")
            if row.get("kept"):
                desc = "〔收着〕" + desc
            self.table.setItem(i, 3, QTableWidgetItem(desc[:160]))
            meta = f"{_size(int(row.get('bytes') or 0))} · {_when(row.get('at'))}"
            self.table.setItem(i, 4, QTableWidgetItem(meta))
        self.lbl.setText(f"{len(self._rows)} 件 · 共 {_size(sum(int(r.get('bytes') or 0) for r in self._rows))}")

    def _current(self) -> dict | None:
        i = self.table.currentRow()
        if i < 0 or i >= len(self._rows):
            return None
        return self._rows[i]

    def open_item(self) -> None:
        row = self._current()
        if not row:
            return
        path = str(row.get("path") or "")
        if not path:
            path = str(warehouse.get(str(row.get("id")), with_path=True).get("path") or "")
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def delete_item(self) -> None:
        row = self._current()
        if not row:
            return
        name = str(row.get("title") or row.get("name") or "这一条")
        if QMessageBox.question(
            self, "删除仓库条目",
            f"把「{name}」从仓库里删掉？\n文件会真的删除；如果它被收进收藏，收藏里那份还在。",
        ) != QMessageBox.Yes:
            return
        try:
            warehouse.remove(str(row.get("id")))
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "删除失败", str(e))
            return
        self.reload()
