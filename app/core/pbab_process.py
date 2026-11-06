"""模组运行期的系统小工具：端口/进程/健康检查/清理。

从 pbab.py 拆出来；这些函数只碰 socket / tasklist / psutil，不认识 registry。
"""
from __future__ import annotations

import json
import logging
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

from . import config

log = logging.getLogger(__name__)


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _install_base() -> int:
    try:
        doc = json.loads((config.APP_DIR / "config" / "install.json").read_text(encoding="utf-8-sig"))
        return int(doc.get("base") or 40720)
    except (OSError, ValueError, TypeError):  # noqa: BLE001
        return 40720


def _wait_health(health: Dict[str, Any], port: int = 0) -> bool:
    if not health:
        return True
    timeout = float(health.get("timeout_s") or 30)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if health.get("type") == "port" and _port_open(
            int(port or health.get("port") or 0), str(health.get("host") or "127.0.0.1")
        ):
            return True
        if health.get("type") == "process" and health.get("pid") and _pid_alive(int(health["pid"])):
            return True
        time.sleep(0.5)
    return False
def _pid_alive(pid: int) -> bool:
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, timeout=8)
        return str(pid) in (out.stdout or "")
    except (OSError, subprocess.SubprocessError):
        return False


def _kill_pid_files(dirs: List[Path]) -> int:
    killed = 0
    for d in dirs:
        try:
            for f in Path(d).glob("*.pid"):
                try:
                    pid = int(f.read_text(encoding="utf-8", errors="ignore").strip())
                except (ValueError, OSError):
                    f.unlink(missing_ok=True)
                    continue
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
                killed += 1
                try:
                    f.unlink()
                except OSError:
                    log.debug("删除模组 pid 文件失败：%s", f, exc_info=True)
        except OSError:
            continue
    return killed


def _kill_module_procs(dirs: List[Path]) -> int:
    try:
        import psutil  # type: ignore
    except (ImportError, OSError):
        return 0
    wants = [str(d).lower() for d in dirs if d]
    if not wants:
        return 0
    killed = 0
    for _ in range(3):
        hit = 0
        for p in psutil.process_iter(["pid", "cmdline", "cwd"]):
            try:
                info = p.info
                cwd = str(info.get("cwd") or "").lower()
                cmd = " ".join(info.get("cmdline") or []).lower()
            except psutil.Error:
                continue
            if not cmd:
                continue
            if any(w in cwd or w in cmd for w in wants):
                try:
                    p.kill()
                    hit += 1
                except psutil.Error:
                    log.debug("结束模组残留进程失败：%s", p.info.get("pid"), exc_info=True)
        killed += hit
        if not hit:
            break
        time.sleep(0.4)
    return killed


def _kill_port_owners(ports: List[int], only_dir: str = "") -> int:
    if not ports:
        return 0
    try:
        import psutil  # type: ignore
    except (ImportError, OSError):
        return 0
    want = {int(p) for p in ports}
    killed = 0
    try:
        conns = psutil.net_connections(kind="tcp")
    except psutil.Error:
        return 0
    for c in conns:
        try:
            if c.status != psutil.CONN_LISTEN or not c.laddr or c.laddr.port not in want or not c.pid:
                continue
            if only_dir:
                try:
                    cmd = " ".join(psutil.Process(c.pid).cmdline()).lower()
                    cwd = str(psutil.Process(c.pid).cwd() or "").lower()
                except psutil.Error:
                    continue
                needle = only_dir.lower()
                if needle not in cmd and needle not in cwd:
                    log.info("端口 %s 被别的安装先占住了（pid %s），不动它", c.laddr.port, c.pid)
                    continue
            subprocess.run(["taskkill", "/PID", str(c.pid), "/T", "/F"], capture_output=True)
            killed += 1
        except (psutil.Error, OSError, ValueError):
            continue
    return killed
