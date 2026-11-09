"""聊天里的图片/文件气泡：能看、能点开，不自动执行。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from .. import fonts


def _size_text(n: int) -> str:
    n = int(n or 0)
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


class MediaBubble(QFrame):
    """一条仓库附件。图片给缩略图，其它给文件名；点一下用系统程序打开。"""

    def __init__(self, media: dict, text: str = "", who: str = "her", parent=None) -> None:
        super().__init__(parent)
        self.media = dict(media or {})
        self.setObjectName("MediaBubbleMe" if who == "me" else "MediaBubbleHer")
        self.setCursor(Qt.PointingHandCursor)
        self.setMaximumWidth(fonts.ui_px(360))
        path = Path(str(self.media.get("path") or ""))
        exists = bool(path) and path.is_file()
        kind = str(self.media.get("kind") or "file")
        name = str(self.media.get("name") or path.name or "文件")
        self.setToolTip(str(path) if exists else "文件已经不在仓库里了")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(fonts.ui_px(10), fonts.ui_px(8),
                               fonts.ui_px(10), fonts.ui_px(8))
        lay.setSpacing(fonts.ui_px(5))

        if kind == "image" and exists:
            pix = QPixmap(str(path))
            if not pix.isNull():
                pix = pix.scaled(fonts.ui_px(260), fonts.ui_px(180),
                                 Qt.KeepAspectRatio, Qt.SmoothTransformation)
                img = QLabel()
                img.setPixmap(pix)
                img.setAlignment(Qt.AlignCenter)
                lay.addWidget(img)
        row = QHBoxLayout()
        row.setSpacing(fonts.ui_px(6))
        icon = QLabel("🖼" if kind == "image" else "📄")
        icon.setObjectName("MediaIcon")
        row.addWidget(icon)
        title = QLabel(name)
        title.setObjectName("MediaName")
        title.setTextInteractionFlags(Qt.NoTextInteraction)
        row.addWidget(title, 1)
        lay.addLayout(row)
        meta = QLabel(("图片" if kind == "image" else "文件") + " · "
                      + _size_text(int(self.media.get("bytes") or 0))
                      + ("" if exists else " · 已不在仓库"))
        meta.setObjectName("MediaMeta")
        lay.addWidget(meta)
        if text:
            cap = QLabel(text)
            cap.setObjectName("MediaCaption")
            cap.setWordWrap(True)
            lay.addWidget(cap)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        path = Path(str(self.media.get("path") or ""))
        if event.button() == Qt.LeftButton and path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        super().mousePressEvent(event)
