"""界面字体：字体族替换、字号等比缩放、边界与日志例外。

    .venv\\Scripts\\python.exe tools\\test_ui_font.py
退出码 0 = 全过；1 = 有断言失败。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def main() -> int:
    app = QApplication(sys.argv[:1])
    assert app is not None

    from app.core.config import DEFAULTS
    from app.ui import fonts

    check(DEFAULTS["ui"].get("font_size") == 13, "默认字号是 13")
    check(DEFAULTS["ui"].get("font_family") == "", "默认字体族是空（系统默认）")
    check(fonts.clamp_size(99) == 18 and fonts.clamp_size(1) == 12, "字号夹在 12–18")
    check(fonts.clamp_size("坏值") == 13, "非法字号回退 13")

    check(fonts.scale_px(13, 16) == 16, "13px 在 16 号下还是 16px")
    check(fonts.scale_px(11, 16) == 14, "11px 在 16 号下变 14px")
    check(fonts.scale_px(9, 12) == 10, "最小夹到 10px")
    check(fonts.scale_px(25, 18) == 24, "最大夹到 24px")

    base = fonts.stylesheet(13, "")
    check("font-size: 13px" in base, "13 号时 QSS 就是 13px")
    check('font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;' in base,
          "13 号时字体族是微软雅黑")
    big = fonts.stylesheet(16, "")
    check("font-size: 16px" in big, "16 号时出现 16px")
    check("font-size: 13px" not in big, "16 号时不再有 13px")
    check("font-size: 12px" in big, "日志等宽区保持 12px")

    real_families = fonts.families
    fonts.families = lambda: ["Consolas", "Cascadia Mono", fonts.DEFAULT_FAMILY]
    try:
        custom = fonts.stylesheet(13, "Consolas")
    finally:
        fonts.families = real_families
    check('font-family: "Consolas", "Segoe UI", sans-serif;' in custom,
          "能换成 Consolas")
    check('font-family: "Cascadia Mono", "Consolas", monospace;' in custom,
          "日志等宽字体不跟着换")

    check(fonts.resolve("NoSuchFontXYZ-不能有") == fonts.DEFAULT_FAMILY,
          "字体不存在时回退微软雅黑")
    check(fonts.point_size(18) > fonts.point_size(12), "字号越大，基础字号越大")

    tpl = (ROOT / "config" / "app.yaml.template").read_text(encoding="utf-8")
    check("font_family:" in tpl and "font_size: 13" in tpl,
          "app.yaml 模板带字体族与字号")

    print("PASS" if not fails else "FAIL")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
