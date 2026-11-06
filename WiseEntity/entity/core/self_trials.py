"""她自己试一下：低风险能力可以先试，试完把真实结果写进能力证据。

P3 的边界：
- L0 只碰她自己（看自己的头像），可以自动；
- L1 会看/听用户那边，必须先问；
- L2 会动文件和命令，必须每次明确同意。
自动循环每天最多一次，只做 L0，且不碰用户数据。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

from . import self_store, tool_bus
from .settings import STATE_DIR, log

TRIAL_STATE = Path(STATE_DIR) / "self_trials.json"
TRIAL_GAP = 20 * 60 * 60
_RUNNING = False

L0 = {"avatar_see"}
L1 = {"look_around", "listen_now"}


def _state() -> Dict[str, Any]:
    try:
        return json.loads(TRIAL_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(st: Dict[str, Any]) -> None:
    TRIAL_STATE.parent.mkdir(parents=True, exist_ok=True)
    TRIAL_STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")


def level_of(name: str) -> str:
    if name in L0:
        return "L0"
    if name in L1:
        return "L1"
    return "L2"


def candidates() -> List[str]:
    try:
        names = set(tool_bus.tools().keys())
    except Exception:
        names = set()
    return [n for n in ("avatar_see", "look_around", "listen_now") if n in names]


def due() -> bool:
    st = _state()
    try:
        last = float(st.get("last_ts") or 0)
    except Exception:
        last = 0.0
    return bool(candidates()) and (time.time() - last >= TRIAL_GAP)


async def try_once(ability: str = "", consent: str = "L0") -> Dict[str, Any]:
    ability = str(ability or "").strip() or (candidates() or [""])[0]
    if not ability:
        return {"ok": False, "error": "没有可试的能力"}
    lv = level_of(ability)
    if lv == "L1" and str(consent).upper() not in ("L1", "L2"):
        return {"ok": False, "need_consent": "L1", "ability": ability,
                "text": "这个会看/听对方那边，得先问一句。"}
    if lv == "L2" and str(consent).upper() != "L2":
        return {"ok": False, "need_consent": "L2", "ability": ability,
                "text": "这个会动文件和命令，得每次明确同意。"}
    one = await tool_bus.call(ability, {})
    st = _state()
    st.update({"last_ts": time.time(), "last": ability, "level": lv,
               "ok": bool(one.get("ok")), "tries": int(st.get("tries") or 0) + 1})
    _save(st)
    log(f"[self] trial {ability} {lv} ok={bool(one.get('ok'))}")
    return {"ok": bool(one.get("ok")), "ability": ability, "level": lv, "result": one}


async def maybe_try() -> Dict[str, Any]:
    """后台循环：一天最多一次，只做 L0。"""
    global _RUNNING
    if _RUNNING:
        return {"ok": False, "skipped": "running"}
    if not due():
        return {"ok": False, "skipped": "not due"}
    _RUNNING = True
    try:
        for ability in candidates():
            if level_of(ability) != "L0":
                continue
            return await try_once(ability, "L0")
        return {"ok": False, "skipped": "no L0 candidate"}
    finally:
        _RUNNING = False


def status() -> Dict[str, Any]:
    st = _state()
    return {"due": due(), "candidates": candidates(), "last": st.get("last", ""),
            "last_ts": st.get("last_ts", 0), "tries": st.get("tries", 0)}
