"""模组运行期的系统小工具：端口/进程/健康检查/清理。

从 pbab.py 拆出来；这些函数只碰 socket / tasklist / psutil，不认识 registry。
"""
from __future__ import annotations

import json
import logging
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple

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


def _http_ok(port: int, health: Dict[str, Any], timeout: float = 1.8) -> bool:
    """模块自己的 /health 语义检查：端口通不代表服务活着。"""
    try:
        p = int(port or health.get("port") or 0)
    except (TypeError, ValueError):
        return False
    if not p:
        return False
    path = str(health.get("path") or "/health")
    if not path.startswith("/"):
        path = "/" + path
    url = f"http://127.0.0.1:{p}{path}"
    try:
        with urllib.request.urlopen(url, timeout=max(0.3, float(timeout))) as resp:
            return 200 <= int(getattr(resp, "status", 0) or 0) < 400
    except OSError:
        return False


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
        if health.get("type") == "http" and _http_ok(int(port or health.get("port") or 0), health):
            return True
        if health.get("type") == "process" and health.get("pid") and _pid_alive(int(health["pid"])):
            return True
        time.sleep(0.5)
    return False


def check_health(mod: Dict[str, Any], health: Dict[str, Any] | None = None,
                 timeout: float = 1.8) -> Tuple[bool, str]:
    """运行期健康检查：返回 (ok, 人话原因)。

    - 有 pid 先看进程；进程没了，端口被别的程序占着也不算它活着。
    - health.type=http 时真请求一次 /health；port 只做 TCP；process 只看 pid。
    - 模组没写 health 时退回「端口能连」或「进程还在」。
    """
    doc = health if health is not None else (mod.get("health") or {})
    try:
        port = int(mod.get("runtime_port") or 0)
    except (TypeError, ValueError):
        port = 0
    if not port:
        try:
            ports = mod.get("ports") or []
            port = int(ports[0]) if ports else 0
        except (TypeError, ValueError, IndexError):
            port = 0
        if not port:
            try:
                port = int(doc.get("port") or 0)
            except (TypeError, ValueError):
                port = 0
    try:
        pid = int(mod.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0

    if pid and not _pid_alive(pid):
        return False, f"进程 {pid} 已经不在"
    typ = str(doc.get("type") or "")
    if typ == "http":
        if _http_ok(port, doc, timeout):
            return True, ""
        return False, f"HTTP 健康检查没通过（端口 {port}{doc.get('path') or '/health'}）"
    if typ == "port":
        if port and _port_open(port, str(doc.get("host") or "127.0.0.1"), timeout):
            return True, ""
        return False, f"端口 {port} 连不上"
    if typ == "process":
        return (True, "") if pid else (False, "清单没给 pid")
    if port:
        if _port_open(port, timeout=timeout):
            return True, ""
        return False, f"端口 {port} 连不上"
    if pid:
        return True, ""
    return True, ""


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
