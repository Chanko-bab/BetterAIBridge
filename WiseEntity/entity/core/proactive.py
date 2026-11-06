"""她会主动开口（只限桌面聊天 web:owner）。

不看日历，只看情绪：驱动（reach/seek/share）够急就说。

- 你在（presence = online）：驱动 ≥ 0.5 就能开口，话直接进聊天，保姆栏不再多一条
  （人就在旁边看着，重复提醒反而吵）。
- 你不在（关窗默认 busy）：要更急，≥ 0.7 才开口，保姆栏提示「对方主动找您」。
  ——「对方」是中性称呼，界面上一律用它，不写「智能体」（那是我们内部区分用的词）。
- 说完这一句，那股劲就使出去了（`drives.mark_fired`），按这个驱动自己的冷却退烧
  （reach 3 小时、share 30 分钟、seek 45 分钟）——不设每日上限，情绪不该被日历管。
- 只留一个 8 分钟的总闸，防两条驱动前后脚轮流刷屏。
- 她选择不说（沉默）时不退烧：话还在心里，下一次更容易开口。
"""
from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime
from typing import Dict

from . import brain_box, chat_core, drives, emotion_core, llm_box, presence, settings as S

STATE_PATH = S.STATE_DIR / "proactive.json"
SESSION = "web:owner"
# 两次主动开口之间的最短间隔（只防刷屏，不是日限）
GAP_SEC = 8 * 60
MIN_URGENCY = 0.5
# 在线很久没说话：25 分钟后可以主动搭一句；两次之间至少 20 分钟
IDLE_SEC = 25 * 60
IDLE_GAP = 20 * 60
# 从忙碌切回在线：10 分钟内不重复为这件事开口
ONLINE_GAP = 10 * 60
# 你不在的时候，门槛更高
AWAY_MIN_URGENCY = 0.7
ALLOWED = ("reach", "seek", "share")

# 在线时不发保姆提醒（人就在聊天里看着，别重复吵）；
# 忙碌/离开时才提示一句。「对方」是中性称呼，界面就用它。
NOTICE_ONLINE = ""
NOTICE_AWAY = "对方主动找您"

_CN = {"reach": "想他", "seek": "想找点事", "share": "想说点开心事"}


def _who(rel: str) -> str:
    """第一人称的关系句；称呼是「他/她/您/你」时不硬塞。"""
    title = str(S.user_title("") or "").strip()
    if title and title not in {"他", "她", "您", "你"}:
        return f"对方是我的{rel}，我平时叫他「{title}」"
    return f"对方是我的{rel}"


