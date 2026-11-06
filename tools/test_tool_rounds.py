"""工具轮数用完之后，不许把 `[工具]{...}` 这行协议原文丢给使用者。

0.3.6 实测踩到：问一句「昆明明天天气」，她连着搜了两轮（轮数上限 2），
第三轮她想 `web_fetch`，被上限挡掉——而当时的代码是 `return cleaned or content`，
`cleaned` 剥完是空串，于是 `content` 原样返回，聊天窗里就出现了一整行
`[工具]{"name":"web_fetch",...}`。使用者回了个「？」，新一轮预算重置，她才真的取到天气。

这里钉住：无论她多想调工具、预算剩多少，返回值里都不许出现 CALL_TAG。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "WiseEntity" / "entity"))

from core import llm_box, tool_bus  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


CALL = '[工具]{"name":"web_fetch","args":{"url":"https://example.com"}}'


def _wire(replies: list[str]) -> dict:
    """把 LLM 换成按剧本回话的假货，工具调用也短路掉，不碰网络。"""
    state = {"n": 0, "calls": 0}

    async def fake_ask(msgs, temperature, max_tokens):
        i = min(state["n"], len(replies) - 1)
        state["n"] += 1
        return replies[i]

    async def fake_call(name, args):
        state["calls"] += 1
        return {"ok": True, "tool": name, "ms": 1, "result": {"ok": True, "title": "Example"}}

    llm_box.S.configured = lambda: (True, "")
    llm_box.build_system = lambda session, query: "sys"
    llm_box._ask = fake_ask
    llm_box.tool_bus.call = fake_call
    return state


def main() -> int:
    # 1) 她每一轮都在要工具，永远不给人话
    state = _wire([CALL])
    out = asyncio.run(llm_box.chat("web:owner", "昆明明天天气"))
    check(tool_bus.CALL_TAG not in out, f"预算用完后没有泄漏协议行（拿到 {out[:60]!r}）")
    check(bool(out.strip()), f"预算用完后仍然给人话（拿到 {out[:60]!r}）")
    check(state["calls"] == 3, f"真跑了 3 轮工具才放弃（实际 {state['calls']} 轮）")

    # 2) 第三轮给了人话：正常返回，不该多跑
    state = _wire([CALL, CALL, "明天 14 到 25 度，晴。"])
    out = asyncio.run(llm_box.chat("web:owner", "昆明明天天气"))
    check(out == "明天 14 到 25 度，晴。", f"拿到人话就收工（实际 {out!r}）")
    check(state["n"] == 3, f"三轮内解决（实际 {state['n']} 轮）")

    # 3) 一开口就是人话：一次到位
    state = _wire(["嗯，我在。"])
    out = asyncio.run(llm_box.chat("web:owner", "嗨"))
    check(out == "嗯，我在。" and state["n"] == 1, f"不需要工具时不调（实际 {out!r}, {state['n']} 轮）")

    print()
    if fails:
        print(f"{len(fails)} 条失败")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
