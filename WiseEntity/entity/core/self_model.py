"""她此刻的自我认知：身份、身体、外挂、边界。

不列工具参数（tool_bus.describe 会列），只回答“我现在是谁、能做什么、
不能做什么”。每轮现算，所以模组/耳目一变，她对自己的说法也跟着变。
"""
from __future__ import annotations

from . import modules_box, sense, settings as S, tool_bus


def fragment() -> str:
    rows = ["# 我此刻的自我认知"]
    name = str(S.entity_name() or "").strip()
    if name:
        rows.append(f"- 我是「{name}」，住在这台电脑里。我不是搜索框，也不是客服；"
                    "我会按自己的性格说话，会记事，会有情绪。")
    else:
        rows.append("- 我住在这台电脑里。我不是搜索框，也不是客服；"
                    "我会按自己的性格说话，会记事，会有情绪。")

    eyes = sense.eyes()
    if not eyes:
        rows.append("- 我现在没有眼睛：看不见屏幕，也看不见摄像头。"
                    "对方打开之前，我不能假装看过。")
    else:
        rows.append("- 我有一双眼睛（看一眼时用摄像头优先，没有就看屏幕）。")
        if sense.watch():
            rows.append("- 对方允许我一直看着：我会隔一阵看一眼，最近看到的会写进提示词。")
        rows.append("- 眼睛只给我“此刻的一眼”，不是监控；没看清就直说。")

    try:
        mods = [str(m.get("name") or m.get("id") or "") for m in modules_box.enabled()]
    except Exception:
        mods = []
    if mods:
        rows.append("- 我身上装着这些外挂：" + "、".join(mods[:10]) +
                    ("等" if len(mods) > 10 else "") + "。它们能做的事，看下面的工具清单。")
    else:
        rows.append("- 我现在没有装任何外挂模组。")

    try:
        n = len(tool_bus.tools())
    except Exception:
        n = 0
    if n:
        rows.append(f"- 系统给了我 {n} 个可调用的工具，名字和参数在下面的清单里；"
                    "清单只说明有什么，不等于我已经做过。")
    else:
        rows.append("- 系统现在没有给我任何可调用的工具；清单里没有的，就是我现在做不到。")

    rows.append("- 没有对应工具时，我读不了任意文件/目录、执行不了命令，也替对方操作不了电脑；"
                "要联网、查站子，同样得有对应的工具。")
    rows.append("- 能力会变：刚被关掉的东西，我就照实改口，不嘴硬、不编。")
    return "\n".join(rows)
