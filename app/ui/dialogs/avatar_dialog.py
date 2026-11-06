"""智能体资料窗口：看她是谁、换她的头像。

头像存 entity/config/avatar.png；换完 emit changed，侧栏卡片自己刷新。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from ...core import framework_setup
from ...services import avatar
from ..widgets.avatar_card import rounded_pixmap


class AvatarDialog(QDialog):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("智能体资料")
        self.setMinimumWidth(420)

        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        self.pic = QLabel(objectName="AvatarBig")
        self.pic.setFixedSize(160, 160)
        self.pic.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.pic, 0, Qt.AlignHCenter)

        self.name_label = QLabel("", objectName="AvatarName")
        self.name_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.name_label)

        form = QFormLayout()
        form.setSpacing(8)
        self.lb_model = QLabel("", objectName="Muted")
        self.lb_avatar = QLabel("", objectName="Muted")
        self.lb_avatar.setWordWrap(True)
        form.addRow("模型", self.lb_model)
        form.addRow("头像", self.lb_avatar)
        lay.addLayout(form)

        self.hint = QLabel("", objectName="Muted")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)

        row = QHBoxLayout()
        self.btn_pick = QPushButton("更换头像…", objectName="Primary")
        self.btn_pick.clicked.connect(self._pick)
        self.btn_reset = QPushButton("恢复默认")
        self.btn_reset.clicked.connect(self._reset)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.accept)
        row.addWidget(self.btn_pick)
        row.addWidget(self.btn_reset)
        row.addStretch(1)
        row.addWidget(self.btn_close)
        lay.addLayout(row)

        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        one = avatar.info()
        self.name_label.setText(framework_setup.display_name())
        self.lb_model.setText(str(framework_setup.read_llm().get("model") or "（未设置）"))
        if one["custom"]:
            when = one.get("updated_at") or "最近"
            self.lb_avatar.setText(f"主人换的（{when}）")
            self.btn_reset.setEnabled(True)
        else:
            self.lb_avatar.setText("默认的灰发头像")
            self.btn_reset.setEnabled(False)
        pm = avatar.pixmap(160)
        if not pm.isNull():
            self.pic.setPixmap(rounded_pixmap(pm, 160, 22))

    def _pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选一张头像", str(Path.home()),
            "图片 (*.png *.jpg *.jpeg *.bmp *.webp *.gif)")
        if not path:
            return
        try:
            avatar.set_from_file(path)
        except ValueError as e:
            self.hint.setText(str(e))
            return
        except Exception as e:  # noqa: BLE001
            self.hint.setText(f"换头像失败：{e}")
            return
        self.hint.setText("换好了。智能体下一句话就会知道自己换了样子。")
        self.refresh()
        self.changed.emit()

    def _reset(self) -> None:
        avatar.reset()
        self.hint.setText("已恢复默认的灰发头像。")
        self.refresh()
        self.changed.emit()
