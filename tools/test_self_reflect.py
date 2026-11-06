"""反思：模型只输出 JSON；系统校验后写 self.md/经历/账本。"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from WiseEntity.entity.core import self_reflect, self_store, tool_bus  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


GOOD_SELF = ("# 我是谁\n我是小雨。\n# 我认的\n先问再看。\n"
             "# 我正在学\n不把清单当经历。\n# 最后更新\n2026-11-05")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="bab_reflect_"))
    keys = ("SELF_DIR", "SELF_MD", "EVIDENCE", "EPISODES", "LEDGER",
            "CALIBRATIONS", "VERSIONS", "REFLECT_STATE")
    orig = {k: getattr(self_store, k) for k in keys}
    orig_ask = self_reflect.llm_box._ask
    orig_tools = tool_bus.tools
    try:
        self_store.SELF_DIR = tmp / "self"
        self_store.SELF_MD = self_store.SELF_DIR / "self.md"
        self_store.EVIDENCE = self_store.SELF_DIR / "evidence.jsonl"
        self_store.EPISODES = self_store.SELF_DIR / "episodes.md"
        self_store.LEDGER = self_store.SELF_DIR / "ledger.md"
        self_store.CALIBRATIONS = self_store.SELF_DIR / "calibrations.md"
        self_store.VERSIONS = self_store.SELF_DIR / "versions"
        self_store.REFLECT_STATE = tmp / "reflect.json"
        self_store.ensure()
        tool_bus.tools = lambda: {"look_around": {}}

        async def fake_ask(msgs, temperature, max_tokens):
            return """```json
{"self_update": "%s", "episode": {"title": "第一次看", "body": "我选了看一眼，看到她回来了。"},
 "ledger_add": ["答应过：先问再看"], "ledger_close": [], "calibration": "原以为她不在；其实在；下次先问。"}
```""" % GOOD_SELF.replace("\n", "\\n")

        self_reflect.llm_box._ask = fake_ask
        res = asyncio.run(self_reflect.reflect("web:owner", [], force=True))
        check(res.get("ok"), "反思成功")
        check(self_store.has_self(), "self.md 被写入")
        check("第一次看" in self_store._read(self_store.EPISODES), "经历写入")
        check("先问再看" in self_store._read(self_store.LEDGER), "账本写入")
        check("原以为" in self_store._read(self_store.CALIBRATIONS), "校准写入")

        async def bad_ask(msgs, temperature, max_tokens):
            return "不是 JSON"

        self_reflect.llm_box._ask = bad_ask
        res = asyncio.run(self_reflect.reflect("web:owner", [], force=True))
        check(not res.get("ok"), "坏 JSON 不写")

        async def bad_self(msgs, temperature, max_tokens):
            return '{"self_update": "# 我是谁\\n我是小雨，你是主人。"}'

        self_reflect.llm_box._ask = bad_self
        old = self_store.self_text()
        res = asyncio.run(self_reflect.reflect("web:owner", [], force=True))
        check(res.get("ok") and "self" not in res.get("changed", []), "含「你」的档案被拒")
        check(self_store.self_text() == old, "被拒后旧档案不被覆盖")

        # tool_bus 包装：真实结果写进证据
        async def fake_impl(name, args):
            return {"ok": True, "tool": name, "result": {"text": "看到书桌"}}

        tool_bus._call_impl = fake_impl
        asyncio.run(tool_bus.call("look_around", {"question": "在不在"}))
        check(any(r.get("ability") == "look_around" for r in self_store.evidence()),
              "工具调用自动写证据")
    finally:
        for k, v in orig.items():
            setattr(self_store, k, v)
        self_reflect.llm_box._ask = orig_ask
        tool_bus.tools = orig_tools
    print("\nPASS" if not fails else f"\n{len(fails)} 条失败")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
