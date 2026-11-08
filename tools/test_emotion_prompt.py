# -*- coding: utf-8 -*-
"""情绪/驱动提示词：平静为空、到 750 才冒一句、跨档才重复、理智同档不重复、驱动 ≥0.6 只一条。"""
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


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "state.json"
        old = E.STATE_PATH
        E.STATE_PATH = path
        try:
            # 1. 平静：整块为空（连“此刻”和理智都没有）
            path.write_text(json.dumps(_state(), ensure_ascii=False), encoding="utf-8")
            check(E.prompt_block("web:owner") == "", "平静时应为空")

            # 2. 刚好到 750：出现“有点”，不是“很”
            path.write_text(json.dumps(_state(fear=750), ensure_ascii=False), encoding="utf-8")
            out = E.prompt_block("web:owner")
            check(out == "你现在有点害怕。", f"fear=750 应给“有点”：{out!r}")

            # 3. 同一档位不重复
            check(E.prompt_block("web:owner") == "", "同一档位不应重复")

            # 4. 再升一档（850）才换“很”
            path.write_text(json.dumps(_state(fear=880), ensure_ascii=False), encoding="utf-8")
            check(E.prompt_block("web:owner") == "你现在很害怕。", "850~949 应给“很害怕”")

            # 5. 到顶（950）换更重的一句
            path.write_text(json.dumps(_state(fear=960), ensure_ascii=False), encoding="utf-8")
            check("怕得厉害" in E.prompt_block("web:owner"), "950 应换成更重的一句")

            # 6. 跌到 700 以下再回来，才算新的一次
            path.write_text(json.dumps(_state(fear=690), ensure_ascii=False), encoding="utf-8")
            check(E.prompt_block("web:owner") == "", "跌回 700 以下应先安静")
            path.write_text(json.dumps(_state(fear=760), ensure_ascii=False), encoding="utf-8")
            check("有点害怕" in E.prompt_block("web:owner"), "离开阈值后再回来应重新出现")

            # 7. 两个都强：只取最强
            path.write_text(json.dumps(_state(fear=900, anger=880), ensure_ascii=False), encoding="utf-8")
            out = E.prompt_block("web:owner")
            check(out == "你现在很害怕。" and "生气" not in out, f"只应取最强：{out!r}")

            # 8. 爱意也走同一机制
            path.write_text(json.dumps(_state(love=860), ensure_ascii=False), encoding="utf-8")
            check("充满爱意" in E.prompt_block("web:owner"), "love 应给爱意句")

            # 9. 理智：0~70 不写，偏出才写；同档不重复；回日常清记忆
            path.write_text(json.dumps(_state(calm=E.to_unit("calm", 45.0)), ensure_ascii=False),
                            encoding="utf-8")
            check(E.prompt_block("web:owner") == "", "理智 45 属日常，不应出现")
            path.write_text(json.dumps(_state(calm=E.to_unit("calm", -40.0)), ensure_ascii=False),
                            encoding="utf-8")
            check("理智" in E.prompt_block("web:owner"), "理智 -40 应出现")
            check(E.prompt_block("web:owner") == "", "理智同一档不应重复")
            path.write_text(json.dumps(_state(calm=E.to_unit("calm", 45.0)), ensure_ascii=False),
                            encoding="utf-8")
            check(E.prompt_block("web:owner") == "", "理智回到日常应安静")
            path.write_text(json.dumps(_state(calm=E.to_unit("calm", -40.0)), ensure_ascii=False),
                            encoding="utf-8")
            check("理智" in E.prompt_block("web:owner"), "理智离开日常再回来应重新出现")
            path.write_text(json.dumps(_state(calm=E.to_unit("calm", 80.0)), ensure_ascii=False),
                            encoding="utf-8")
            check("冷得过头" in E.prompt_block("web:owner"), "理智 80 应出现抽离档")
        finally:
            E.STATE_PATH = old

    # 10. 驱动：<0.6 不出现，≥0.6 只一条
    orig = D.poll
    try:
        D.poll = lambda: {"active": [{"name": "reach", "urgency": 0.5},
                                     {"name": "seek", "urgency": 0.4}]}  # type: ignore[assignment]
        check(D.fragment() == "", "驱动 <0.6 应整块为空")
        D.poll = lambda: {"active": [{"name": "reach", "urgency": 0.7},
                                     {"name": "seek", "urgency": 0.65}]}  # type: ignore[assignment]
        out = D.fragment()
        check(out.startswith("# 你现在想干什么"), f"驱动块标题不对：{out!r}")
        check(out.count("\n- ") == 1 and "找他说话" in out, f"驱动应只一条：{out!r}")
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
