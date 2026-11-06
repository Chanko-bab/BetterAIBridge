"""记忆维护：把「聊天原文」变成「长期记忆」，并每天合并一次重复。

两件事：
1. ingest()  —— 读 internal\\.raw\\<门>\\YYYY.MM.DD.jsonl 的新行，抽成
   internal\\<门>\\YYYY.MM.DD.txt 里的一行行「HH:MM 我做了什么」（每 20 分钟最多一轮）
2. digest()  —— 每天 10:30 之后真写一次（--apply，不是演练）

设计约束：
- .raw 是原文全量，不动；.txt 只写"以后再提起仍成立"的事实，第一人称「我」。
- 游标按字节记，存在 entity\\state\\maintenance.json，重启不重复抽。
- 任何失败都只记日志，不影响她说话。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

from datetime import datetime

from . import (brain_box, persona_drift, memory_box, memory_compact, memory_store,
               settings as S, stomach_box)

STATE_PATH = S.STATE_DIR / "maintenance.json"
DIGEST_SCRIPT = S.ROOT / "source_code" / "tools" / "memory_digest.py"

INGEST_EVERY = 20 * 60          # 秒
DIGEST_AT = (10, 30)            # 本地时间
MAX_LINES = 90                  # 每轮最多看多少行原文
MAX_NOTES_PER_ROUND = 6         # 每片每轮最多新增几条
NOTE_MAX_CHARS = 48

def prompt_head() -> str:
    """记忆整理提示词里的关系词跟着配置走，不再写死「主人」。"""
    return f"""你在给一个叫「无名」的角色整理长期记忆。
