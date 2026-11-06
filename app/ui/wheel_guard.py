"""滚轮防误触：设置/外观页的数值控件不再被滚轮改值。

滚轮事件仍然交给页面的滚动条，保证「滚页面」这件事本身不被吃掉。
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QComboBox, QDial, QScrollArea, QSlider,
    QWidget,
)

GUARDED = (QAbstractSpinBox, QComboBox, QSlider, QDial)


class _Guard(QObject):
    def __init__(self, scroll: QScrollArea | None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._scroll = scroll

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:  # noqa: N802
        if ev.type() != QEvent.Wheel or not isinstance(obj, GUARDED):
            return False
        # 不把滚轮交给控件自己（否则会改值）；转给滚动条，页面照常滚。
        if self._scroll is not None:
            QApplication.sendEvent(self._scroll.verticalScrollBar(), ev)
        ev.accept()
        return True


def install(page: QWidget, scroll: QScrollArea | None = None) -> None:
    """给页面里现有的数值控件装滚轮保护；guard 挂在 page 上防止被回收。"""
    guard = _Guard(scroll, page)
    page._wheel_guard = guard  # type: ignore[attr-defined]
    for child in page.findChildren(QWidget):
        if isinstance(child, GUARDED):
            child.installEventFilter(guard)
