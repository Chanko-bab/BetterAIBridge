"""能力自画像：第一人称、随耳目/模组/工具变化、不吹牛。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from WiseEntity.entity.core import self_model  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def main() -> int:
    S = self_model.S
    orig = (S.entity_name, self_model.sense.eyes, self_model.sense.ears,
            self_model.sense.watch, self_model.sense.listen_always,
            self_model.modules_box.enabled, self_model.tool_bus.tools)
    try:
        S.entity_name = lambda: "小雨"
        self_model.sense.eyes = lambda: False
        self_model.sense.ears = lambda: False
        self_model.sense.watch = lambda: False
        self_model.sense.listen_always = lambda: False
        self_model.modules_box.enabled = lambda: []
        self_model.tool_bus.tools = lambda: {}
        txt = self_model.fragment()
        check("我此刻的自我认知" in txt, "有自画像标题")
        check("我是「小雨」" in txt, "用第一人称说名字")
        check("没有眼睛，也没有耳朵" in txt, "耳目关闭时照实说")
        check("没有给我任何可调用的工具" in txt, "没工具时照实说")
        check("读不了任意文件" in txt, "边界写清楚")
        check("用户" not in txt and "你的" not in txt, "没有向外的代称")
        check("清单里没有的" in txt, "强调以清单为准")

        self_model.sense.eyes = lambda: True
        self_model.sense.watch = lambda: True
        self_model.modules_box.enabled = lambda: [
            {"id": "m1", "name": "日常事务"},
            {"id": "m2", "name": "B 站桥"},
        ]
        self_model.tool_bus.tools = lambda: {"a": {}, "b": {}}
        txt = self_model.fragment()
        check("一双眼睛" in txt, "有眼睛时写眼睛")
        check("一直看着" in txt, "一直看着时写出来")
        check("日常事务" in txt and "B 站桥" in txt, "列出装着的模组")
        check("系统给了我 2 个可调用的工具" in txt, "工具数量准确")
        check("没有装任何外挂" not in txt, "有模组时不写没装")
    finally:
        (S.entity_name, self_model.sense.eyes, self_model.sense.ears,
         self_model.sense.watch, self_model.sense.listen_always,
         self_model.modules_box.enabled, self_model.tool_bus.tools) = orig
    print("\nPASS" if not fails else f"\n{len(fails)} 条失败")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
