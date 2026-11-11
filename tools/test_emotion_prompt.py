# -*- coding: utf-8 -*-
"""情绪提示：三段上升、三段下降、最高档 15 分钟提醒；理智同档不重复；驱动 ≥0.6 只一条。"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "WiseEntity" / "entity"))

from core import drives as D  # noqa: E402
from core import emotion_core as E  # noqa: E402

FAILS: list[str] = []
OKS = 0


def check(ok: bool, msg: str) -> None:
    global OKS
    if ok:
        OKS += 1
    else:
        FAILS.append(msg)


def _state(**vals) -> dict:
    st = E._blank()
    st["updated_at"] = time.time()
    for k, v in vals.items():
        st["values"][k] = float(v)
    return st


def _write(path: Path, **vals) -> None:
    path.write_text(json.dumps(_state(**vals), ensure_ascii=False), encoding="utf-8")


def _write_keep(path: Path, **vals) -> None:
    st = json.loads(path.read_text(encoding="utf-8"))
    st["updated_at"] = time.time()
    for k, v in vals.items():
        st["values"][k] = float(v)
    path.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "state.json"
        old = E.STATE_PATH
        E.STATE_PATH = path
        try:
            # 1. 平静：整块为空
            _write(path)
            check(E.prompt_block("web:owner") == "", "平静时应为空")

            # 2. 750：第一段
            _write(path, fear=750)
            out = E.prompt_block("web:owner")
            check(out == "你现在有点害怕。", f"fear=750 应给“有点”：{out!r}")
            check(E.prompt_block("web:owner") == "", "同一档位不应重复")

            # 3. 880：第二段（带“体会”）
            _write_keep(path, fear=880)
            out = E.prompt_block("web:owner")
            check(out == "你现在挺害怕的，并试着体会这种感觉。", f"880 应给“挺害怕”：{out!r}")

            # 4. 960：第三段（带“克制”）
            _write_keep(path, fear=960)
            out = E.prompt_block("web:owner")
            check(out == "你现在怕得静不下来，你得略微克制一下自己。", f"960 应给“克制”：{out!r}")

            # 5. 高原：15 分钟后补一句，且不重复
            st = json.loads(path.read_text(encoding="utf-8"))
            st["prompt"]["hold_at"] = time.time() - E.PROMPT_HOLD_EVERY - 5
            path.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
            out = E.prompt_block("web:owner")
            check(out == "那股怕还在，别被它推着做决定。", f"高原提醒不对：{out!r}")
            check(E.prompt_block("web:owner") == "", "高原提醒不应连续出现")

            # 6. 960 -> 920：第二段下降
            _write_keep(path, fear=920)
            out = E.prompt_block("web:owner")
            check(out == "那股恐惧退下去一些了，但还在。", f"920 应给“退下去一些”：{out!r}")

            # 7. 920 -> 840：第一段下降
            _write_keep(path, fear=840)
            out = E.prompt_block("web:owner")
            check(out == "你缓过来一点了，恐惧在退。", f"840 应给“缓过来一点”：{out!r}")

            # 8. 840 -> 720：落到线下
            _write_keep(path, fear=720)
            out = E.prompt_block("web:owner")
            check(out == "你松下来了，恐惧在退。", f"720 应给“松下来了”：{out!r}")

            # 9. 700 以下：安静并清记忆
            _write_keep(path, fear=690)
            check(E.prompt_block("web:owner") == "", "700 以下应先安静")

            # 10. 再回 760：重新从第一段开始
            _write_keep(path, fear=760)
            out = E.prompt_block("web:owner")
            check(out == "你现在有点害怕。", f"重新回到 760 应重新出现：{out!r}")

            # 11. 两个都强：只取最强
            _write_keep(path, fear=900, anger=880)
            out = E.prompt_block("web:owner")
            check(out == "你现在挺害怕的，并试着体会这种感觉。" and "生气" not in out,
                  f"只应取最强：{out!r}")

            # 12. 爱意走同一套文案
            _write_keep(path, fear=520, anger=0, love=860)
            out = E.prompt_block("web:owner")
            check(out == "你现在挺想亲近对方的，并试着体会这种感觉。", f"love 段不对：{out!r}")

            # 13. 理智：0~70 不写，偏出才写；同档不重复；回日常清记忆
            _write(path, calm=E.to_unit("calm", 45.0))
            check(E.prompt_block("web:owner") == "", "理智 45 属日常，不应出现")
            _write(path, calm=E.to_unit("calm", -40.0))
            check("理智" in E.prompt_block("web:owner"), "理智 -40 应出现")
            check(E.prompt_block("web:owner") == "", "理智同一档不应重复")
            _write_keep(path, calm=E.to_unit("calm", 45.0))
            check(E.prompt_block("web:owner") == "", "理智回到日常应安静")
            _write_keep(path, calm=E.to_unit("calm", -40.0))
            check("理智" in E.prompt_block("web:owner"), "理智离开日常再回来应重新出现")
            _write_keep(path, calm=E.to_unit("calm", 80.0))
            check("冷得过头" in E.prompt_block("web:owner"), "理智 80 应出现抽离档")
        finally:
            E.STATE_PATH = old

    # 14. 驱动：<0.6 不出现，≥0.6 只一条
    orig = D.poll
    try:
        D.poll = lambda: {"active": [{"name": "reach", "urgency": 0.5},
                                     {"name": "seek", "urgency": 0.4}]}  # type: ignore[assignment]
        check(D.fragment() == "", "驱动 <0.6 应整块为空")
        D.poll = lambda: {"active": [{"name": "reach", "urgency": 0.7},
                                     {"name": "seek", "urgency": 0.65}]}  # type: ignore[assignment]
        out = D.fragment()
        check(out.startswith("# 你现在想干什么"), f"驱动块标题不对：{out!r}")
        check(out.count("\n- ") == 1 and "找对方说话" in out, f"驱动应只一条：{out!r}")
    finally:
        D.poll = orig

    if FAILS:
        print(f"FAIL {len(FAILS)} / OK {OKS}")
        for f in FAILS:
            print("  -", f)
        return 1
    print(f"OK {OKS} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
