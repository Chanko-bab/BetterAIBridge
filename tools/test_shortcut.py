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

    # 安装脚本的两条硬约束（2026-11-08 实测踩过）：
    # 1) 静默/测试安装可用 BAB_TEST_SHORTCUT 建稳定入口；
    # 2) 覆盖安装时目录必须合并，不能套娃成 app\app。
    inst = (Path(__file__).resolve().parents[1] / "packaging" / "install.ps1").read_text(
        encoding="utf-8-sig")
    check("BAB_TEST_SHORTCUT" in inst, "静默安装应支持建稳定入口")
    check("Copy-Except $item.FullName (Join-Path $Dst $item.Name) @() 0" in inst,
          "覆盖安装时目录应合并复制")
    check("-Destination (Join-Path $Dst $item.Name) -Recurse -Force" not in inst,
          "不能再把目录套娃复制")

    print("test_shortcut: 8 checks passed")


if __name__ == "__main__":
    main()
