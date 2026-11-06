"""事件总线：把后台探测/聊天结果送到 UI（Qt 信号，跨线程安全）。"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class Bus(QObject):
    ports_changed = Signal(dict)      # {"core": True, ...}
    state_changed = Signal(dict)      # /state + /brain/state + /drives + /stomach 汇总
    chat_reply = Signal(str, str)     # (用户文本, 无名回复)
    chat_failed = Signal(str)         # 错误信息
    log_line = Signal(str, str)       # (级别, 文本)


bus = Bus()
