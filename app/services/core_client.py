"""内核 REST 客户端：只读 40720，唯一的写是 POST /chat（等同于在网页客厅说话）。

契约来源：docs/core-api-snapshot.json（实抓），不是只信 openapi。
"""
from __future__ import annotations

import atexit
import logging
import threading
from typing import Any, Dict, List, Optional

import httpx

from ..core import config

# 共享连接池：每个请求原来都新建 httpx.Client，本地握手与连接建立全浪费。
# httpx.Client 本身线程安全；按 base 分开，端口换了不会串。
_CLIENTS: Dict[str, httpx.Client] = {}
log = logging.getLogger("xiaochen.core_client")
_CLIENT_LOCK = threading.Lock()
_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE: Dict[str, Any] = {"path": "", "mtime": 0.0, "token": ""}


def _core_token() -> str:
    """读内核写的本机 token；文件可能还没生成（内核刚起），读不到就空。"""
    try:
        path = config.entity_dir() / "state" / "core_token"
    except Exception:  # noqa: BLE001
        return ""
    try:
        st = path.stat()
    except OSError:
        return ""
    key = str(path)
    with _TOKEN_LOCK:
        if _TOKEN_CACHE["path"] == key and float(_TOKEN_CACHE["mtime"]) == st.st_mtime:
            return str(_TOKEN_CACHE["token"] or "")
        try:
            val = path.read_text(encoding="utf-8").strip()
        except Exception:  # noqa: BLE001
            val = ""
        _TOKEN_CACHE.update({"path": key, "mtime": st.st_mtime, "token": val})
        return val


def _local_headers() -> Dict[str, str]:
    tok = _core_token()
    return {"X-BAB-Core-Token": tok} if tok else {}


def _shared_client(base: str) -> httpx.Client:
    with _CLIENT_LOCK:
        c = _CLIENTS.get(base)
        if c is None or c.is_closed:
            c = httpx.Client(base_url=base, timeout=8.0,
                             limits=httpx.Limits(max_connections=24,
                                                 max_keepalive_connections=12))
            _CLIENTS[base] = c
        return c


def _close_clients() -> None:
    with _CLIENT_LOCK:
        for c in _CLIENTS.values():
            try:
                c.close()
            except Exception:  # noqa: BLE001
                log.debug("关闭共享 HTTP client 失败", exc_info=True)
        _CLIENTS.clear()


atexit.register(_close_clients)


class CoreUnavailable(RuntimeError):
    pass


