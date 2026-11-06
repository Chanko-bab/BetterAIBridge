"""P3：她自己试一下的权限与状态。"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from WiseEntity.entity.core import self_trials as T  # noqa: E402


def test_levels():
    assert T.level_of("avatar_see") == "L0"
    assert T.level_of("look_around") == "L1"
    assert T.level_of("listen_now") == "L1"
    assert T.level_of("fs.mkdir") == "L2"


def test_consent(tmp=Path("test_self_trials.json")):
    old = T.TRIAL_STATE
    T.TRIAL_STATE = tmp
    calls = []

    async def fake(name, args):
        calls.append(name)
        return {"ok": True, "text": "done"}

    old_call = T.tool_bus.call
    T.tool_bus.call = fake
    try:
        r = asyncio.run(T.try_once("look_around", "L0"))
        assert not r["ok"] and r["need_consent"] == "L1" and not calls
        r = asyncio.run(T.try_once("fs.mkdir", "L1"))
        assert not r["ok"] and r["need_consent"] == "L2" and not calls
        r = asyncio.run(T.try_once("avatar_see", "L0"))
        assert r["ok"] and calls == ["avatar_see"]
        st = json.loads(tmp.read_text(encoding="utf-8"))
        assert st["last"] == "avatar_see" and st["tries"] == 1
        assert not T.due()
    finally:
        T.tool_bus.call = old_call
        T.TRIAL_STATE = old
        tmp.unlink(missing_ok=True)


def test_maybe_try():
    old = T.TRIAL_STATE
    T.TRIAL_STATE = Path("test_self_trials2.json")
    calls = []

    async def fake(name, args):
        calls.append(name)
        return {"ok": True}

    old_call = T.tool_bus.call
    T.tool_bus.call = fake
    old_c = T.candidates
    T.candidates = lambda: ["avatar_see", "look_around"]
    try:
        r = asyncio.run(T.maybe_try())
        assert r["ok"] and calls == ["avatar_see"]
        r = asyncio.run(T.maybe_try())
        assert r.get("skipped") == "not due"
    finally:
        T.tool_bus.call = old_call
        T.candidates = old_c
        T.TRIAL_STATE = old
        Path("test_self_trials2.json").unlink(missing_ok=True)


if __name__ == "__main__":
    test_levels()
    test_consent()
    test_maybe_try()
    print("self_trials ok")
