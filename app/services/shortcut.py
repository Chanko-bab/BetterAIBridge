"""桌面快捷方式的一次性改名（0.6.4）。

旧版稳定入口叫 `BetterAIBridge.lnk`；0.6.4 起叫 `BetterAIBridgeLauncher.lnk`。
自动更新不会跑安装器，所以启动器自己改名一次；安装器也会做同样的迁移。
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("xiaochen.shortcut")

OLD_NAME = "BetterAIBridge.lnk"
NEW_NAME = "BetterAIBridgeLauncher.lnk"


def desktop_dir() -> Path | None:
    try:
        from PySide6.QtCore import QStandardPaths

        p = QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)
        return Path(p) if p else None
    except Exception:  # noqa: BLE001
        log.debug("取桌面路径失败", exc_info=True)
        return None


def migrate_old_shortcut() -> bool:
    """把旧稳定入口改成新名字；新入口已存在就不动。"""
    desktop = desktop_dir()
    if desktop is None:
        return False
    old = desktop / OLD_NAME
    new = desktop / NEW_NAME
    if not old.is_file() or new.exists():
        return False
    try:
        old.rename(new)
    except OSError:
        log.warning("桌面快捷方式改名失败：%s", old, exc_info=True)
        return False
    log.info("桌面快捷方式已改名：%s -> %s", old.name, new.name)
    return True
