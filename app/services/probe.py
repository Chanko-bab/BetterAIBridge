"""探测：端口是否在听、进程是否存在。只读，不改任何东西。"""
from __future__ import annotations

import socket
from typing import Dict, Iterable, Tuple

from ..core import config, registry

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def ports_snapshot() -> Dict[str, bool]:
    cfg = config.get("ports", {}) or {}
    return {name: port_open(port) for name, port in cfg.items()}


def qq_processes() -> int:
    if psutil is None:
        return 0
    n = 0
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info.get("name") or "").lower() == "qq.exe":
                n += 1
        except psutil.Error:
            continue
    return n


def python_main_processes() -> int:
    """AstrBot 的 python main.py（含 venv 转发进程）大致计数。"""
    if psutil is None:
        return 0
    n = 0
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            if (p.info.get("name") or "").lower() != "python.exe":
                continue
            cmd = " ".join(p.info.get("cmdline") or [])
            if "main.py" in cmd:
                n += 1
        except psutil.Error:
            continue
    return n


def module_installed(root: str, rel: str) -> bool:
    try:
        return (__import__("pathlib").Path(root) / rel).exists()
    except (OSError, TypeError, ValueError):
        return False


def summary() -> Dict[str, object]:
    ports = ports_snapshot()
    mods = registry.modules()
    installed = [m for m in mods if str(m.get("state")) != "not_installed"]
    enabled = [m for m in mods if str(m.get("state")) == "enabled"]
    return {
        "ports": ports,
        "core_up": ports.get("core", False),
        "asr_up": ports.get("asr", False),
        "mods_installed": len(installed),
        "mods_enabled": len(enabled),
        "mods_total": len(mods),
    }

