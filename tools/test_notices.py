# -*- coding: utf-8 -*-
"""保姆提醒能不能落盘：内核 chat_core.push_notice / notices 走一遍真的写读。

0.3.7 的 bug：chat_core 里用了 json 却没 import，push_notice 抛 NameError 被吞、
notices 读回来永远是空的。这个测试用内核自己的解释器跑（GUI 的 venv 装不下 fastapi）。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTITY = ROOT / "WiseEntity" / "entity"


def entity_python() -> Path | None:
    for rel in ("Scripts/python.exe", "bin/python"):
        p = ENTITY / ".venv" / rel
        if p.exists():
            return p
    return None


def main() -> int:
    fails: list[str] = []

    def check(ok: bool, msg: str) -> None:
        print(("ok   " if ok else "FAIL ") + msg)
        if not ok:
            fails.append(msg)

    src = (ENTITY / "core" / "chat_core.py").read_text(encoding="utf-8-sig")
    check("\nimport json" in "\n" + src, "chat_core.py 顶部 import 了 json")

    py = entity_python()
    if py is None:
        print("skip 内核：没有 WiseEntity/entity/.venv（安装副本不发依赖），只查源码")
        print(f"\n{len(fails)} 条失败" if fails else "\nPASS")
        return 1 if fails else 0

    with tempfile.TemporaryDirectory(prefix="bab-notice-") as tmp:
        script = f'''
import json, sys
sys.path.insert(0, r"{ENTITY}")
from core import chat_core
from pathlib import Path
chat_core.NOTICE_PATH = Path(r"{tmp}") / "notices.jsonl"
row = chat_core.push_notice("web:owner", "保姆程序：对方在找您")
rows = chat_core.notices("web:owner", 0.0)
print(json.dumps({{"row": row, "rows": rows}}, ensure_ascii=False))
'''
        proc = subprocess.run([str(py), "-c", script], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            check(False, f"调内核写提醒失败：{(proc.stderr or '').strip()[-400:]}")
        else:
            out = json.loads(proc.stdout.strip().splitlines()[-1])
            rows = out.get("rows") or []
            check(len(rows) == 1, f"push_notice 真写进文件、notices 读得回来（实际 {len(rows)} 条）")
            if rows:
                check(rows[0].get("text", "").endswith("对方在找您"),
                      f"读回来的正文对（实际 {rows[0].get('text')!r}）")
                check(float(rows[0].get("ts") or 0) > 0, "带真实的 ts")

        script2 = f'''
import json, sys
sys.path.insert(0, r"{ENTITY}")
from core import chat_core as cc

long_text = "〖抬了下眼皮〗您这段时间到底在忙些什么呢，我瞧着您好像一直没停下来过。"
parts = cc.split_reply(long_text, max_len=18, max_parts=4)
print(json.dumps({{
    "act_match": bool(cc._ACT_RE.fullmatch("〖抬了下眼皮〗")),
    "paren_match": bool(cc._ACT_RE.fullmatch("（顿了顿）")),
    "kept": cc.limit_actions(["〖甲〗一", "〖乙〗二", "〖丙〗三"]),
    "parts": parts,
}}, ensure_ascii=False))
'''
        proc2 = subprocess.run([str(py), "-c", script2], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
        if proc2.returncode != 0:
            check(False, f"调内核分条失败：{(proc2.stderr or '').strip()[-400:]}")
        else:
            out2 = json.loads(proc2.stdout.strip().splitlines()[-1])
            check(out2.get("act_match") is True, "内核只把〖…〗当动作")
            check(out2.get("paren_match") is False, "（）在内核眼里不是动作")
            kept = out2.get("kept") or []
            check(sum(1 for p in kept for _ in [0] if "〖" in p) <= 1,
                  f"多条里最多留一处动作（实际 {kept}）")
            parts = out2.get("parts") or []
            check(len(parts) > 1, f"长句会被拆成几条（实际 {len(parts)}）")
            broken = [p for p in parts if p.count("〖") != p.count("〗")]
            check(not broken, f"没有把动作劈成两半（实际 {parts}）")

        script3 = f'''
import json, sys
sys.path.insert(0, r"{ENTITY}")
from core import bridge, chat_core

seen = []
chat_core.push_notice = lambda session, text, kind="nanny": seen.append((kind, text)) or {{"ts": 1}}
out = bridge._notice_push("m", "该喝水了", chat=True)
bad = None
try:
    bridge._notice_push("m", "   ")
except Exception as exc:  # noqa: BLE001
    bad = getattr(exc, "status_code", None) or type(exc).__name__
print(json.dumps({{"out": out, "seen": seen, "bad": bad}}, ensure_ascii=False))
'''
        proc3 = subprocess.run([str(py), "-c", script3], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
        if proc3.returncode != 0:
            check(False, f"调内核 notice.push 失败：{(proc3.stderr or '').strip()[-400:]}")
        else:
            out3 = json.loads(proc3.stdout.strip().splitlines()[-1])
            seen3 = out3.get("seen") or []
            kinds = [k for k, _t in seen3]
            check(kinds == ["nanny", "chat"], f"notice.push(chat=True) 应推两条、顺序 nanny->chat（实际 {kinds}）")
            check(all(str(tx).strip() for _k, tx in seen3), "两条都不能是空话")
            check((out3.get("out") or {}).get("pushed") is True, "返回里要说明推成功了")
            check(out3.get("bad") == 400, f"空 text 应 400（实际 {out3.get('bad')}）")

    # chat.say：她说一句真话，而且以「她的发言」进会话
    script4 = f'''
import asyncio, json, sys
sys.path.insert(0, r"{ENTITY}")
from core import bridge, chat_core, llm_box

async def fake_chat(session, query, history=None):
    return "到点了，喝口水吧。"

llm_box.chat = fake_chat
chat_core._sessions = {{}}
out = asyncio.run(bridge._chat_say("routine", "到喝水的时间了"))
turns = (chat_core._sessions.get("web:owner") or [])
bad = None
try:
    asyncio.run(bridge._chat_say("routine", "  "))
except Exception as exc:  # noqa: BLE001
    bad = getattr(exc, "status_code", None) or type(exc).__name__
print(json.dumps({{"out": out, "turns": turns, "bad": bad}}, ensure_ascii=False))
'''
    proc4 = subprocess.run([str(py), "-c", script4], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    if proc4.returncode != 0:
        check(False, f"调内核 chat.say 失败：{(proc4.stderr or '').strip()[-400:]}")
    else:
        out4 = json.loads(proc4.stdout.strip().splitlines()[-1])
        said = (out4.get("out") or {}).get("text") or ""
        turns = out4.get("turns") or []
        check(said.startswith("到点了"), f"chat.say 用模型写的那句（实际 {said!r}）")
        check(bool(turns) and turns[-1].get("role") == "assistant",
              f"这句要作为她的发言进会话（实际 {turns}）")
        check(turns[-1].get("content") == said, "会话里存的就是这句")
        check(out4.get("bad") == 400, f"空 hint 应 400（实际 {out4.get('bad')}）")

    print(f"\n{len(fails)} 条失败" if fails else "\nPASS")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
