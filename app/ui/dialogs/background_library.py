"""背景图片内部库：缩略图选图、导入、删除。

只服务启动器外观，不进智能体提示词；导入即复制，选完不用再找原文件。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QLabel, QListView,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)

from ...services import bg_library

IMAGE_FILTER = "图片 (*.png *.jpg *.jpeg *.bmp *.webp *.gif)"


def _human(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


class BackgroundLibraryDialog(QDialog):
    def __init__(self, parent=None, current: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("背景图片库")
        self.setModal(True)
        self.resize(760, 540)
        self._current = str(current or "")
        self._last_dir = ""
        self._chosen = ""
        self._deleted_current = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        lay.addWidget(QLabel("背景图片库", objectName="CardTitle"))
        tip = QLabel(
            "导入后会复制进库里，以后换背景直接从这里挑，不用再找原文件。"
            "只收图片；库随安装目录一起备份。", objectName="Muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        self.lst = QListWidget(objectName="BgLibList")
        self.lst.setViewMode(QListView.IconMode)
        self.lst.setResizeMode(QListView.Adjust)
        self.lst.setMovement(QListView.Static)
        self.lst.setIconSize(QSize(176, 116))
        self.lst.setGridSize(QSize(196, 168))
        self.lst.setSpacing(6)
        self.lst.setWordWrap(True)
        self.lst.setSelectionMode(QAbstractItemView.SingleSelection)
        self.lst.itemSelectionChanged.connect(self._sync_buttons)
        self.lst.itemDoubleClicked.connect(lambda _it: self._use())
        lay.addWidget(self.lst, 1)

        self.empty = QLabel(
            "库还是空的。点「导入图片」把喜欢的图放进来；导入会复制一份，"
            "原图挪走也不影响。", objectName="Muted")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setMinimumHeight(120)
        lay.addWidget(self.empty, 1)

        self.count = QLabel("", objectName="Muted")
        lay.addWidget(self.count)

        row = QHBoxLayout()
        self.btn_import = QPushButton("导入图片…", objectName="Ghost")
        self.btn_import.clicked.connect(self._import)
        row.addWidget(self.btn_import)
        row.addStretch(1)
        self.btn_delete = QPushButton("删除", objectName="Ghost")
        self.btn_delete.clicked.connect(self._delete)
        row.addWidget(self.btn_delete)
        self.btn_use = QPushButton("使用这张", objectName="Primary")
        self.btn_use.clicked.connect(self._use)
        row.addWidget(self.btn_use)
        self.btn_cancel = QPushButton("取消", objectName="Ghost")
        self.btn_cancel.clicked.connect(self.reject)
        row.addWidget(self.btn_cancel)
        lay.addLayout(row)

        self.refresh()

    # ---- 数据 -----------------------------------------------------------
    def refresh(self) -> None:
        keep = self._current_id()
        self.lst.clear()
        items = bg_library.list_items()
        for it in items:
            path = Path(str(it.get("path") or ""))
            icon = QIcon()
            if path.is_file():
                img = QImage(str(path))
                if not img.isNull():
                    icon = QIcon(QPixmap.fromImage(
                        img.scaled(176, 116, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            item = QListWidgetItem(icon, str(it.get("name") or path.name or "图片"))
            item.setData(Qt.UserRole, str(it.get("id") or ""))
            item.setToolTip(f"{path}\n{_human(int(it.get('bytes') or 0))}")
            if not path.is_file():
                item.setText(f"{item.text()}（文件丢了）")
            self.lst.addItem(item)

        has = bool(items)
        self.lst.setVisible(has)
        self.empty.setVisible(not has)
        try:
            n, b = len(items), sum(int(i.get("bytes") or 0) for i in items)
            self.count.setText(f"共 {n} 张，约 {_human(b)}" if n else "")
        except (TypeError, ValueError):
            self.count.setText("")
        if keep:
            self._select_id(keep)
        elif has:
            self.lst.setCurrentRow(0)
        self._sync_buttons()

    def _current_id(self) -> str:
        it = self.lst.currentItem()
        return str(it.data(Qt.UserRole) or "") if it else ""

    def _select_id(self, item_id: str) -> None:
        for i in range(self.lst.count()):
            it = self.lst.item(i)
            if str(it.data(Qt.UserRole) or "") == str(item_id):
                self.lst.setCurrentItem(it)
                return

    def _selected(self) -> dict | None:
        item_id = self._current_id()
        return bg_library.get(item_id) if item_id else None

    def _sync_buttons(self, *_args) -> None:
        ok = self._selected() is not None
        self.btn_use.setEnabled(ok)
        self.btn_delete.setEnabled(ok)

    # ---- 动作 -----------------------------------------------------------
    def _import(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "导入背景图片", self._last_dir or str(Path.home()), IMAGE_FILTER)
        if not paths:
            return
        self._last_dir = str(Path(paths[0]).parent)
        errors: list[str] = []
        last_id = ""
        for p in paths:
            try:
                row = bg_library.import_file(p)
                last_id = str(row.get("id") or "")
            except (ValueError, OSError) as e:
                errors.append(f"{Path(p).name}：{e}")
        self.refresh()
        if last_id:
            self._select_id(last_id)
        if errors:
            QMessageBox.warning(self, "有图片没导进来", "\n".join(errors[:6]))

    def _use(self) -> None:
        row = self._selected()
        if not row:
            return
        bg_library.touch(str(row["id"]))
        self._chosen = str(row.get("path") or "")
        self.accept()

    def _delete(self) -> None:
        row = self._selected()
        if not row:
            return
        name = str(row.get("name") or "这张图")
        if QMessageBox.question(
                self, "删除图片", f"从库里删掉「{name}」？\n原图如果还在，不会被删。",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        if bg_library.remove(str(row["id"])):
            try:
                if self._current and Path(self._current).resolve() == Path(str(row["path"])).resolve():
                    self._deleted_current = True
            except OSError:
                pass
            self.refresh()

    # ---- 结果 -----------------------------------------------------------
    def chosen_path(self) -> str:
        return self._chosen

    def deleted_current(self) -> bool:
        return self._deleted_current
