"""耳目的本机小门：内核（以及模组经内核）问启动器「看一眼 / 听一下」。

只在 127.0.0.1 上开一个临时端口，端口和令牌写进 `config/sense.json`；
内核那边 `bridge._sense_post` 照着这个文件来敲门。启动器一关，门就没了。
"""
from __future__ import annotations

import hmac
import logging
import json
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

from . import sense

log = logging.getLogger("xiaochen.sense_server")

_LOCK = threading.Lock()
STATE: Dict[str, Any] = {"server": None, "thread": None, "port": 0, "token": "", "error": "",
                         "bg_rev": 0, "mouse": {"x": 0, "y": 0, "inside": False}}


def set_mouse(x: float, y: float, inside: bool) -> None:
    """主线程每 200ms 喂一次：鼠标在窗口里的坐标（窗口外不算）。"""
    STATE["mouse"] = {"x": round(float(x), 1), "y": round(float(y), 1), "inside": bool(inside)}


def mouse() -> Dict[str, Any]:
    return dict(STATE.get("mouse") or {"x": 0, "y": 0, "inside": False})


def ui_rev() -> int:
    return int(STATE.get("bg_rev") or 0)


def _bump_ui() -> None:
    STATE["bg_rev"] = int(STATE.get("bg_rev") or 0) + 1


def _safe_dir(raw: str) -> Path:
    """只允许在安装目录里建目录；越界、指向文件、空路径都拒绝。"""
    from ..core import config

    text = str(raw or "").strip()
    if not text:
        raise ValueError("path 不能为空")
    p = Path(text).expanduser()
    root = Path(config.APP_DIR).resolve()
    if not p.is_absolute():
        p = root / p
    p = p.resolve()
    if p != root and root not in p.parents:
        raise ValueError("只能在本安装目录里建目录")
    if p.exists() and not p.is_dir():
        raise ValueError("这个路径已经被一个文件占用了")
    p.mkdir(parents=True, exist_ok=True)
    return p


class _Handler(BaseHTTPRequestHandler):
    server_version = "BAB-Sense/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:  # noqa: D401
        pass

    def _send(self, code: int, doc: Dict[str, Any]) -> None:
        raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        self.send_response(int(code))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except Exception:  # noqa: BLE001
            log.debug("写回耳目响应失败（客户端可能已断开）", exc_info=True)

    def _auth(self) -> bool:
        got = str(self.headers.get("X-Sense-Token") or "")
        want = str(STATE.get("token") or "")
        return bool(want) and hmac.compare_digest(got, want)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/health":
            self._send(200, {"ok": True, "service": "sense"})
            return
        if not self._auth():
            self._send(403, {"ok": False, "error": "令牌不对"})
            return
        try:
            if path == "/ui/background":
                from ..ui import backdrop
                self._send(200, {"ok": True, "config": backdrop.cfg()})
                return
            if path == "/ui/mouse":
                self._send(200, {"ok": True, **mouse()})
                return
        except Exception as e:  # noqa: BLE001
            self._send(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})
            return
        self._send(404, {"ok": False, "error": "没有这个路口"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n > 0 else b"{}"
            payload = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                payload = {}
        except Exception:  # noqa: BLE001
            payload = {}
        if not self._auth():
            self._send(403, {"ok": False, "error": "令牌不对"})
            return
        path = self.path.split("?")[0]
        try:
            if path == "/devices":
                doc = sense.devices()
            elif path == "/look":
                q = str(payload.get("question") or "")
                doc = sense.look(q, quiet=True) if payload.get("quiet") else sense.look(q)
            elif path == "/listen":
                try:
                    sec = float(payload.get("seconds") or 6)
                except (TypeError, ValueError):
                    sec = 6.0
                doc = sense.listen(sec, quiet=True) if payload.get("quiet") else sense.listen(sec)
            elif path == "/ui/background":
                from ..ui import backdrop
                keep = {"enabled", "effect", "follower", "click", "click_style",
                        "opacity", "speed"}
                patch = {k: payload[k] for k in keep if k in payload}
                if not patch:
                    raise ValueError("没有可改的项")
                doc = {"ok": True, "config": backdrop.save(patch)}
                _bump_ui()
            elif path == "/bridge/project/apply":
                from ..core import pbab, pre_bridge, registry

                mid = str(payload.get("module") or "").strip()
                rec = registry.get(mid) or {}
                if str(rec.get("kind") or "") != pbab.KIND_PRE:
                    raise ValueError("只有 pre-program_*.pbab 前置模组能申请改文件")
                if str(rec.get("state") or "") != "enabled":
                    raise ValueError("这个前置模组还没启用")
                ops = payload.get("ops")
                # 前置模组按设计是「装一次、之后自己干活」：不再逐次弹窗，
                # 只保留整包备份和 pre_audit.jsonl 审计。
                doc = pre_bridge.apply(ops, mid, str(payload.get("reason") or ""))
            elif path == "/fs/mkdir":
                p = _safe_dir(str(payload.get("path") or ""))
                doc = {"ok": True, "path": str(p)}
            elif path == "/config/set":
                from ..core import config
                key = str(payload.get("key") or "").strip()
                if not key.startswith("ui."):
                    raise ValueError("模组只能改 ui.* 这类界面配置")
                if "value" not in payload:
                    raise ValueError("缺少 value")
                if key.startswith("ui.background"):
                    leaf = key.split(".")[-1]
                    if leaf in ("media", "source"):
                        raise ValueError("图片/视频路径只能由主人自己在「外观」页选")
                    if isinstance(payload["value"], (dict, list)):
                        raise ValueError("背景配置只能一项一项改，不能整块塞")
                config.set_value(key, payload["value"])
                if key.startswith("ui.background"):
                    _bump_ui()
                doc = {"ok": True, "key": key, "value": config.get(key)}
            else:
                self._send(404, {"ok": False, "error": "没有这个路口"})
                return
        except Exception as e:  # noqa: BLE001
            self._send(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})
            return
        if not isinstance(doc, dict):
            doc = {"ok": True, "data": doc}
        self._send(200, doc)


def start() -> Dict[str, Any]:
    """开一个小端口；已经在跑就回原来的。失败不抛，把原因写进 STATE。"""
    with _LOCK:
        srv: Optional[ThreadingHTTPServer] = STATE.get("server")
        if srv is not None:
            return info()
        try:
            token = sense.token()
            srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
            srv.daemon_threads = True
            port = int(srv.server_address[1])
            STATE.update({"server": srv, "port": port, "token": token, "error": ""})
            sense.set_port(port)
            th = threading.Thread(target=srv.serve_forever, name="sense-http", daemon=True)
            th.start()
            STATE["thread"] = th
        except Exception as e:  # noqa: BLE001
            STATE.update({"server": None, "port": 0, "error": f"{type(e).__name__}: {e}"})
        return info()


def stop() -> None:
    with _LOCK:
        srv = STATE.get("server")
        STATE.update({"server": None, "thread": None, "port": 0})
        if srv is not None:
            try:
                srv.shutdown()
            except Exception:  # noqa: BLE001
                log.debug("关闭耳目小门失败", exc_info=True)
            try:
                srv.server_close()
            except Exception:  # noqa: BLE001
                log.debug("释放耳目小门端口失败", exc_info=True)
    try:
        sense.set_port(0)
    except Exception:  # noqa: BLE001
        log.debug("清空耳目端口失败", exc_info=True)


def info() -> Dict[str, Any]:
    return {"ok": STATE.get("server") is not None, "port": int(STATE.get("port") or 0),
            "error": str(STATE.get("error") or "")}


def running() -> bool:
    return STATE.get("server") is not None
