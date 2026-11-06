"""弹窗背景：QDialog / QMessageBox 第一次显示时自动铺内置白底图。

    .venv\\Scripts\\python.exe tools\\test_dialog_bg.py
退出码 0 = 全过；1 = 有断言失败。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def main() -> int:
    app = QApplication(sys.argv[:1])
    from app.ui import dialog_bg

    check(dialog_bg.background_file().is_file(), "内置弹窗背景存在")
    dialog_bg.install(app)

    dlg = QDialog()
    dlg.resize(360, 240)
    dlg.show()
    app.processEvents()
    check(bool(dlg.property("_bab_dialog_bg")), "QDialog 显示时自动铺背景")
    check("bab-bg.jpg" in dlg.styleSheet(), "样式指向内置图")
    check("border-image" in dlg.styleSheet(), "用 border-image 铺满")

    box = QMessageBox()
    box.setText("测试")
    box.show()
    app.processEvents()
    check(bool(box.property("_bab_dialog_bg")), "QMessageBox 也算弹窗")

    dlg.close()
    box.close()
    print("PASS" if not fails else "FAIL")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
