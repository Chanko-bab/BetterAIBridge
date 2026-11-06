"""事件总线：内核里发生的事，排一条带序号的队，交给桥分发给模组。

为什么要有它：
- 模组想知道「她刚说了什么」「她现在什么情绪」，不能自己去翻文件；
- 内核也不想为每个模组写一份推送代码。

所以这里只做两件最小的事：publish（谁发生了什么事）和 since/wait_new（从某个序号往后取）。
环形缓冲 400 条，进程内、不落盘；真要留痕，看 bridge_audit.jsonl。
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Dict, List, Optional

MAX_EVENTS = 400

_events: "deque[Dict[str, Any]]" = deque(maxlen=MAX_EVENTS)
_seq = 0
_loop: Optional[asyncio.AbstractEventLoop] = None
_waiters: List[asyncio.Event] = []


def bind(loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
    """内核启动时把事件循环交进来（长轮询要靠它唤醒）。"""
    global _loop
    try:
        _loop = loop or asyncio.get_running_loop()
    except RuntimeError:
        _loop = None


def publish(kind: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """发一条事件，返回落库的那条记录（含 seq）。"""
    global _seq
    _seq += 1
    rec = {"seq": _seq, "kind": str(kind), "ts": round(time.time(), 3), "data": data or {}}
    _events.append(rec)
    for ev in list(_waiters):
        try:
            ev.set()
        except Exception:  # noqa: BLE001
            pass
    return rec


def since(seq: int, kinds: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    out = [e for e in _events if int(e.get("seq") or 0) > int(seq or 0)]
    if kinds:
        keep = set(kinds)
        out = [e for e in out if e.get("kind") in keep]
    return out


def last_seq() -> int:
    return _seq


async def wait_new(seq: int, kinds: Optional[List[str]] = None, timeout: float = 25.0) -> List[Dict[str, Any]]:
    """等到有新事件（或超时），返回 seq 之后、且属于 kinds 的那些。"""
    got = since(seq, kinds)
    if got:
        return got
    ev = asyncio.Event()
    _waiters.append(ev)
    try:
        try:
            await asyncio.wait_for(ev.wait(), timeout=max(0.0, min(float(timeout), 30.0)))
        except asyncio.TimeoutError:
            pass
        return since(seq, kinds)
    finally:
        try:
            _waiters.remove(ev)
        except ValueError:
            pass
