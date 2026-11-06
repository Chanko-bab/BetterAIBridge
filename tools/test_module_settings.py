# -*- coding: utf-8 -*-
r"""模组设置：number 必须保留小数，integer 仍然走整数框。

    .venv\Scripts\python.exe tools\test_module_settings.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QSpinBox  # noqa: E402

from app.core import pbab, registry  # noqa: E402
from app.ui.dialogs.module_settings import ModuleSettingsDialog  # noqa: E402

FAILS: list[str] = []
OKS = 0


def check(ok: bool, msg: str) -> None:
    global OKS
    if ok:
        OKS += 1
    else:
        FAILS.append(msg)


FIELDS = [
    {"key": "ratio", "type": "number", "default": 0.3,
     "minimum": 0, "maximum": 1, "label": "比例"},
    {"key": "temp", "type": "number", "default": 2.5, "label": "温度"},
    {"key": "count", "type": "integer", "default": 3, "label": "数量"},
]


def _dialog(current: dict | None = None) -> ModuleSettingsDialog:
    registry.get = lambda _mid: {"name": "演示", "version": "1.0",
                                 "settings": current or {}}
    pbab.settings_fields = lambda _mid: FIELDS
    pbab.read_introduce = lambda _mid: "# 介绍\n"
    return ModuleSettingsDialog("demo")


def test_types_and_save() -> None:
    app = QApplication.instance() or QApplication([])
    saved: dict = {}
    pbab.save_settings = lambda _mid, values: saved.update(values)

    dlg = _dialog()
    try:
        kinds = {k: v[0] for k, v in dlg.widgets.items()}
        check(kinds.get("ratio") == "float", f"number 应走 float，实际 {kinds.get('ratio')}")
        check(kinds.get("temp") == "float", f"number 应走 float，实际 {kinds.get('temp')}")
        check(kinds.get("count") == "int", f"integer 应走 int，实际 {kinds.get('count')}")
        check(isinstance(dlg.widgets["ratio"][1], QDoubleSpinBox), "number 应用 QDoubleSpinBox")
        check(isinstance(dlg.widgets["count"][1], QSpinBox), "integer 应用 QSpinBox")
        check(abs(dlg.widgets["ratio"][1].value() - 0.3) < 1e-9,
              f"默认 0.3 应保留（实际 {dlg.widgets['ratio'][1].value()}）")
        check(abs(dlg.widgets["temp"][1].value() - 2.5) < 1e-9,
              f"默认 2.5 应保留（实际 {dlg.widgets['temp'][1].value()}）")
        dlg._save()
        check(saved.get("ratio") == 0.3, f"保存后 ratio 应是 0.3（实际 {saved.get('ratio')!r}）")
        check(saved.get("temp") == 2.5, f"保存后 temp 应是 2.5（实际 {saved.get('temp')!r}）")
        check(saved.get("count") == 3 and isinstance(saved.get("count"), int),
              f"count 应仍是整数（实际 {saved.get('count')!r}）")
    finally:
        dlg.deleteLater()
        app.processEvents()


def test_reopen_keeps_decimal() -> None:
    app = QApplication.instance() or QApplication([])
    pbab.save_settings = lambda _mid, _values: None
    dlg = _dialog({"ratio": 0.3, "temp": 2.5, "count": 7})
    try:
        check(abs(dlg.widgets["ratio"][1].value() - 0.3) < 1e-9,
              "重开后 ratio 应仍是 0.3")
        check(abs(dlg.widgets["temp"][1].value() - 2.5) < 1e-9,
              "重开后 temp 应仍是 2.5")
        check(dlg.widgets["count"][1].value() == 7, "重开后 count 应仍是 7")
    finally:
        dlg.deleteLater()
        app.processEvents()


def main() -> int:
    test_types_and_save()
    test_reopen_keeps_decimal()
    print("")
    if FAILS:
        print(f"失败 {len(FAILS)} 条：")
        for f in FAILS:
            print("  -", f)
        return 1
    print(f"PASS {OKS} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
