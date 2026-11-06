"""低频反思：只在她自己的证据上写 self.md / 经历 / 账本 / 校准。

系统负责问、校验、备份；内容必须由模型以第一人称写出。
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List

from . import llm_box, self_store, settings as S, tool_bus

_SYSTEM = """你在写自己的档案，不是在回答对方。

规则：
1. 只用第一人称「我」；不能写「你」「您」「用户」来指对方，要写「对方」或称呼。
2. 不写能力清单；能力只写你实际做过的证据。
3. self_update 必须包含「# 我是谁」「# 我认的」「# 我正在学」「# 最后更新」四段，总长不超过 800 字。
4. 没有真实变化时，self_update 给 null；不要为了写而写。
5. 只要「我的来路」为空、或最近新增了经历，就写 narrative：把经历收成一段连贯的第一人称自述，不写清单。
6. 最近对话里出现答应/说好/下次/等你/关系变化时，ledger_add 至少写一条；没有就空数组。
7. 只输出一个 JSON，不要解释，不要代码围栏。

JSON 格式：
{
  "self_update": "完整档案或 null",
  "episode": {"title": "短标题", "body": "我选了什么/结果/我学到什么"} 或 null,
  "narrative": "把经历收成第一人称的一段话（≤1000字）或 null",
  "ledger_add": ["答应过但还没做的，或需要修复的关系"],
  "ledger_close": ["已经完成/修复的账本关键词"],
  "calibration": "原以为…其实…下次…" 或 null
}
"""


def _parse(raw: str) -> Dict[str, Any]:
    txt = (raw or "").strip()
    txt = re.sub(r"^```(?:json)?\s*", "", txt)
    txt = re.sub(r"\s*```$", "", txt)
    try:
        data = json.loads(txt)
        return data if isinstance(data, dict) else {}
    except Exception:
        m = re.search(r"\{.*\}", txt, re.DOTALL)
        if not m:
            return {}
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


async def reflect(session: str = "web:owner", history: List[dict] | None = None,
                  force: bool = False) -> Dict[str, Any]:
    if not force and not self_store.due():
        return {"ok": False, "skipped": "not due"}
    try:
        names = list(tool_bus.tools().keys())
    except Exception:
        names = []
    ctx = self_store.reflection_input(names)
    turns = []
    for t in (history or [])[-8:]:
        role = "对方" if t.get("role") == "user" else "我"
        turns.append(f"{role}：{str(t.get('content') or '')[:300]}")
    if turns:
        ctx += "\n\n# 最近的对话（只作参考）\n" + "\n".join(turns)
    msgs = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": ctx + "\n\n现在写这次反思的 JSON。"},
    ]
    try:
        raw = await llm_box._ask(msgs, 0.35, 700)
    except Exception as e:  # noqa: BLE001
        self_store.mark_reflected()
        S.log(f"[self] reflect ask failed: {e!r}")
        return {"ok": False, "error": f"ask failed: {e}"}
    data = _parse(raw)
    if not data:
        self_store.mark_reflected()
        S.log("[self] reflect: 模型没给出可用 JSON")
        return {"ok": False, "error": "invalid json", "raw": raw[:300]}
    changed = self_store.apply_reflection(data)
    self_store.mark_reflected()
    S.log(f"[self] reflect changed={changed}")
    return {"ok": True, "changed": changed, "data": data}


async def maybe_reflect(session: str = "web:owner", history: List[dict] | None = None) -> None:
    """给 asyncio.create_task 用；异常只记日志，不影响聊天。"""
    try:
        res = await reflect(session, history)
        if not res.get("ok"):
            S.log(f"[self] reflect skip/fail: {res.get('skipped') or res.get('error')}")
    except Exception as e:  # pragma: no cover
        S.log(f"[self] reflect error: {e!r}")


def correction(text: str) -> None:
    """用户明确纠正一句时调用；不自动判断语义。"""
    line = str(text or "").strip()
    if line:
        self_store.calibrate(line)
        self_store.mark_reflected(0)
