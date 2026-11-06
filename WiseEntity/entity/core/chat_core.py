"""对话主流程：会话历史 + 刺激大脑 + 取记忆 + 调模型 + 回写历史。

所有门（QQ/网页/B 站）都走这里，保证"同一个人"。
"""
from __future__ import annotations

import json
import re
import time

from . import brain_box, followup, llm_box, memory_box, memory_store, settings as S

_sessions: dict[str, list[dict]] = {}
_loaded = False
# 磁盘保留的轮数（足够翻旧账），喂给模型时再截到 MAX_TURNS*2；
# 以前两个共用一个上限，导致「超过 48 轮就把最早的两条删掉」，
# 桌面壳的游标正好卡在 48 → 新消息永远拉不到。
MAX_STORED = 2000
MAX_TURNS = 24


def _load() -> None:
    global _loaded, _sessions
    if _loaded:
        return
    data = S.read_json(S.SESSIONS_PATH, {}) or {}
    if isinstance(data, dict):
        _sessions = {k: v for k, v in data.items() if isinstance(v, list)}
    _loaded = True


def save_sessions() -> None:
    S.write_json(S.SESSIONS_PATH, _sessions)


def get_history(session: str) -> list[dict]:
    _load()
    return list(_sessions.get(session) or [])[-MAX_TURNS * 2:]