下面是某段对话。只抽取「以后再提起仍然成立」的事实，例如：
- 他的身份/偏好/习惯/近况（吃了什么、几点睡、在忙什么、喜欢什么）
- 两人之间的约定、承诺、称呼变化
- 她自己的重要经历（去过哪、做了什么、答应了什么）
不要抽取：寒暄、一次性的情绪、她的说话风格（人格文件里已有）、重复信息。
输出严格 JSON：{{"notes": ["...", "..."]}}
每条 ≤40 字、**第一人称**（"我……"），提到对方写「{S.user_title()}」，不加日期、不加编号、不加引号。
没有值得记的就输出 {{"notes": []}}。
"""


def _state() -> dict:
    data = S.read_json(STATE_PATH, {}) or {}
    return data if isinstance(data, dict) else {}


def _save_state(st: dict) -> None:
    S.write_json(STATE_PATH, st)


def _door_of_raw(tpath: Path) -> str:
    """`internal/.raw/<门>/2026.10.31.jsonl` → 门名。"""
    try:
        rel = tpath.relative_to(S.MEM_DIR).parts
    except ValueError:
        return ""
    if len(rel) >= 4 and rel[0] == memory_store.INTERNAL and rel[1] == ".raw":
        try:
            return memory_store._safe_door(rel[2])
        except ValueError:
            return ""
    return ""


def _norm(t: str) -> str:
    return "".join(ch for ch in (t or "").lower() if ch.isalnum())


def _existing_texts(door: str) -> list[str]:
    return [str(r.get("text") or "") for r in memory_store.entries(_door_to_session(door), days=0)]


def _door_to_session(door: str) -> str:
    program, kind, key = memory_box.door_parts(door)
    if kind == "owner":
        return {"program_qq": "qq:owner", "program_bilibili": "bili:owner"}.get(program, "web:owner")
    if kind == "group":
        return f"qq:group:{key}"
    if kind == "friend":
        return f"qq:friend:{key}"
    return f"bili:other:{key}"


def _ask_notes(turns: list[dict], existing: list[str]) -> list[str]:
    key = S.deepseek_key()
    if not key:
        return []
    convo = []
    for t in turns:
        role = "我" if t.get("role") == "assistant" else "他"
        text = str(t.get("text") or "").strip()
        if text:
            convo.append(f"{role}: {text}")
    if not convo:
        return []
    body = "\n".join(convo[-MAX_LINES:])
    known = "\n".join(f"- {x}" for x in existing[-60:]) or "（还没有）"
    prompt = f"{prompt_head()}\n已存在的记忆（不要重复）：\n{known}\n\n对话：\n{body}"
    try:
        r = httpx.post(
            S.deepseek_base() + "/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "deepseek-chat",
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.2, "max_tokens": 700, "stream": False},
            timeout=90.0,
        )
        if r.status_code != 200:
            S.log(f"[maint] llm HTTP {r.status_code}: {r.text[:160]}")
            return []
        text = (r.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        S.log(f"[maint] llm failed: {e!r}")
        return []
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except Exception:
        return []
    notes = data.get("notes") if isinstance(data, dict) else None
    if not isinstance(notes, list):
        return []
    clean = []
    for n in notes:
        s = str(n or "").strip().strip('"“”')
        if 4 <= len(s) <= NOTE_MAX_CHARS:
            clean.append(s)
    return clean[:MAX_NOTES_PER_ROUND]


def ingest(force: bool = False) -> dict:
    st = _state()
    now = time.time()
    last = float(st.get("last_ingest") or 0)
    if not force and now - last < INGEST_EVERY:
        return {"skipped": "too soon", "in": int(now - last)}
    cursors = st.setdefault("cursors", {})
    added_total = 0
    touched = 0
    raw_root = Path(S.MEM_DIR) / memory_store.INTERNAL / ".raw"
    for tpath in sorted(raw_root.glob("*/*.jsonl")):
        door = _door_of_raw(tpath)
        if not door:
            continue
        rel = str(tpath.relative_to(S.MEM_DIR))
        try:
            size = tpath.stat().st_size
        except OSError:
            continue
        off = int(cursors.get(rel) or 0)
        if size <= off:
            continue
        try:
            with open(tpath, "rb") as fh:
                fh.seek(off)
                raw = fh.read()
                new_off = fh.tell()
        except OSError:
            continue
        turns = []
        for line in raw.decode("utf-8", "ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                turns.append(json.loads(line))
            except Exception:
                continue
        if not turns:
            continue
        existing = _existing_texts(door)
        known_norm = {_norm(x) for x in existing}
        try:
            fresh = [n for n in _ask_notes(turns, existing) if _norm(n) not in known_norm]
        except Exception as e:
            S.log(f"[maint] 提炼失败，游标不前进（下轮重试）：{e!r}")
            continue
        cursors[rel] = new_off
        stamp = str(turns[-1].get("ts") or "") or None
        for n in fresh:
            try:
                res = memory_store.append(door, n, ts=stamp)
                if res.get("ok") and not res.get("duplicate"):
                    added_total += 1
                    known_norm.add(_norm(n))
            except Exception as e:
                S.log(f"[maint] add_note failed: {e!r}")
        touched += 1
    st["last_ingest"] = now
    _save_state(st)
    if added_total:
        S.log(f"[maint] ingest: +{added_total} notes from {touched} drawers")
    return {"added": added_total, "shards": touched}


def digest(force: bool = False) -> dict:
    """每天 10:30 之后：把太旧的那几天压成几行，原文打包收起来。"""
    st = _state()
    today = time.strftime("%Y-%m-%d")
    lt = time.localtime()
    if not force:
        if (lt.tm_hour, lt.tm_min) < DIGEST_AT:
            return {"skipped": "too early"}
        if st.get("last_digest") == today:
            return {"skipped": "done today"}
    try:
        res = memory_compact.run(force=force)
    except Exception as e:  # noqa: BLE001
        S.log(f"[maint] compact failed: {e!r}")
        return {"error": repr(e)}
    if st.get("last_digest") != today:
        st["last_digest"] = today
        _save_state(st)
    return res



_LAST_EVENT_DAY = ""


def push_daily_event() -> None:
    """每天 22:00 之后，把"今天做过的事"喂给大脑一次（只走事件通道，不写记忆）。"""
    global _LAST_EVENT_DAY
    now = datetime.now()
    if now.hour < 22:
        return
    day = now.strftime("%Y-%m-%d")
    st = _state()
    if st.get("last_event_day") == day:
        return
    text = "今天又过完了，她还在这儿。"
    try:
        brain_box.stimulate("moments", text=text)
    except Exception:
        pass
    st["last_event_day"] = day
    _save_state(st)
    S.log(f"[maint] daily event -> {day}")



def tick() -> dict:
    push_daily_event()
    try:
        from . import emotion_core
        emotion_core.tick()
    except Exception as e:
        S.log(f"[maint] emotion error: {e!r}")
    out = {}
    try:
        if persona_drift.due():
            out["drift"] = persona_drift.run()
    except Exception as e:
        S.log(f"[maint] drift error: {e!r}")
        out["drift"] = {"error": repr(e)}
    try:
        out["stomach"] = stomach_box.poll_if_due()
    except Exception as e:
        S.log(f"[maint] stomach error: {e!r}")
        out["stomach"] = {"error": repr(e)}
    try:
        out["ingest"] = ingest()
    except Exception as e:
        S.log(f"[maint] ingest error: {e!r}")
        out["ingest"] = {"error": repr(e)}
    try:
        out["digest"] = digest()
    except Exception as e:
        S.log(f"[maint] digest error: {e!r}")
        out["digest"] = {"error": repr(e)}
    return out


if __name__ == "__main__":
    print(json.dumps(tick(), ensure_ascii=False))