def _load() -> Dict:
    data = S.read_json(STATE_PATH, {}) or {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("last_ts", 0.0)
    data.setdefault("sent", [])
    return data


def _save(data: Dict) -> None:
    S.write_json(STATE_PATH, data)


def _last_user_ts() -> float:
    try:
        rows = chat_core.get_history(SESSION) or []
    except Exception:  # noqa: BLE001
        return 0.0
    for row in reversed(rows):
        if str(row.get("role") or "") != "user":
            continue
        ts = str(row.get("ts") or "")
        try:
            return datetime.fromisoformat(ts).timestamp()
        except Exception:  # noqa: BLE001
            return 0.0
    return 0.0


def idle_status() -> Dict:
    last = _last_user_ts()
    age = max(0.0, time.time() - last) if last else 0.0
    data = _load()
    since = time.time() - float(data.get("last_ts") or 0)
    return {"last_user_ts": last, "idle_sec": age,
            "due": bool(last) and age >= IDLE_SEC and since >= IDLE_GAP}


def _today_count(data: Dict) -> int:
    today = time.strftime("%Y-%m-%d")
    return sum(1 for ts in data.get("sent", []) if str(ts).startswith(today))


def pick_drive(active: list[dict], min_urgency: float = MIN_URGENCY) -> dict | None:
    cands = [d for d in (active or []) if d.get("name") in ALLOWED]
    if not cands:
        return None
    cands.sort(key=lambda d: float(d.get("urgency") or 0), reverse=True)
    top = cands[0]
    return top if float(top.get("urgency") or 0) >= min_urgency else None


def _bars(online: bool) -> tuple[float, float]:
    """(最小紧迫度, 两次开口之间的最短间隔)"""
    return (MIN_URGENCY if online else AWAY_MIN_URGENCY), GAP_SEC


def status() -> Dict:
    data = _load()
    online = presence.is_online()
    min_urgency, gap = _bars(online)
    dr = drives.poll()
    top = pick_drive(dr.get("active") or [], min_urgency)
    return {
        "enabled": online,
        "presence": presence.get(),
        "last_ts": data.get("last_ts", 0.0),
        "today": _today_count(data),
        "candidate": top,
        "last_text": str(data.get("last_text") or ""),
        "cooldown_left": max(0, int(gap - (time.time() - float(data.get("last_ts") or 0)))),
    }


def last() -> Dict:
    data = _load()
    return {"ts": float(data.get("last_ts") or 0.0),
            "text": str(data.get("last_text") or ""),
            "kind": str(data.get("last_kind") or "")}


async def maybe_send(force: bool = False, trigger: str = "") -> Dict:
    """跑一轮判断；发了就返回 {"sent": True, "text": ...}。

    trigger:
      ""      按驱动紧迫度（原逻辑）
      "idle"  在线很久没说话，主动搭一句
      "online"刚从忙碌切回在线，可以主动搭一句
    """
    data = _load()
    online = presence.is_online()
    trigger = trigger if trigger in ("idle", "online") else ""
    now = time.time()
    last_ts = float(data.get("last_ts") or 0)

    if trigger == "idle":
        if not online or not idle_status().get("due"):
            return {"sent": False, "reason": "还没到主动搭话的时候"}
        if not force and now - last_ts < IDLE_GAP:
            return {"sent": False, "reason": "刚说过"}
    elif trigger == "online":
        if not online:
            return {"sent": False, "reason": "现在不是在线"}
        if not force and now - last_ts < ONLINE_GAP:
            return {"sent": False, "reason": "刚说过"}

    min_urgency, gap = _bars(online)
    if not trigger and not force and now - last_ts < gap:
        return {"sent": False, "reason": "刚说过"}

    if trigger:
        top = {"name": "reach", "urgency": 0.55}
    else:
        dr = drives.poll()
        top = pick_drive(dr.get("active") or [], min_urgency)
        if force and not top:
            top = {"name": "reach", "urgency": min_urgency}
        if not top:
            return {"sent": False, "reason": "没有想说话的驱动"}

    st = brain_box.state()
    mood = st.get("mood_line") or "平平的"
    urge = _CN.get(top["name"], top["name"])
    rel = S.relation()
    if trigger == "idle":
        prompt = (
            f"（{_who(rel)}。"
            "他这会儿一直在线，可很久没出声了。我想主动说一句，"
            "或者问一句他在忙什么；用我们平常的说法，可以随口一点，"
            "别客服腔，别每次都问「在吗」，别解释我为什么开口，不超过 25 个字。）"
        )
    elif trigger == "online":
        prompt = (
            f"（{_who(rel)}。"
            "他刚把状态从「忙碌」改回「在线」，说明现在可以打扰。"
            "我想主动说一句，或者问一句；用我们平常的说法，可以随口一点，"
            "别客服腔，别每次都问「在吗」，别解释我为什么开口，不超过 25 个字。）"
        )
    else:
        prompt = (
            f"（{_who(rel)}。"
            f"我现在心里有点{urge}（{float(top.get('urgency') or 0):.2f}），"
            "想主动找他说一句。只说一句，不超过 20 个字；别说「在吗」，别解释我为什么开口。）"
        )
    # 想说话，但也可以选择不说：驱动越低越容易闭嘴
    urge = float(top.get("urgency") or 0.0)
    try:
        g = emotion_core.gates()
        quiet = float(g.get("hide") or 1.0)
    except Exception:
        quiet = 1.0
    if trigger == "online":
        silence_chance = 0.20
    elif trigger == "idle":
        silence_chance = 0.28
    else:
        silence_chance = max(0.15, min(0.75, 0.55 - urge * 0.5 + (quiet - 1.0) * 0.4))
    if not force and random.random() < silence_chance:
        data["last_ts"] = time.time()
        data.setdefault("silent", []).append(time.strftime("%Y-%m-%dT%H:%M:%S"))
        data["silent"] = data["silent"][-60:]
        _save(data)
        chat_core.push_notice(SESSION, "对方选择沉默")
        S.log(f"[proactive] {top['name']} u={urge:.2f} 选择沉默（p={silence_chance:.2f}）")
        return {"sent": False, "silent": True, "reason": "选择沉默", "drive": top}

    text = await llm_box.chat(SESSION, prompt, chat_core.get_history(SESSION),
                              temperature=1.0, max_tokens=80)
    text = (text or "").strip().strip('"').strip()
    if not text:
        return {"sent": False, "reason": "模型没说话"}

    notice = NOTICE_ONLINE if online else NOTICE_AWAY
    if notice:
        chat_core.push_notice(SESSION, notice)
    parts = chat_core.split_reply(text, max_len=32, max_parts=2) or [text]
    for part in parts:
        chat_core.append_assistant(SESSION, part, proactive=True)
    # 这股劲使出去了：按驱动自己的冷却退烧（不设每日上限）；沉默时不退，话还堵着
    try:
        drives.mark_fired(str(top.get("name") or ""))
    except Exception as e:  # noqa: BLE001
        S.log(f"[proactive] mark_fired failed: {e!r}")
    data["last_ts"] = time.time()
    data["last_text"] = text
    data["last_kind"] = trigger or str(top.get("name") or "")
    data.setdefault("sent", []).append(time.strftime("%Y-%m-%dT%H:%M:%S"))
    data["sent"] = data["sent"][-60:]
    _save(data)
    S.log(f"[proactive] {top['name']} u={urge:.2f} mood={mood} -> {text}")
    return {"sent": True, "text": text, "messages": parts, "drive": top, "mood": mood}


def maybe_send_sync(force: bool = False) -> Dict:
    try:
        return asyncio.run(maybe_send(force=force))
    except RuntimeError:
        return {"sent": False, "reason": "事件循环已在跑"}
