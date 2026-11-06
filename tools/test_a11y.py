"""可访问性：可点击标题能用键盘触发，图标按钮有可读名字。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("BAB_NO_PERSIST", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui.widgets.nanny_panel import NannyPanel  # noqa: E402
from app.ui.widgets.titlebar import TitleBar  # noqa: E402


def check(ok: bool, msg: str) -> None:
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        raise SystemExit(1)


app = QApplication.instance() or QApplication([])

panel = NannyPanel()
check(panel.title.focusPolicy() == Qt.StrongFocus, "保姆标题可用 Tab 聚焦")
check(bool(panel.title.accessibleName()), "保姆标题有可读名字")
check(bool(panel.btn_clear.accessibleName()), "清空按钮有可读名字")

hits = []
panel.title.clicked.connect(lambda: hits.append(1))
QTest.keyClick(panel.title, Qt.Key_Return)
check(hits == [1], "回车能打开保姆小屋")

bar = TitleBar()
check(bar.btn_min.accessibleName() == "最小化窗口", "最小化按钮有名字")
check(bar.btn_close.accessibleName() == "收进托盘", "关闭按钮有名字")

src = (ROOT / "app" / "ui" / "pages" / "chat.py").read_text(encoding="utf-8")
check('setAccessibleName("发送消息")' in src, "发送按钮有可读名字")

def _lum(hex_color: str) -> float:
    c = hex_color.lstrip("#")
    rgb = [int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    vals = [(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4) for v in rgb]
    return 0.2126 * vals[0] + 0.7152 * vals[1] + 0.0722 * vals[2]


def _contrast(hex_color: str) -> float:
    a, b = _lum(hex_color), _lum("#ffffff")
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


qss = (ROOT / "app" / "ui" / "theme" / "style.qss").read_text(encoding="utf-8")
for name in ("Muted", "CardTitle", "LogoSub"):
    line = next((x for x in qss.splitlines() if f"QLabel#{name}" in x and "color:" in x), "")
    color = line.split("color:")[1].split(";")[0].strip() if "color:" in line else ""
    check(bool(color), f"{name} 有颜色")
    check(_contrast(color) >= 4.5, f"{name} 对白底对比度 ≥ 4.5（{color} → {_contrast(color):.1f}）")

print("OK")

