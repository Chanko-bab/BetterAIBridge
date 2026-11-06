"""启动耗时埋点：只记内存里的几行，不引入依赖、不写盘。

用法：
    from app.core import perf
    perf.mark("main.import")
    ...
    log.info("启动耗时 %s", perf.summary())

`perf` 必须在 `main.py` 最前面 import 之一，这样 `t=0` 尽量接近进程启动。
"""
from __future__ import annotations

import time
from typing import Any

_T0 = time.perf_counter()
_marks: list[dict[str, Any]] = []


def reset() -> None:
    global _T0
    _T0 = time.perf_counter()
    _marks.clear()


def mark(name: str, **extra: Any) -> float:
    """记一个节点；返回相对 t=0 的秒数，方便调用处直接打日志。"""
    elapsed = time.perf_counter() - _T0
    row: dict[str, Any] = {"name": str(name), "ms": round(elapsed * 1000, 1)}
    if extra:
        row.update(extra)
    _marks.append(row)
    return elapsed


def since(name: str | None = None) -> float:
    """从 t=0（或指定节点）到现在的秒数。"""
    base = _T0
    if name:
        for row in _marks:
            if row.get("name") == name:
                base = _T0 + float(row.get("ms", 0)) / 1000.0
    return time.perf_counter() - base


def snapshot() -> list[dict[str, Any]]:
    return [dict(row) for row in _marks]


def summary(limit: int = 10) -> str:
    """一行给日志看；只列前 limit 个节点，避免刷屏。"""
    rows = _marks[: max(1, int(limit))]
    if not rows:
        return "（无埋点）"
    body = " · ".join(f"{r['name']} {r['ms']:.0f}ms" for r in rows)
    return f"总 {since() * 1000:.0f}ms | {body}"
