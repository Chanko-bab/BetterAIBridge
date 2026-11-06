"""启动埋点与字号缩放：不依赖屏幕，纯逻辑。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import perf  # noqa: E402
from app.ui import fonts  # noqa: E402


def check(ok: bool, msg: str) -> None:
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        raise SystemExit(1)


perf.reset()
perf.mark("a")
time.sleep(0.01)
perf.mark("b", detail="x")
rows = perf.snapshot()
check(len(rows) == 2, "记两个节点")
check(rows[0]["name"] == "a" and rows[0]["ms"] >= 0, "节点名与毫秒")
check(rows[1]["ms"] >= rows[0]["ms"], "毫秒单调")
check("a " in perf.summary() and "b " in perf.summary(), "summary 含节点")
check(isinstance(perf.since(), float), "since 返回秒数")

old = fonts.size
try:
    fonts.size = lambda: 13
    base = fonts.ui_px(196)
    fonts.size = lambda: 18
    big = fonts.ui_px(196)
    fonts.size = lambda: 12
    small = fonts.ui_px(196)
finally:
    fonts.size = old
check(base == 196, "13px 不缩放")
check(big > base, "字号变大时布局变大")
check(small < base, "字号变小时布局变小")
check(fonts.ui_px(38) >= 34, "窄条不会缩没")

print("OK")
