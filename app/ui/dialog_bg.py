"""给启动器的弹窗统一铺默认白底图（0.5.1）。

安装向导、首次建档、钥匙、二维码、保姆小屋……都是 QDialog，一个个改样式太容易漏；
这里在 QApplication 上装一个事件过滤器，第一次显示时统一铺 assets/bab-bg.jpg。
卡片自己仍是白底，图片只在窗口最底层。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QDialog

from ..core import config

_PROP = "_bab_dialog_bg"


def background_file() -> Path:
    """内置白底图；跟启动器背景用同一张。"""
    return Path(config.APP_DIR) / "assets" / "bab-bg.jpg"


def stylesheet_for(path: Path | None = None) -> str:
    p = Path(path) if path else background_file()
    url = p.as_posix().replace('"', '\\"')
    return f'QDialog {{ border-image: url("{url}") 0 0 0 0 stretch stretch; }}'


def apply_to(dialog: QDialog) -> bool:
    """给一个对话框铺背景；已经铺过或图不在就返回 False。"""
    if dialog.property(_PROP):
        return False
    path = background_file()
    if not path.is_file():
        return False
    dialog.setProperty(_PROP, True)
    dialog.setStyleSheet(dialog.styleSheet() + "\n" + stylesheet_for(path))
    return True


class _Filter(QObject):
    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() in (QEvent.Show, QEvent.Polish) and isinstance(obj, QDialog):
            apply_to(obj)
        return False


_filter: _Filter | None = None


def install(app: QApplication | None = None) -> None:
    """装一次即可；必须在第一个对话框显示前调用。"""
    global _filter
    if _filter is not None:
        return
    app = app or QApplication.instance()
    if app is None:
        return
    _filter = _Filter(app)
    app.installEventFilter(_filter)
