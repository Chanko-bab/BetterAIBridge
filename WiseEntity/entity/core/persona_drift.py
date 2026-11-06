# -*- coding: utf-8 -*-
"""性格随记忆缓慢变化：每月最多一次，小步、可追溯。"""
from __future__ import annotations
import json, os, re, time
from datetime import date, datetime

from . import brain_box, memory_box, memory_store, settings as S

PATH = S.ENTITY / "persona" / "drift.json"
DUE_DAYS = 30
MAX_TRAITS = 6
DECAY = 0.8
NEW_WEIGHT = 0.45
LOG = "persona-drift"

def _load() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"updated_at": "", "traits": []}

def _save(st: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")

def due() -> bool:
    st = _load()
    up = st.get("updated_at") or ""
    if not up:
        return True
    try:
        d = datetime.fromisoformat(up)
    except Exception:
        return True
    return (datetime.now() - d).days >= DUE_DAYS

def _notes_sample(limit: int = 400) -> list[str]:
    rows = []
    for rec in memory_store.index_records():
        door = str(rec.get("door") or "")
        if not memory_store.is_owner_door(door):
            continue
        t = str(rec.get("text") or "").strip()
        if t:
            rows.append(t)
    return rows[-limit:]

def run(force: bool = False) -> dict:
    if not force and not due():
        return {"ok": True, "skipped": "not due"}
    notes = _notes_sample()
    if len(notes) < 20:
        return {"ok": True, "skipped": "too few notes"}
    prompt = (
        "下面是她（无名）这一个月记住的事。只判断一件事：这些经历有没有让她的性情发生**细微**变化。\n"
        "要求：最多 3 条；每条不超过 18 个字；必须是「现在的她」的样子，不是事件复述；\n"
        "不许写能力、功能、插件、程序；找不到依据就返回空数组。\n"
        '输出 JSON：{"traits":[{"text":"...","weight":0.5,"why":"一句依据"}]}\n\n记忆：\n'
        + "\n".join("- " + n for n in notes[-250:])
    )
    raw = ""
    try:
        import httpx
        key = S.deepseek_key()
        r = httpx.post(S.deepseek_base() + "/chat/completions",
                       headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                       json={"model": "deepseek-chat", "temperature": 0.3, "max_tokens": 500,
                             "messages": [{"role": "user", "content": prompt}]},
                       timeout=60.0)
        raw = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {"traits": []}
    except Exception as e:
        S.log(f"[drift] failed: {e}")
        return {"ok": False, "error": str(e)}

    st = _load()
    old = {t.get("text", ""): t for t in st.get("traits", []) if t.get("text")}
    for t in old.values():
        t["weight"] = round(float(t.get("weight", 0.5)) * DECAY, 3)
    for item in (data.get("traits") or [])[:3]:
        text = str(item.get("text") or "").strip()[:24]
        if not text:
            continue
        w = max(0.0, min(1.0, float(item.get("weight") or 0.5)))
        if text in old:
            old[text]["weight"] = round(min(1.0, old[text]["weight"] + NEW_WEIGHT), 3)
            old[text]["last"] = date.today().isoformat()
        else:
            old[text] = {"text": text, "weight": round(w * NEW_WEIGHT + 0.2, 3),
                         "born": date.today().isoformat(), "last": date.today().isoformat(),
                         "why": str(item.get("why") or "")[:60]}
    traits = [t for t in old.values() if float(t.get("weight", 0)) >= 0.12]
    traits.sort(key=lambda x: -float(x.get("weight", 0)))
    traits = traits[:MAX_TRAITS]
    st = {"updated_at": datetime.now().isoformat(timespec="seconds"), "traits": traits}
    _save(st)
    S.log(f"[drift] updated: {len(traits)} traits")
    return {"ok": True, "traits": traits}

def fragment() -> str:
    st = _load()
    traits = st.get("traits") or []
    if not traits:
        return ""
    lines = []
    for t in traits:
        w = float(t.get("weight", 0))
        tone = "已经很明显" if w >= 0.6 else ("有一点" if w >= 0.3 else "偶尔会")
        lines.append(f"- {t.get('text')}（{tone}）")
    return "# 你这一个月慢慢变成的样子（不用挂在嘴上）\n" + "\n".join(lines)
