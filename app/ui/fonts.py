"""界面字体：字体族 + 字号。

QSS 里的字号是写死的（基准 13px），`app.setFont` 会被 QSS 盖住；所以这里
读 `style.qss`，把 `font-size: Npx` 按 `N × 字号 / 13` 等比缩放，并替换
`*` 规则里的字体族。等宽日志（QPlainTextEdit 那条）保持 12px 不动。
"""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase

from ..core import config

BASE_SIZE = 13
MIN_SIZE = 12
MAX_SIZE = 18
DEFAULT_FAMILY = "Microsoft YaHei UI"

_SIZE_RE = re.compile(r"font-size:\s*(\d+)px")
_FAMILY_RE = re.compile(r"font-family:\s*[^;]+;")


def clamp_size(value) -> int:
    try:
        n = int(value)
    except Exception:  # noqa: BLE001
        n = BASE_SIZE
    return max(MIN_SIZE, min(MAX_SIZE, n))


def size() -> int:
    return clamp_size(config.get("ui.font_size", BASE_SIZE))


def families() -> list[str]:
    """系统里可用的字体族（去掉 @ 开头的竖排变体）。"""
    try:
        return [f for f in QFontDatabase.families() if not f.startswith("@")]
    except Exception:  # noqa: BLE001
        return []


def resolve(name: str = "") -> str:
    name = str(name or "").strip()
    if name and name in families():
        return name
    return DEFAULT_FAMILY


def family() -> str:
    return resolve(str(config.get("ui.font_family") or ""))


def scale_px(n: int, target: int | None = None) -> int:
    t = clamp_size(target if target is not None else size())
    return max(10, min(24, round(int(n) * t / BASE_SIZE)))


def point_size(target: int | None = None) -> int:
    t = clamp_size(target if target is not None else size())
    return max(8, round(9 * t / BASE_SIZE))


def _scale_block(block: str, target: int) -> str:
    # 日志区用等宽字体，跟随字号会把对齐和宽度弄乱
    if "QPlainTextEdit" in block and "font-family" in block:
        return block
    return _SIZE_RE.sub(lambda m: f"font-size: {scale_px(int(m.group(1)), target)}px", block)


def stylesheet(target: int | None = None, fam: str | None = None) -> str:
    t = clamp_size(target if target is not None else size())
    f = resolve(fam) if fam is not None else family()
    path = Path(config.APP_DIR) / "app" / "ui" / "theme" / "style.qss"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    out: list[str] = []
    for block in text.split("}"):
        if "font-family" in block and re.search(r"(?m)^\s*\*\s*\{", block):
            block = _FAMILY_RE.sub(f'font-family: "{f}", "Segoe UI", sans-serif;', block, count=1)
        out.append(_scale_block(block, t))
    return "}".join(out)


def ui_px(n: int) -> int:
    """按界面字号缩放一个布局像素值（Qt 自己还会再做 DPI 缩放）。"""
    t = size()
    factor = max(0.90, min(1.55, t / BASE_SIZE))
    return max(1, round(int(n) * factor))


def apply(app) -> None:
    from ..core import perf
    perf.mark("ui.fonts")
    sheet = stylesheet()
    if sheet:
        app.setStyleSheet(sheet)
    app.setFont(QFont(family(), point_size()))
