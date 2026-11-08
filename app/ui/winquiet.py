"""让 QProcess 启动的控制台程序也隐藏窗口。

QProcess 默认按父进程的方式创建子进程；GUI 进程没有控制台，子进程是
``cmd.exe``/``powershell.exe`` 时就会闪一个黑窗。这里给 QProcess 的创建参数
补 ``CREATE_NO_WINDOW``。
"""
from __future__ import annotations

import os

from PySide6.QtCore import QProcess

NO_WINDOW = 0x08000000


def hide_console(proc: QProcess) -> None:
    if os.name != "nt":
        return

    def _modify(args) -> None:
        try:
            args.flags = int(getattr(args, "flags", 0)) | NO_WINDOW
        except (AttributeError, TypeError, ValueError):
            pass

    try:
        proc.setCreateProcessArgumentsModifier(_modify)
    except (AttributeError, RuntimeError):
        pass
