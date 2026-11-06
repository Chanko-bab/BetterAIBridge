"""模组注册表：唯一真相 program_bundle\\registry.json。

程序只认这张表；界面上"装了没有、开着没有"都从这里读，不再硬编码路径。
状态机：not_installed -> installed -> enabled <-> disabled；异常 -> broken
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from . import config

LOCK = threading.RLock()

STATES = ("not_installed", "installed", "enabled", "disabled", "broken")
STATE_LABEL = {
    "not_installed": "未安装",
    "installed": "已安装（未启用）",
    "enabled": "运行中",
    "disabled": "已停用",
    "broken": "异常",
}


def path() -> Path:
    return config.bundle_dir() / "registry.json"


def _empty() -> Dict[str, Any]:
    return {"format": "bab-registry/1", "updated": "", "modules": {}}


def load() -> Dict[str, Any]:
    p = path()
    if not p.exists():
        return _empty()
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return _empty()
    if not isinstance(data, dict) or not isinstance(data.get("modules"), dict):
        return _empty()
    data.setdefault("format", "bab-registry/1")
    return data


def save(data: Dict[str, Any]) -> None:
    with LOCK:
        data["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        path().parent.mkdir(parents=True, exist_ok=True)
        tmp = path().with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path())


def modules() -> List[Dict[str, Any]]:
    return list(load()["modules"].values())


def get(mid: str) -> Dict[str, Any] | None:
    return load()["modules"].get(mid)


def upsert(mod: Dict[str, Any]) -> None:
    with LOCK:
        data = load()
        old = data["modules"].get(mod["id"], {})
        old.update(mod)
        old.setdefault("settings", {})
        data["modules"][mod["id"]] = old
        save(data)


def patch(mid: str, **kw) -> None:
    with LOCK:
        data = load()
        mod = data["modules"].get(mid)
        if not mod:
            return
        mod.update(kw)
        save(data)


def remove(mid: str) -> None:
    with LOCK:
        data = load()
        data["modules"].pop(mid, None)
        save(data)
