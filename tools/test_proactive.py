"""她会主动开口吗？——保姆（nanny/proactive）这条线的回归检查。

三个点各钉一条：
1. 在线时她说一句，聊天里就这一句，保姆栏不重复提醒；
2. 不在线（关窗=忙碌）时她也能找你，但门槛更高，保姆栏说「对方主动找您」；
3. 「选择沉默」那条随机分支不能炸（曾经少了 import random）。

不连内核、不发网络请求：驱动、模型、写盘全用假的。
    .venv\\Scripts\\python.exe tools\\test_proactive.py
退出码 0 = 全过；1 = 有断言失败。
"""

from __future__ import annotations

import asyncio
import random
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from WiseEntity.entity.core import chat_core, drives, llm_box, presence, proactive  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def run_case(*, online: bool, urgency: float, silence: float = 1.0,
             last_ago: float = 10 * 3600, trigger: str = "", idle_ago: float = 0.0) -> dict:
    """跑一轮 maybe_send，返回 {"res":..., "notices": [...], "said": [...]}"""
    said: list[str] = []
    notices: list[str] = []
    moved: list[str] = []
    prompts: list[str] = []

    orig = {
        "is_online": presence.is_online,
        "poll": drives.poll,
        "fired": drives.mark_fired,
        "chat": llm_box.chat,
        "notice": chat_core.push_notice,
        "append": chat_core.append_assistant,
        "rand": random.random,
        "state": proactive.STATE_PATH,
        "gates": proactive.emotion_core.gates,
        "state_of": proactive.brain_box.state,
    }
    tmp = tempfile.mkdtemp(prefix="bab_pro_")
    try:
        presence.is_online = lambda: online
        drives.poll = lambda: {"active": [{"name": "reach", "urgency": urgency}]}
        drives.mark_fired = lambda name: moved.append(name)
        proactive.emotion_core.gates = lambda: {"hide": 1.0}
        proactive.brain_box.state = lambda: {"mood_line": "平平的"}

        async def fake_chat(session, prompt, hist, **kw):
            prompts.append(str(prompt))
            return "在呢，刚想跟你说句话。" if silence >= 1.0 else ""

        llm_box.chat = fake_chat
        chat_core.push_notice = lambda session, text: notices.append(text)
        chat_core.append_assistant = lambda session, text, **kw: said.append(text)
        random.random = lambda: silence
        proactive.STATE_PATH = Path(tmp) / "proactive.json"
        proactive.STATE_PATH.write_text(
            '{"last_ts": %f, "sent": []}' % (time.time() - last_ago), encoding="utf-8")

        orig_idle = proactive._last_user_ts
        proactive._last_user_ts = lambda: (time.time() - idle_ago) if idle_ago else 0.0
        try:
            res = asyncio.run(proactive.maybe_send(trigger=trigger))
        finally:
            proactive._last_user_ts = orig_idle
        return {"res": res, "notices": notices, "said": said, "moved": moved,
                "prompts": prompts}
    finally:
        presence.is_online = orig["is_online"]
        drives.poll = orig["poll"]
        drives.mark_fired = orig["fired"]
        llm_box.chat = orig["chat"]
        chat_core.push_notice = orig["notice"]
        chat_core.append_assistant = orig["append"]
        random.random = orig["rand"]
        proactive.STATE_PATH = orig["state"]
        proactive.emotion_core.gates = orig["gates"]
        proactive.brain_box.state = orig["state_of"]


def main() -> int:
    # --- 1. 在线 + 驱动够急 → 说话，聊天里就多这一句，保姆栏不再重复提醒
    out = run_case(online=True, urgency=0.8)
    check(out["res"].get("sent") is True, f"在线时她开口了（{out['res']}）")
    check(out["notices"] == [],
          f"在线时保姆栏不重复提醒（实际 {out['notices']}）")
    check(bool(out["said"]), f"她那句话进了聊天记录（{out['said']}）")
    check(out["moved"] == ["reach"],
          f"说完这句，那股劲按驱动冷却退烧（实际 {out['moved']}）")

    # --- 2. 不在线（关窗=忙碌）+ 够急 → 也能找，保姆栏说「对方主动找您」
    out = run_case(online=False, urgency=0.8)
    check(out["res"].get("sent") is True, f"不在线时她也能找你（{out['res']}）")
    check(out["notices"] == ["对方主动找您"],
          f"忙碌时保姆栏提示「对方主动找您」（实际 {out['notices']}）")

    # --- 3. 不在线 + 只是有点想 → 别打扰
    out = run_case(online=False, urgency=0.55)
    check(out["res"].get("sent") is False, f"你不在、她又没那么急时不出声（{out['res']}）")
    check(not out["notices"], f"不出声就不提示（实际 {out['notices']}）")

    # --- 4. 沉默分支不炸（曾经少 import random）
    out = run_case(online=True, urgency=0.6, silence=0.0)
    check(out["res"].get("sent") is False and out["res"].get("silent") is True,
          f"她想说但选择沉默（{out['res']}）")
    check("对方选择沉默" in " ".join(out["notices"]),
          f"沉默时保姆说了一句（实际 {out['notices']}）")
    check(out["moved"] == [],
          f"沉默不消耗那股劲（实际 {out['moved']}）")

    # --- 5. 在线很久没说话 → 用第一人称关系句主动搭话
    out = run_case(online=True, urgency=0.2, last_ago=30 * 60,
                   trigger="idle", idle_ago=30 * 60)
    check(out["res"].get("sent") is True, f"在线久了会主动搭话（{out['res']}）")
    check("一直在线" in out["prompts"][0], "空闲触发的提示词写的是「一直在线」")
    check("我的朋友" in out["prompts"][0], "提示词用第一人称关系词，不写「用户」")
    check("你的" not in out["prompts"][0], "提示词里没有向外的「你的」")

    # --- 6. 忙碌切回在线 → 可以说一句
    out = run_case(online=True, urgency=0.2, last_ago=30 * 60, trigger="online")
    check(out["res"].get("sent") is True, f"切回在线时她可以开口（{out['res']}）")
    check("改回「在线」" in out["prompts"][0], "在线触发的提示词写的是状态切换")

    # --- 7. 不再有每日上限：情绪不该被日历管
    check(not hasattr(proactive, "MAX_PER_DAY") and not hasattr(proactive, "AWAY_MAX_PER_DAY"),
          "日限常量已经删掉（只留驱动冷却 + 最短间隔）")

    print(f"\n{len(fails)} 条失败" if fails else "\nPASS")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
