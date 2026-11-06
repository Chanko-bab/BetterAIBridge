"""设置/外观页滚轮防误触的离屏检查。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QComboBox, QScrollArea, QSlider, QSpinBox, QVBoxLayout,
    QWidget,
)

from app.ui import wheel_guard  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def wheel(widget: QWidget) -> None:
    pos = QPointF(widget.width() / 2, widget.height() / 2)
    ev = QWheelEvent(
        pos, QPointF(10, 10), QPoint(0, 0), QPoint(0, -120),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False,
    )
    QApplication.sendEvent(widget, ev)


def main() -> int:
    app = QApplication(sys.argv[:1])
    host = QWidget()
    host.resize(300, 200)
    outer = QVBoxLayout(host)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    outer.addWidget(scroll)

    body = QWidget()
    body.setMinimumHeight(1200)
    lay = QVBoxLayout(body)
    spin = QSpinBox()
    spin.setRange(0, 100)
    spin.setValue(10)
    combo = QComboBox()
    combo.addItems(["甲", "乙", "丙"])
    combo.setCurrentIndex(0)
    slider = QSlider(Qt.Horizontal)
    slider.setRange(0, 100)
    slider.setValue(50)
    for w in (spin, combo, slider):
        lay.addWidget(w)
    scroll.setWidget(body)
    host.show()
    app.processEvents()

    wheel_guard.install(body, scroll)
    bar = scroll.verticalScrollBar()
    bar.setValue(0)
    before = bar.value()

    wheel(spin)
    app.processEvents()
    check(spin.value() == 10, f"滚轮不该改数字（实际 {spin.value()}）")

    wheel(combo)
    app.processEvents()
    check(combo.currentIndex() == 0, f"滚轮不该改下拉（实际 {combo.currentIndex()}）")

    wheel(slider)
    app.processEvents()
    check(slider.value() == 50, f"滚轮不该改滑条（实际 {slider.value()}）")

    check(bar.value() > before, f"滚轮应继续滚页面（滚动条 {before} → {bar.value()}）")

    host.close()
    print("PASS" if not fails else f"FAIL {len(fails)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
