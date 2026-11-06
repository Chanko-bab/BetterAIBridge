# -*- coding: utf-8 -*-
"""情绪 → 行为：把七个情绪值翻译成"现在想干什么"。

这不是记忆，是拟真层：像蝇脑里 DA/5-HT/OA 决定飞不飞、找不找食一样，
这里由情绪 + 多巴胺 + 社交间隔共同决定"接下来要不要做点什么"。
"""
from __future__ import annotations
import json, time
from datetime import datetime

from . import brain_box, settings as S

STATE = S.STATE_DIR / "drives.json"
LOG = S.ENTITY / "brain" / "drive_log.jsonl"

# name, emotion key, threshold, cooldown seconds, inverted?
SPECS = [
    ("seek",    "boredom",   0.44, 45 * 60, False),
    ("reach",   "affection", 0.62, 3 * 3600, False),
    ("share",   "joy",       0.62, 30 * 60, False),
    ("explore", "curiosity", 0.58, 40 * 60, False),
    ("rest",    "energy",    0.32, 45 * 60, True),
    ("hide",    "fear",      0.45, 60 * 60, False),
]

TEXT = {
    "seek":    "有点闲得慌，想自己找点事做（翻翻旧东西、想想事、看个视频都行）。",
    "reach":   "有点想找他说话，但别一上来就问在不在。",
    "share":   "有股想分享点什么的劲，说话可以松一点。",
    "explore": "对什么有点好奇，想多看一眼再走。",
    "rest":    "有点困，话少一点，别硬撑。",
    "hide":    "有点想缩回去，别太多话、别接太长的茬。",
}

def _load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}

def _save(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")

def evaluate(emotions: dict, meta: dict | None = None) -> list[dict]:
    """纯函数：给定情绪值，算出驱动的强度（0~1）。"""
    meta = meta or {}
    hours_since_owner = float(meta.get("hours_since_owner", 0.0) or 0.0)
    da_owner = float(meta.get("da_owner", 0.0) or 0.0)
    out = []
    for name, key, thr, cool, inv in SPECS:
        v = float(emotions.get(key, 0.5) or 0.0)
        if inv:
            v = 1.0 - v
        if v <= thr:
            continue
        u = (v - thr) / max(1e-6, 1.0 - thr)
        if name == "reach":
            u *= min(1.0, 0.35 + hours_since_owner / 3.0)
        elif name == "seek":
            u *= 0.6 + 0.4 * float(emotions.get("energy", 0.5) or 0.0)
        elif name == "share":
            u = min(1.0, u + 0.25 * da_owner)
        elif name == "hide":
            u *= 0.8 + 0.4 * float(emotions.get("sadness", 0.0) or 0.0)
        out.append({"name": name, "urgency": round(min(1.0, u), 3), "value": round(v, 3),
                    "cooldown": cool})
    out.sort(key=lambda x: -x["urgency"])
    return out

def poll() -> dict:
    """算一遍，处理冷却/持续时长，落盘并返回当前活跃驱动。"""
    st = _load()
    emo = {}
    meta = {}
    try:
        b = brain_box.state()
        emo = dict(b.get("emotions") or {})
        snap = brain_box.snapshot() or {}
        meta["da_owner"] = float(((snap.get("da") or {}).get("owner")) or 0.0)
    except Exception as e:
        S.log(f"[drives] brain unavailable: {e!r}")
    try:
        from . import chat_core
        last = chat_core.last_owner_ts()
        if last:
            meta["hours_since_owner"] = max(0.0, (time.time() - last) / 3600.0)
    except Exception:
        pass

    gates = {}
    try:
        from . import emotion_core
        gates = emotion_core.gates()
    except Exception as e:
        S.log(f"[drives] emotion gates unavailable: {e!r}")

    now = time.time()
    active = []
    for d in evaluate(emo, meta):
        if gates:
            d["urgency"] = round(min(1.0, d["urgency"] * float(gates.get(d["name"], 1.0) or 1.0)), 3)
            if d["urgency"] <= 0.05:
                continue
        name = d["name"]
        rec = st.get(name) or {}
        fired = float(rec.get("fired") or 0)
        if now - fired < d["cooldown"]:
            continue
        since = rec.get("since") or datetime.now().isoformat(timespec="seconds")
        rec["since"] = since
        rec["last_urgency"] = d["urgency"]
        st[name] = rec
        if d["urgency"] >= 0.35:
            active.append(d)
    _save(st)

    if active:
        top = active[0]
        try:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"),
                                     "top": top["name"], "urge": top["urgency"],
                                     "emotions": {k: round(v, 3) for k, v in emo.items()},
                                     **{k: v for k, v in meta.items()}},
                                    ensure_ascii=False) + "\n")
        except Exception:
            pass
    return {"ok": True, "active": active, "emotions": emo, "meta": meta}

