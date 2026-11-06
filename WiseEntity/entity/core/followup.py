"""她说完了、你还没回——隔一会儿补一句（"插话"）。

纯逻辑，不负责真的说话：只回答三个问题——
  1. 该不该补？（这轮还没补够、你还没回、没被免打扰）
  2. 什么时候补？（按性格 + 关系 + 当前情绪算一个等待秒数）
  3. 补多长？（按性格给字数上限）

真正的开口交给调用方（内核在 tick 里调 `due()`，拿到就生成一句短话发出去）。
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any, Dict, Optional

from . import settings as S

# 主动程度（设置页滑条）：0 关 / 1 克制 / 2 正常 / 3 黏人。
# 只改「等多久」和「一轮最多补几次」；性格（PROFILES）与关系仍然是底表。
LEVELS: Dict[int, Dict[str, Any]] = {
    0: {"name": "关", "label": "说完就说完，不补话",
        "wait_scale": 1.0, "max_extra": 0},
    1: {"name": "克制", "label": "隔得久一点，最多补一句",
        "wait_scale": 1.8, "max_extra": 1},
    2: {"name": "正常", "label": "你没回，过一会儿补一句",
        "wait_scale": 1.0, "max_extra": 1},
    3: {"name": "黏人", "label": "很快补，最多两句",
        "wait_scale": 0.6, "max_extra": 2},
}
DEFAULT_LEVEL = 2
CFG_PATH = S.ENTITY / "config" / "followup.json"

# 四档性格参数：等待区间、每轮最多补几次、补几句之后闭嘴、字数上限
PROFILES: Dict[str, Dict[str, Any]] = {
    "clingy": {       # 黏人、热烈
        "wait": (5.0, 10.0), "max_extra": 2, "max_silent": 2, "max_chars": 14,
        "tone": "黏",
    },
    "normal": {       # 常态
        "wait": (8.0, 20.0), "max_extra": 1, "max_silent": 2, "max_chars": 18,
        "tone": "平",
    },
    "tsundere": {     # 傲娇、嘴硬
        "wait": (15.0, 35.0), "max_extra": 1, "max_silent": 2, "max_chars": 10,
        "tone": "冲",
    },
    "calm": {         # 冷静、理性
        "wait": (25.0, 45.0), "max_extra": 1, "max_silent": 2, "max_chars": 20,
        "tone": "淡",
    },
}

# 关系对等待的缩放：越亲近越等得住？这里反过来——越亲近越容易凑上来
RELATION_SCALE = {"恋人": 0.8, "家人": 0.85, "朋友": 1.0, "搭档": 1.25, "老师": 1.3}

CLINGY_WORDS = ("热烈", "活泼", "黏", "元气", "开朗", "撒娇")
TSUNDERE_WORDS = ("傲娇", "毒舌", "嘴硬", "高冷", "冷淡")
CALM_WORDS = ("冷静", "理性", "沉稳", "安静", "克制", "成熟")


def _clamp_level(v: Any) -> int:
    try:
        n = int(v)
    except Exception:  # noqa: BLE001
        return DEFAULT_LEVEL
    return max(0, min(3, n))


def cfg() -> Dict[str, Any]:
    """读主动程度；文件坏了就当作「正常」，不让设置把内核拖死。"""
    out: Dict[str, Any] = {"level": DEFAULT_LEVEL}
    try:
        raw = json.loads(Path(CFG_PATH).read_text(encoding="utf-8-sig"))
        if isinstance(raw, dict) and "level" in raw:
            out["level"] = _clamp_level(raw.get("level"))
    except Exception:  # noqa: BLE001
        pass
    return out


def save_cfg(patch: Dict[str, Any]) -> Dict[str, Any]:
    cur = cfg()
    if "level" in patch and patch.get("level") is not None:
        cur["level"] = _clamp_level(patch.get("level"))
    p = Path(CFG_PATH)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        S.log(f"[followup] 存配置失败: {e!r}")
    return cur


def level() -> int:
    return _clamp_level(cfg().get("level"))


def enabled() -> bool:
    """0 档＝关：她说完了就完了，不再补。"""
    return level() > 0


def apply_level(profile: Optional[Dict[str, Any]], lv: Optional[int] = None) -> Dict[str, Any]:
    """把主动程度叠在性格底表上：只缩放等待区间、定「一轮最多补几次」。"""
    lv = _clamp_level(level() if lv is None else lv)
    spec = LEVELS[lv]
    p = dict(profile or PROFILES["normal"])
    lo, hi = p.get("wait", (8.0, 20.0))
    scale = float(spec.get("wait_scale") or 1.0)
    p["wait"] = (float(lo) * scale, float(hi) * scale)
    p["max_extra"] = int(spec.get("max_extra") or 0)
    p["level"] = lv
    return p


def profile_for(style: str = "", relation: str = "") -> Dict[str, Any]:
    """把人格风格 / 关系翻成一档参数（返回副本，调用方可随便改）。"""
    s = (style or "").strip()
    key = "normal"
    if any(w in s for w in CLINGY_WORDS):
        key = "clingy"
    elif any(w in s for w in TSUNDERE_WORDS):
        key = "tsundere"
    elif any(w in s for w in CALM_WORDS):
        key = "calm"
    p = dict(PROFILES[key])
    p["profile"] = key
    p["relation_scale"] = RELATION_SCALE.get((relation or "").strip(), 1.0)
    return p


def mood_scale(emotions: Optional[Dict[str, float]]) -> float:
    """当前情绪对等待的缩放：开心/亲近会更快凑上来，难过/生气更慢，惊讶略快。"""
    e = emotions or {}
    pos = float(e.get("joy") or 0) + float(e.get("love") or 0)
    neg = float(e.get("sadness") or 0) + float(e.get("anger") or 0)
    sur = float(e.get("surprise") or 0)
    scale = 1.0
    if pos >= 60:
        scale *= 0.75
    if neg >= 50:
        scale *= 1.5
    if sur >= 50:
        scale *= 0.85
    return max(0.5, min(2.0, scale))


def wait_seconds(profile: Dict[str, Any], emotions: Optional[Dict[str, float]] = None,
                 rng: Optional[random.Random] = None) -> float:
    lo, hi = profile.get("wait", (8.0, 20.0))
    r = (rng or random).uniform(lo, hi)
    return max(3.0, r * float(profile.get("relation_scale") or 1.0) * mood_scale(emotions))


class Tracker:
    """每个会话一份：记她说完的时间、补过几次、你回过没有。"""

    def __init__(self) -> None:
        self.sessions: Dict[str, Dict[str, Any]] = {}

    def _s(self, session: str) -> Dict[str, Any]:
        return self.sessions.setdefault(session, {
            "t0": 0.0, "extra": 0, "silent": 0, "pending": False,
            "wait": 0.0, "max_chars": 18,
        })

    def note_reply(self, session: str, now: Optional[float] = None,
                   profile: Optional[Dict[str, Any]] = None,
                   emotions: Optional[Dict[str, float]] = None,
                   rng: Optional[random.Random] = None) -> Dict[str, Any]:
        """她说了一句：按性格 + 主动程度开始计时，准备要不要补。"""
        st = self._s(session or "web:owner")
        p = apply_level(profile)
        st.update({
            "t0": now if now is not None else time.time(),
            "extra": 0,
            "pending": True,
            "wait": wait_seconds(p, emotions, rng),
            "max_chars": int(p.get("max_chars") or 18),
            "profile": dict(p),
        })
        return st

    def note_user(self, session: str) -> None:
        """你说话了：这一轮作废，计数清零。"""
        st = self._s(session or "web:owner")
        st.update({"pending": False, "extra": 0, "silent": 0})

    def pending_sessions(self) -> list[str]:
        """还在等补话的会话（tick 只处理这些，不遍历全部历史）。"""
        return [k for k, v in self.sessions.items() if isinstance(v, dict) and v.get("pending")]

    def due(self, session: str, now: Optional[float] = None,
            profile: Optional[Dict[str, Any]] = None, quiet: bool = False) -> Optional[Dict[str, Any]]:
        """到点了吗？到点返回 {extra, max_chars}，否则 None。"""
        st = self._s(session or "web:owner")
        if quiet or not st.get("pending"):
            return None
        p = profile or st.get("profile") or PROFILES["normal"]
        now = now if now is not None else time.time()
        if now - float(st.get("t0") or 0) < float(st.get("wait") or 0):
            return None
        # 注意别写成 `p.get("max_extra") or 1`：0 是「关档」，不能被当成缺省值
        cap_silent = p.get("max_silent")
        cap_silent = 2 if cap_silent is None else int(cap_silent)
        if int(st.get("silent") or 0) >= cap_silent:
            st["pending"] = False
            return None
        cap_extra = p.get("max_extra")
        cap_extra = 1 if cap_extra is None else int(cap_extra)
        if int(st.get("extra") or 0) >= cap_extra:
            st["pending"] = False
            return None
        st["extra"] = int(st.get("extra") or 0) + 1
        st["t0"] = now
        # 关系系数在 note_reply 里已经乘进 wait 了，这里别再乘一次
        st["wait"] = wait_seconds({**p, "relation_scale": 1.0})
        if int(st["extra"]) > 1:
            st["silent"] = int(st.get("silent") or 0) + 1
        return {"extra": int(st["extra"]), "max_chars": int(st.get("max_chars") or 18)}

    def state(self, session: str) -> Dict[str, Any]:
        return dict(self._s(session or "web:owner"))


# 全局一份：chat_core 记「她说了 / 你回了」，内核 tick 读「该不该补」。
tracker = Tracker()
