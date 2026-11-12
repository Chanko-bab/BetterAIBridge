# -*- coding: utf-8 -*-
r"""开机自启与启动器配置项。

    .venv\Scripts\python.exe tools\test_startup.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from PySide6.QtCore import QLockFile  # noqa: E402

from app.core import config, instance  # noqa: E402
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

    # 单实例辅助：活/死 PID、回到前台请求、锁主人 PID
    check(instance.pid_alive(os.getpid()), "当前进程 PID 应判为活")
    check(not instance.pid_alive(99999999), "不存在的 PID 应判为死")
    tmp2 = Path(tempfile.mkdtemp(prefix="bab-instance-"))
    try:
        check(instance.request_show(tmp2), "应能写 launcher.show 请求")
        check(instance.consume_show(tmp2), "应能消费 launcher.show 请求")
        check(not instance.consume_show(tmp2), "请求消费后不应重复触发")
        lock = QLockFile(str(tmp2 / "test.lock"))
        check(lock.tryLock(100), "临时锁应能拿到")
        try:
            check(instance.lock_pid(lock) == os.getpid(), "锁主人 PID 应等于当前进程")
        finally:
            lock.unlock()
    finally:
        import shutil

        shutil.rmtree(tmp2, ignore_errors=True)

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
