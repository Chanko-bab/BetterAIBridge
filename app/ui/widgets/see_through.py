"""让 QScrollArea 的 viewport 透明，但不把样式级联到卡片上。"""
from __future__ import annotations

from PySide6.QtGui import QPalette
from PySide6.QtCore import Qt


def see_through(scroll) -> None:
    vp = scroll.viewport()
    vp.setAutoFillBackground(False)
    pal = vp.palette()
    pal.setColor(QPalette.Base, Qt.transparent)
    pal.setColor(QPalette.Window, Qt.transparent)
    vp.setPalette(pal)
    scroll.setStyleSheet(
        "QScrollArea { background: transparent; border: none; }"
        "QScrollArea > QWidget > QWidget { background: transparent; }"
    )


def see_through_widget(widget) -> None:
    """把滚动区里承载卡片的那层 QWidget 也变透明（QScrollArea 会替它铺底色）。"""
    widget.setAutoFillBackground(False)
    widget.setAttribute(Qt.WA_TranslucentBackground, True)
    pal = widget.palette()
    pal.setColor(QPalette.Base, Qt.transparent)
    pal.setColor(QPalette.Window, Qt.transparent)
    widget.setPalette(pal)
