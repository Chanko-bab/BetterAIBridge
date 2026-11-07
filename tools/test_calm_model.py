# -*- coding: utf-8 -*-
"""理智（calm）新模型：分档、基线、软饱和、迁移与调质上限。"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "WiseEntity" / "entity"))

from core import emotion_core as E  # noqa: E402
from core import persona_styles as P  # noqa: E402

FAILS: list[str] = []
OKS = 0


def check(ok: bool, msg: str) -> None:
    global OKS
    if ok:
        OKS += 1
    else:
        FAILS.append(msg)


def main() -> int:
    # 分档：-70/+70 之外不是好状态，-100/+100 是极难到达的两端
    check(E.calm_level(-100) == 0, "calm_level(-100) 应为 0")
    check(E.calm_level(-70) == 1, "calm_level(-70) 应为 1")
    check(E.calm_level(-30) == 2, "calm_level(-30) 应为 2")
    check(E.calm_level(0) == 3, "calm_level(0) 应为 3")
    check(E.calm_level(30) == 4, "calm_level(30) 应为 4")
    check(E.calm_level(70) == 5, "calm_level(70) 应为 5")
    check(E.calm_level(100) == 5, "calm_level(100) 应为 5")
    check("几乎没了理智" in E.san_sentence(-100), "崩溃档文案不对")
    check("冷得过头" in E.san_sentence(70), "抽离档文案不对")

    # 种子与基线：所有底子都不允许一开局站到 +70
    for name, style in P.STYLES.items():
        seed = float(style["seeds"].get("calm") or 0.0)
        check(seed <= 55.0, f"{name} 的 calm 种子应 <= 55：{seed}")
        check(seed >= -45.0, f"{name} 的 calm 种子应 >= -45：{seed}")
    check(E._sanitize_calm_seed(75.0) == 55.0, "种子 75 应压到 55")
    check(E._sanitize_calm_seed(-80.0) == -45.0, "种子 -80 应压到 -45")

    # 软饱和：越靠近极端，同向事件越推不动
    check(abs(E._calm_gain(70.0, 1.0) - 0.5) < 1e-9, "70 处增益应为 0.5")
    check(abs(E._calm_gain(90.0, 1.0) - 1 / 6) < 1e-9, "90 处增益应为 1/6")
    check(E._calm_gain(100.0, 1.0) == 0.0, "100 处增益应为 0")
    check(abs(E._calm_gain(-70.0, -1.0) - 0.5) < 1e-9, "-70 处增益应为 0.5")

    # 衰减回人格基线，而不是回 0
    now = time.time()
    st = E._blank()
    st["values"]["calm"] = E.to_unit("calm", 60.0)
    st["calm_home"] = 20.0
    st["updated_at"] = now - 120 * 60
    st["started"] = True
    E.decay(st, now=now)
    p = E.from_unit("calm", st["values"]["calm"])
    check(38.0 <= p <= 42.0, f"calm 应衰减到基线 40 左右：{p}")

    # 旧存档迁移：+70 以上压回 55，-70 以下压回 -55
    with tempfile.TemporaryDirectory() as td:
        state = Path(td) / "state.json"
        old = E._blank()
        old["values"] = {k: E.to_unit(k, 0.0) for k in E.KEYS}
        old["values"]["calm"] = E.to_unit("calm", 90.0)
        old.pop("calm_model", None)
        old.pop("calm_home", None)
        state.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        saved = E.STATE_PATH
        E.STATE_PATH = state
        try:
            loaded = E.load()
            p = E.from_unit("calm", loaded["values"]["calm"])
            check(abs(p - 55.0) < 0.01, f"导入 90 应压到 55：{p}")
            check("calm_home" in loaded and "calm_model" in loaded, "导入后应补 calm_home/calm_model")
        finally:
            E.STATE_PATH = saved

    # 负向事件：被骂会拉低 calm
    with tempfile.TemporaryDirectory() as td:
        saved_ev = E.EVENTS_PATH
        E.EVENTS_PATH = Path(td) / "events.jsonl"
        try:
            st = E._blank()
            st["values"]["calm"] = E.to_unit("calm", 0.0)
            st["calm_home"] = 0.0
            rec = E.apply_event(st, "calm", -0.06, "被骂")
            p = E.from_unit("calm", st["values"]["calm"])
            check(p < 0.0, f"被骂后 calm 应下降：{p}")
            check(float(rec.get("delta") or 0) < 0, "事件日志应记负向 delta")
        finally:
            E.EVENTS_PATH = saved_ev

    # 软饱和：90 处再被夸一次，不能直接加满 6 点
    with tempfile.TemporaryDirectory() as td:
        saved_ev = E.EVENTS_PATH
        E.EVENTS_PATH = Path(td) / "events.jsonl"
        try:
            st = E._blank()
            st["values"]["calm"] = E.to_unit("calm", 90.0)
            st["calm_home"] = 0.0
            rec = E.apply_event(st, "calm", 0.06, "被夸")
            p = E.from_unit("calm", st["values"]["calm"])
            check(90.0 < p < 92.0, f"90 处 +6 应只加约 1 点：{p}")
            check(abs(float(rec.get("delta") or 0)) < 2.0, "软饱和后的 delta 应 < 2")
        finally:
            E.EVENTS_PATH = saved_ev

    # tick 的调质注入：单次 calm 最多 ±2；|calm|>=60 直接跳过
    saved_load, saved_save, saved_decay = E.load, E.save, E.decay
    saved_levels, saved_push, saved_refine = E.bridge.levels, E.bridge.push, E.llm_refine
    try:
        st = E._blank()
        st["values"]["calm"] = E.to_unit("calm", 0.0)
        st["calm_home"] = 0.0
        E.load = lambda: st
        E.save = lambda _st: None
        E.decay = lambda _st, now=None: _st
        E.bridge.levels = lambda: {k: 0.3 for k in E.bridge.NT_ORDER}
        E.bridge.push = lambda _lv: {"calm": 10.0}
        E.llm_refine = lambda: {}
        E.tick()
        p = E.from_unit("calm", st["values"]["calm"])
        check(abs(p - 2.0) < 0.01, f"tick calm 注入应夹到 2：{p}")

        st2 = E._blank()
        st2["values"]["calm"] = E.to_unit("calm", 70.0)
        st2["calm_home"] = 70.0
        E.load = lambda: st2
        E.tick()
        p2 = E.from_unit("calm", st2["values"]["calm"])
        check(abs(p2 - 70.0) < 0.01, f"|calm|>=60 时不应再被调质推：{p2}")
    finally:
        E.load, E.save, E.decay = saved_load, saved_save, saved_decay
        E.bridge.levels, E.bridge.push, E.llm_refine = saved_levels, saved_push, saved_refine

    if FAILS:
        print("FAIL", len(FAILS))
        for msg in FAILS:
            print(" -", msg)
        return 1
    print(f"PASS {OKS} 项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