class CoreClient:
    def __init__(self, base: Optional[str] = None, timeout: float = 8.0):
        self.base = (base or config.get("core_url")).rstrip("/")
        self.timeout = timeout

    # ---- 基础 ----
    def _get(self, path: str, timeout: Optional[float] = None) -> Any:
        try:
            c = _shared_client(self.base)
            r = c.get(path, timeout=timeout or self.timeout, headers=_local_headers())
            r.raise_for_status()
            return r.json()
        except Exception as e:
            raise CoreUnavailable(f"GET {path} 失败：{e}") from e

    def _post(self, path: str, payload: Dict[str, Any], timeout: Optional[float] = None) -> Any:
        try:
            c = _shared_client(self.base)
            r = c.post(path, json=payload, timeout=timeout or self.timeout,
                       headers=_local_headers())
            r.raise_for_status()
            return r.json()
        except Exception as e:
            raise CoreUnavailable(f"POST {path} 失败：{e}") from e

    # ---- 读 ----
    def health(self) -> Dict[str, Any]:
        return self._get("/health", timeout=4)

    def state(self) -> Dict[str, Any]:
        return self._get("/state")

    def brain_state(self) -> Dict[str, Any]:
        return self._get("/brain/state")

    def drives(self) -> Dict[str, Any]:
        return self._get("/drives")

    def stomach(self) -> Dict[str, Any]:
        return self._get("/stomach")

    def stomach_config(self) -> Dict[str, Any]:
        """饱 / 饿两个分界（元）。"""
        return self._get("/stomach/config")

    def stomach_set(self, full_at: float, hungry_at: float) -> Any:
        return self._post("/stomach/config",
                          {"full_at": float(full_at), "hungry_at": float(hungry_at)},
                          timeout=20)

    def memory_stats(self) -> Dict[str, Any]:
        """记忆库占了多少 / 压缩与保留的配置。"""
        return self._get("/memory/stats", timeout=6)

    def memory_save(self, max_gb: float, compress_gb: float, keep_days: int) -> Any:
        return self._post("/memory/config",
                          {"max_gb": float(max_gb), "compress_gb": float(compress_gb),
                           "keep_days": int(keep_days)},
                          timeout=15)

    def emotions(self) -> Dict[str, Any]:
        return self._get("/emotions")

    def persona(self) -> Dict[str, Any]:
        return self._get("/persona")

    def proactive_last(self) -> Dict[str, Any]:
        """内核最近一次主动开口（给托盘小窗用）。"""
        try:
            return self._get("/proactive/last", timeout=4) or {}
        except CoreUnavailable:
            return {}

    def self_state(self) -> Dict[str, Any]:
        """她自己写的自我档案与能力证据统计（只读）。"""
        try:
            return self._get("/self", timeout=4) or {}
        except CoreUnavailable:
            return {}

    def notices(self, session: str = "web:owner", after: float = 0.0) -> List[Dict[str, Any]]:
        try:
            out = self._get(f"/notices?session={session}&after={after:.3f}", timeout=4)
            return out.get("notices", []) if isinstance(out, dict) else []
        except CoreUnavailable:
            return []

    def notice_push(self, text: str, session: str = "web:owner",
                    kind: str = "nanny") -> Dict[str, Any]:
        """把外壳这边的保姆提醒写进内核的 notices.jsonl（重启后还能看到）。"""
        return self._post("/notice", {"text": text, "session": session, "kind": kind}, timeout=6)

    def vision(self, path: str = "", question: str = "") -> Dict[str, Any]:
        """让内核的主模型看一张图（启动器的耳目用它）。"""
        return self._post("/vision", {"path": path, "question": question}, timeout=120) or {}

    def asr(self, path: str = "", audio: str = "", hint: str = "") -> Dict[str, Any]:
        """让内核的语音服务把一段录音转成字。"""
        return self._post("/asr", {"path": path, "audio": audio, "hint": hint}, timeout=140) or {}

    def ports_map(self) -> Dict[str, Any]:
        return self._get("/ports", timeout=4) or {}

    def bridge_modules(self) -> Dict[str, Any]:
        return self._get("/bridge/modules", timeout=4) or {}

    def set_grant(self, module: str, cap: str, allow: bool) -> Dict[str, Any]:
        return self._post("/bridge/grants", {"module": module, "cap": cap, "allow": bool(allow)}, timeout=4) or {}

    def programs(self) -> List[Dict[str, Any]]:
        try:
            out = self._get("/programs")
            return out.get("programs", out) if isinstance(out, dict) else out
        except CoreUnavailable:
            return []

    def diary(self, days: int = 3) -> Any:
        return self._get(f"/diary?days={days}")

    def memory(self, q: str = "", session: str = "qq:owner", all_: bool = False) -> Any:
        return self._get(f"/memory?q={q}&session={session}&all={'1' if all_ else '0'}")

    def presence(self) -> Dict[str, Any]:
        return self._get("/presence")

    def feed(self, session: Optional[str] = None, after: int = 0) -> Dict[str, Any]:
        session = session or config.get("chat.session", "web:owner")
        return self._get(f"/chat/feed?session={session}&after={after}")

    def proactive_send(self, force: bool = True) -> Dict[str, Any]:
        return self._post(f"/proactive/send?force={1 if force else 0}", {}, timeout=120)

    # ---- 写（唯一的两个：说话、改自己的在线状态） ----
    def set_presence(self, state: str) -> Dict[str, Any]:
        return self._post("/presence", {"state": state}, timeout=6)

    def emotion_stimulus(self, kind: str, intensity: float = 1.0) -> Dict[str, Any]:
        """给她的情绪记一笔（比如话说一半被打断，剩下几句咽回去了）。"""
        return self._post("/emotion/stimulus", {"kind": kind, "intensity": intensity},
                          timeout=10)

    def tts_voices(self) -> Any:
        return self._get("/tts/voices", timeout=10)

    def tts_config(self, voice: str = "", rate: str = "", **kw: Any) -> Any:
        payload: Dict[str, Any] = {"voice": voice, "rate": rate}
        payload.update({k: v for k, v in kw.items()
                        if v not in (None, "") or k == "local_ref"})
        return self._post("/tts/config", payload, timeout=10)

    def followup_get(self) -> Any:
        return self._get("/followup/config", timeout=8)

    def followup_set(self, level: int) -> Any:
        return self._post("/followup/config", {"level": int(level)}, timeout=8)

    def tts_say(self, text: str, voice: str = "", rate: str = "",
                use: str = "chat", timeout: Optional[float] = None) -> bytes:
        """合成一句音频，返回字节；失败抛异常。

        use="chat" 用「朗读引擎」，use="preview" 用「试听引擎」。
        """
        import httpx

        # 试听可能走 BreezeBlue（实测十几秒到一分钟），本地 MOSS 首次加载模型更久
        if timeout is None:
            timeout = 180.0 if use == "preview" else 45.0
        with httpx.Client(timeout=timeout) as c:
            r = c.post(self.base + "/tts",
                       json={"text": text, "voice": voice, "rate": rate, "use": use},
                       headers=_local_headers())
            if r.status_code != 200:
                raise RuntimeError(f"TTS {r.status_code}: {r.text[:160]}")
            return r.content

    def chat(self, text: str, session: Optional[str] = None,
             is_owner: Optional[bool] = True, sender_name: str = "") -> Dict[str, Any]:
        session = session or config.get("chat.session", "web:owner")
        timeout = float(config.get("chat.timeout_s", 90))
        return self._post("/chat", {"session": session, "text": text,
                                    "sender_name": sender_name, "is_owner": is_owner},
                          timeout=timeout)

    def event(self, kind: str, text: str = "", is_owner: bool = True) -> Dict[str, Any]:
        return self._post("/event", {"kind": kind, "text": text, "is_owner": is_owner})

    # ---- 保姆 / 教程 / 建档 ----
    def nanny_status(self) -> Dict[str, Any]:
        return self._get("/nanny/status")

    def nanny_panel(self, limit: int = 160) -> Dict[str, Any]:
        return self._get(f"/nanny/panel?limit={int(limit)}", timeout=20) or {}

    def nanny_analyze(self, kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._post("/nanny/analyze", {"kind": kind, "payload": payload}, timeout=90)

    def nanny_chat_open(self) -> Dict[str, Any]:
        return self._post("/nanny/chat/open", {}, timeout=20) or {}

    def nanny_chat(self, session: str, text: str) -> Dict[str, Any]:
        return self._post("/nanny/chat", {"session": session, "text": text}, timeout=120) or {}

    def nanny_chat_close(self, session: str) -> Dict[str, Any]:
        return self._post("/nanny/chat/close", {"session": session}, timeout=10) or {}

    def tutorial_get(self) -> Dict[str, Any]:
        return self._get("/tutorial")

    def tutorial_update(self, action: str, turn: Optional[int] = None) -> Dict[str, Any]:
        return self._post("/tutorial", {"action": action, "turn": turn})

    def setup(self, api_key: str = "", api_base: str = "", model: str = "",
              entity_name: str = "", persona: str = "") -> Dict[str, Any]:
        return self._post("/setup", {"api_key": api_key, "api_base": api_base,
                                     "model": model, "entity_name": entity_name,
                                     "persona": persona}, timeout=20)
