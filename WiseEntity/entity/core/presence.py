"""主人现在在不在：online / busy / away。

- 桌面壳上的【在线】【忙碌】按钮改这里；
- 关掉窗口默认 busy；
- 每轮拼提示词时读一次，让她知道该不该主动搭话。
"""
from __future__ import annotations

import time
from typing import Dict

from . import settings as S

STATE_PATH = S.STATE_DIR / "presence.json"
LEVELS = ("online", "busy", "away")
_LABEL = {
    "online": "在线",
    "busy": "忙碌",
    "away": "不在家",
}
_HINT = {
    "online": "他现在在电脑前，也没在忙别的事。你可以自然地找他说话。",
    "busy": "他现在忙。别主动找他，他说话你就简短回，别拉长。",
    "away": "他现在不在家 / 不在电脑前。别主动找他；他要是说话，正常回。",
}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def get() -> Dict[str, str]:
    data = S.read_json(STATE_PATH, {}) or {}
    state = str(data.get("state") or "busy")
    if state not in LEVELS:
        state = "busy"
    return {"state": state, "updated_at": str(data.get("updated_at") or "")}


def set_state(state: str, *, source: str = "") -> Dict[str, str]:
    if state not in LEVELS:
        state = "busy"
    data = {"state": state, "updated_at": _now(), "source": source}
    S.write_json(STATE_PATH, data)
    S.log(f"[presence] {state} ({source or '-'})")
    return {"state": state, "updated_at": data["updated_at"]}


def label() -> str:
    return _LABEL.get(get()["state"], "忙碌")


def fragment() -> str:
    st = get()
    state = st["state"]
    hint = _HINT.get(state, _HINT["busy"])
    return f"# 他现在的状态\n{_LABEL.get(state, '忙碌')}（{st.get('updated_at', '')[:16]}）。{hint}"


def is_online() -> bool:
    return get()["state"] == "online"
