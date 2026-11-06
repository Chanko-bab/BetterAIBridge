"""检查更新：先只做「打开下载页」。

地址优先读 `config/app.yaml` 的 `update_url`；没配就提示作者还没给地址。
版本号读安装目录的 `VERSION.txt`，只用于在按钮旁边显示，不发任何网络请求。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QWidget

from ..core import config

# 作者发布页；留空时按钮会提示「还没配置」
DEFAULT_URL = ""


def url() -> str:
    try:
        return str(config.get("update_url") or DEFAULT_URL).strip()
    except Exception:
        return DEFAULT_URL


def version() -> str:
    """返回 '0.4.20' 这样的版本号；读不到就空串。"""
    try:
        p = Path(config.APP_DIR) / "VERSION.txt"
        text = p.read_text(encoding="utf-8-sig").strip()
        parts = text.split()
        return parts[-1] if parts else ""
    except Exception:
        return ""


def open_download(parent: Optional[QWidget] = None) -> bool:
    """打开下载页。没有地址时给一句人话，不装死。"""
    target = url()
    if not target:
        QMessageBox.information(
            parent, "检查更新",
            "下载页地址还没配置。\n\n"
            "可以在 config\\app.yaml 里填 update_url，"
            "或等下一次安装包里带上默认地址。",
        )
        return False
    return bool(QDesktopServices.openUrl(QUrl(target)))
