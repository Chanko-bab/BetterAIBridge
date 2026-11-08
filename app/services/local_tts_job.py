"""本地语音包安装任务：窗口关掉，下载和安装也继续跑。

放在进程级单例里，而不是挂在对话框上——对话框只是观察者。这样用户点「关闭」
只是不再看进度，pip / 模型下载 / 启动服务都不受影响；下次打开对话框还能接上。

用普通 daemon 线程而不是 QThread：任务结束前进程退出也不会卡住 Qt 的析构。
Qt 信号从工作线程 emit，槽在主线程执行（AutoConnection 自动排队）。
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Any, Dict, List

from PySide6.QtCore import QObject, Signal

from ..core import local_tts

log = logging.getLogger("xiaochen.local_tts_job")


class LocalTtsJob(QObject):
    progress = Signal(int, str)
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._pct = 0
        self._msg = ""
        self._error = ""
        self._ok = False
        self._lines: deque[str] = deque(maxlen=400)
        self._doc: Dict[str, Any] = {}

    # ---- 给界面看的快照 -------------------------------------------------
    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    def state(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "pct": self._pct,
                "msg": self._msg,
                "error": self._error,
                "ok": self._ok,
                "lines": list(self._lines),
            }

    # ---- 启动 -----------------------------------------------------------
    def start(self) -> bool:
        """开始安装；已经在跑就返回 False（界面直接连上去看进度）。"""
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._pct = 0
            self._msg = "正在准备…"
            self._error = ""
            self._ok = False
            self._lines.clear()
            self._doc = {}
            self._thread = threading.Thread(
                target=self._run, name="local-tts-install", daemon=True)
            thread = self._thread
        thread.start()
        return True

    def _run(self) -> None:
        try:
            doc = local_tts.install(lambda p, m: self._report(p, m))
            self._report(97, "启动本地语音服务…")
            local_tts.start()
            with self._lock:
                self._ok = True
                self._pct = 100
                self._msg = "装好了，本地语音服务已经起来。"
                self._doc = doc if isinstance(doc, dict) else {}
            self.done.emit(self._doc)
        except Exception as exc:  # noqa: BLE001  # 任务边界：任何失败都要回到界面
            why = str(exc).strip() or type(exc).__name__
            log.warning("本地语音包安装失败：%s", why, exc_info=True)
            with self._lock:
                self._ok = False
                self._error = why
                self._msg = "没装成。"
            self.failed.emit(why)
        finally:
            with self._lock:
                self._running = False

    def _report(self, pct: int, msg: str) -> None:
        p = max(0, min(100, int(pct)))
        text = str(msg)
        with self._lock:
            self._pct = p
            self._msg = text
            self._lines.append(text)
        self.progress.emit(p, text)


job = LocalTtsJob()
