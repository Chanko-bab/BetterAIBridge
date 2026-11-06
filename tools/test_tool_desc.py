# -*- coding: utf-8 -*-
"""工具说明：结构化 args 渲染成中文，不再把 dict repr 塞进提示词。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "WiseEntity"))

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def setup() -> None:
    from entity.core import tool_bus

    tool_bus._cache["at"] = time.time() + 3600
    tool_bus._cache["tools"] = {
        "web_search": {
            "module_name": "联网",
            "hint": "搜网页",
            "args": {"query": {"type": "string", "required": True, "description": "搜什么"}},
        },
        "m_demo": {
            "module_name": "M",
            "hint": "演示",
            "args": {
                "limit": {"type": "integer", "required": False, "description": "条数", "default": 5},
                "flag": {"type": "boolean", "required": False, "description": "开关", "default": False},
                "opts": {"type": "object", "required": False, "description": "选项", "default": {"a": 1}},
            },
        },
        "legacy": {
            "module_name": "旧模组",
            "hint": "",
            "sample": {"q": "x"},
            "args": {},
        },
    }


def main() -> int:
    from entity.core import tool_bus

    setup()
    text = tool_bus.describe()
    check("{'type'" not in text and '{"type"' not in text, "提示词里没有 dict repr")
    check("query（文字，必填）：搜什么" in text, "string + 必填 渲染成中文")
    check("参数：query" in text, "整段参数带「参数：」前缀")
    check("limit（整数，可选，默认 5）：条数" in text, "整数 + 默认值")
    check("flag（开关，可选，默认 False）：开关" in text, "布尔默认值不会被当成空")
    check('opts（对象，可选，默认 {"a": 1}）：选项' in text, "对象默认值用 JSON")
    check("参数示例" in text, "没有 args 时仍保留参数示例兜底")

    one = tool_bus._arg_text(
        {"type": "string", "required": False, "description": "很长的说明" * 40}
    )
    check(len(one) <= 120, f"单个参数截到 120 字以内（实际 {len(one)}）")
    check(one.endswith("…"), "单个参数截断有省略号")

    line = tool_bus._arg_line(
        {f"k{i}": {"type": "string", "required": True, "description": "说明" * 30} for i in range(8)}
    )
    check(len(line) <= 300, f"整段参数截到 300 字以内（实际 {len(line)}）")
    check(line.endswith("…"), "整段截断有省略号")

    legacy = tool_bus._arg_line({"q": "可选：你想找什么"})
    check(legacy == "参数：q（可选：你想找什么）", "非 dict 的老写法原样保留")

    print()
    if fails:
        print(f"FAILED {len(fails)}")
        return 1
    print("PASS 工具说明")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
