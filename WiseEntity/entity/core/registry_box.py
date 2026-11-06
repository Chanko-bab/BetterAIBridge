# -*- coding: utf-8 -*-
"""程序清单：她「可以查看的地方」。不写进记忆，只在这里维护。"""
from __future__ import annotations
import json
from . import settings as S

PATH = S.ENTITY / "registry" / "programs.json"

def all_programs() -> list[dict]:
    """程序清单兼容三种写法：list（旧）、{"programs": [...]}、{"items": [...]}。"""
    try:
        raw = json.loads(PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    if isinstance(raw, dict):
        raw = raw.get("programs") or raw.get("items") or []
    if not isinstance(raw, list):
        return []
    return [p for p in raw if isinstance(p, dict)]

def get(name: str) -> dict | None:
    name = (name or "").strip().lower()
    for p in all_programs():
        if name in (p.get("name", "").lower(), p.get("title", "").lower(), p.get("what", "").lower()):
            return p
    return None

def dump_text() -> str:
    rows = []
    for p in all_programs():
        rows.append(f"- {p.get('title')}（{p.get('what')}）入口：{p.get('entry')}")
        rows.append("  " + "、".join(p.get("can") or []))
    return "\n".join(rows)

def pointer() -> str:
    names = "、".join(p.get("title", "") for p in all_programs())
    return ("# 你能用的程序\n"
            f"现在有：{names}。\n"
            "每样具体能干什么、怎么进，清单在 entity/registry/programs.json（他随时能给你看）。\n"
            "别凭印象编能力；真要用的时候先问他一句入口还在不在。")
