"""语音转写（ASR）小服务的启停。

和内核一样由外壳看着：设置里勾上「语音转写」→ 启动它；取消 → 停掉。
它只是个本机 HTTP 服务（默认 40715），引擎与模型都在
`WiseEntity\\capability\\voice\\asr\\` 里，不存在就不启动，也不假装能用。
"""
from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from ..core import config

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None

STATE: Dict[str, Any] = {
    "state": "unknown",      # unknown | off | starting | ok | failed | no_engine
    "port": None,
    "detail": "",
    "engine": "",
    "model": "",
    "at": 0.0,
}

_lock = threading.Lock()
_handle = None          # 保住子进程 stdout 的文件句柄


def port() -> int:
    try:
        return int(config.get("ports.asr") or 40715)
    except Exception:
        return 40715


def enabled() -> bool:
    return bool(config.get("asr_enabled", False))


def set_enabled(on: bool) -> None:
    cfg = config.load(force=True)
    cfg["asr_enabled"] = bool(on)
    config.save(cfg)


def cmd_path() -> Path:
    return Path(str(config.get("start_asr") or ""))


def installed() -> bool:
    try:
        return cmd_path().is_file()
    except Exception:
        return False


def _set(**kw: Any) -> None:
    STATE.update(kw)
    STATE["at"] = time.time()


def _port_open(p: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(p)), timeout=timeout):
            return True
    except OSError:
        return False


def health(timeout: float = 1.5) -> Optional[Dict[str, Any]]:
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.get(f"http://127.0.0.1:{port()}/health")
            if r.status_code == 200:
                data = r.json()
                return data if isinstance(data, dict) else None
    except (httpx.HTTPError, OSError, ValueError):
        return None
    return None


def status(probe: bool = True) -> Dict[str, Any]:
    """给界面看的一眼状态。probe=False 只读缓存，不碰网络。"""
    if not enabled():
        _set(state="off", port=port(), detail="没开")
        return dict(STATE)
    if not installed():
        _set(state="no_engine", port=port(), detail="找不到 start-asr.cmd")
        return dict(STATE)
    if not probe:
        return dict(STATE)
    data = health()
    if data:
        engine = "ok" if data.get("engine") else str(data.get("engine_why") or "没装引擎")
        _set(state="ok", port=port(), engine=engine, model=str(data.get("model") or ""),
             detail="")
        return dict(STATE)
    if _port_open(port()):
        _set(state="starting", port=port(), detail="端口开着，还没应答")
    else:
        _set(state="failed", port=port(), detail="没在跑")
    return dict(STATE)


def _spawn() -> None:
    global _handle
    cmd = cmd_path()
    logs = Path(str(config.get("logs_dir") or (config.APP_DIR / "logs")))
    logs.mkdir(parents=True, exist_ok=True)
    if _handle is None:
        _handle = (logs / "asr-boot.log").open("a", encoding="utf-8", errors="replace")
    flags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        flags = subprocess.CREATE_NO_WINDOW
    env = dict(os.environ)
    env["BAB_ASR_PORT"] = str(port())
    subprocess.Popen(
        ["cmd.exe", "/c", str(cmd)],
        cwd=str(cmd.parent),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=_handle,
        stderr=subprocess.STDOUT,
        creationflags=flags,
    )


def start(timeout: float = 20.0) -> Dict[str, Any]:
    with _lock:
        if not installed():
            _set(state="no_engine", detail="找不到 start-asr.cmd")
            return dict(STATE)
        data = health(1.0)
        if data:
            _set(state="ok", port=port(), engine="ok" if data.get("engine") else str(data.get("engine_why") or ""),
                 model=str(data.get("model") or ""))
            return dict(STATE)
        _set(state="starting", port=port(), detail="正在启动语音服务…")
        try:
            _spawn()
        except Exception as exc:  # noqa: BLE001
            _set(state="failed", detail=str(exc))
            return dict(STATE)
        deadline = time.time() + max(3.0, float(timeout))
        while time.time() < deadline:
            time.sleep(0.3)
            data = health(0.8)
            if data:
                _set(state="ok", engine="ok" if data.get("engine") else str(data.get("engine_why") or ""),
                     model=str(data.get("model") or ""), detail="")
                return dict(STATE)
        _set(state="failed", detail="20 秒没起来，看 logs/asr-boot.log")
        return dict(STATE)


def _pids_on_port(p: int) -> list[int]:
    if psutil is None:
        return []
    out: list[int] = []
    try:
        for conn in psutil.net_connections(kind="inet"):
            if not conn.laddr or int(getattr(conn.laddr, "port", 0) or 0) != int(p):
                continue
            if conn.status != psutil.CONN_LISTEN:
                continue
            if conn.pid:
                out.append(int(conn.pid))
    except psutil.Error:
        return []
    return out


def stop() -> Dict[str, Any]:
    for pid in set(_pids_on_port(port())):
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            proc.wait(timeout=5)
        except (psutil.Error, OSError):
            try:
                psutil.Process(pid).kill()
            except psutil.Error:
                pass
    _set(state="off", detail="已停")
    return dict(STATE)


def ensure_async() -> None:
    """启动时叫一次：开着才拉起，别每次开程序都弹个失败。"""
    if not enabled() or not installed():
        return
    if health(1.0):
        status(probe=False)
        return
    threading.Thread(target=start, name="asr-start", daemon=True).start()
