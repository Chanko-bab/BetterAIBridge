"""背景图片库界面：网格、空库、使用、删除当前图。"""
from __future__ import annotations

import base64
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from app.services import bg_library  # noqa: E402
from app.ui.dialogs.background_library import BackgroundLibraryDialog  # noqa: E402

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


def main():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        lib = base / "lib"
        old_root = bg_library.root
        bg_library.root = lambda: lib
        try:
            empty = BackgroundLibraryDialog(None, current="")
            check("empty count 0", empty.lst.count() == 0)
            check("empty hint shown", empty.lst.isHidden() and not empty.empty.isHidden())
            check("empty use disabled", not empty.btn_use.isEnabled())

            src = base / "一张图.png"
            src.write_bytes(PNG)
            row = bg_library.import_file(src)
            dlg = BackgroundLibraryDialog(None, current=row["path"])
            check("one item", dlg.lst.count() == 1)
            check("list shown", not dlg.lst.isHidden())
            dlg.lst.setCurrentRow(0)
            check("use enabled", dlg.btn_use.isEnabled())
            dlg._use()
            check("chosen path", dlg.chosen_path() == row["path"], dlg.chosen_path())
            check("accepted", dlg.result() == QDialog.Accepted)

            src2 = base / "第二张.png"
            img = QImage(4, 4, QImage.Format_RGB32)
            img.fill(QColor("#cc3344"))
            assert img.save(str(src2))
            row2 = bg_library.import_file(src2)
            dlg2 = BackgroundLibraryDialog(None, current=row["path"])
            dlg2._select_id(row["id"])
            old_q = QMessageBox.question
            QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
            try:
                dlg2._delete()
            finally:
                QMessageBox.question = old_q
            check("deleted current flag", dlg2.deleted_current())
            check("current file gone", not Path(row["path"]).is_file())
            check("one left", dlg2.lst.count() == 1)
            check("second still there", Path(row2["path"]).is_file())
        finally:
            bg_library.root = old_root

    print(f"\n{PASS} passed, {FAIL} failed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
