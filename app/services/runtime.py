"""内核托管：保证「这一份」的内核在跑，而不是连到别人的 40720。

背景：一个端口只能有一个内核。先起来的那份占住 40720 之后，另一份安装点开
只会连到「别人的内核」——它读的是人家目录里的 llm.json / persona.md，于是
出现「明明填了 Key，保姆还说 no api key」「人格写不进去」这类怪事。

这里的策略不是让用户去停别人的进程，而是：
- 端口上是我们自己的内核 → 直接用；
- 端口上跑着别人的内核 → 换一个空闲端口，写回 config/app.yaml 与启动脚本，自己拉起一份；
- 端口上什么都没有 → 直接拉起。

STATE 是给界面轮询的：调用方不必等线程，读 STATE 就知道现在到哪一步了。
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import httpx

from ..core import config

log = logging.getLogger("xiaochen")

STATE: Dict[str, Any] = {
    "state": "unknown",  # unknown | starting | ok | failed
    "port": None,
    "url": "",
    "root": "",
    "detail": "",
    "at": 0.0,
}

_lock = threading.Lock()
_boot_handle = None  # 保持文件句柄，别让子进程的 stdout 被 GC 关掉


def _set(**kw: Any) -> None:
    STATE.update(kw)
    STATE["at"] = time.time()


def status() -> Dict[str, Any]:
    return dict(STATE)


def project() -> Path:
    return Path(config.get("project_root", config.DEFAULTS["project_root"]))


def core_url() -> str:
    return str(config.get("core_url") or "http://127.0.0.1:40720").rstrip("/")


def _port_of(url: str) -> int:
    try:
        tail = url.rsplit(":", 1)[-1].rstrip("/")
        return int(tail)
    except (ValueError, IndexError, AttributeError):
        return int(config.get("ports.core", 40720) or 40720)


def _probe(url: str, timeout: float = 2.0) -> Optional[Dict[str, Any]]:
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.get(url.rstrip("/") + "/health")
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict):
                    return data
    except (httpx.HTTPError, OSError, ValueError):
        return None
    return None


def _root_of(health: Any) -> str:
    return str((health or {}).get("root") or "").strip().rstrip("\\").lower()


def is_ours(health: Any) -> bool:
    root = _root_of(health)
    local = str(project()).strip().rstrip("\\").lower()
    return bool(root) and bool(local) and root == local


def _port_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        s.bind(("127.0.0.1", int(port)))
        return True
    except OSError:
        return False
    finally:
        try:
            s.close()
        except OSError:
            pass


def _write_install_base(base: int) -> None:
    """把端口块基址写进 config/install.json（install_id 保持不变）。"""
    import json

    path = config.APP_DIR / "config" / "install.json"
    doc = {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    doc.setdefault("install_id", __import__("uuid").uuid4().hex)
    doc["base"] = int(base)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        log.warning("写 install.json 失败：%s", exc)


def _allocate_block(start: int) -> int:
    """找一段 20 个口的块：B(core)、B+1(asr)、B+5..B+19(模组池)。"""
    base = int(start)
    for b in range(base, base + 800, 20):
        need = [b, b + 1] + list(range(b + 5, b + 20))
        if all(_port_free(p) for p in need):
            if b != int(start):
                _write_install_base(b)
            return b
    return _pick_port(start)


def _pick_port(start: int, avoid: Iterable[int] = ()) -> int:
    skip = {int(p) for p in avoid}
    for port in range(int(start), int(start) + 80):
        if port in skip:
            continue
        if _port_free(port):
            return port
    raise RuntimeError("从 %d 起找不到空闲端口" % start)


def _replace_in_file(path: Path, pairs: Iterable[tuple]) -> None:
    if not path.exists():
        return
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    new = text
    for old, val in pairs:
        new = new.replace(old, val)
    if new != text:
        try:
            path.write_text(new, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            log.warning("改写 %s 失败：%s", path, exc)


def write_port(port: int) -> str:
    """把新端口写回配置与启动脚本；返回新的 core_url。"""
    cfg = config.load(force=True)
    url = "http://127.0.0.1:%d" % port
    old_url = str(cfg.get("core_url") or "")
    cfg["core_url"] = url
    ports = cfg.get("ports")
    if isinstance(ports, dict):
        ports["core"] = int(port)
    else:
        cfg["ports"] = {"core": int(port), "asr": int(config.get("ports.asr", 40715) or 40715)}
    config.save(cfg)
    config_load = getattr(config, "load", None)
    if config_load:
        try:
            config_load(force=True)
        except (OSError, ValueError, RuntimeError):
            pass

    old_port = str(_port_of(old_url)) if old_url else ""
    proj = project()
    files = [
        proj / "source_code" / "scripts" / "start-core.cmd",
        proj / "source_code" / "scripts" / "start-all.ps1",
        proj / "source_code" / "scripts" / "stop-all.ps1",
    ]
    for f in files:
        if old_port and old_port != str(port):
            _replace_in_file(f, [(old_port, str(port))])
    log.info("内核端口改为 %s（%s）", port, url)
    return url


def _venv_python() -> Optional[Path]:
    cand = project() / "entity" / ".venv" / "Scripts" / "python.exe"
    if cand.exists():
        return cand
    alt = project() / "entity" / "core" / ".venv" / "Scripts" / "python.exe"
    if alt.exists():
        return alt
    return None


def _spawn(port: int) -> int:
    global _boot_handle
    entity = project() / "entity"
    py = _venv_python()
    if py is None:
        raise RuntimeError("找不到内核解释器：%s 不存在（先跑一遍 setup）" % (entity / ".venv"))
    env = os.environ.copy()
    env.update(
        {
            "BAB_ROOT": str(config.APP_DIR),  # 程序根（内核会自己拼 WiseEntity）
            "BAB_PORT": str(port),
            "PYTHONPATH": str(entity),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
        }
    )
    logdir = config.APP_DIR / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    if _boot_handle is None:
        _boot_handle = (logdir / "core-boot.log").open("a", encoding="utf-8", errors="replace")
    flags = 0
    if os.name == "nt":
        flags = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        [str(py), "-m", "uvicorn", "core.app:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(entity),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=_boot_handle,
        stderr=subprocess.STDOUT,
        creationflags=flags,
    )
    log.info("已拉起内核 pid=%s port=%s", proc.pid, port)
    return proc.pid


def ensure(timeout: float = 45.0) -> Dict[str, Any]:
    """确保「我们自己的」内核在跑；返回 {ok, how, port, url, detail, root}。"""
    with _lock:
        url = core_url()
        health = _probe(url)
        if health and is_ours(health):
            _set(state="ok", port=_port_of(url), url=url, root=_root_of(health), detail="")
            return dict(STATE, ok=True, how="already")

        moved = bool(health)  # 端口上是别人的内核
        start_port = _port_of(url)
        if moved or not _port_free(start_port):
            port = _allocate_block(start_port)
            how = "moved"
        else:
            port = start_port
            how = "started"

        if port != start_port:
            url = write_port(port)
        else:
            url = "http://127.0.0.1:%d" % port

        _set(state="starting", port=port, url=url, detail="正在启动这一份的内核…")
        try:
            _spawn(port)
        except Exception as exc:  # noqa: BLE001
            _set(state="failed", detail=str(exc))
            return dict(STATE, ok=False, how=how)

        deadline = time.time() + max(5.0, float(timeout))
        while time.time() < deadline:
            time.sleep(0.4)
            health = _probe(url, 1.5)
            if health and is_ours(health):
                _set(state="ok", root=_root_of(health), detail="")
                return dict(STATE, ok=True, how=how)
            if health and not is_ours(health):
                _set(state="failed", detail="端口 %d 上又出现了别人的内核" % port)
                return dict(STATE, ok=False, how=how)

        _set(state="failed", detail="内核 %d 秒内没起来，看 logs/core-boot.log" % int(timeout))
        return dict(STATE, ok=False, how=how)


def ensure_async(timeout: float = 45.0) -> None:
    """界面用：不阻塞，进度看 STATE。失败后 20 秒内不反复重拉。"""
    age = time.time() - float(STATE.get("at") or 0)
    if STATE.get("state") == "starting" and age < 90:
        return
    if STATE.get("state") == "failed" and age < 20:
        return
    _set(state="starting", detail="正在确认内核…")
    threading.Thread(target=ensure, kwargs={"timeout": timeout}, name="core-ensure", daemon=True).start()


def quick() -> Dict[str, Any]:
    """一次很短的探测（给界面周期刷新用），不启动任何东西。"""
    url = core_url()
    health = _probe(url, 1.0)
    if health and is_ours(health):
        _set(state="ok", port=_port_of(url), url=url, root=_root_of(health), detail="")
    elif health:
        _set(state="failed", port=_port_of(url), url=url, root=_root_of(health),
             detail="这个端口上是另一份安装的内核（%s）" % _root_of(health))
    else:
        _set(state="failed", port=_port_of(url), url=url, detail="内核没有响应")
    return status()
