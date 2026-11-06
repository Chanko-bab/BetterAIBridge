"""她把一句话说完要多久 —— 按字数和当前语速估一个时长（纯函数，不碰 Qt）。

为什么不直接量音频：关掉朗读时根本没有音频可量，可「她话还没说完」这件事还在。
所以两种模式共用一套语义，只是计时器不同：开着朗读听真实的，关掉朗读按这个估。

语速来自 core 的 tts 配置（`GET /tts/voices` 里带回 config），形如 "+0%" / "-30%"。
公式：秒数 = 字数 / (5.0 * (1 + rate%/100))，5.0 是中文女声 +0% 的中位语速。
"""

from __future__ import annotations

import re

CPS_BASE = 5.0          # 字/秒：+0% 时的中位语速
READ_FACTOR = 0.6       # 只看字时乘这个（读比听快）
MIN_SPEECH = 0.4        # 再短的句子也要占这么久
MAX_SPEECH = 20.0
MIN_TEXT_WINDOW = 0.8   # 关掉朗读后，一句至少留这么久好让你插话
MAX_TEXT_WINDOW = 8.0


def rate_pct(rate: str) -> float:
    """'+20%' → 20.0；'-30%' → -30.0；认不出（含空串）→ 0.0。"""
    m = re.search(r"([+-]?\d+(?:\.\d+)?)", str(rate or ""))
    return float(m.group(1)) if m else 0.0


def char_count(text: str) -> int:
    """有效字数：去掉空白，标点各算一个字（它确实占停顿）。"""
    return len(re.sub(r"\s", "", str(text or "")))


def speed_factor(rate: str = "+0%") -> float:
    """语速系数：+20% → 1.2，-30% → 0.7。"""
    return max(0.2, 1.0 + rate_pct(rate) / 100.0)


def speech_seconds(text: str, rate: str = "+0%") -> float:
    """这句话念出来大概多久（秒）。"""
    n = char_count(text)
    return max(MIN_SPEECH, min(MAX_SPEECH, n / (CPS_BASE * speed_factor(rate))))


def text_window_seconds(text: str, rate: str = "+0%") -> float:
    """关掉朗读时，这句占的窗口：读比听快，但留够插话的余地。"""
    raw = speech_seconds(text, rate) * READ_FACTOR
    return max(MIN_TEXT_WINDOW, min(MAX_TEXT_WINDOW, raw))
