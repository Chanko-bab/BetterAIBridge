# -*- coding: utf-8 -*-
"""情绪接线：把果蝇脑的 6 种调质，接到 13 维情绪上。

分工（2026-11-04 与用户定稿，2026-11-05 接真实 6×6 接线）：

    6 种调质（ach/glu/gaba/da/5ht/oa）
        │  只做体内状态，不直接给用户看
        ▼
    13 维情绪（6 基础 + 6 复合 + calm 理智）
        │  calm 量程 -100~100，其余 -10~100
        ▼
    提示词档位 / drives 门控 / 界面

这里做三件事：
1. `wiring(levels)`：用 FlyWire v783 的真实 6×6 突触连接比例，把 6 群调质
   做一次「接线混合」。这不是全脑脉冲仿真，只是让群与群之间的耦合有真实依据。
2. `push(levels)`：混合后的调质偏离静息（0.30）时，给 13 维一个很小的持续推力。
   每 90 秒最多 ±6 点，不会盖过人设和事件。
3. `rate(levels)`：同一组偏离，给「变化强度」一个 0.88~1.12 的乘子。

注意：6×6 是真实接线统计；6→13 仍是工程映射，不是果蝇实验结论。真实数据
只给出 6 种递质的比例和接线；「快乐/羞耻/嫉妒」是人给 13 维起的名字。
"""
from __future__ import annotations

from typing import Dict, Optional

NT_ORDER = ("ach", "glu", "gaba", "da", "5ht", "oa")
REST = 0.30

EMO_KEYS = (
    "joy", "calm", "love", "pride", "anger", "anxiety", "fear",
    "sadness", "shame", "disgust", "envy", "surprise", "confusion",
)

# 每 1.0 的调质偏离，给该情绪加多少点。正=抬高，负=压低。
# 来源：ach 注意/新奇；glu 兴奋/威胁；gaba 抑制/安静；da 奖赏/动机；
#       5ht 情绪稳定；oa 唤醒/攻击。
WEIGHTS: Dict[str, Dict[str, float]] = {
    "ach": {"surprise": 14.0, "confusion": 8.0, "joy": 6.0, "anxiety": 5.0, "pride": 2.0},
    "glu": {"fear": 14.0, "anxiety": 10.0, "anger": 8.0, "surprise": 6.0, "confusion": 4.0},
    "gaba": {"calm": 18.0, "anxiety": -10.0, "fear": -8.0, "anger": -8.0, "disgust": -4.0},
    "da": {"joy": 12.0, "pride": 10.0, "love": 8.0, "envy": 6.0, "anger": 4.0},
    "5ht": {"calm": 14.0, "love": 8.0, "sadness": -10.0, "anxiety": -6.0, "envy": -4.0},
    "oa": {"anger": 12.0, "fear": 8.0, "disgust": 8.0, "surprise": 5.0, "joy": -4.0},
}

# 一次 tick 的推力上限（点）。宁可小，不要让人设失效。
PUSH_CAP = 6.0
# 变化强度乘子的幅度：1 ± RATE_AMP
RATE_AMP = 0.12
# 把「权重和」压进 tanh 的除数
RATE_DIV = 8.0

# FlyWire FAFB v783：按 top_nt 分 6 群后，真实突触连接占「后群总输入」的比例。
# 行 = 后（post），列 = 前（pre）；每列和为 1。数据由 1684 万条连接聚合。
# 这不是全脑脉冲仿真，只作为 6 群之间的一步耦合增益。
WIRING = (
    # pre: ach    glu    gaba   da     5ht    oa
    (0.526591, 0.582438, 0.634460, 0.413043, 0.514892, 0.625147),  # post ach
    (0.186365, 0.194438, 0.144188, 0.070803, 0.154977, 0.150212),  # post glu
    (0.267707, 0.198883, 0.192295, 0.117871, 0.174172, 0.198161),  # post gaba
    (0.009643, 0.015198, 0.019625, 0.388263, 0.029448, 0.011760),  # post da
    (0.007720, 0.006282, 0.005665, 0.008681, 0.124108, 0.011834),  # post 5ht
    (0.001973, 0.002761, 0.003766, 0.001340, 0.002404, 0.002887),  # post oa
)
# 接线混合强度：0=不混合，1=完全按输入比例替换。取 0.45，保留本群自身状态。
WIRING_GAIN = 0.45
# 递质方向：GABA 是抑制性，其余按兴奋/调质处理。真实连接本身不带符号，
# 这里用神经递质类型补一个工程符号，避免把抑制性接成兴奋性。
NT_SIGN = {"ach": 1.0, "glu": 1.0, "gaba": -1.0, "da": 1.0, "5ht": 1.0, "oa": 1.0}


def mix(levels: Optional[Dict[str, float]]) -> Optional[Dict[str, float]]:
    """用真实 6×6 接线比例，把当前 6 群调质混合一次。"""
    if not levels:
        return None
    z = [_z(levels.get(nt, REST)) for nt in NT_ORDER]
    out = {}
    for i, nt in enumerate(NT_ORDER):
        drive = 0.0
        for j, pre in enumerate(NT_ORDER):
            drive += WIRING[i][j] * NT_SIGN[pre] * z[j]
        out[nt] = REST + (1.0 - WIRING_GAIN) * z[i] + WIRING_GAIN * drive
    return out



def _z(level: float) -> float:
    try:
        return float(level) - REST
    except Exception:  # noqa: BLE001
        return 0.0


def push(levels: Optional[Dict[str, float]]) -> Dict[str, float]:
    """调质水平 → 13 维的增量（点）。缺项按静息算。"""
    out = {k: 0.0 for k in EMO_KEYS}
    levels = mix(levels)
    if not levels:
        return out
    for nt in NT_ORDER:
        z = _z(levels.get(nt, REST))
        if abs(z) < 1e-9:
            continue
        for emo, w in WEIGHTS.get(nt, {}).items():
            out[emo] += w * z
    for k in out:
        out[k] = round(max(-PUSH_CAP, min(PUSH_CAP, out[k])), 3)
    return out


def rate(levels: Optional[Dict[str, float]]) -> Dict[str, float]:
    """调质水平 → 13 维的变化强度乘子（约 0.88~1.12）。"""
    out = {k: 1.0 for k in EMO_KEYS}
    levels = mix(levels)
    if not levels:
        return out
    raw = {k: 0.0 for k in EMO_KEYS}
    for nt in NT_ORDER:
        z = _z(levels.get(nt, REST))
        if abs(z) < 1e-9:
            continue
        for emo, w in WEIGHTS.get(nt, {}).items():
            raw[emo] += w * z
    for k, v in raw.items():
        out[k] = round(1.0 + RATE_AMP * _tanh(v / RATE_DIV), 3)
    return out


def _tanh(x: float) -> float:
    # 不引 math 也行，但这里用标准库更稳
    import math

    return math.tanh(float(x))


def levels() -> Optional[Dict[str, float]]:
    """读当前 6 种调质；大脑没起来就返回 None。"""
    try:
        from . import brain_box

        return brain_box.nt_levels()
    except Exception:  # noqa: BLE001
        return None


def debug() -> Dict[str, object]:
    raw = levels() or {k: REST for k in NT_ORDER}
    wired = mix(raw) or raw
    return {"levels": raw, "wired": wired, "push": push(raw), "rate": rate(raw)}
