"""侧栏顶部的头像卡：方形头像 + 名字，点头像开资料窗口。

为什么不是圆形：用户要的是一块「方形区域」，头像方、名字在下；
圆角只做视觉柔化，不做裁圆。
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ...services import avatar


def rounded_pixmap(pm: QPixmap, size: int, radius: int = 14) -> QPixmap:
    """把图裁成圆角方形；空图返回空。"""
    if pm.isNull():
        return pm
    side = min(pm.width(), pm.height())
    src = pm.copy((pm.width() - side) // 2, (pm.height() - side) // 2, side, side)
    src = src.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setClipPath(path)
    p.drawPixmap(0, 0, src)
    p.end()
    return out


class AvatarCard(QWidget):
    """方形头像 + 下面的名字；整块可点。"""

    clicked = Signal()

    def __init__(self, name: str = "", size: int = 96, parent=None) -> None:
        super().__init__(parent)
        self._size = int(size)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("查看智能体资料 / 更换头像")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.pic = QLabel(objectName="AvatarCard")
        self.pic.setFixedSize(self._size, self._size)
        self.pic.setAlignment(Qt.AlignCenter)
        self.pic.setScaledContents(False)
        lay.addWidget(self.pic, 0, Qt.AlignHCenter)

        self.name_label = QLabel(name, objectName="AvatarName")
        self.name_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.name_label)

        self.refresh(name)

    def refresh(self, name: str | None = None) -> None:
        if name is not None:
            self.name_label.setText(str(name or ""))
        pm = avatar.pixmap(self._size)
        if not pm.isNull():
            self.pic.setPixmap(rounded_pixmap(pm, self._size))

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
            e.accept()
            return
        super().mousePressEvent(e)
