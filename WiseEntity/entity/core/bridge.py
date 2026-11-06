"""桥：模组与 BAB 之间唯一的门（保姆在这里鉴权、限权、审计、分发）。

三个端点，模组只需要记住两个：
  GET  /bridge/manifest          我这次能申请什么（能力清单 + 事件种类）
  POST /bridge/call              要一样东西          {"cap": "...", "args": {...}}
  GET  /bridge/events?since=&wait=   等信号（长轮询）

鉴权：每个模组启用时会在自己目录里拿到 bridge_token.txt，请求带 X-BAB-Token。
权限：module.json 的 bridge.wants 就是白名单，没申请的调不动。
审计：每次调用写一行 entity/state/bridge_audit.jsonl。
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from . import (brain_box, drives, emotion_core, event_bus, llm_box, memory_box,
               memory_store, modules_box, presence, sense, settings as S,
               style_box, tts)
from .llm_box import NotConfigured

router = APIRouter(prefix="/bridge", tags=["bridge"])
BRIDGE_VERSION = "1"

EVENT_KINDS = [
    "message.in", "message.out", "mood.changed", "drive.urge",
    "memory.written", "presence.changed", "proactive.spoke", "world.event",
]

AUDIT_PATH = S.STATE_DIR / "bridge_audit.jsonl"
GRANTS_PATH = S.APP_ROOT / "config" / "bridge_grants.json"


# ---------------------------------------------------------------- 模组与身份

def _token_path(mid: str) -> Path:
    return modules_box.folder(mid) / "bridge_token.txt"


def module_token(mid: str) -> str:
    p = _token_path(mid)
    try:
        return p.read_text(encoding="utf-8").strip() if p.exists() else ""
    except Exception:  # noqa: BLE001
        return ""


def ensure_token(mid: str) -> str:
    """没有就发一个（启用时调用；这里是幂等的兜底）。"""
    tok = module_token(mid)
    if tok:
        return tok
    import secrets

    tok = secrets.token_hex(16)
    try:
        _token_path(mid).write_text(tok, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        S.log(f"[bridge] 写 token 失败 {mid}: {e!r}")
    return tok


def _bridge_cfg(mid: str) -> Dict[str, Any]:
    cfg = modules_box.manifest(mid).get("bridge") or {}
    return cfg if isinstance(cfg, dict) else {}


def _module_by_token(token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    for mod in modules_box.enabled():
        mid = str(mod.get("id") or "")
        if mid and module_token(mid) == token:
            return mod
    return None


def _grants() -> Dict[str, Any]:
    try:
        doc = json.loads(GRANTS_PATH.read_text(encoding="utf-8-sig"))
        return doc if isinstance(doc, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _deny_of(mid: str) -> List[str]:
    rec = (_grants().get("modules") or {}).get(mid) or {}
    return [str(x) for x in (rec.get("deny") or [])]


def _allowed(mid: str, cap: str) -> tuple[bool, str]:
    wants = [str(x) for x in (_bridge_cfg(mid).get("wants") or [])]
    # "*" = 框架类模组：申请所有能力（含以后新加的），不用每加一条就改清单
    if wants and "*" not in wants and cap not in wants:
        return False, "这个模组没申请"
    if cap in _deny_of(mid):
        return False, "使用者在设置里关了"
    return True, ""


def _program_of(mid: str) -> str:
    """模组的记忆抽屉名：清单里写了就用，没写就按它的 id 现起一个。

    以前这里兜底 `program_qq`——清单漏写 memory.program 的模组，记忆会
    悄悄落进 QQ 抽屉。现在按 id 生成，兜底也只兜自己。
    """
    mem = modules_box.manifest(mid).get("memory") or {}
    prog = str(mem.get("program") or "").strip()
    if prog:
        return prog
    return memory_box.program_key("program_" + str(mid))


def _base_url(mod: Dict[str, Any]) -> str:
    port = mod.get("runtime_port") or (modules_box.manifest(str(mod.get("id"))) .get("ports") or [0])[0]
    return f"http://127.0.0.1:{int(port or 0)}"


def _audit(mid: str, cap: str, ok: bool, extra: Optional[Dict[str, Any]] = None) -> None:
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "module": mid, "cap": cap, "ok": bool(ok)}
    if extra:
        rec.update(extra)
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- 能力实现

def _search_notes(mid: str, query: str, limit: int = 8) -> List[Dict[str, Any]]:
    """只在这个模组自己的抽屉里搜：external/<program>/<分类>/<天>.txt。"""
    program = _program_of(mid)
    root = memory_store.memory_root() / memory_store.EXTERNAL / program
    q = (query or "").strip().lower()
    hits: List[Dict[str, Any]] = []
    if not root.exists():
        return hits
    for f in sorted(root.glob("*/*.txt")):
        for rec in memory_store._parse_day_file(f, f.parent.name):
            text = str(rec.get("text") or "")
            if not text:
                continue
            if q and q not in text.lower():
                continue
            hits.append({
                "text": text[:600],
                "scope": f.parent.name,
                "date": rec.get("date") or "",
                "time": rec.get("time") or "",
            })
    hits.sort(key=lambda x: (str(x.get("date") or ""), str(x.get("time") or "")), reverse=True)
    return hits[: max(1, min(int(limit or 8), 50))]


def _brain_snapshot(mid: str) -> Dict[str, Any]:
    emo = emotion_core.state()
    out: Dict[str, Any] = {
        "mood": emotion_core.mood_word(),
        "emotions": emo.get("values") or {},
        "levels": emo.get("levels") or emo.get("band_names") or {},
        "started": emo.get("started"),
        "presence": presence.get().get("state"),
        "notes_total": memory_box.total_notes(),
    }
    try:
        out["drives"] = drives.status()
    except Exception:  # noqa: BLE001
        out["drives"] = {}
    return out


def _mood(mid: str) -> Dict[str, Any]:
    emo = emotion_core.state()
    return {"mood": emotion_core.mood_word(), "values": emo.get("values") or {},
            "levels": emo.get("levels") or emo.get("band_names") or {}}


def _presence(mid: str) -> Dict[str, Any]:
    st = presence.get()
    return {"state": st.get("state"), "label": presence.label(), "updated_at": st.get("updated_at")}


def _note(mid: str, **kw) -> Dict[str, Any]:
    text = str(kw.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text 不能为空")
    program = _program_of(mid)
    category = str(kw.get("category") or "笔记")
    try:
        res = memory_box.add_note(
            text[:1000], program=program, category=category, target="external",
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    event_bus.publish("memory.written", {"program": program, "scope": category, "text": text[:200]})
    return {"saved": True, "program": program, "result": res}


async def _chat_say(mid: str, hint: str = "", text: str = "", **_ignored: Any) -> Dict[str, Any]:
    """让她用自己的话说一句（真发一条消息，不是聊天里插一条系统提示）。

    hint 是「要她说什么事」，例如「到喝水的时间了」。她的话由模型现写。
    """
    from . import chat_core, llm_box, memory_store  # 惰性：避免循环导入

    what = str(hint or text or "").strip()
    if not what:
        raise HTTPException(400, "hint 不能为空")
    session = "web:owner"
    ask = (
        f"（现在轮到你先开口。你要告诉他：{what[:120]}。"
        "用你自己的语气说一句，20 字上下，别用括号写动作，"
        "别提「提醒」「工具」「模组」这些词，也别解释你为什么开口。）"
    )
    line = ""
    try:
        line = await llm_box.chat(session, ask, chat_core.get_history(session))
    except Exception as e:  # noqa: BLE001
        S.log(f"[bridge] chat.say 生成失败：{e!r}")
    line = str(line or "").strip()[:160]
    if not line:
        line = what[:40]
    chat_core.remember_turn(session, "assistant", line)
    chat_core.save_sessions()
    try:
        memory_store.raw_append(session, line, "assistant", who="无名")
    except Exception as e:  # noqa: BLE001
        S.log(f"[bridge] chat.say 落盘失败：{e!r}")
    return {"said": True, "text": line}


def _notice_push(mid: str, text: str = "", chat: bool = False, **_ignored: Any) -> Dict[str, Any]:
    """模组往保姆栏推一条提醒；chat=True 时另推一条 kind=chat，外壳会把它当聊天里的一句话。"""
    body = str(text or "").strip()
    if not body:
        raise HTTPException(400, "text 不能为空")
    body = body[:400]
    from . import chat_core  # 惰性导入，避免循环

    row = chat_core.push_notice("web:owner", body, kind="nanny")
    out: Dict[str, Any] = {"pushed": True, "notice": row}
    if chat:
        short = body if len(body) <= 60 else body[:58] + "…"
        chat_core.push_notice("web:owner", short, kind="chat")
        out["chat"] = True
    return out


# ---------------------------------------------------------------- 声音与眼睛（0.3.20）

_TTS_HITS: Dict[str, List[float]] = {}
_TTS_PER_MIN = 6
_ASR_TIMEOUT = 180.0
_VOICE_IN = S.STATE_DIR / "voice_in"


def _tts_budget(mid: str) -> None:
    now = time.time()
    hits = [t for t in _TTS_HITS.get(mid, []) if now - t < 60.0]
    if len(hits) >= _TTS_PER_MIN:
        raise HTTPException(429, f"语音太密了：一分钟最多 {_TTS_PER_MIN} 段，等一会儿")
    hits.append(now)
    _TTS_HITS[mid] = hits


def _mp3_seconds(path: Path) -> float:
    """粗估时长：mp3 按 48kbps 估，wav 直接读头。"""
    try:
        if str(path).lower().endswith(".wav"):
            import wave

            with wave.open(str(path), "rb") as w:
                return round(w.getnframes() / max(1, w.getframerate()), 2)
        return round(path.stat().st_size * 8 / 48000.0, 2)
    except Exception:  # noqa: BLE001
        return 0.0


def _voice_tts(mid: str, text: str = "", voice: str = "", rate: str = "",
               **_ignored: Any) -> Dict[str, Any]:
    """把一句话合成语音，回 mp3 的路径（模组自己读文件发出去）。"""
    body = str(text or "").strip()
    if not body:
        raise HTTPException(400, "text 不能为空")
    if len(body) > tts.MAX_CHARS:
        raise HTTPException(400, f"一次最多 {tts.MAX_CHARS} 字，这条 {len(body)} 字，拆开说")
    _tts_budget(mid)
    try:
        path = tts.synth_sync(body, str(voice or ""), str(rate or ""))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"合成失败：{e}") from e
    wav = str(path).lower().endswith(".wav")
    return {
        "path": str(path), "mime": "audio/wav" if wav else "audio/mpeg", "chars": len(body),
        "duration_s": _mp3_seconds(path), "cached": tts.cached(body, str(voice or ""), str(rate or "")) is not None,
    }


def _asr_url() -> str:
    return f"http://127.0.0.1:{S.ASR_PORT}"


def _voice_asr(mid: str, path: str = "", audio: str = "", hint: str = "",
               **_ignored: Any) -> Dict[str, Any]:
    """把一段音频转成文字。音频可以是本地路径，也可以是 base64。"""
    import base64

    src = Path(str(path or "")).expanduser()
    if not str(path or "").strip() and audio:
        _VOICE_IN.mkdir(parents=True, exist_ok=True)
        dst = _VOICE_IN / f"in-{int(time.time() * 1000)}.wav"
        try:
            dst.write_bytes(base64.b64decode(str(audio)))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"audio 不是合法的 base64：{e}") from e
        src = dst
    if not str(src) or not src.is_file():
        raise HTTPException(400, "找不到这段音频（path 要给本地文件，或把字节放 audio）")

    token = S.memory_token()
    try:
        r = httpx.post(f"{_asr_url()}/stt",
                       json={"path": str(src), "hint": str(hint or "")},
                       headers={"x-bridge-token": token}, timeout=_ASR_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, "语音服务没起来：先在 设置 → 语音 里打开 ASR") from e
    if r.status_code == 401:
        raise HTTPException(500, "语音服务的令牌对不上：重启一次内核会重新发")
    if r.status_code != 200:
        raise HTTPException(502, f"转写失败：HTTP {r.status_code} {r.text[:160]}")
    try:
        doc = r.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(502, "语音服务回的不是 JSON")
    text = str(doc.get("text") or "").strip()
    return {"text": text, "chars": len(text), "seconds": doc.get("seconds"),
            "engine": doc.get("engine") or "", "path": str(src)}


async def _vision_describe(mid: str, image: str = "", path: str = "",
                           question: str = "", **_ignored: Any) -> Dict[str, Any]:
    """让她看一眼图（文件路径 / data URL / 裸 base64）。"""
    src = str(image or path or "").strip()
    if not src:
        raise HTTPException(400, "image 不能为空（路径、data URL 或 base64）")
    q = str(question or "").strip() or "这张图里有什么？"
    try:
        text = await llm_box.describe_image(src, q)
    except NotConfigured as e:
        raise HTTPException(503, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"看图失败：{e}") from e
    return {"text": text, "chars": len(text), "question": q}


def _avatar_get(mid: str, **_ignored: Any) -> Dict[str, Any]:
    """她的头像：路径 + 是不是主人换的 + 什么时候换的。"""
    from . import avatar

    one = avatar.info()
    return {"ok": True, **one}


# ---------------------------------------------------------------- 耳目（启动器本体）
_SENSE_CFG = sense.CFG_PATH


def _sense_cfg() -> Dict[str, Any]:
    try:
        doc = json.loads(_SENSE_CFG.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _sense_post(path: str, payload: Dict[str, Any], timeout: float = 120.0) -> Dict[str, Any]:
    """转身问启动器：它的耳目服务在本机一个小端口上。"""
    cfg = _sense_cfg()
    try:
        port = int(cfg.get("port") or 0)
    except Exception:  # noqa: BLE001
        port = 0
    if not port:
        raise HTTPException(503, "耳目没开：先打开启动器，在 设置 → 耳目 里开启")
    token = str(cfg.get("token") or "")
    try:
        r = httpx.post(f"http://127.0.0.1:{port}{path}", json=payload,
                       headers={"X-Sense-Token": token}, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, "启动器没在跑，耳目连不上") from e
    if r.status_code == 403:
        raise HTTPException(503, "耳目令牌对不上：重启一次启动器")
    if r.status_code != 200:
        raise HTTPException(502, f"耳目出错：HTTP {r.status_code} {r.text[:160]}")
    try:
        doc = r.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(502, "耳目回的不是 JSON")
    return doc if isinstance(doc, dict) else {"ok": True, "data": doc}


def _sense_devices(mid: str, **_ignored: Any) -> Dict[str, Any]:
    return _sense_post("/devices", {}, timeout=20.0)


def _sense_look(mid: str, question: str = "", **_ignored: Any) -> Dict[str, Any]:
    return _sense_post("/look", {"question": str(question or "")}, timeout=120.0)


def _sense_get(path: str, timeout: float = 20.0) -> Dict[str, Any]:
    """同 _sense_post，只是读：背景参数、鼠标位置走这里。"""
    cfg = _sense_cfg()
    try:
        port = int(cfg.get("port") or 0)
    except Exception:  # noqa: BLE001
        port = 0
    if not port:
        raise HTTPException(503, "启动器没开：界面桥先要启动器在本机开着")
    token = str(cfg.get("token") or "")
    try:
        r = httpx.get(f"http://127.0.0.1:{port}{path}",
                      headers={"X-Sense-Token": token}, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, "启动器没在跑，界面桥连不上") from e
    if r.status_code == 403:
        raise HTTPException(503, "界面桥令牌对不上：重启一次启动器")
    if r.status_code != 200:
        raise HTTPException(502, f"界面桥出错：HTTP {r.status_code} {r.text[:160]}")
    try:
        doc = r.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(502, "界面桥回的不是 JSON")
    return doc if isinstance(doc, dict) else {"ok": True, "data": doc}


def _ui_background_get(mid: str, **_ignored: Any) -> Dict[str, Any]:
    return _sense_get("/ui/background")


def _ui_background_set(mid: str, **kw: Any) -> Dict[str, Any]:
    patch: Dict[str, Any] = {}
    for k in ("enabled", "effect", "follower", "click", "click_style", "opacity", "speed"):
        if k in kw and kw[k] is not None:
            patch[k] = kw[k]
    if not patch:
        raise HTTPException(400, "ui.background.set 至少要给一个要改的项")
    return _sense_post("/ui/background", patch, timeout=20.0)


def _persona_style_get(mid: str, **_ignored: Any) -> Dict[str, Any]:
    doc = style_box.load()
    return {"ok": True, "active": doc is not None, "style": doc,
            "face": style_box.face_spec(doc)}


def _persona_face_get(mid: str, **_ignored: Any) -> Dict[str, Any]:
    return {"ok": True, **style_box.face_spec()}


def _ui_mouse_get(mid: str, **_ignored: Any) -> Dict[str, Any]:
    return _sense_get("/ui/mouse")


def _fs_mkdir(mid: str, path: str = "", **_ignored: Any) -> Dict[str, Any]:
    return _sense_post("/fs/mkdir", {"path": str(path or "")}, timeout=20.0)


def _config_set(mid: str, key: str = "", value: Any = None, **_ignored: Any) -> Dict[str, Any]:
    k = str(key or "").strip()
    if not k.startswith("ui."):
        raise HTTPException(400, "现在只开放 ui.* 这类界面配置，别的一律不改")
    return _sense_post("/config/set", {"key": k, "value": value}, timeout=20.0)


def _project_apply(mid: str, ops: Any = None, reason: str = "", **_ignored: Any) -> Dict[str, Any]:
    """只有 kind=pre 的模组能申请；真正的批准在启动器里由主人点。"""
    doc = modules_box.manifest(mid)
    if str(doc.get("kind") or "") != "pre":
        raise HTTPException(403, "只有 pre-program_*.pbab 前置模组能申请改程序文件")
    if not isinstance(ops, list) or not ops:
        raise HTTPException(400, "ops 必须是非空数组")
    return _sense_post("/bridge/project/apply",
                       {"module": mid, "ops": ops, "reason": str(reason or "")},
                       timeout=200.0)


def _sense_listen(mid: str, seconds: float = 6, **_ignored: Any) -> Dict[str, Any]:
    try:
        sec = float(seconds) if seconds is not None else 6.0
    except Exception:  # noqa: BLE001
        sec = 6.0
    sec = max(1.0, min(20.0, sec))
    return _sense_post("/listen", {"seconds": sec}, timeout=140.0)


CAPS: Dict[str, Dict[str, Any]] = {
    "chat.say": {
        "desc": "让她用自己的话说一句（会真的作为她的发言出现，不是系统提示）",
        "args": {"hint": "string说明要她说什么"},
        "fn": lambda mid, a: _chat_say(mid, **a),
    },
    "memory.search": {
        "desc": "在 BAB 给这个模组留的抽屉里搜记忆（只看得到自己这个程序的抽屉）",
        "args": {"query": "string", "limit": "int=8"},
        "fn": lambda mid, a: _search_notes(mid, str(a.get("query") or ""), int(a.get("limit") or 8)),
    },
    "memory.note": {
        "desc": "往自己的抽屉里记一条（写进 notes.jsonl，也会进她的事件流）",
        "args": {"text": "string", "scope": "owner|friend|group", "group": "string?", "kind_key": "string?"},
        "fn": lambda mid, a: _note(mid, **a),
    },
    "brain.snapshot": {
        "desc": "她的此刻：情绪值、理智、驱力、在线状态、记忆总数",
        "args": {},
        "fn": lambda mid, a: _brain_snapshot(mid),
    },
    "mood.read": {
        "desc": "只看情绪：mood 词 + 13 个值",
        "args": {},
        "fn": lambda mid, a: _mood(mid),
    },
    "presence.read": {
        "desc": "使用者在不在（online/busy/away）",
        "args": {},
        "fn": lambda mid, a: _presence(mid),
    },
    "voice.tts": {
        "desc": "把一句话合成她的声音（edge-tts），回 mp3 的路径；一分钟最多 6 段",
        "args": {"text": "string", "voice": "string?", "rate": "string?"},
        "fn": lambda mid, a: _voice_tts(mid, **a),
    },
    "voice.asr": {
        "desc": "把一段音频转成文字（内核自带的语音服务；没装模型会告诉你）",
        "args": {"path": "string?", "audio": "string?", "hint": "string?"},
        "fn": lambda mid, a: _voice_asr(mid, **a),
    },
    "vision.describe": {
        "desc": "让她看一眼图并说出来（可以直接给图片路径）",
        "args": {"image": "string", "question": "string?"},
        "fn": lambda mid, a: _vision_describe(mid, **a),
    },
    "avatar.get": {
        "desc": "她现在的头像：文件路径、是不是主人换的、什么时候换的",
        "args": {},
        "fn": lambda mid, a: _avatar_get(mid, **a),
    },
    "sense.devices": {
        "desc": "问启动器：这台机器有几个摄像头、几个麦克风，现在选的是哪台",
        "args": {},
        "fn": lambda mid, a: _sense_devices(mid, **a),
    },
    "sense.look": {
        "desc": "让启动器的耳目看一眼（有摄像头用摄像头，没有就看屏幕），回文字描述",
        "args": {"question": "string?"},
        "fn": lambda mid, a: _sense_look(mid, **a),
    },
    "sense.listen": {
        "desc": "让启动器的耳目听几秒（麦克风），回听到的话",
        "args": {"seconds": "number=6"},
        "fn": lambda mid, a: _sense_listen(mid, **a),
    },
    "ui.background.get": {
        "desc": "看启动器现在的背景设置（开关、效果、跟随、点击、浓淡、速度）",
        "args": {},
        "fn": lambda mid, a: _ui_background_get(mid, **a),
    },
    "ui.background.set": {
        "desc": "改启动器的背景观感（只改观感，不能塞本地图片/视频路径）",
        "args": {"enabled": "bool?", "effect": "gradient|blobs|dots?",
                 "follower": "off|glow|trail|particles?", "click": "bool?",
                 "click_style": "ripple|double|spark|bubble?",
                 "opacity": "number0-1?", "speed": "number0.2-3?"},
        "fn": lambda mid, a: _ui_background_set(mid, **a),
    },
    "ui.mouse.get": {
        "desc": "鼠标在启动器窗口里的位置（窗口外 inside=false，坐标归零）",
        "args": {},
        "fn": lambda mid, a: _ui_mouse_get(mid, **a),
    },
    "persona.style.get": {
        "desc": "主人写的自定义性格：摘要、13 维情绪参数、脸谱规格",
        "args": {},
        "fn": lambda mid, a: _persona_style_get(mid, **a),
    },
    "persona.face.get": {
        "desc": "性格脸谱的规格（四个维度、发色、表情），可以照着画一张",
        "args": {},
        "fn": lambda mid, a: _persona_face_get(mid, **a),
    },
    "fs.mkdir": {
        "desc": "在 BAB 安装目录里建一个目录（只建目录，不能写文件、不能出安装目录）",
        "args": {"path": "string（相对安装目录或绝对路径）"},
        "fn": lambda mid, a: _fs_mkdir(mid, **a),
    },
    "project.apply": {
        "desc": "前置模组改程序文件/代码：不再逐次确认，先整包备份再写，记审计；可建目录、写任意文件；只支持 mkdir/write/delete",
        "args": {"ops": "array[{op:mkdir|write|delete, path:string, content?:string}]",
                 "reason": "string 说明为什么改"},
        "fn": lambda mid, a: _project_apply(mid, **a),
    },
    "config.write": {
        "desc": "改一项界面配置（只开放 ui.*，例如 ui.background.opacity）",
        "args": {"key": "string（ui.*）", "value": "any"},
        "fn": lambda mid, a: _config_set(mid, **a),
    },
    "notice.push": {
        "desc": "让保姆栏记一条提醒（带时间）；chat=true 时也在她的聊天里插一句短话",
        "args": {"text": "string", "chat": "bool=false"},
        "fn": lambda mid, a: _notice_push(mid, **a),
    },
}


# ---------------------------------------------------------------- 路由

class CallIn(BaseModel):
    cap: str
    args: Dict[str, Any] = {}


def _auth(token: str) -> Dict[str, Any]:
    mod = _module_by_token(token)
    if not mod:
        raise HTTPException(401, "bridge token 不认识：请在本安装里重新启用一次这个模组")
    return mod


@router.get("/manifest")
def manifest(x_bab_token: str = Header(default="")) -> Dict[str, Any]:
    mod = _auth(x_bab_token)
    mid = str(mod.get("id"))
    cfg = _bridge_cfg(mid)
    return {
        "ok": True,
        "version": BRIDGE_VERSION,
        "install": {"root": str(S.ROOT), "core_port": S.PORT},
        "module": {
            "id": mid, "name": mod.get("name"), "version": mod.get("version"),
            "program": _program_of(mid),
            "wants": [str(x) for x in (cfg.get("wants") or [])],
            "subscribes": [str(x) for x in (cfg.get("subscribes") or [])],
            # 模组自己那几项设置：用户在模组卡的「模组设置」里改的就是这些值。
            # 不带出去的话，模组进程永远看不见自己的设置（只能当摆设）。
            "settings": modules_box.settings_of(mid),
        },
        "capabilities": [
            {"name": k, "desc": v["desc"], "args": v.get("args") or {}} for k, v in CAPS.items()
        ],
        "events": EVENT_KINDS,
    }


@router.post("/call")
async def call(inp: CallIn, x_bab_token: str = Header(default="")) -> Dict[str, Any]:
    mod = _auth(x_bab_token)
    mid = str(mod.get("id"))
    ok_grant, why = _allowed(mid, inp.cap)
    if not ok_grant:
        _audit(mid, inp.cap, False, {"why": why})
        raise HTTPException(403, f"这个模组现在拿不到「{inp.cap}」：{why}")
    cap = CAPS.get(inp.cap)
    if not cap:
        _audit(mid, inp.cap, False, {"why": "unknown cap"})
        raise HTTPException(404, f"没有这个能力：{inp.cap}")
    fn: Callable = cap["fn"]
    try:
        data = fn(mid, inp.args or {})
        if asyncio.iscoroutine(data):
            data = await data
    except HTTPException as e:
        _audit(mid, inp.cap, False, {"why": str(e.detail)[:120]})
        raise
    except Exception as e:  # noqa: BLE001
        _audit(mid, inp.cap, False, {"why": repr(e)[:120]})
        raise HTTPException(500, f"能力执行失败：{e!r}") from e
    size = len(json.dumps(data, ensure_ascii=False, default=str)) if data is not None else 0
    _audit(mid, inp.cap, True, {"size": size})
    return {"ok": True, "cap": inp.cap, "data": data}


class GrantIn(BaseModel):
    module: str
    cap: str
    allow: bool = True


@router.get("/modules")
def bridge_modules() -> Dict[str, Any]:
    """给设置页看的：谁申请了什么、现在开没开（不需要 token，仅本机）。"""
    out: List[Dict[str, Any]] = []
    for m in modules_box.enabled():
        mid = str(m.get("id") or "")
        cfg = _bridge_cfg(mid)
        wants = [str(x) for x in (cfg.get("wants") or [])]
        deny = _deny_of(mid)
        man_ports = modules_box.manifest(mid).get("ports") or [0]
        cap_names = list(CAPS.keys())
        out.append({
            "id": mid, "name": m.get("name"), "version": m.get("version"),
            "port": m.get("runtime_port") or man_ports[0],
            "wants": wants, "subscribes": [str(x) for x in (cfg.get("subscribes") or [])],
            "events": str(cfg.get("events") or "pull"),
            # "*" 要把每一项能力的实际放行结果都摊开给界面看
            "caps": {c: (not wants or "*" in wants or c in wants) and c not in deny
                     for c in cap_names},
        })
    return {"ok": True, "count": len(out), "modules": out,
            "capabilities": [{"name": k, "desc": v["desc"]} for k, v in CAPS.items()]}


@router.post("/grants")
def set_grant(inp: GrantIn) -> Dict[str, Any]:
    doc = _grants()
    if not isinstance(doc.get("modules"), dict):
        doc["modules"] = {}
    rec = doc["modules"].get(inp.module) if isinstance(doc["modules"].get(inp.module), dict) else {}
    deny = [str(x) for x in (rec.get("deny") or [])]
    if inp.allow:
        deny = [x for x in deny if x != inp.cap]
    elif inp.cap not in deny:
        deny.append(inp.cap)
    rec["deny"] = deny
    doc["modules"][inp.module] = rec
    try:
        GRANTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        GRANTS_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"写权限文件失败：{e!r}") from e
    _audit(inp.module, f"grant:{inp.cap}", bool(inp.allow), {"by": "user"})
    return {"ok": True, "module": inp.module, "cap": inp.cap, "allow": bool(inp.allow)}


@router.get("/events")
async def events(since: int = 0, wait: int = 25, x_bab_token: str = Header(default="")) -> Dict[str, Any]:
    mod = _auth(x_bab_token)
    mid = str(mod.get("id"))
    kinds = [str(x) for x in (_bridge_cfg(mid).get("subscribes") or [])]
    got = await event_bus.wait_new(int(since or 0), kinds or None, timeout=float(wait or 0))
    return {"ok": True, "seq": event_bus.last_seq(), "module": mid, "events": got}


# ---------------------------------------------------------------- 反向：BAB -> 模组

async def _push_one(url: str, token: str, rec: Dict[str, Any]) -> None:
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            await c.post(url, json=rec, headers={"X-BAB-Token": token})
    except Exception as e:  # noqa: BLE001
        S.log(f"[bridge] 推送失败 {url}: {e!r}")


async def fanout(rec: Dict[str, Any]) -> None:
    """把一条事件推给声明了 push + 订阅了该类型的模组（失败只记日志）。"""
    kind = str(rec.get("kind") or "")
    for mod in modules_box.enabled():
        mid = str(mod.get("id") or "")
        cfg = _bridge_cfg(mid)
        if str(cfg.get("events") or "pull") != "push":
            continue
        if kind not in [str(x) for x in (cfg.get("subscribes") or [])]:
            continue
        url = _base_url(mod).rstrip("/") + str(cfg.get("events_endpoint") or "/events")
        if not url.startswith("http"):
            continue
        asyncio.create_task(_push_one(url, module_token(mid), rec))
