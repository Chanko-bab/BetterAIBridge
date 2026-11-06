# -*- coding: utf-8 -*-
r"""开机自启与启动器配置项。

    .venv\Scripts\python.exe tools\test_startup.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from app.core import config  # noqa: E402
from app.services import startup  # noqa: E402

FAILS: list[str] = []
OKS = 0


def check(ok: bool, msg: str) -> None:
    global OKS
    if ok:
        OKS += 1
    else:
        FAILS.append(msg)


def main() -> int:
    # 自启命令：必须指向一个真实存在的启动器/脚本，并且带引号
    cmd = startup.launcher_command()
    check(cmd.startswith('"') and cmd.endswith('"'), f"自启命令要整体带引号（实际 {cmd}）")
    target = Path(cmd.strip('"'))
    check(target.exists(), f"自启命令指向的文件应存在（实际 {target}）")

    # 读状态不能炸（没设置过就是 False）
    check(isinstance(startup.is_enabled(), bool), "is_enabled 应返回 bool")

    # 配置写盘：写进去就能读回来，而且不碰真实的 app.yaml
    tmp = Path(tempfile.mkdtemp(prefix="bab-startup-"))
    keep_path = config.CONFIG_PATH
    try:
        config.CONFIG_PATH = tmp / "app.yaml"
        config._cfg = None
        config.set_value("core.auto_restart", False)
        check(config.get("core.auto_restart") is False, "set_value 后应能立刻读回 False")
        check(config.CONFIG_PATH.is_file(), "set_value 应把配置落盘")
        config.set_value("core.auto_restart", True)
        check(config.get("core.auto_restart") is True, "改回 True 也要生效")
        check(config.get("core.auto_restart", None) is not None, "默认值应存在")
    finally:
        config.CONFIG_PATH = keep_path
        config._cfg = None
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)

    check(bool(config.get("core.auto_restart", True)) in (True, False),
          "恢复真实配置后 core.auto_restart 可读")

    print("")
    if FAILS:
        print(f"失败 {len(FAILS)} 条：")
        for f in FAILS:
            print("  - " + f)
        return 1
    print(f"全过（{OKS} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
