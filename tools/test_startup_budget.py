"""启动预算回归：只建聊天页、控件数受控、埋点节点齐全。

时间断言给得宽（2.5s），主要防的是“又把七个页面全构造一遍”的结构回退。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("BAB_NO_PERSIST", "1")
os.environ.setdefault("BAB_NO_ANIM", "1")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from app.core import perf  # noqa: E402


def check(ok: bool, msg: str) -> None:
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        raise SystemExit(1)


app = QApplication.instance() or QApplication([])
perf.reset()
perf.mark("test.start")

# 0.4.54 基线：65 控件 / 约 0.21s（离屏）。留 1.5x 余量，
# 超了说明又把页面或重控件加回启动路径了。
BASELINE_WIDGETS = 65
BASELINE_SECONDS = 0.25

from app.ui import fonts  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

fonts.apply(app)
t0 = time.perf_counter()
win = MainWindow()
win.show()
win.show_page("chat")
for _ in range(5):
    app.processEvents()
built = time.perf_counter() - t0
widgets = len(win.findChildren(QWidget))
names = [r["name"] for r in perf.snapshot()]

check("ui.window.built" in names, "建窗有埋点")
check("page.chat" in names, "聊天页有埋点")
check(list(win.pages) == ["chat"], f"启动只建聊天页（实际 {list(win.pages)}）")
check(widgets < 200, f"启动控件数 < 200（实际 {widgets}）")
check(widgets <= int(BASELINE_WIDGETS * 1.5), f"控件数不超过基线 1.5x（{BASELINE_WIDGETS} → 实际 {widgets}）")
check(built < 2.5, f"建窗+首屏 < 2.5s（实际 {built:.2f}s）")
check(built <= max(1.0, BASELINE_SECONDS * 4), f"建窗+首屏不超过基线 4x（{BASELINE_SECONDS:.2f}s → 实际 {built:.2f}s）")

win.hide()
win.deleteLater()
app.processEvents()
print("OK")
