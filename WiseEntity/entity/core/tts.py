"""TTS：把文字变成声音（edge-tts，在线、零显存）。

一次调用一个 mp3；结果按 (文本+音色+语速) 的 sha1 缓存在 state/tts_cache/。
断网时返回 502，由前端决定要不要提示，不影响文字聊天。
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import settings as S

CACHE = S.STATE_DIR / "tts_cache"
VOICE_PATH = S.ENTITY / "config" / "tts.json"

DEFAULT = {
    # 聊天朗读、试听各用哪个引擎：0.3.26 起分开。
    # BreezeBlue 实测比实时慢 4–10 倍（3 秒的话要 15–25 秒才合成完），
    # 日常朗读留在 edge，BreezeBlue 只给「试听」用。
    "engine": "edge",            # 聊天朗读：edge | breezeblue | local
    "preview_engine": "edge",    # 试听：edge | breezeblue | local
    "voice": "zh-CN-XiaoxiaoNeural",
    "rate": "+0%",
    "volume": "+0%",
    "enabled": True,
    # BreezeBlue（或任何 OpenAI 兼容 TTS）
    "bb_base": "https://api.breezeblue.ai/v1",
    "bb_key": "",
    "bb_voice": "",
    "bb_model": "breeze-tts-2",
    # 本地 MOSS-TTS-Nano（launcher 起的 sidecar）
    "local_url": "http://127.0.0.1:18084",
    "local_voice": "Junhao",
    "local_ref": "",
}

KEYS = ("engine", "preview_engine", "voice", "rate", "volume", "enabled",
        "bb_base", "bb_key", "bb_voice", "bb_model",
        "local_url", "local_voice", "local_ref")

# 常用中文音色（前端下拉用；要别的名字直接填字符串也行）
VOICES: List[Dict[str, str]] = [
    {"id": "zh-CN-XiaoxiaoNeural", "label": "晓晓 · 女 · 温和"},
    {"id": "zh-CN-XiaoyiNeural", "label": "晓伊 · 女 · 活泼"},
    {"id": "zh-CN-YunxiNeural", "label": "云希 · 男 · 少年"},
    {"id": "zh-CN-YunjianNeural", "label": "云健 · 男 · 沉稳"},
    {"id": "zh-CN-YunxiaNeural", "label": "云夏 · 男 · 少年"},
    {"id": "zh-CN-liaoning-XiaobeiNeural", "label": "晓北 · 女 · 东北"},
    {"id": "zh-CN-shaanxi-XiaoniNeural", "label": "晓妮 · 女 · 陕西"},
]

MAX_CHARS = 600


def cfg() -> Dict[str, Any]:
    import json

    base = dict(DEFAULT)
    raw: Dict[str, Any] = {}
    try:
        doc = json.loads(VOICE_PATH.read_text(encoding="utf-8-sig"))
        if isinstance(doc, dict):
            raw = doc
            base.update({k: v for k, v in raw.items() if k in KEYS})
    except Exception:  # noqa: BLE001
        pass
    # 迁移：0.3.25 及更早只有一个 engine。那时候选 BreezeBlue 的人是拿它当朗读用，
    # 现在它太慢，默认把「朗读」落回 edge，把这个选择挪给「试听」，别让升级后突然变慢。
    if "preview_engine" not in raw and str(base.get("engine") or "") == "breezeblue":
        base["preview_engine"] = "breezeblue"
        base["engine"] = "edge"
    return base


def save_cfg(patch: Dict[str, Any]) -> Dict[str, Any]:
    import json

    cur = cfg()
    for k in KEYS:
        if k not in patch:
            continue
        if patch[k] in (None, "") and k != "local_ref":
            continue
        cur[k] = patch[k]
    try:
        VOICE_PATH.parent.mkdir(parents=True, exist_ok=True)
        VOICE_PATH.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return cur


def engine(purpose: str = "chat") -> str:
    key = "preview_engine" if purpose == "preview" else "engine"
    e = str(cfg().get(key) or "edge").strip().lower()
    return e if e in ("edge", "breezeblue", "local") else "edge"


def cache_path(text: str, voice: str, rate: str, purpose: str = "chat") -> Path:
    e = engine(purpose)
    c = cfg()
    extra = f"|{c.get('local_voice')}|{c.get('local_ref')}" if e == "local" else ""
    key = hashlib.sha1(f"{e}|{voice}|{rate}|{text}{extra}".encode("utf-8")).hexdigest()
    return CACHE / f"{key}{'.wav' if e == 'local' else '.mp3'}"


def _fallback_path(text: str, voice: str, rate: str, purpose: str) -> Path:
    key = hashlib.sha1(f"edge|{voice}|{rate}|{text}".encode("utf-8")).hexdigest()
    return CACHE / f"{key}.mp3"


def cached(text: str, voice: str = "", rate: str = "",
           purpose: str = "chat") -> Optional[Path]:
    c = cfg()
    p = cache_path(text, voice or c["voice"], rate or c["rate"], purpose)
    return p if p.exists() and p.stat().st_size > 800 else None


async def _synth_edge(text: str, voice: str, rate: str, volume: str, out: Path) -> Path:
    import edge_tts  # 延迟导入：没装的时候只有 /tts 不可用

    tmp = out.with_suffix(".part")
    comm = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
    with open(tmp, "wb") as f:
        async for chunk in comm.stream():
            if chunk.get("type") == "audio":
                f.write(chunk["data"])
    if not tmp.exists() or tmp.stat().st_size < 800:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("edge-tts 没返回音频（网络或音色名不对）")
    tmp.replace(out)
    return out


async def _synth_local(text: str, out: Path, c: Dict[str, Any]) -> Path:
    """调 launcher 起在本机的 MOSS sidecar；只走 127.0.0.1。"""
    import httpx

    base = str(c.get("local_url") or "http://127.0.0.1:18084").strip().rstrip("/")
    payload = {
        "text": text,
        "voice": str(c.get("local_voice") or ""),
        "reference": str(c.get("local_ref") or ""),
    }
    try:
        timeout = httpx.Timeout(300.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{base}/tts", json=payload)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"本地语音服务没起来：{_err_text(e)}") from e
    if resp.status_code != 200:
        detail = (resp.text or "").strip()[:200]
        raise RuntimeError(f"本地语音合成失败 {resp.status_code}：{detail}")
    data = resp.content or b""
    if len(data) < 800 or not data.startswith(b"RIFF"):
        raise RuntimeError("本地语音服务没返回 WAV")
    tmp = out.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(out)
    return out


async def synth(text: str, voice: str = "", rate: str = "",
                purpose: str = "chat") -> Path:
    """合成一句，返回音频路径；已缓存直接返回。

    purpose="chat"（默认）用 engine，purpose="preview" 用 preview_engine。
    本地 MOSS 失败时自动退回 edge（本地包坏了也不至于哑掉）。
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("没有文字")
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
    c = cfg()
    v = voice or c["voice"]
    r = rate or c["rate"]
    e = engine(purpose)
    out = cache_path(text, v, r, purpose)
    if out.exists() and out.stat().st_size > 800:
        return out

    CACHE.mkdir(parents=True, exist_ok=True)
    if e == "local":
        try:
            return await _synth_local(text, out, c)
        except Exception:  # noqa: BLE001
            fb = _fallback_path(text, v, r, purpose)
            if fb.exists() and fb.stat().st_size > 800:
                return fb
            return await _synth_edge(text, v, r, c.get("volume") or "+0%", fb)
    if e == "breezeblue":
        return await _synth_http(text, out, c)
    return await _synth_edge(text, v, r, c.get("volume") or "+0%", out)


