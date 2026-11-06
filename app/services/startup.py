"""开机自启：只动当前用户的 Run 键，不碰计划任务、不碰系统目录。

启动器是同目录下的 `BetterAIBridgeLauncher <版本>.vbs`（安装时改名）；
开发树里可能只有 `launch.vbs`，再退到 `python main.py`。
"""
from __future__ import annotations

import sys
from pathlib import Path

from ..core import config

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "BetterAIBridge"


def launcher_command() -> str:
    """自启时该执行的命令行（带引号，路径里有空格也安全）。"""
    d = Path(config.APP_DIR)
    try:
        vbs = sorted(d.glob("BetterAIBridgeLauncher *.vbs"))
    except Exception:  # noqa: BLE001
        vbs = []
    if not vbs:
        vbs = sorted(d.glob("launch.vbs"))
    if vbs:
        return f'"{vbs[0]}"'
    return f'"{sys.executable}" "{d / "main.py"}"'


def is_enabled() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            val, _ = winreg.QueryValueEx(k, VALUE_NAME)
        return bool(str(val or "").strip())
    except FileNotFoundError:
        return False
    except OSError:
        return False


def enable() -> str:
    try:
        import winreg

        cmd = launcher_command()
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, cmd)
        return cmd
    except OSError as exc:
        raise RuntimeError(f"写开机自启失败（可能没有权限）：{exc}") from exc


def disable() -> None:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, VALUE_NAME)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise RuntimeError(f"取消开机自启失败：{exc}") from exc
