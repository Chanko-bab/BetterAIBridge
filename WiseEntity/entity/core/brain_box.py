"""大脑盒：把 flybrain_core 包成一个线程安全的常驻对象。

职责：
1. 载入/保存 `entity\\brain\\flybrain_state.json`
2. 生物钟：每 90 秒推进 30 秒（`run`），这样她就算没人说话也在"活着"
3. 消费 `entity\\brain\\event_inbox.jsonl`（其它程序投喂的世界事件）
"""
from __future__ import annotations

import importlib.util
import json
import threading
import time
from pathlib import Path

from . import settings as S

_lock = threading.RLock()
_sim = None
_fb_mod = None
_started_at = time.time()


def _load_module():
    global _fb_mod
    if _fb_mod is not None:
        return _fb_mod
    path = Path(S.BRAIN_DIR) / "flybrain_core.py"
    spec = importlib.util.spec_from_file_location("flybrain_core", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    _fb_mod = mod
    return mod


def ensure() -> object | None:
    """懒加载大脑；失败返回 None（服务不因此崩溃）。"""
    global _sim
    with _lock:
        if _sim is not None:
            return _sim
        try:
            mod = _load_module()
            sim = mod.FlyBrain.load_or_new(
                state_path=str(S.BRAIN_STATE), n=S.BRAIN_N, seed=S.BRAIN_SEED
            )
            sim.run(1.0)
            _sim = sim
            S.log(f"[brain] loaded n={S.BRAIN_N} seed={S.BRAIN_SEED} mood={sim.mood_line()}")
            return _sim
        except Exception as e:  # pragma: no cover
            S.log(f"[brain] load failed: {e!r}")
            return None


def _sim_or_none():
    global _sim
    if _sim is None:
        return ensure()
    return _sim


def run(seconds: float) -> None:
    sim = _sim_or_none()
    if sim is None:
        return
    with _lock:
        try:
            sim.run(float(seconds))
        except Exception as e:
            S.log(f"[brain] run failed: {e!r}")


def stimulate_text(text: str, is_owner: bool) -> None:
    sim = _sim_or_none()
    if sim is None:
        return
    with _lock:
        try:
            sim.stimulate_text(text or "", is_owner=bool(is_owner))
        except Exception as e:
            S.log(f"[brain] stimulate failed: {e!r}")


def stimulate(kind: str, **kw) -> None:
    sim = _sim_or_none()
    if sim is None:
        return
    with _lock:
        try:
            sim.stimulate(kind, **kw)
        except Exception as e:
            S.log(f"[brain] stimulate({kind}) failed: {e!r}")


def nt_levels() -> dict | None:
    """6 种调质的当前水平（0~1，静息 0.30）；大脑没起来返回 None。"""
    sim = _sim
    if sim is None:
        return None
    with _lock:
        try:
            tone = getattr(sim, "tone", None) or {}
            return {k: round(float(tone.get(k, 0.30)), 4)
                    for k in ("ach", "glu", "gaba", "da", "5ht", "oa")}
        except Exception:
            return None


def state() -> dict:
    sim = _sim_or_none()
    if sim is None:
        return {"ready": False}
    with _lock:
        try:
            emo = sim.emotions()
            return {
                "ready": True,
                "emotions": emo,
                "mood_line": sim.mood_line(),
                "situation_line": sim.situation_line(),
                "fight": bool(sim.fight_active()),
                "uptime": round(time.time() - _started_at, 1),
            }
        except Exception as e:
            return {"ready": False, "error": repr(e)}


def prompt_fragment() -> str:
    """给 LLM 的情绪/处境提示块（不含记忆）。"""
    sim = _sim_or_none()
    if sim is None:
        return ""
    with _lock:
        try:
            head = sim.instructions() or ""
            parts = [head]
            sit = sim.situation_line()
            if sit and sit not in head:
                parts.append(sit)
            if sim.fight_active():
                parts.append("（你现在有点炸，说话会更冲。）")
            return "\n".join(p for p in parts if p)
        except Exception:
            return ""


def save() -> None:
    sim = _sim_or_none()
    if sim is None:
        return
    with _lock:
        try:
            sim.save(str(S.BRAIN_STATE))
        except Exception as e:
            S.log(f"[brain] save failed: {e!r}")


def drain_inbox() -> list[dict]:
    """读掉其它程序写的事件；文件里没有内容时返回空表。"""
    path = Path(S.EVENT_INBOX)
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except Exception:
        return []
    if not raw.strip():
        return []
    try:
        path.write_text("", encoding="utf-8")
    except Exception:
        pass
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if isinstance(ev, dict):
            out.append(ev)
    for ev in out:
        kind = str(ev.get("kind") or ev.get("type") or "event")
        text = ev.get("text") or ""
        try:
            if kind in ("msg", "owner_msg", "other_msg", "group_msg", "moments") and text:
                simulate_event_text(kind, text, ev)
            else:
                aliases = {"qzone_like": "qzone_like", "qzone_reply": "qzone_reply", "video": "video", "sticker": "sticker", "idle": "idle", "moments": "qzone_like"}
                stimulate(aliases.get(kind, "msg"))
        except Exception as e:
            S.log(f"[brain] inbox event failed: {e!r}")
    return out


def simulate_event_text(kind: str, text: str, ev: dict) -> None:
    owner = bool(ev.get("is_owner", kind in ("msg", "owner_msg", "moments")))
    stimulate_text(text, owner)


def note_thought(text: str, origin: str) -> None:
    try:
        with open(S.THOUGHTS, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
                "thought": text,
                "origin": origin,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass

def snapshot() -> dict:
    """给驱动层看的原始神经快照（多巴胺等）。"""
    sim = _sim_or_none()
    if sim is None:
        return {}
    try:
        return sim.snapshot()
    except Exception as e:
        S.log(f"[brain] snapshot failed: {e!r}")
        return {}

