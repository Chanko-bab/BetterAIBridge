"""教程状态机。

- 第一次进聊天页：弹一次欢迎（跳过教程 / 开始教程）。
- 跳过：永不再弹。
- 开始：先记成"延后"，等聊过几轮（或她主动开口一次）再用轻气泡讲三条，
  讲完标 seen。这样既不挡第一次聊天，也不占一次正式弹窗。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

from . import settings as S

STATE_PATH: Path = S.ENTITY / "state" / "tutorial.json"
DELAY_TURNS = 6  # 延后到第 6 轮（或她第一次主动开口）

_state: Dict[str, Any] = {}


def _load() -> Dict[str, Any]:
    global _state
    if _state:
        return _state
    try:
        _state = json.loads(STATE_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        _state = {}
    _state.setdefault("seen", False)
    _state.setdefault("mode", None)      # None | "deferred" | "done"
    _state.setdefault("pending_since", None)
    _state.setdefault("updated_at", 0)
    return _state


def _save() -> None:
    st = _load()
    st["updated_at"] = time.time()
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(STATE_PATH)
    except Exception as e:  # noqa: BLE001
        S.log(f"[tutorial] save failed: {e}")


def get() -> Dict[str, Any]:
    st = _load()
    return {
        "seen": bool(st.get("seen")),
        "mode": st.get("mode"),
        "pending_since": st.get("pending_since"),
        "delay_turns": DELAY_TURNS,
        "updated_at": st.get("updated_at") or 0,
    }


def update(action: str, turn: int | None = None) -> Dict[str, Any]:
    st = _load()
    a = (action or "").strip().lower()
    if a == "skip":
        st.update({"seen": True, "mode": "done", "pending_since": None})
        S.log("[tutorial] skipped by user")
    elif a == "start":
        st.update({"seen": False, "mode": "deferred", "pending_since": int(turn or 0)})
        S.log(f"[tutorial] deferred until turn {st['pending_since']} + {DELAY_TURNS}")
    elif a == "finish":
        st.update({"seen": True, "mode": "done", "pending_since": None})
        S.log("[tutorial] finished")
    elif a == "reset":
        st.update({"seen": False, "mode": None, "pending_since": None})
        S.log("[tutorial] reset")
    else:
        raise ValueError(f"unknown action: {action}")
    _save()
    return get()
