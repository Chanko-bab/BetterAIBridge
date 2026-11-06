"""后台执行小工具：把阻塞调用（HTTP/探测）丢到线程池，结果用 Qt 信号回 UI 线程。

注意：QRunnable 不归 Qt 管理生命周期，_Signals 必须由 Python 侧持引用，
否则任务还没跑完 QObject 就被回收 → "Signal source has been deleted"。
"""
from __future__ import annotations

import os
from typing import Any, Callable, Optional, Set

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

_ALIVE: Set[Any] = set()
_POOL: Optional[QThreadPool] = None


def _pool() -> QThreadPool:
    global _POOL
    if _POOL is None:
        _POOL = QThreadPool()
        # 不跟全局池抢：最多 6 条后台链，长聊天也不会把一百个线程全拉起来。
        _POOL.setMaxThreadCount(max(4, min(6, (os.cpu_count() or 4))))
    return _POOL


class _Signals(QObject):
    ok = Signal(object)
    err = Signal(str)
    err_obj = Signal(object)
    done = Signal()


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()
        self.setAutoDelete(True)

    def run(self) -> None:  # noqa: D401
        try:
            try:
                result = self.fn()
            except Exception as e:  # noqa: BLE001
                self._emit(self.signals.err, str(e))
                self._emit(self.signals.err_obj, e)
                return
            self._emit(self.signals.ok, result)
        finally:
            # done 走同一条信号队列；窗口销毁时连 done 都发不出去，
            # 那就直接在这里把引用放掉，避免 _ALIVE 越攒越多。
            try:
                self.signals.done.emit()
            except RuntimeError:
                _ALIVE.discard(self)

    def _emit(self, sig: Signal, payload: Any = None) -> None:
        try:
            sig.emit(payload)
        except RuntimeError:
            _ALIVE.discard(self)


def run_async(fn: Callable[[], Any], on_ok: Optional[Callable[[Any], None]] = None,
              on_err: Optional[Callable[[str], None]] = None,
              on_err_obj: Optional[Callable[[BaseException], None]] = None) -> None:
    task = _Task(fn)
    _ALIVE.add(task)
    if on_ok:
        task.signals.ok.connect(on_ok)
    if on_err:
        task.signals.err.connect(on_err)
    if on_err_obj:
        task.signals.err_obj.connect(on_err_obj)
    task.signals.ok.connect(lambda _r: _ALIVE.discard(task))
    task.signals.err.connect(lambda _e: _ALIVE.discard(task))
    task.signals.err_obj.connect(lambda _e: _ALIVE.discard(task))
    task.signals.done.connect(lambda: _ALIVE.discard(task))
    _pool().start(task)