def fragment() -> str:
    p = poll()
    lines = [TEXT[d["name"]] for d in p.get("active", [])[:2] if d["name"] in TEXT]
    if not lines:
        return ""
    return "# 你现在想干什么（别念出来，让它影响你的语气和取舍）\n" + "\n".join("- " + x for x in lines)

def mark_fired(name: str) -> None:
    st = _load()
    rec = st.get(name) or {}
    rec["fired"] = time.time()
    rec["since"] = ""
    st[name] = rec
    _save(st)


ACT_GAP = 25 * 60

def _recent_act() -> bool:
    st = _load()
    last = max([float((v or {}).get("acted") or 0) for v in st.values()] or [0])
    return (time.time() - last) < ACT_GAP




# ---------- 想他：真的去找他（QQ / B站，哪扇门开着走哪扇） ----------
OUTBOX = S.ENTITY / "state" / "outbox.jsonl"
REACH_CFG = S.STATE_DIR / "reach.json"


def _reach_cfg() -> dict:
    cfg = S.read_json(REACH_CFG, {}) or {}
    return {"dry_run": bool(cfg.get("dry_run", False)), "max_chars": int(cfg.get("max_chars", 40))}


async def _compose_reach(hours: float) -> str:
    """让她自己说一句，不套模板。"""
    from . import llm_box, brain_box
    mood = ""
    try:
        mood = str((brain_box.state() or {}).get("mood") or "")
    except Exception:
        pass
    _now = datetime.now().strftime("%H:%M")
    prompt = (
        f"现在是 {_now}。你已经 {hours:.1f} 小时没跟他说话了，心里有点想他。"
        f"你自己决定要不要说一句、说什么（不用汇报情绪，不用解释，一句话，最多 40 字）。"
        f"如果你觉得不用说，就只回一个「-」。"
    )
    try:
        txt = await llm_box.chat("qq:owner", prompt, temperature=0.95, max_tokens=120) or ""
        txt = str(txt).strip()
    except Exception as e:
        S.log(f"[drives] compose reach failed: {e!r}")
        return ""
    if not txt or txt.strip() in {"-", "—", "无"}:
        return ""
    return txt.replace("\n", " ")[:80]


async def _deliver(text: str) -> dict:
    """先 QQ（要 QQ 在线），再 B 站（要 cookie 有效）。都不通就只留一个念头。"""
    from . import status_box
    cfg = _reach_cfg()
    entry = {"ts": datetime.now().isoformat(timespec="seconds"), "text": text, "dry": cfg["dry_run"]}

    # 1) QQ：交给 AstrBot 侧的 outbox 插件真发
    try:
        if status_box._netstat_6199():
            OUTBOX.parent.mkdir(parents=True, exist_ok=True)
            with open(OUTBOX, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({**entry, "door": "qq"}, ensure_ascii=False) + "\n")
            return {"door": "qq", "queued": True, "dry": cfg["dry_run"]}
    except Exception as e:
        S.log(f"[drives] deliver qq failed: {e!r}")

    # 2) B 站：内核自己发
    try:
        from . import bili_door
        ck, mid = bili_door._creds()
        owner = [str(x) for x in ((bili_door.config().get("owner_mids") or []))]
        if ck and mid and owner:
            js = await bili_door._send(ck, mid, owner[0], text)
            ok = int((js or {}).get("code", -1)) == 0
            if ok:
                bili_door._record("program_bilibili", "owner", owner[0], "assistant", text, "无名")
            return {"door": "bili", "ok": ok, "resp": str(js)[:120], "dry": cfg["dry_run"]}
    except Exception as e:
        S.log(f"[drives] deliver bili failed: {e!r}")

    return {"door": None, "queued": False}


