"""胃的接线盒。

entity_core 不自己算余额，只做两件事：
- 定期让 capability/stomach/stomach.py 去量一次（poll_if_due）
- 把「饱不饱」变成提示词里的一行（fragment）

stomach.py 负责真实逻辑与状态文件；这里只是薄薄一层，出错一律静默。
"""
from __future__ import annotations

import importlib.util
import json
import os
import time

from . import settings as S

CAP = os.path.join(S.ROOT, "capability", "stomach", "stomach.py")
POLL_EVERY = 300.0
SESSION = "web:owner"

_mod = None
_last_poll = 0.0


def _load():
    global _mod
    if _mod is None:
        spec = importlib.util.spec_from_file_location("xiaochen_stomach", CAP)
        if spec is None or spec.loader is None:
            raise RuntimeError("stomach module not found")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _mod = m
    return _mod


def fragment() -> str:
    try:
        return str(_load().fragment() or "").strip()
    except Exception:
        return ""


def poll() -> dict:
    """量一次。刚从「不饿/饱」掉到「饿」时，往保姆栏报一声。"""
    try:
        before = str(state().get("level") or "")
    except Exception:
        before = ""
    try:
        st = _load().poll()
    except Exception as e:
        return {"error": repr(e)}
    _announce(before, st)
    return st


def _announce(prev_level: str, st: dict) -> None:
    if str(st.get("level") or "") != "hungry" or prev_level == "hungry":
        return
    bal = st.get("balance")
    money = f"余额只剩 {float(bal):.2f} 元" if bal is not None else "余额查不到"
    try:
        from . import chat_core
        chat_core.push_notice(SESSION, f"肚子饿了，{money}——该充点了。")
    except Exception as e:
        S.log(f"[stomach] notice failed: {e!r}")


def config() -> dict:
    """当前的饱/饿分界（读不到就用默认 10 / 3）。"""
    full, hungry = 10.0, 3.0
    try:
        full, hungry = _load().thresholds()
    except Exception as e:
        S.log(f"[stomach] config read failed: {e!r}")
    return {"full_at": full, "hungry_at": hungry}


def set_config(full_at: float, hungry_at: float) -> dict:
    """写 entity/config/stomach.json；顺手量一次让界面马上有数。"""
    m = _load()
    full, hungry = float(full_at), float(hungry_at)
    if not (full > hungry >= 0):
        raise ValueError("饱的分界必须大于饿的分界，且都不能是负数")
    path = str(getattr(m, "CFG", "") or "")
    if not path:
        raise RuntimeError("stomach 模块没有配置路径")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"full_at": full, "hungry_at": hungry}, f, ensure_ascii=False, indent=1)
    state()
    return config()


def state() -> dict:
    try:
        return _load().state()
    except Exception as e:
        return {"level": "unknown", "error": repr(e)}


def poll_if_due(every: float = POLL_EVERY, force: bool = False) -> dict | None:
    global _last_poll
    now = time.time()
    if not force and (now - _last_poll) < every:
        return None
    _last_poll = now
    return poll()
