# -*- coding: utf-8 -*-
"""保姆日志：落盘、截尾、坏行跳过、面板聚合。"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "WiseEntity"))

from entity.core import nanny  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


tmp = Path(tempfile.mkdtemp(prefix="bab-nanny-"))
nanny.LOG_PATH = tmp / "state" / "nanny_log.jsonl"
nanny.STATE_PATH = tmp / "state"
nanny.LOG_MAX_BYTES = 400_000

# 空文件
check(nanny.log_tail() == [], "没有日志时返回空列表")
check(isinstance(nanny.panel(10), dict), "空日志也能给面板")

nanny.log_event("notice", "第一条提醒")
nanny.log_event("degraded", "模组没了")
nanny.log_event("note", "随手记")
tail = nanny.log_tail(10)
check(len(tail) == 3, "三条都读回来")
check(tail[0]["kind"] == "notice" and tail[0]["text"] == "第一条提醒", "第一条内容对")
check(all(isinstance(r.get("ts"), (int, float)) for r in tail), "每条都有 ts")

check(len(nanny.log_tail(2)) == 2, "limit 生效")
check(nanny.log_tail(2)[-1]["text"] == "随手记", "limit 取的是最后两条")

# 坏行
with nanny.LOG_PATH.open("a", encoding="utf-8") as f:
    f.write("这不是 JSON\n")
    f.write(json.dumps({"ts": 0, "kind": "note", "text": "零时间"}) + "\n")
rows = nanny.log_tail(20)
check(len(rows) == 4, "坏行跳过、后面正常行仍读")
check(rows[-1]["text"] == "零时间", "坏行之后的记录在")

panel = nanny.panel(10)
check(len(panel.get("log") or []) == 4, "panel 给最近的四条")
panel2 = nanny.panel(2)["log"]
check(len(panel2) <= 2 and panel2[-1]["text"] == "零时间", "panel limit 生效（坏行占位会少一条）")
check("checks" in panel and "modules" in panel, "panel 带看门状态")

# 截断：塞超过 400KB，尾部保留、早期记录被丢掉
big = "x" * 500
for i in range(1200):
    nanny.log_event("note", f"{i}-{big}")
rows = nanny.log_tail(1000)
check(len(rows) < 1200, f"超限后早期记录被丢（剩余 {len(rows)}）")
check(rows[-1]["text"].startswith("1199-"), "保留的是最后一条")
check(nanny.LOG_PATH.stat().st_size < nanny.LOG_MAX_BYTES + 4000,
      f"日志体积受控（{nanny.LOG_PATH.stat().st_size}）")
check(not rows[0]["text"].startswith("0-"), "最早那条已经不在了")

print()
if fails:
    print(f"FAIL {len(fails)}")
    sys.exit(1)
print("PASS")