def api_base(base: str) -> str:
    """把用户填的地址归一成「带 /v1」的 API 根。

    https://api.breezeblue.ai        -> https://api.breezeblue.ai/v1
    https://api.breezeblue.ai/v1     -> 原样
    """
    b = str(base or "").strip().rstrip("/")
    if not b:
        return ""
    return b if b.endswith("/v1") else b + "/v1"


def _err_text(e: Exception) -> str:
    """httpx 的超时异常经常 str() 是空的，界面上会只剩「合成失败：」——给个类型名兜底。"""
    return str(e).strip() or type(e).__name__


def _error_detail(resp) -> str:
    """BreezeBlue 的错误是 JSON：{code, detail, error}；取不到就说原文。"""
    try:
        doc = resp.json()
        if isinstance(doc, dict):
            for k in ("detail", "error", "message", "code"):
                v = doc.get(k)
                if v:
                    return str(v)[:200]
    except Exception:  # noqa: BLE001
        pass
    return (resp.text or "").strip()[:200] or "（服务没给说明）"


async def _synth_http(text: str, out: Path, c: Dict[str, Any]) -> Path:
    """BreezeBlue 的 POST /v1/text-to-speech/{voice_id}（不是 OpenAI 的 /audio/speech）。"""
    base = api_base(str(c.get("bb_base") or ""))
    key = str(c.get("bb_key") or "").strip()
    voice = str(c.get("bb_voice") or "").strip()
    if not base or not key:
        raise RuntimeError("语音引擎选的是 BreezeBlue，但还没填地址或 API Key")
    if not voice:
        raise RuntimeError("语音引擎选的是 BreezeBlue，但还没填音色")
    import httpx

    payload = {
        "text": text,
        "model_id": str(c.get("bb_model") or "breeze-tts-2"),
    }
    headers = {"xi-api-key": key}
    url = f"{base}/text-to-speech/{voice}"
    try:
        # BreezeBlue 生成慢的时候几十秒才回一段（实测 5s～50s+），给足时间
        timeout = httpx.Timeout(180.0, connect=15.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, params={"output_format": "mp3"},
                                     json=payload, headers=headers)
    except httpx.TimeoutException as e:
        raise RuntimeError(f"语音服务没回应（{type(e).__name__}）：检查地址和网络") from e
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"连不上语音服务：{_err_text(e)}") from e
    if resp.status_code != 200:
        raise RuntimeError(f"BreezeBlue 返回 {resp.status_code}：{_error_detail(resp)}")
    data = resp.content or b""
    if len(data) < 800:
        raise RuntimeError("BreezeBlue 没返回音频（检查音色名或额度）")
    tmp = out.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(out)
    return out

def synth_sync(text: str, voice: str = "", rate: str = "",
               purpose: str = "chat") -> Path:
    return asyncio.run(synth(text, voice, rate, purpose))