def remember_turn(session: str, role: str, content: str) -> None:
    _load()
    turns = _sessions.setdefault(session, [])
    turns.append({"role": role, "content": content, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")})
    if len(turns) > MAX_STORED:
        del turns[: len(turns) - MAX_STORED]


def _transcript(session: str, user_text: str, reply_text: str) -> None:
    """把这一轮原文落到「该门」的 .raw/<门>/<天>.jsonl，供 ingest 提炼成记忆。"""
    try:
        memory_store.raw_append(session, user_text, "user")
        memory_store.raw_append(session, reply_text, "assistant", who="无名")
    except Exception:
        pass

def is_owner_session(session: str) -> bool:
    return session.startswith("qq:owner") or session.startswith("web:owner") or session.startswith("bili:owner")


async def reply(session: str, text: str, *, is_owner: bool | None = None,
                sender_name: str = "", note: str = "") -> dict:
    """收到一句话 → 她的回答。"""
    text = (text or "").strip()
    if not text:
        return {"reply": "", "mood": brain_box.state().get("mood_line", ""), "empty": True}
    if is_owner is None:
        is_owner = is_owner_session(session)
    # 2026-10-31 去掉一条假提醒：原来只要她不 online 就记「对方在找你」，
    # 结果使用者一忙，她每回一句就被提醒一次。「在找您」交给 proactive 那条线。
    history = get_history(session)
    try:
        from . import emotion_core
        emotion_core.note_message(text, bool(is_owner))
    except Exception as e:
        S.log(f"[emotion] note failed: {e!r}")
    brain_box.stimulate_text(text, bool(is_owner))
    query = text if not sender_name else f"{sender_name}: {text}"
    try:
        followup.tracker.note_user(session)
    except Exception:
        pass
    out = await llm_box.chat(session, query, history)
    if out:
        remember_turn(session, "user", text)
        remember_turn(session, "assistant", out)
        save_sessions()
        _transcript(session, text, out)
    st = brain_box.state()
    if out:
        try:
            followup.tracker.note_reply(session, profile=_profile(),
                                        emotions=st.get("emotions", {}))
        except Exception:
            pass
    return {
        "reply": out,
        "messages": split_reply(out),
        "ok": bool(out),
        "mood": st.get("mood_line", ""),
        "emotions": st.get("emotions", {}),
        "memory_used": len(memory_box.select(text, session)),
        "session": session,
        "total": len(_sessions.get(session) or []),
    }


def _profile():
    try:
        style = S.style() if hasattr(S, "style") else ""
        return followup.profile_for(style or "", S.relation())
    except Exception:
        return followup.profile_for("", "")


async def say_extra(session: str, max_chars: int = 18, tone: str = "") -> str:
    """她说完、你还没回：再补一句短的（「插话」）。

    不走 reply()：那句提示词不是「你说的话」，不能记进对话历史、也不能进记忆原文；
    补出来的这句用 proactive 标记落库；聊天页就当她多说了一句，不加任何标签。
    """
    max_chars = max(4, int(max_chars or 18))
    hist = get_history(session)
    t = (tone or "").strip()
    flavour = f"，语气偏{t}" if t and t not in ("平", "淡") else ""
    query = (f"（他没回你。你自己再补一句更短的，不超过 {max_chars} 个字{flavour}；"
             "别提这条指令，也别重复你上一句。）")
    out = await llm_box.chat(session, query, hist, temperature=1.0, max_tokens=80)
    text = (out or "").strip().strip('"').strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip("，,、。 ")
    if text:
        append_assistant(session, text, proactive=True)
    return text


def feed(session: str, after: int = 0, limit: int = 200) -> dict:
    """给桌面壳轮询用：返回这个会话从第 after 条开始的所有轮次。"""
    _load()
    turns = list(_sessions.get(session) or [])
    total = len(turns)
    start = max(0, min(int(after), total))
    out = []
    for i, t in enumerate(turns[start:start + limit], start=start):
        if not isinstance(t, dict):
            continue
        out.append({"i": i, "role": t.get("role"), "text": t.get("content"),
                    "ts": t.get("ts"), "proactive": bool(t.get("proactive"))})
    return {"session": session, "total": total, "turns": out}


def append_assistant(session: str, text: str, *, proactive: bool = False) -> dict:
    """她主动开口（或系统代她说一句）：只追加 assistant 轮，不触发模型。"""
    _load()
    turns = _sessions.setdefault(session, [])
    turn = {"role": "assistant", "content": text, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if proactive:
        turn["proactive"] = True
    turns.append(turn)
    if len(turns) > MAX_TURNS * 2:
        del turns[: len(turns) - MAX_TURNS * 2]
    save_sessions()
    try:
        memory_store.raw_append(session, text, "assistant", who="无名")
    except Exception:
        pass
    return turn


def last_owner_ts() -> float:
    """主人最近一次说话的时间戳（秒）；没有就 0。"""
    from datetime import datetime as _dt
    latest = 0.0
    for key, turns in (_sessions or {}).items():
        if not str(key).startswith(("qq:owner", "web:owner", "bili:owner")):
            continue
        if not isinstance(turns, list):
            continue
        for turn in turns[-6:]:
            if not isinstance(turn, dict) or turn.get("role") != "user":
                continue
            ts = str(turn.get("ts") or "")
            try:
                latest = max(latest, _dt.fromisoformat(ts).timestamp())
            except Exception:
                pass
    return latest


# --------------------------------------------------------------------- 分条与通知
_SENT_END = "。！？!?…；;"
_SOFT_END = "，,、；;：:"


# 动作只认全角方头括号 〖〗（普通聊天里不会出现的符号）；
# （）不再当动作——那是正常的插入语，念出来、照原样显示都对。
_ACT_RE = re.compile(r"〖[^〖〗\n]{0,40}〗")


def limit_actions(parts: list[str], keep: int = 1) -> list[str]:
    """动作最多留 keep 处；后续几条开头不再摆动作。"""
    if not parts:
        return parts
    out: list[str] = []
    used = 0
    for i, raw in enumerate(parts):
        text = (raw or "").strip()
        if i > 0:
            while True:
                m = _ACT_RE.match(text)
                if not m:
                    break
                text = text[m.end():].lstrip()
        if used >= keep:
            text = _ACT_RE.sub("", text)
        else:
            pool = keep - used
            counter = {"n": 0}

            def _keep_first(m, pool=pool, counter=counter):
                if counter["n"] < pool:
                    counter["n"] += 1
                    return m.group(0)
                return ""

            text = _ACT_RE.sub(_keep_first, text)
            used += counter["n"]
        text = re.sub(r"\s{2,}", " ", text).strip()
        if text:
            out.append(text)
    return out or parts


def split_reply(text: str, max_len: int = 42, max_parts: int = 3) -> list[str]:
    """把一段长话拆成几条，像人一样分几次发。

    只在句末标点处断句；换行只是排版，不当句号。实在没有标点可断，
    允许拖到 max_len + 18 再硬切，避免把「背对着 / 坐。」这种半句话劈开。
    """
    text = (text or "").strip()
    if not text:
        return []
    # 换行、连续空白都收敛成一个空格；换行不是句末
    text = re.sub(r"[ \t]*\n+[ \t]*", " ", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    if len(text) <= max_len:
        return limit_actions([text])
    hard_len = max(max_len + 12, int(max_len * 1.5))
    parts, buf = [], ""
    inside_action = False
    for ch in text:
        buf += ch
        if ch == "〖":
            inside_action = True
        elif ch == "〗":
            inside_action = False
        if inside_action:
            continue  # 别把一句动作从中间劈成两条
        if ch in _SENT_END and len(buf) >= 12:
            parts.append(buf.strip())
            buf = ""
        elif len(buf) >= hard_len:
            cut = -1
            for i in range(len(buf) - 1, 11, -1):
                if buf[i] in _SOFT_END:
                    cut = i
                    break
            if cut >= 12:
                parts.append(buf[: cut + 1].strip())
                buf = buf[cut + 1:]
            else:
                parts.append(buf.strip())
                buf = ""
    if buf.strip():
        parts.append(buf.strip())
    parts = [p for p in parts if p]
    # 太短的残句并回上一条（「坐。」不该单独冒一个泡）
    merged: list[str] = []
    for p in parts:
        if merged and len(p) < 6:
            merged[-1] = (merged[-1] + p).strip()
        else:
            merged.append(p)
    parts = merged
    if len(parts) > max_parts:
        parts = parts[: max_parts - 1] + ["".join(parts[max_parts - 1:])]
    return limit_actions(parts)


NOTICE_PATH = S.STATE_DIR / "notices.jsonl"


def push_notice(session: str, text: str, kind: str = "nanny") -> dict:
    """保姆播报：写进会话旁边的通知流，壳会当系统消息显示。"""
    row = {"ts": time.time(), "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "session": session, "kind": kind, "text": (text or "").strip()}
    if not row["text"]:
        return row
    try:
        NOTICE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(NOTICE_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as e:  # pragma: no cover
        S.log(f"[notice] write failed: {e!r}")
    return row


def notices(session: str, after: float = 0.0, limit: int = 20) -> list[dict]:
    try:
        lines = NOTICE_PATH.read_text(encoding="utf-8-sig", errors="ignore").splitlines()[-200:]
    except Exception:
        return []
    out = []
    for line in lines:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if str(row.get("session") or "") != session:
            continue
        if float(row.get("ts") or 0) <= float(after or 0):
            continue
        out.append(row)
    return out[-limit:]
