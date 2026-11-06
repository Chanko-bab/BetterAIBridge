# -*- coding: utf-8 -*-
"""情绪接线：6 种调质 → 13 维情绪的回归（非 pytest，退出码 0/1）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "WiseEntity" / "entity"))

from core import emotion_bridge as B  # noqa: E402
from core import emotion_core as E  # noqa: E402
from core import style_box  # noqa: E402

FAILS: list[str] = []
OKS = 0


def check(ok: bool, msg: str) -> None:
    global OKS
    if ok:
        OKS += 1
    else:
        FAILS.append(msg)


rest = {k: 0.30 for k in B.NT_ORDER}
zero = B.push(rest)
check(all(abs(v) < 1e-9 for v in zero.values()), f"静息时推力应为 0：{zero}")
check(all(abs(v - 1.0) < 1e-9 for v in B.rate(rest).values()), "静息时变化强度应为 1.0")

high_da = dict(rest, da=0.60)
p = B.push(high_da)
check(p["joy"] > 0 and p["pride"] > 0 and p["love"] > 0, f"多巴胺应抬高快乐/自豪/爱：{p}")
check(0 < p["calm"] < 1.0, f"多巴胺只应经接线间接小幅带动理智：{p['calm']}")

# 真实 6×6 接线：每列是后群总输入的分布，列和应为 1。
for j, pre in enumerate(B.NT_ORDER):
    col = sum(B.WIRING[i][j] for i in range(6))
    check(abs(col - 1.0) < 2e-6, f"接线列 {pre} 应归一化：{col}")
m = B.mix(rest)
check(all(abs(m[k] - B.REST) < 1e-9 for k in B.NT_ORDER), f"静息时接线混合应不变：{m}")
high_ach = dict(rest, ach=0.60)
m = B.mix(high_ach)
check(m["gaba"] > B.REST, f"ACh 应经真实接线带动 GABA 群：{m}")

high_gaba = dict(rest, gaba=0.60)
p = B.push(high_gaba)
check(p["calm"] > 0, f"GABA 应抬高理智：{p}")
check(p["anxiety"] < 0 and p["fear"] < 0 and p["anger"] < 0, f"GABA 应压低焦虑/恐惧/愤怒：{p}")

high_oa = dict(rest, oa=0.60)
p = B.push(high_oa)
check(p["anger"] > 0 and p["fear"] > 0, f"章鱼胺应抬高愤怒/恐惧：{p}")
check(p["joy"] < 0, f"章鱼胺应压低快乐：{p}")

low_5ht = dict(rest, **{"5ht": 0.05})
p = B.push(low_5ht)
check(p["sadness"] > 0, f"血清素低应抬高悲伤：{p}")
check(p["calm"] < 0, f"血清素低应压低理智：{p}")

boil = {k: 1.0 for k in B.NT_ORDER}
p = B.push(boil)
check(all(-B.PUSH_CAP <= v <= B.PUSH_CAP for v in p.values()), f"单次推力应夹在 ±{B.PUSH_CAP}：{p}")
r = B.rate(boil)
check(all(1.0 - B.RATE_AMP - 1e-9 <= v <= 1.0 + B.RATE_AMP + 1e-9 for v in r.values()),
      f"变化强度乘子应在 ±{B.RATE_AMP}：{r}")

# 13 维的内部单位：0~1000，500 为基线；展示层再换算
check(E._clamp(-999) == 0, "内部单位下限是 0")
check(E._clamp(9999) == 1000, "内部单位上限是 1000")
check(E.display_value("calm", 0) == -100, "展示层：理智 0 应显示 -100")
check(E.display_value("calm", 500) == 0, "展示层：理智 500 应显示 0")
check(E.display_value("calm", 1000) == 100, "展示层：理智 1000 应显示 100")
check(E.display_value("joy", 0) == -10, "展示层：普通情绪 0 应显示 -10")
check(E.display_value("joy", 500) == 0, "展示层：普通情绪 500 应显示 0")
check(E.display_value("joy", 685) == 37, "展示层：普通情绪 685 应显示 37")

# 内部/展示往返：迁移不能改变用户看到的数
for key, p in (("joy", -10), ("joy", 0), ("joy", 37), ("joy", 100),
               ("calm", -100), ("calm", 0), ("calm", 31), ("calm", 100)):
    check(E.display_value(key, E.to_unit(key, p)) == p, f"{key} 展示点 {p} 往返不一致")
check(0 <= E.to_unit("joy", -10) <= E.to_unit("joy", 100) <= 1000, "普通情绪内部量程应在 0~1000")
check(0 <= E.to_unit("calm", -100) <= E.to_unit("calm", 100) <= 1000, "理智内部量程应在 0~1000")

# 旧存档迁移：旧 values 是展示点，读进来要变成内部 0~1000，展示不变
import json as _json
import tempfile as _tempfile
old_path = E.STATE_PATH
with _tempfile.TemporaryDirectory() as td:
    p = Path(td) / "emotion_state.json"
    p.write_text(_json.dumps({"values": {"joy": 50, "calm": -50}}, ensure_ascii=False), encoding="utf-8")
    E.STATE_PATH = p
    try:
        st = E.load()
        check(st.get("unit") == "act1000", f"旧存档应升级到 act1000：{st.get('unit')}")
        check(abs(E.display_value("joy", st["values"]["joy"]) - 50) < 0.05, "迁移后快乐展示值不变")
        check(abs(E.display_value("calm", st["values"]["calm"]) + 50) < 0.05, "迁移后理智展示值不变")
    finally:
        E.STATE_PATH = old_path

doc = style_box.normalize({"seeds": {"joy": 999, "calm": -999}})
check(doc["seeds"]["joy"] == 100, f"普通 seed 应夹到 100：{doc['seeds']}")
check(doc["seeds"]["calm"] == -10, f"理智 seed 内部仍夹到 -10：{doc['seeds']}")

if FAILS:
    for f in FAILS:
        print("FAIL", f)
    print(f"\n{len(FAILS)} 条失败")
    sys.exit(1)
print(f"PASS {OKS} 项")
