"""桌面快捷方式改名：0.6.4 一次性迁移。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import shortcut


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="bab-shortcut-") as td:
        desk = Path(td)
        old = desk / shortcut.OLD_NAME
        new = desk / shortcut.NEW_NAME
        old.write_text("x", encoding="utf-8")
        shortcut.desktop_dir = lambda: desk  # type: ignore[assignment]
        check(shortcut.migrate_old_shortcut() is True, "旧入口应改名为新入口")
        check(not old.exists(), "旧入口应已消失")
        check(new.is_file(), "新入口应存在")
        check(shortcut.migrate_old_shortcut() is False, "新入口已存在时不应重复迁移")

    with tempfile.TemporaryDirectory(prefix="bab-shortcut-") as td:
        desk = Path(td)
        shortcut.desktop_dir = lambda: desk  # type: ignore[assignment]
        check(shortcut.migrate_old_shortcut() is False, "没有旧入口时无事可做")

    print("test_shortcut: 5 checks passed")


if __name__ == "__main__":
    main()