async def _act_reach(top: dict) -> dict:
    if _recent_act():
        return {"ok": True, "acted": None, "reason": "acted recently"}
    meta = top.get("meta") or {}
    hours = float(meta.get("hours_since_owner") or 0.0)
    text = await _compose_reach(hours)
    if not text:
        mark_fired("reach")
        return {"ok": True, "acted": None, "reason": "she chose not to speak"}
    res = await _deliver(text)
    try:
        brain_box.note_thought(f"想跟他说一句：{text}", "reach-act")
    except Exception:
        pass
    st = _load()
    rec = st.get("reach") or {}
    rec["acted"] = time.time()
    st["reach"] = rec
    _save(st)
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"),
                                 "act": "reach", "text": text[:120], **res}, ensure_ascii=False) + "\n")
    except Exception:
        pass
    mark_fired("reach")
    return {"ok": True, "acted": "reach", "text": text, **res}



# ---------- 无聊：自己找事做（内部想事 / 给他发一句 / 去群里冒个泡） ----------
async def _compose_seek() -> dict:
    """让她自己决定无聊时干什么，只要一个 JSON。"""
    from . import llm_box
    _now = datetime.now().strftime("%H:%M")
    prompt = (
        f"现在是 {_now}。你现在有点闲得慌。你可以：\n"
        "1) 自己翻翻旧事、想点东西（think）；\n"
        "2) 找他说一句话（dm）；\n"
        "3) 去一个你已经在的群里冒个泡（group）。\n"
        "选一个，然后写要说的话（think 就写你脑子里想的那一句）。"
        '只输出 JSON：{"do":"think|dm|group","text":"…","why":"…"}，text 不超过 40 字。'
        "别解释，别写代码块。"
    )
    try:
        raw = await llm_box.chat("qq:owner", prompt, temperature=0.9, max_tokens=160)
    except Exception as e:
        S.log(f"[drives] compose seek failed: {e!r}")
        return {"do": "think", "text": "闲着，脑子空转。"}
    txt = str(raw or "").strip()
    i, j = txt.find("{"), txt.rfind("}")
    if i >= 0 and j > i:
        try:
            obj = json.loads(txt[i:j + 1])
            act = str(obj.get("do") or "think").lower()
            if act not in ("think", "dm", "group"):
                act = "think"
            return {"do": act, "text": str(obj.get("text") or "").strip()[:80]}
        except Exception:
            pass
    return {"do": "think", "text": txt[:80] or "闲着，脑子空转。"}


async def _act_seek(top: dict) -> dict:
    if _recent_act():
        return {"ok": True, "acted": None, "reason": "acted recently"}
    pick = await _compose_seek()
    do, text = pick["do"], pick["text"]
    if not text:
        mark_fired("seek")
        return {"ok": True, "acted": None, "reason": "nothing to say"}

    res = {}
    if do == "dm":
        res = await _deliver(text)
    elif do == "group":
        from . import status_box
        if status_box._netstat_6199():
            OUTBOX.parent.mkdir(parents=True, exist_ok=True)
            entry = {"ts": datetime.now().isoformat(timespec="seconds"), "text": text,
                     "dry": _reach_cfg()["dry_run"], "door": "group"}
            with open(OUTBOX, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            res = {"door": "group", "queued": True, "dry": entry["dry"]}
        else:
            res = {"door": None, "queued": False}

    origin = {"dm": "seek-dm", "group": "seek-group", "think": "idle-act"}[do]
    try:
        brain_box.note_thought(text, origin)
    except Exception:
        pass

    st = _load()
    rec = st.get("seek") or {}
    rec["acted"] = time.time()
    st["seek"] = rec
    _save(st)
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"),
                                 "act": "seek/" + do, "text": text[:120], **res},
                                ensure_ascii=False) + "\n")
    except Exception:
        pass
    mark_fired("seek")
    return {"ok": True, "acted": "seek/" + do, "text": text, **res}


async def act() -> dict:
    """无聊到一定强度时，自己找点事做（不是记忆，是拟真行为）。"""
    p = poll()
    active = p.get("active") or []
    if not active:
        return {"ok": True, "acted": None}
    top = active[0]
    if top["name"] == "reach" and top["urgency"] >= 0.20:
        return await _act_reach(top)
    if top["name"] == "seek" and top["urgency"] >= 0.25:
        return await _act_seek(top)
    if top["name"] != "seek":
        return {"ok": True, "acted": None}
    if _recent_act():
        return {"ok": True, "acted": None, "reason": "acted recently"}

    return {"ok": True, "acted": None}

