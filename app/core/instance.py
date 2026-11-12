"""单实例启动的小工具：判断锁主人、给已有窗口留一个“回到前台”的请求。

锁本身仍用 QLockFile；这里只补两件它不擅长的事：
- 进程已经死了但锁文件还在时，尽快判断出来；
- 第二次双击快捷方式时，不弹“已经有一个窗口在跑了”，而是叫已有窗口出来。
"""
from __future__ import annotations

import os
from pathlib import Path

# 放在程序数据目录；第二次启动写、第一个实例的定时器读。
SHOW_REQUEST = "launcher.show"


def show_request_path(data_dir: Path) -> Path:
    return Path(data_dir) / SHOW_REQUEST


def request_show(data_dir: Path) -> bool:
    """请求已经运行的实例回到前台；写失败不影响第二次启动退出。"""
    try:
        path = show_request_path(data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("1", encoding="ascii")
        return True
    except OSError:
        return False


def consume_show(data_dir: Path) -> bool:
    """消费一次“回到前台”请求；没有请求就返回 False。"""
    try:
        path = show_request_path(data_dir)
        if not path.is_file():
            return False
        path.unlink()
        return True
    except OSError:
        return False


def pid_alive(pid: int) -> bool:
    """判断 PID 是否还活着；没有 psutil 时退回 os.kill(pid, 0)。"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        import psutil

        return bool(psutil.pid_exists(pid))
    except ImportError:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True


def lock_pid(lock) -> int:
    """取出 QLockFile 记录的 PID；取不到返回 0。"""
    try:
        info = lock.getLockInfo()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return 0
    if isinstance(info, (tuple, list)) and info:
        try:
            return int(info[0])
        except (TypeError, ValueError):
            return 0
    return 0
