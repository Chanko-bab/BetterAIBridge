"""从 GUI 进程调控制台工具时，别让 Windows 给它新开控制台窗口。

pythonw 启动的进程没有控制台；这时再跑 ``tasklist``/``taskkill``/``where``/
``netstat``/``mklink``/``powershell`` 这类控制台程序，系统会给子进程开一个
控制台窗口。哪怕它只活几十毫秒，也会在屏幕上闪一下。

这里统一塞 ``CREATE_NO_WINDOW``；调用方只改 import，不改行为。
"""
from __future__ import annotations

import os
import subprocess

NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def run(cmd, **kwargs):
    if os.name == "nt" and "creationflags" not in kwargs:
        kwargs["creationflags"] = NO_WINDOW
    return subprocess.run(cmd, **kwargs)


def popen(cmd, **kwargs):
    if os.name == "nt" and "creationflags" not in kwargs:
        kwargs["creationflags"] = NO_WINDOW
    return subprocess.Popen(cmd, **kwargs)
