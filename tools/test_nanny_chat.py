# -*- coding: utf-8 -*-
"""保姆本体：开场白、项目快照、会话保留、失败原因。"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "WiseEntity"))

from entity.core import nanny_chat  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


nanny_chat.reset()

# 开场白必须是原话
check("虽然不清楚您是怎么找到这儿的" in nanny_chat.OPENING, "开场白有原话前半")
check("您不妨说说" in nanny_chat.OPENING, "开场白有原话结尾")
check("没有任何写文件" in nanny_chat.SYSTEM, "系统提示写死了只读")

# 快照：项目根、结构、模组、人格、记忆、最近对话
snap = nanny_chat.snapshot()
for word in ("项目快照", "项目结构", "已装模组", "智能体人格", "最近记忆", "最近对话"):
    check(word in snap, f"快照含「{word}」")
check(str(ROOT) in snap, "快照含项目根")

# 开会话
s = nanny_chat.start()
check(s.get("ok") is True, "start ok")
sid = str(s.get("session") or "")
check(len(sid) == 12, "session 是 12 位")
check(s.get("opening") == nanny_chat.OPENING, "首次打开带回开场白")
check(nanny_chat._sessions.get(sid) is not None, "会话存在内存里")

# 空文本
r = asyncio.run(nanny_chat.chat(sid, "  "))
check(r.get("ok") is False and "还没说事" in str(r.get("reply")), "空文本被拒")

# 没配 Key：中文原因
real_cfg = nanny_chat.S.configured
real_ask = nanny_chat.llm_box._ask
try:
    nanny_chat.S.configured = lambda: (False, "还没填 API Key")  # type: ignore[assignment]
    r = asyncio.run(nanny_chat.chat(sid, "我加了哪些模组？"))
    check(r.get("ok") is False, "没配 Key 时不硬答")
    check("API Key" in str(r.get("reply")), "没配 Key 时给 Key 提示")

    # 配了 Key：用假模型回一句，会话继续
    nanny_chat.S.configured = lambda: (True, "")  # type: ignore[assignment]
    seen: list[list[dict]] = []

    async def fake_ask(msgs, **kw):
        seen.append(msgs)
        return "你装了一个日常事务模组。"

    nanny_chat.llm_box._ask = fake_ask  # type: ignore[assignment]
    r = asyncio.run(nanny_chat.chat(sid, "我加了哪些模组？"))
    check(r.get("ok") is True, "配了 Key 能回")
    check("日常事务" in str(r.get("reply")), "回复原样带回")
    check(len(seen) == 1 and seen[0][0]["role"] == "system", "系统提示在最前")
    check(any("虽然不清楚" in str(m.get("content")) for m in seen[0]) is False,
          "系统提示里不重复开场白")
    check(seen[0][-1]["content"] == "我加了哪些模组？", "用户这句在最后")
    check("## 项目快照" in str(seen[0][0]["content"]), "system 带项目快照")

    r2 = asyncio.run(nanny_chat.chat(sid, "下一句怎么回？"))
    check(r2.get("ok") is True, "同一会话能继续")
    check(len(seen) == 2 and len(seen[1]) >= 4, "第二轮带上历史")

    # 落盘：消息和打开时间都在
    raw = json.loads(nanny_chat.PERSIST.read_text(encoding="utf-8"))
    check(str(raw.get("session")) == sid, "会话写进磁盘")
    check(len(raw.get("msgs") or []) >= 4, "消息写进磁盘")
    check(bool(raw.get("opened")), "打开时间写进磁盘")
    check(nanny_chat.OPENS.exists(), "打开日志文件存在")
finally:
    nanny_chat.S.configured = real_cfg  # type: ignore[assignment]
    nanny_chat.llm_box._ask = real_ask  # type: ignore[assignment]

# 关闭后再说：保留上次会话，不再新开
nanny_chat.close(sid)
check(sid not in nanny_chat._sessions, "close 只移除内存")
try:
    nanny_chat.S.configured = lambda: (True, "")  # type: ignore[assignment]

    async def fake_ask2(msgs, **kw):
        return "在。"

    nanny_chat.llm_box._ask = fake_ask2  # type: ignore[assignment]
    r = asyncio.run(nanny_chat.chat(sid, "还在吗"))
    check(r.get("ok") is True and r.get("session") == sid, "旧会话会接着用")
finally:
    nanny_chat.S.configured = real_cfg  # type: ignore[assignment]
    nanny_chat.llm_box._ask = real_ask  # type: ignore[assignment]

# 重新打开：带回上次消息与时间，不再重复开场白
nanny_chat.close(sid)
s2 = nanny_chat.start()
check(str(s2.get("session")) == sid, "重新打开是同一会话")
check(len(s2.get("msgs") or []) >= 4, "重新打开带回上次消息")
check(s2.get("opening") == "", "有历史时不再重复开场白")
check(all(m.get("ts") for m in (s2.get("msgs") or [])), "每条消息带时间")

# 最多 8 个
for _ in range(12):
    nanny_chat.start()
check(len(nanny_chat._sessions) <= nanny_chat.MAX_SESSIONS, "会话数不超过上限")

nanny_chat.reset()

print()
if fails:
    print(f"FAILED {len(fails)}")
    sys.exit(1)
print("PASS")
