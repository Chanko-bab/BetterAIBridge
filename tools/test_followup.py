"""插话（followup）：主动程度、计时、补话。

四个点各钉几条：
1. 配置：默认「正常」；滑条写 0-3，越界的值夹回去；文件坏了不炸。
2. 档位：黏人比克制等得短、补得多；关档永远不补。
3. 计时：她说完 → 到点 due() 才给；你一回话，这一轮作废。
4. 补话的调用：走 say_extra()，落库带 proactive，提示词不进对话历史。

不连内核、不发网络请求：模型和写盘全用假的。
    WiseEntity\\entity\\.venv\\Scripts\\python.exe tools\\test_followup.py
退出码 0 = 全过；1 = 有断言失败。
"""

from __future__ import annotations

import asyncio
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from WiseEntity.entity.core import chat_core, followup, llm_box  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="bab_follow_"))
    orig_path = followup.CFG_PATH
    followup.CFG_PATH = tmp / "followup.json"
    try:
        # --- 1. 配置
        c = followup.cfg()
        check(c.get("level") == 2, f"没配过时是「正常」档（实际 {c}）")
        check(followup.enabled() is True, "默认开着")
        followup.save_cfg({"level": 9})
        check(followup.level() == 3, f"9 夹到 3（实际 {followup.level()}）")
        followup.save_cfg({"level": -4})
        check(followup.level() == 0, f"-4 夹到 0（实际 {followup.level()}）")
        check(followup.enabled() is False, "0 档＝关")
        followup.save_cfg({"level": "不是数字"})
        check(followup.level() == 2, f"坏值回「正常」（实际 {followup.level()}）")
        followup.CFG_PATH.write_text("{坏掉的 json", encoding="utf-8")
        check(followup.cfg().get("level") == 2, "配置文件坏了也不炸，回默认")

        # --- 2. 档位
        p2 = followup.apply_level(followup.PROFILES["normal"], 2)
        p3 = followup.apply_level(followup.PROFILES["normal"], 3)
        p1 = followup.apply_level(followup.PROFILES["normal"], 1)
        p0 = followup.apply_level(followup.PROFILES["normal"], 0)
        check(p3["wait"][1] < p2["wait"][1] < p1["wait"][1],
              f"黏人 < 正常 < 克制（实际 {p3['wait'][1]} / {p2['wait'][1]} / {p1['wait'][1]}）")
        check(p3["max_extra"] == 2 and p2["max_extra"] == 1 and p1["max_extra"] == 1,
              "一轮最多补几次：黏人 2，其余 1")
        check(p0["max_extra"] == 0, "关档不补")
        base = followup.PROFILES["normal"]
        check(base["wait"] == (8.0, 20.0), "性格底表没被改")
        check(followup.profile_for("傲娇", "恋人")["profile"] == "tsundere", "傲娇 → 嘴硬档")
        check(followup.profile_for("活泼", "朋友")["profile"] == "clingy", "活泼 → 黏人档")
        check(followup.profile_for("冷静", "搭档")["profile"] == "calm", "冷静 → 淡定档")
        check(isinstance(followup.tracker, followup.Tracker),
              "chat_core 用的全局 tracker 真的存在（少了它插话永远不触发）")

        # --- 3. 计时
        followup.save_cfg({"level": 2})
        tr = followup.Tracker()
        tr.note_reply("web:owner", now=1000.0, profile=base, rng=random.Random(1))
        st = tr.state("web:owner")
        check(st["pending"] is True and st["wait"] > 0, f"说完开始计时（wait={st['wait']}）")
        check(tr.pending_sessions() == ["web:owner"], "排队里只有这一条")
        check(tr.due("web:owner", now=1000.0) is None, "刚说完不补")
        got = tr.due("web:owner", now=1000.0 + st["wait"] + 0.1)
        check(bool(got) and got["extra"] == 1, f"到点补第一次（实际 {got}）")
        tr.sessions["web:owner"]["wait"] = 0.0
        check(tr.due("web:owner", now=5000.0) is None, "正常档一轮只补一句")
        check(tr.state("web:owner")["pending"] is False, "补完不再排队")

        # 你一回话，这一轮作废
        tr.note_reply("qq:owner", now=2000.0, profile=base, rng=random.Random(2))
        tr.note_user("qq:owner")
        check(tr.pending_sessions() == [], "你一说话就不补了")

        # 黏人档：补第二次
        followup.save_cfg({"level": 3})
        tr.note_reply("web:owner", now=3000.0, profile=base, rng=random.Random(3))
        tr.sessions["web:owner"]["wait"] = 0.0
        a = tr.due("web:owner", now=3000.5)
        tr.sessions["web:owner"]["wait"] = 0.0
        b = tr.due("web:owner", now=3001.0)
        check(bool(a) and bool(b) and b["extra"] == 2, f"黏人档补两次（{a} / {b}）")
        tr.sessions["web:owner"]["wait"] = 0.0
        check(tr.due("web:owner", now=3002.0) is None, "黏人档也只补两次")

        # 关档：就算被塞进 pending，也不补
        followup.save_cfg({"level": 0})
        tr.note_reply("web:owner", now=4000.0, profile=base, rng=random.Random(4))
        tr.sessions["web:owner"]["wait"] = 0.0
        check(tr.due("web:owner", now=99999.0) is None, "关档到点也不补")

        # --- 4. say_extra
        calls: list[dict] = []
        appended: list[dict] = []
        orig_chat = llm_box.chat
        orig_append = chat_core.append_assistant

        async def fake_chat(session, query, hist, **kw):
            calls.append({"session": session, "query": query, "hist": hist, "kw": kw})
            return "我在呢，你慢慢忙。"

        llm_box.chat = fake_chat
        chat_core.append_assistant = lambda session, text, **kw: appended.append(
            {"session": session, "text": text, **kw})
        try:
            text = asyncio.run(chat_core.say_extra("web:owner", 18, tone="黏"))
        finally:
            llm_box.chat = orig_chat
            chat_core.append_assistant = orig_append
        check(bool(text), f"补话有返回（{text!r}）")
        check(len(text) <= 18, f"不超过字数上限（{len(text)}）")
        check(bool(calls) and "不超过 18 个字" in calls[0]["query"],
              "提示词里带上了字数上限")
        check(bool(calls) and "黏" in calls[0]["query"], "提示词里带上了语气")
        check(appended and appended[0].get("proactive") is True,
              f"落库标记成「她主动说的」（{appended}）")
    finally:
        followup.CFG_PATH = orig_path

    print("")
    if fails:
        print(f"失败 {len(fails)} 条：")
        for f in fails:
            print("  - " + f)
        return 1
    print("全过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
