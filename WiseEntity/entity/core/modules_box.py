"""只读的模组视图（内核侧用，不依赖 launcher 的 yaml/PySide）。

launcher 里那套 `app.core.pbab` 负责装/卸/起停；内核只需要知道"现在有哪些模组、
开没开、提供了什么"，所以这里用纯 json 重新读一遍，保持轻依赖。

目录：program_bundle\\program_<id>.pbab\\{module.json, connection.json, persona.md}
注册表：program_bundle\\registry.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from . import settings as S

BUNDLE: Path = S.BUNDLE


def _norm_mods(raw) -> Dict[str, Any]:
    """注册表的 modules 有三种历史写法：dict（现行）、list（0.1.x 出厂）、None。统一成 dict。"""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        out: Dict[str, Any] = {}
        for m in raw:
            if isinstance(m, dict) and m.get("id"):
                out[str(m["id"])] = m
        return out
    return {}


def _json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def registry() -> Dict[str, Any]:
    return _json(BUNDLE / "registry.json")


def modules() -> List[Dict[str, Any]]:
    mods = _norm_mods(registry().get("modules"))
    return [m for m in mods.values() if isinstance(m, dict)]


def record(mid: str) -> Dict[str, Any]:
    """注册表里的这一条（state / runtime_port / settings / installed_at）。

    桥要用它把「模组自己在设置页上改的值」回给模组——不然模组看不见自己的设置。
    """
    for m in modules():
        if str(m.get("id")) == str(mid):
            return m
    return {}


def settings_of(mid: str) -> Dict[str, Any]:
    """模组当前的设置值（安装时已把 schema 默认值并进 registry，这里只取用户值）。"""
    got = record(mid).get("settings")
    if isinstance(got, dict):
        return {str(k): v for k, v in got.items()}
    return {}


def folder(mid: str) -> Path:
    return BUNDLE / f"program_{mid}.pbab"


def manifest(mid: str) -> Dict[str, Any]:
    return _json(folder(mid) / "module.json")


def connection(mid: str) -> Dict[str, Any]:
    return _json(folder(mid) / "connection.json")


def intro(mid: str) -> str:
    """模组自己写的介绍（introduce.md）——给智能体看的那一份。"""
    p = folder(mid) / "introduce.md"
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8-sig").strip()
    except Exception:  # noqa: BLE001
        return ""


def agent_doc(mid: str) -> str:
    """模组写给智能体看的说明（agent.md）。

    和 introduce.md 分开：introduce 是给使用者的说明书（怎么装、点哪里），
    agent.md 是给她的操作须知（什么时候用、能做什么、做不到什么）。
    """
    p = folder(mid) / "agent.md"
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8-sig").strip()
    except Exception:  # noqa: BLE001
        return ""


def persona(mid: str) -> str:
    p = folder(mid) / "persona.md"
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8-sig").strip()
    except Exception:
        return ""


def enabled() -> List[Dict[str, Any]]:
    return [m for m in modules() if str(m.get("state")) == "enabled"]


def not_enabled() -> List[Dict[str, Any]]:
    return [m for m in modules() if str(m.get("state")) in ("installed", "disabled", "broken")]


WALL_WORDS = {
    "哔哩哔哩": "那个站点",
    "bilibili": "那个站点",
    "B 站": "那个站点",
    "B站": "那个站点",
    "NapCat": "那个协议端",
    "AstrBot": "那个框架",
    "QQ": "那个聊天软件",
}


def wall(text: str) -> str:
    """把模组自带文案里的平台名换成泛称：门没装之前，她不该知道门外是什么。"""
    out = str(text or "")
    for k, v in WALL_WORDS.items():
        out = out.replace(k, v)
    return out


def persona_text() -> str:
    """给智能体看的那一小段：她的 persona.md + 模组的 agent.md。

    introduce.md 是给使用者看的说明书，**不进提示词**——那里面写着怎么装、
    点哪个按钮、包多大，她读了只会把这些当成自己的经历说出去。
    """
    parts = []
    for mod in enabled():
        mid = str(mod.get("id") or "")
        frag = persona(mid)
        doc = agent_doc(mid)
        if frag or doc:
            body = frag
            if doc:
                body = (body + "\n\n" if body else "") + doc[:1600]
            parts.append(f"# 关于「{mod.get('name') or mid}」\n{body}")
    return "\n\n".join(parts)


def tool_names(mid: str) -> List[str]:
    conn = connection(mid)
    provides = conn.get("provides") or {}
    names = provides.get("tools") or []
    return [str(t) for t in names if t]
