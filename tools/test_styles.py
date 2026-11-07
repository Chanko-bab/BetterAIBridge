# -*- coding: utf-8 -*-
"""16 套人设的回归测试（非 pytest，退出码 0/1）。

跑法（内核解释器）：
    D:\\BetterAIBridge\\WiseEntity\\entity\\.venv\\Scripts\\python.exe tools\\test_styles.py

测什么：16 套都在、键齐、量程对、敏感度是那五档、分组不漏不重、
老名字还能落到新人设上、开局真的按人设落值（理智不再被硬写成 0）、
情绪刺激表里的键都是真键。
"""
from __future__ import annotations

import sys
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


ALLOWED = {0.2, 0.4, 0.7, 1.0, 1.4}

names = P.names()
check(len(names) == 16, f"应有 16 套人设，实际 {len(names)}：{names}")
check(len(set(names)) == 16, "人设名字不该重复")

grouped_names = [n for _g, _d, members in P.grouped() for n in members]
check(sorted(grouped_names) == sorted(names), "分组里的名字应正好覆盖 16 套、不漏不重")
check([len(m) for _g, _d, m in P.grouped()] == [6, 7, 3], "三组的条数应为 6 / 7 / 3")

for name in names:
    row = P.get(name)
    seeds, delta, hl = row["seeds"], row["delta"], row["half_life"]
    check(set(seeds) == set(P.KEYS), f"{name} 的 seeds 键不齐：缺 {set(P.KEYS) - set(seeds)}")
    bad = {k: v for k, v in seeds.items()
           if not (E.SAN_MIN <= v <= E.SAN_MAX) if k == "calm"}
    bad = {k: v for k, v in seeds.items()
           if (k == "calm" and not (E.SAN_MIN <= v <= E.SAN_MAX))
           or (k != "calm" and not (E.DISPLAY_MIN <= v <= E.DISPLAY_MAX))}
    check(not bad, f"{name} 的初始值越界：{bad}")
    unknown = set(delta) - set(P.KEYS)
    check(not unknown, f"{name} 的 delta 里有不认识的键：{unknown}")
    odd = {k: v for k, v in delta.items() if float(v) not in ALLOWED}
    check(not odd, f"{name} 的 delta 不是五档（0.2/0.4/0.7/1.0/1.4）：{odd}")
    odd_hl = {k: v for k, v in hl.items() if abs(float(v) - 0.7) > 1e-6 and abs(float(v) - 1.2) > 1e-6}
    check(not odd_hl, f"{name} 的 half_life 只该是 0.7 或 1.2：{odd_hl}")
    check(bool(row.get("logic")), f"{name} 缺一句 logic")

# 老名字兼容
check(E._ALIASES == {"温柔": "温柔共情", "理性": "清冷理智", "跳脱": "热烈乐天"}, "别名表变了")
for old, new in E._ALIASES.items():
    check(E._SEEDS.get(old) == E._SEEDS.get(new), f"{old} 应指向 {new} 的同一份初始值")
    check(E._PROFILE.get(old) == E._PROFILE.get(new), f"{old} 应指向 {new} 的同一份敏感度")

check(P.seeds("病娇")["love"] == 35, "病娇的爱意初始值应是 35")
check(P.seeds("傲娇")["calm"] == 18, "傲娇的理智初始值应是 18")
check(P.delta("雌小鬼")["envy"] == 1.0, "雌小鬼的嫉妒应是强 1.0")
check(P.delta("病娇")["envy"] == 1.4, "病娇的嫉妒应是极强 1.4")
check(P.half_life("病娇")["envy"] == 0.7, "极强情绪的回落应更快（0.7）")

# 情绪刺激表：键必须都是真情绪键（之前 cut_off 里写过一个不存在的 affection）
for kind, rows in E.STIMULI.items():
    bad_keys = [(k, _v) for k, _v in rows if k not in E.KEYS]
    check(not bad_keys, f"STIMULI[{kind!r}] 里有不存在的情绪键：{bad_keys}")

# 开局：按人设落值，理智不再被硬写成 0
old_profile = E.profile
E.profile = lambda: {"styles": E._PROFILE, "seeds": E._SEEDS}
saved = {}
for style in ("傲娇", "病娇", "温柔", "不存在的性格"):
    old_cfg, old_save = E.S.llm_cfg, E.save
    E.S.llm_cfg = lambda style=style: {"style": style}
    E.save = lambda st: saved.update({"doc": st})
    try:
        st = E.start({})
    finally:
        E.S.llm_cfg, E.save = old_cfg, old_save
    want = E._ALIASES.get(style, "温柔共情" if style == "不存在的性格" else style)
    check(st.get("seed_style") == want, f"{style} 开局的 seed_style 应是 {want}，实际 {st.get('seed_style')}")
    check(st["values"]["calm"] == E.to_unit("calm", P.seeds(want)["calm"]),
          f"{style} 开局的理智应取自人设（{P.seeds(want)['calm']}），实际 {st['values']['calm']}")
E.profile = old_profile

print("PASS" if not FAILS else "FAIL", f"{OKS} 条", "" if not FAILS else "")
for f in FAILS:
    print("  -", f)
sys.exit(0 if not FAILS else 1)
