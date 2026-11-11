"""模组排他绑定表：一个模组实例同时只属于一个智能体。

文件放安装根 ``modules.bindings.json``，结构可重建（扫各智能体 registry 的
enabled 记录）。绑定只在启用时检查/写入；停用不自动解绑，必须显式解绑，
这样切到别的智能体时模组页还能说清“此模组绑定到谁”。
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from . import agent_paths

LOCK = threading.RLock()
BINDINGS_NAME = "modules.bindings.json"


class BindingError(RuntimeError):
    """模组已被别的智能体绑定；message 可直接展示。"""


def path() -> Path:
    return agent_paths.install_root() / BINDINGS_NAME


def _empty() -> Dict[str, Any]:
    return {"format": "bab-bindings/1", "updated": "", "bindings": {}}


def load() -> Dict[str, Any]:
    p = path()
    if not p.exists():
        return _empty()
    try:
        doc = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(doc, dict) or not isinstance(doc.get("bindings"), dict):
        return _empty()
    return doc


def save(doc: Dict[str, Any]) -> None:
    with LOCK:
        doc["format"] = "bab-bindings/1"
        doc["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)


def owner(mid: str) -> str:
    return str((load().get("bindings") or {}).get(str(mid)) or "")


def message(mid: str) -> str:
    who = owner(mid)
    if not who:
        return "这个模组没有绑定智能体"
    return f"此模组绑定到「{who}」。要使用它，请切换到「{who}」，或先在那里解除绑定。"


def ensure_free(mid: str) -> None:
    """当前智能体能不能启用这个模组；没设置 BAB_AGENT_ID 时不做限制。"""
    me = agent_paths.agent_id()
    if not me:
        return
    who = owner(mid)
    if who and who != me:
        raise BindingError(message(mid))


def bind(mid: str, slug: str | None = None) -> None:
    me = (slug or agent_paths.agent_id()).strip()
    if not me:
        return
    with LOCK:
        doc = load()
        rows = doc.setdefault("bindings", {})
        who = str(rows.get(str(mid)) or "")
        if who and who != me:
            raise BindingError(message(mid))
        rows[str(mid)] = me
        save(doc)


def unbind(mid: str, slug: str | None = None) -> bool:
    """显式解绑；slug 给了就只允许绑定者解。返回是否真的删了一行。"""
    me = (slug or agent_paths.agent_id()).strip()
    with LOCK:
        doc = load()
        rows = doc.setdefault("bindings", {})
        who = str(rows.get(str(mid)) or "")
        if not who:
            return False
        if me and who != me:
            raise BindingError(message(mid))
        rows.pop(str(mid), None)
        save(doc)
        return True


def reconcile(existing_slugs: list[str]) -> list[str]:
    """清掉指向已不存在智能体的绑定；返回清掉的 module id。"""
    alive = {str(x) for x in existing_slugs}
    removed: list[str] = []
    with LOCK:
        doc = load()
        rows = doc.setdefault("bindings", {})
        for mid, who in list(rows.items()):
            if str(who) not in alive:
                rows.pop(mid, None)
                removed.append(str(mid))
        if removed:
            save(doc)
    return removed
