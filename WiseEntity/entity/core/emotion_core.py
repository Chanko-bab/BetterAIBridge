# -*- coding: utf-8 -*-
"""情绪核：13 种情绪（6 基础 / 6 复合 / 1 基线）× 五档，量程 −10 ~ 100。

设计意图（2026-10-30 与主人定稿第二版）：

    6 种调质（flybrain）  →  13 种情绪的强度  →  三条出口
                                                   ├─ 话（档位 → 语气，不报数字）
                                                   ├─ 行为（drives / 主动 / 回避）
                                                   └─ 记忆（强事件留痕，供人格漂移）

这一版多了三件事：

1. **分型**：基础情绪（快乐/悲伤/愤怒/恐惧/厌恶/惊讶）是与生俱来的；
   复合情绪（爱意/自豪/焦虑/羞耻/嫉妒/困惑）由基础情绪叠加社会经验长出来；
   平静不是情绪，是情绪回落后的基线。界面按这三栏摆。
2. **量程**：内部用「点」，−10 ~ 100。0 是中性，负值是"沉到基线以下"（比如傲娇的怕会压到 −3）。
3. **性格驱动**：人格配置里的 style（傲娇/温柔/理性/跳脱）决定两件事——
   开局给一组起始值（不是全 0），以及每种情绪涨得多快、退得多慢。
   这张表落在 `entity/config/emotion_profile.json`，可手工改。

数据：
- `entity/emotion/intensity_table.json`  档位原话（单一真源）
- `entity/emotion/state.json`            当前强度 / 最近事件 / 习惯化计数
- `entity/emotion/events.jsonl`          事件流水
- `entity/config/emotion_profile.json`   性格 → 起始值 / 敏感度
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import settings as S
from . import emotion_bridge as bridge

DIR = S.ENTITY / "emotion"
TABLE_PATH = DIR / "intensity_table.json"
STATE_PATH = DIR / "state.json"
EVENTS_PATH = DIR / "events.jsonl"
PROFILE_PATH = S.ENTITY / "config" / "emotion_profile.json"

# 内部单位：0~1000 的「激活度」，500 = 基线。界面只做一次线性换算。
UNIT_MIN, UNIT_MAX = 0.0, 1000.0
NEUTRAL = 500.0

# 界面展示刻度（只在 UI / display 字段里用，不参与存储和计算）
DISPLAY_MIN, DISPLAY_MAX = -10.0, 100.0
SAN_MIN, SAN_MAX = -100.0, 100.0

# 规则/刺激里的 delta 是 0~1 的“比例”，落库时换算成展示点
UNIT = 100.0

# 情绪键 → 表里的中文名（顺序与表一致）
EMOTIONS: List[tuple[str, str]] = [
    ("joy", "快乐/兴奋"),
    ("calm", "理智"),
    ("love", "爱/感激"),
    ("pride", "自豪/骄傲"),
    ("anger", "愤怒"),
    ("anxiety", "焦虑/担心"),
    ("fear", "恐惧/害怕"),
    ("sadness", "悲伤"),
    ("shame", "内疚/羞耻"),
    ("disgust", "厌恶/反感"),
    ("envy", "嫉妒/怨恨"),
    ("surprise", "惊讶/意外"),
    ("confusion", "困惑/矛盾"),
]
KEYS = [k for k, _ in EMOTIONS]
NAME = dict(EMOTIONS)

# 分型：界面按这个摆三栏
BASIC = ["joy", "sadness", "anger", "fear", "disgust", "surprise"]
COMPOUND = ["love", "pride", "anxiety", "shame", "envy", "confusion"]
BASELINE = ["calm"]
SAN_MIN, SAN_MAX = -100.0, 100.0
# 理智不是“越高越好”：-100 是完全崩溃，+100 是抽离/无情。
# 两端都只能渐近；-70 以下、+70 以上都不是日常状态。
CALM_MODEL = "calm-v2"
CALM_BANDS = [-70.0, -30.0, 0.0, 30.0, 70.0]
CALM_BAND_NAMES = ["完全崩溃", "崩溃边缘", "明显失衡", "还稳", "冷静", "抽离/无情"]
SAN_TEXT = [
    (-1e9, "几乎没了理智：想什么说什么，拦不住，也不管后果。"),
    (-70.0, "压不太住：容易上头，说话冲，事后也不一定后悔。"),
    (-30.0, "有点浮：嘴上比脑子快半拍。"),
    (0.0, "还稳：知道自己在说什么。"),
    (30.0, "很冷静：能按住脾气，也能把话说圆。"),
    (70.0, "冷得过头：几乎不起波澜，听起来像在讲别人的事。"),
]


def calm_level(p: float) -> int:
    """展示刻度（-100~100）→ 0..5 档；-70/+70 之外都不是好状态。"""
    p = float(p)
    n = 0
    for th in CALM_BANDS:
        if p >= th:
            n += 1
    return n


def san_sentence(v: float) -> str:
    return SAN_TEXT[calm_level(v)][1]

TYPE: Dict[str, str] = {**{k: "basic" for k in BASIC},
                        **{k: "compound" for k in COMPOUND},
                        **{k: "baseline" for k in BASELINE}}

# 半衰期（分钟）：愤怒来得快去得也快，爱能留很久，惊讶只闪一下
HALF_LIFE = {
    "joy": 40, "calm": 120, "love": 720, "pride": 120,
    "anger": 8, "anxiety": 25, "fear": 12, "sadness": 180, "shame": 40,
    "disgust": 30, "envy": 120, "surprise": 2, "confusion": 10,
}

# 档位阈值（内部单位）：展示点 20/45/70/90 → 600/725/850/950
BANDS = [600.0, 725.0, 850.0, 950.0]
BAND_NAMES = ["几乎没有", "有一点", "明显", "很强", "到顶了"]

# 互相抑制：(弱的, 被压的, 权重)
INHIBIT = [
    ("anger", "anxiety", 0.35),
    ("love", "anger", 0.20),
    ("calm", "anxiety", 0.25),
    ("calm", "fear", 0.30),
    ("love", "fear", 0.15),
    ("joy", "sadness", 0.20),
    ("shame", "anger", 0.15),
    ("disgust", "love", 0.15),
    ("pride", "shame", 0.10),
    ("confusion", "pride", 0.05),
]

# 到 L3/L4 时才给的"现在会怎么做"（不进表，是行为钩子）
ACTION_HINT = {
    "joy": "想分享，话可以多一点；没人接也别硬凑。",
    "calm": "不急不躁，别主动挑事。",
    "love": "想靠近，可以主动搭一句；别腻。",
    "pride": "想被看见，可以提一句自己干的活；不许自夸成推销。",
    "anger": "话短、直接，能不接的茬就不接；不许骂人、不许威胁。",
    "anxiety": "会想确认、想追问；别连环问。",
    "fear": "先退半步、想确认对方安不安全；别说狠话，也别逞强。",
    "sadness": "想独处，话少；主动开口先停一停。",
    "shame": "想躲，避开被提的那件事；别自嘲过头。",
    "disgust": "想远离这个话题，回应会冷；别损人。",
    "envy": "心里有点堵，嘴上别扎人；别翻旧账。",
    "surprise": "先停一下再回；可以用「啊？」「等一下」。",
    "confusion": "没想明白就反问，别硬答。",
}

# 最快的一层：关键词/句式（0 延迟）。delta 是"明显"级别的一次性涨幅。
RULES: List[tuple[str, str, float, str]] = [
    (r"你.{0,6}(笨|蠢|傻|废物|垃圾|没用)|脑子(坏|有病)|闭嘴|滚(开|蛋)?|别烦我|烦死", "anger", 0.42, "被骂"),
    (r"(真|太)?(棒|厉害|牛|强|聪明|可爱|好看|好听)了?|干得漂亮|不错啊|挺好的", "joy", 0.26, "被夸"),
    (r"喜欢你|爱你|想你|抱抱|亲亲|乖|宝贝|小家伙", "love", 0.30, "被亲近"),
    (r"谢谢|多谢|辛苦了|麻烦你了", "love", 0.18, "被感谢"),
    (r"对不起|抱歉|我错了|别生气", "calm", 0.22, "被道歉"),
    (r"哈哈|笑死|绷不住|太好笑|乐死", "joy", 0.16, "被逗"),
    (r"真的假的|居然|没想到|不会吧|卧槽|啊？", "surprise", 0.28, "意外"),
    (r"为什么|怎么办|咋办|不懂|没明白|什么意思|\?\?+", "confusion", 0.20, "没听懂"),
    (r"删了|封号|拉黑|举报|报警|完蛋|来不及了", "anxiety", 0.30, "威胁"),
    (r"失败|报错|崩了|挂了|没成功|又坏了", "sadness", 0.22, "受挫"),
    (r"成功了|搞定了|通了|过了|拿到了|赢了", "pride", 0.26, "成了"),
    (r"不理你|不想说|随便你|算了|无所谓", "sadness", 0.20, "被晾"),
    (r"你(好)?恶心|讨厌你|受不了你|烦人", "disgust", 0.30, "被嫌"),
    (r"别人(家|的)?的?(机器人|无名|助手)|你看人家", "envy", 0.26, "被比较"),
    (r"你(自己)?(说|觉得)呢|你猜|不知道", "confusion", 0.10, "被反问"),
    (r"有(血|刀|枪)|流(血|好多血)|死人|尸体|杀人|恐怖|吓死|吓人|太可怕|好可怕", "fear", 0.40, "被吓到"),
    (r"你敢|弄死你|打死你|揍你|报警抓你|删了你|封了你|别让我看见你", "fear", 0.34, "被威胁"),
    # 理智的负向：辱骂、威胁、冷落、抛弃会把 calm 往下拽
    (r"你.{0,6}(笨|蠢|傻|废物|垃圾|没用)|脑子(坏|有病)|闭嘴|滚(开|蛋)?|别烦我|烦死", "calm", -0.06, "被骂"),
    (r"你敢|弄死你|打死你|揍你|报警抓你|删了你|封了你|别让我看见你", "calm", -0.07, "被威胁"),
    (r"不理你|不想说|随便你|算了|无所谓|闭嘴吧", "calm", -0.03, "被晾"),
    (r"分手|离开你|不要你|再也不想见|滚出去|永远别回来", "calm", -0.08, "被抛弃"),
]

# 事件 → 情绪（世界给她的刺激）
STIMULI = {
    "owner_msg": [("love", 0.03), ("calm", 0.01)],
    "other_msg": [("calm", 0.005)],
    "group_msg": [("calm", 0.005)],
    "qzone_like": [("pride", 0.10), ("joy", 0.08)],
    "qzone_reply": [("joy", 0.10), ("surprise", 0.04)],
    "video": [("calm", 0.02)],
    "sticker": [("joy", 0.03)],
    "idle": [("calm", 0.01)],
    "error": [("anxiety", 0.14), ("confusion", 0.08)],
    "success": [("pride", 0.14), ("joy", 0.10)],
    "neglect": [("sadness", 0.06), ("calm", -0.02)],
    # 话说了一半被打断：剩下几句咽回去。只登记一次，不按句数叠。
    "cut_off": [("surprise", 0.05), ("shame", 0.04), ("sadness", 0.03),
                ("love", 0.02), ("calm", -0.01)],
    "threat": [("fear", 0.40), ("anxiety", 0.15), ("calm", -0.05)],
    "humiliation": [("shame", 0.30), ("anger", 0.20), ("calm", -0.06)],
    "betrayal": [("sadness", 0.35), ("anger", 0.25), ("calm", -0.08)],
    "horror": [("fear", 0.30)],
}

# --------------------------------------------------------------------- 性格表
# 16 套人设的底表在 persona_styles.py（主人在《性格配置再优化》里定的那份口径）。
# 这里的 _SEEDS / _PROFILE 只是把它摊成「按名字取初始值 / 敏感度」的形状；
# entity/config/emotion_profile.json 里的同名项仍然可以逐项覆盖。
from . import persona_styles as P  # noqa: E402

_SEEDS: Dict[str, Dict[str, float]] = {name: dict(row["seeds"]) for name, row in P.STYLES.items()}
_PROFILE: Dict[str, Dict[str, Dict[str, float]]] = {
    name: {"delta": dict(row["delta"]), "half_life": dict(row["half_life"])}
    for name, row in P.STYLES.items()
}

# 老名字（0.3.9 之前的四套）指到最接近的新人设，免得已有档案突然退回「温柔」
_ALIASES: Dict[str, str] = {
    "温柔": "温柔共情",
    "理性": "清冷理智",
    "跳脱": "热烈乐天",
}
for _old, _new in _ALIASES.items():
    _SEEDS.setdefault(_old, _SEEDS[_new])
    _PROFILE.setdefault(_old, _PROFILE[_new])

_DEFAULT_PROFILE = {"version": 1, "note": "性格 → 起始值与敏感度；改这里会立刻生效",
                    "styles": _PROFILE, "seeds": _SEEDS}

_cache: Dict[str, Any] = {"at": 0.0, "doc": None}
_LLM_AT = 0.0


# --------------------------------------------------------------------- 性格 / 档案
def _style() -> str:
    try:
        style = str((S.llm_cfg() or {}).get("style") or "").strip()
    except Exception:
        style = ""
    style = _ALIASES.get(style, style)
    if style == "自定义":
        try:
            from . import style_box
            if style_box.active():
                return style
        except Exception:
            pass
        return "温柔共情"
    return style if style in _SEEDS else "温柔共情"


def profile() -> dict:
    """读性格表；没有就按默认写一份（改文件即可覆盖默认值）。"""
    try:
        mtime = PROFILE_PATH.stat().st_mtime
    except Exception:
        mtime = 0.0
    if _cache["doc"] is not None and mtime and mtime <= _cache["at"]:
        return _cache["doc"]
    doc = json.loads(json.dumps(_DEFAULT_PROFILE))
    try:
        raw = json.loads(PROFILE_PATH.read_text(encoding="utf-8-sig"))
        for part in ("styles", "seeds"):
            for style, val in (raw.get(part) or {}).items():
                doc[part].setdefault(style, {})
                if isinstance(val, dict):
                    for k, v in val.items():
                        doc[part][style][k] = v
    except FileNotFoundError:
        try:
            PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
            PROFILE_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    except Exception as e:
        S.log(f"[emotion] profile 读取失败，用默认：{e!r}")
    _cache.update({"at": time.time(), "doc": doc})
    return doc


def _sens(emo: str) -> float:
    try:
        base = float(((profile()["styles"].get(_style()) or {}).get("delta") or {}).get(emo, 1.0))
    except Exception:
        base = 1.0
    try:
        base *= float(bridge.rate(bridge.levels()).get(emo, 1.0))
    except Exception:
        pass
    return max(0.1, min(2.0, base))


def _hl(emo: str) -> float:
    try:
        mult = float(((profile()["styles"].get(_style()) or {}).get("half_life") or {}).get(emo, 1.0))
    except Exception:
        mult = 1.0
    return max(1.0, float(HALF_LIFE[emo]) * max(0.2, mult))


def _clamp_display(key: str, p: float) -> float:
    p = float(p)
    lo, hi = (SAN_MIN, SAN_MAX) if key == "calm" else (DISPLAY_MIN, DISPLAY_MAX)
    return max(lo, min(hi, p))


def _sanitize_calm_seed(p: float) -> float:
    """人格种子只负责“起点”：不允许一开局就站到 +70 的无情区。"""
    return max(-45.0, min(55.0, float(p)))


def calm_home_point(style: Optional[str] = None) -> float:
    """这套人格的理智基线（展示点）：decay 回这里，不是回 0。"""
    try:
        st = profile()["seeds"].get(style or _style()) or _SEEDS["温柔"]
        return _sanitize_calm_seed(float(st.get("calm", 0.0)))
    except Exception:
        return 0.0


def _calm_gain(p: float, eff: float) -> float:
    """软饱和：离 0 越远，同向事件越推不动；±70 外只能慢慢蹭过去。"""
    p = float(p)
    dist = max(0.0, p - 40.0) if eff > 0 else max(0.0, -p - 40.0)
    return max(0.0, 1.0 - dist / 60.0)


def seeds(style: Optional[str] = None) -> Dict[str, float]:
    st = profile()["seeds"].get(style or _style()) or _SEEDS["温柔"]
    pts = {k: float(st.get(k, 0.0)) for k in KEYS}
    try:
        for k, v in bridge.push(bridge.levels()).items():
            pts[k] = pts.get(k, 0.0) + v
    except Exception:
        pass
    if "calm" in pts:
        pts["calm"] = _sanitize_calm_seed(pts["calm"])
    return {k: to_unit(k, _clamp_display(k, pts.get(k, 0.0))) for k in KEYS}


# --------------------------------------------------------------------- 基础状态
def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _clamp(v: float) -> float:
    """夹到内部激活度 0~1000。"""
    v = float(v)
    return max(UNIT_MIN, min(UNIT_MAX, v))


def to_unit(key: str, p: float) -> float:
    """展示点 → 内部激活度（0~1000，500 为基线）。"""
    p = float(p)
    if key == "calm":
        v = NEUTRAL + p * 5.0
    else:
        v = NEUTRAL + (p * 50.0 if p < 0 else p * 5.0)
    return _clamp(v)


def from_unit(key: str, v: float) -> float:
    """内部激活度 → 展示点（普通 -10~100；理智 -100~100）。"""
    v = _clamp(v)
    if key == "calm":
        p = (v - NEUTRAL) / 5.0
        return max(SAN_MIN, min(SAN_MAX, p))
    if v < NEUTRAL:
        p = (v - NEUTRAL) / 50.0
        return max(DISPLAY_MIN, min(0.0, p))
    p = (v - NEUTRAL) / 5.0
    return max(0.0, min(DISPLAY_MAX, p))


def display_value(key: str, v: float) -> float:
    """给用户看的刻度：普通 -10~100；理智 -100~100。"""
    return round(from_unit(key, v), 1)


def display_values(st: Optional[dict] = None) -> Dict[str, float]:
    st = st or load()
    return {k: round(from_unit(k, st["values"].get(k, NEUTRAL)), 1) for k in KEYS}


def _blank() -> dict:
    return {"values": {k: NEUTRAL for k in KEYS}, "updated_at": time.time(),
            "habit": {}, "pending": [], "last_event": "", "events_today": 0,
            "day": datetime.now().strftime("%Y-%m-%d"),
            "started": False, "started_at": "", "seed_style": "",
            "calm_model": CALM_MODEL, "calm_home": calm_home_point(),
            "unit": "act1000"}


def load() -> dict:
    try:
        st = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return _blank()
    vals = st.get("values") or {}
    if st.get("unit") != "act1000":
        # 0.4.37 及以前：values 是展示点（普通 -10~100，理智 -100~100）。
        # 迁到 0~1000 的内部激活度，用户看到的数值不变。
        vals = {k: to_unit(k, float(vals.get(k) or 0.0)) for k in KEYS}
        st["unit"] = "act1000"
    else:
        vals = {k: _clamp(float(vals.get(k, NEUTRAL))) for k in KEYS}
    st["values"] = vals
    if st.get("calm_model") != CALM_MODEL:
        p = from_unit("calm", vals["calm"])
        if p > 70.0:
            p = 55.0
        elif p < -70.0:
            p = -55.0
        vals["calm"] = to_unit("calm", p)
        st["calm_model"] = CALM_MODEL
    st.setdefault("calm_home", calm_home_point())
    st.setdefault("updated_at", time.time())
    st.setdefault("habit", {})
    st.setdefault("pending", [])
    st.setdefault("day", datetime.now().strftime("%Y-%m-%d"))
    st.setdefault("events_today", 0)
    st.setdefault("started", False)
    st.setdefault("seed_style", "")
    return st


def save(st: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    st["updated_at"] = time.time()
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def start(st: Optional[dict] = None) -> dict:
    """开局：按性格落一组起始值（只在第一次对话时调）。"""
    st = st or load()
    if st.get("started"):
        return st
    style = _style()
    st["values"] = seeds(style)
    st["started"] = True
    st["started_at"] = _now()
    st["seed_style"] = style
    st["calm_home"] = calm_home_point(style)
    st["calm_model"] = CALM_MODEL
    save(st)
    S.log(f"[emotion] 开局（{style}）：" + " ".join(f"{k}={st['values'][k]:.0f}" for k in KEYS))
    return st


def level(v: float) -> int:
    n = 0
    for th in BANDS:
        if v >= th:
            n += 1
    return n


def bands(st: Optional[dict] = None) -> Dict[str, int]:
    st = st or load()
    return {k: (calm_level(display_value(k, st["values"][k])) if k == "calm"
                else level(st["values"][k])) for k in KEYS}


# --------------------------------------------------------------------- 衰减 / 抑制
def decay(st: dict, now: Optional[float] = None) -> dict:
    now = now or time.time()
    dt_min = max(0.0, (now - float(st.get("updated_at") or now)) / 60.0)
    if dt_min < 0.05:
        return st
    calm_home = to_unit("calm", _sanitize_calm_seed(st.get("calm_home") or calm_home_point()))
    for k in KEYS:
        f = 0.5 ** (dt_min / _hl(k))
        target = calm_home if k == "calm" else NEUTRAL
        st["values"][k] = _clamp(target + (st["values"][k] - target) * f)
    st["updated_at"] = now
    return st


def inhibit(st: dict) -> dict:
    v = st["values"]
    for src, dst, w in INHIBIT:
        sp = from_unit(src, v[src])
        if sp <= 30.0:
            continue
        cut = 1.0 - w * min(1.0, max(0.0, sp) / UNIT)
        dp = _clamp_display(dst, from_unit(dst, v[dst]) * cut)
        v[dst] = to_unit(dst, dp)
    return st


# --------------------------------------------------------------------- 施加事件
def _habit_key(emo: str, why: str) -> str:
    return f"{emo}:{why}"


def _habit_factor(st: dict, key: str) -> float:
    rec = (st.get("habit") or {}).get(key) or {}
    n = int(rec.get("n") or 0)
    last = float(rec.get("last") or 0)
    if time.time() - last > 6 * 3600:
        return 1.0
    return max(0.2, 0.75 ** n)


def apply_event(st: dict, emo: str, delta: float, why: str = "",
                source: str = "appraisal", scale: float = 1.0) -> dict:
    """把一个事件施加到状态上，返回落盘后的记录。delta 是 0~1 的比例。"""
    if emo not in KEYS or delta == 0:
        return {}
    key = _habit_key(emo, why)
    factor = _habit_factor(st, key)
    eff = float(delta) * UNIT * float(scale) * factor * _sens(emo)
    if emo == "calm":
        eff *= _calm_gain(from_unit("calm", st["values"][emo]), eff)
    dp = _clamp_display(emo, from_unit(emo, st["values"][emo]) + eff)
    st["values"][emo] = to_unit(emo, dp)
    hb = st.setdefault("habit", {}).setdefault(key, {"n": 0, "last": 0})
    hb["n"] = int(hb.get("n") or 0) + 1
    hb["last"] = time.time()
    inhibit(st)
    rec = {"at": _now(), "emo": emo, "delta": round(eff, 1), "why": why, "source": source}
    try:
        EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(EVENTS_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    st["last_event"] = f"{NAME[emo]}：{why or source}"
    day = datetime.now().strftime("%Y-%m-%d")
    if st.get("day") != day:
        st["day"], st["events_today"] = day, 0
    st["events_today"] = int(st.get("events_today") or 0) + 1
    return rec


# --------------------------------------------------------------------- 规则层
def _scale(is_owner: bool) -> float:
    """主人说的话更算数（和 DA 阈值 0.68 / 0.30 一个口径）。"""
    return 1.0 if is_owner else 0.45


def appraise(text: str, is_owner: bool = True, sender_name: str = "") -> List[dict]:
    """关键词层：每条规则最多命中一次，取最强的那条。"""
    st = start(load())
    decay(st)
    hits: Dict[str, tuple] = {}
    for pat, emo, delta, why in RULES:
        if re.search(pat, text or ""):
            if emo not in hits or abs(delta) > abs(hits[emo][0]):
                hits[emo] = (delta, why)
    out = []
    for emo, (delta, why) in hits.items():
        rec = apply_event(st, emo, delta, why, source="rule", scale=_scale(is_owner))
        if rec:
            out.append(rec)
    save(st)
    return out


def note_message(text: str, is_owner: bool = True) -> dict:
    """一条新消息进来：先跑规则，再把原句放进 LLM 队列等细评。"""
    st = start(load())
    save(st)
    recs = appraise(text, is_owner)
    st = load()
    pend = st.setdefault("pending", [])
    pend.append({"text": (text or "")[:400], "owner": bool(is_owner), "at": _now()})
    st["pending"] = pend[-12:]
    save(st)
    return {"rule_events": recs, "pending": len(st["pending"])}


def stimulus(kind: str, intensity: float = 1.0, why: str = "") -> dict:
    st = start(load())
    decay(st)
    recs = []
    for emo, base in STIMULI.get(kind, []):
        rec = apply_event(st, emo, base * intensity, why or kind, source="stimulus")
        if rec:
            recs.append(rec)
    save(st)
    return {"events": recs}


# --------------------------------------------------------------------- LLM 细评（可选增强）
def _llm_chat(prompt: str) -> str:
    import httpx
    key = S.deepseek_key()
    base = S.deepseek_base()
    r = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "deepseek-chat", "temperature": 0.2, "max_tokens": 400,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=60.0,
    )
    r.raise_for_status()
    return (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "")


def llm_refine(force: bool = False) -> dict:
    """把攒着的消息交给模型识别（每 60 秒最多一批，失败不影响聊天）。"""
    global _LLM_AT
    st = load()
    pend = list(st.get("pending") or [])
    if not pend:
        return {"refined": 0}
    if not force and time.time() - _LLM_AT < 60:
        return {"refined": 0, "skipped": "too soon"}
    _LLM_AT = time.time()
    lines = "\n".join(
        f"{i+1}. [{'他' if p.get('owner') else '别人'}] {p.get('text')}"
        for i, p in enumerate(pend)
    )
    prompt = (
        "你在帮一个中文 QQ 角色识别「这些话让她产生了什么情绪」。\n"
        "可选情绪键：" + "、".join(f"{k}({NAME[k]})" for k in KEYS) + "\n"
        "对每条消息，判断她真正会起的情绪，强度 0.05–0.45（同一情绪重复出现要减弱）。\n"
        "只输出 JSON：{\"events\":[{\"i\":1,\"emo\":\"anger\",\"delta\":0.3,\"why\":\"八个字内\"}]}\n"
        "没有明显情绪就别输出那条。不要解释。\n\n" + lines
    )
    try:
        raw = _llm_chat(prompt)
        m = re.search(r"\{[\s\S]*\}", raw or "")
        data = json.loads(m.group(0)) if m else {}
    except Exception as e:
        S.log(f"[emotion] llm_refine failed: {e!r}")
        return {"refined": 0, "error": str(e)}
    n = 0
    for ev in (data.get("events") or [])[:12]:
        try:
            i = int(ev.get("i")) - 1
            emo = str(ev.get("emo") or "")
            delta = max(0.0, min(0.6, float(ev.get("delta") or 0)))
            if i < 0 or i >= len(pend) or emo not in KEYS:
                continue
            apply_event(st, emo, delta, str(ev.get("why") or "")[:12],
                        source="llm", scale=_scale(bool(pend[i].get("owner"))))
            n += 1
        except Exception:
            continue
    st["pending"] = []
    save(st)
    S.log(f"[emotion] llm_refine: {n} events from {len(pend)} msgs")
    return {"refined": n}


# --------------------------------------------------------------------- 出口一：话
def _table_sentence(emo: str, lv: int) -> str:
    """档位原话（来自那张表）。"""
    try:
        doc = json.loads(TABLE_PATH.read_text(encoding="utf-8-sig"))
        for row in doc.get("emotions") or []:
            if row.get("emotion") == NAME[emo]:
                levels = row.get("levels") or []
                if 0 <= lv < len(levels):
                    return levels[lv]
    except Exception:
        pass
    return ""


def prompt_block(session: str = "web:owner") -> str:
    """给 LLM 的"此刻"：只给档位句子，不给数字。"""
    st = load()
    decay(st)
    save(st)
    vals = st["values"]
    top = sorted(((v, k) for k, v in vals.items() if k != "calm" and v >= BANDS[1]), reverse=True)[:3]
    san_line = f"- 理智：{san_sentence(display_value('calm', float(vals.get('calm') or NEUTRAL)))}"
    if not top:
        return "# 此刻\n- 情绪很淡，几乎不影响你说话。\n" + san_line
    lines = ["# 此刻（照这个说话，别报数字，也别解释情绪）"]
    for v, k in top:
        lv = level(v)
        sent = _table_sentence(k, lv)
        lines.append(f"- {NAME[k]}（{BAND_NAMES[lv]}）：{sent}")
        if lv >= 3 and k in ACTION_HINT:
            lines.append(f"  · {ACTION_HINT[k]}")
    # 傲娇面具：真实的强情绪可以嘴上不认，但行为照真值来
    if any(level(v) >= 3 for v, _ in top):
        lines.append("- 你可以嘴硬不承认，但别把行为演反了。")
    lines.append(san_line)
    return "\n".join(lines)


def mood_word() -> str:
    st = load()
    decay(st)
    vals = display_values(st)
    pos = sum(max(0.0, vals[k]) for k in ("joy", "calm", "love", "pride"))
    neg = sum(vals[k] for k in ("anger", "anxiety", "fear", "sadness", "shame", "disgust", "envy"))
    if pos < 15 and neg < 15:
        return "平平的"
    return "偏亮" if pos >= neg else "偏沉"


# --------------------------------------------------------------------- 出口二/三：行为与记忆
def gates() -> Dict[str, float]:
    """给 drives 用的闸门系数（1.0 = 不拦）。"""
    st = load()
    decay(st)
    v = display_values(st)
    g = {"reach": 1.0, "share": 1.0, "seek": 1.0, "explore": 1.0, "hide": 1.0}
    if v["anger"] >= 70:
        g["reach"] *= 0.20
        g["share"] *= 0.30
        g["hide"] *= 1.40
    if v["sadness"] >= 70:
        g["reach"] *= 0.30
        g["share"] *= 0.40
    if v["anxiety"] >= 70:
        g["reach"] *= 1.35
        g["seek"] *= 0.60
    if v["fear"] >= 70:
        g["hide"] *= 1.60
        g["reach"] *= 0.40
        g["seek"] *= 0.70
    if v["love"] >= 70:
        g["reach"] *= 1.40
        g["share"] *= 1.25
    if v["shame"] >= 60:
        g["share"] *= 0.20
        g["reach"] *= 0.60
    if v["disgust"] >= 60:
        g["explore"] *= 0.50
    if v["pride"] >= 70:
        g["share"] *= 1.30
    san = float(v.get("calm") or 0.0)
    if san <= -30:
        g["hide"] *= 0.55
        g["reach"] *= 1.25
        g["share"] *= 1.15
    elif san >= 30:
        g["hide"] *= 1.30
        g["share"] *= 0.80
    return g


def salient_event() -> Optional[dict]:
    """记忆用：最近一次"值得记住"的情绪事件（升幅 ≥35 点的那种）。"""
    try:
        lines = EVENTS_PATH.read_text(encoding="utf-8").splitlines()[-40:]
    except Exception:
        return None
    best = None
    for line in lines:
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if float(rec.get("delta") or 0) >= 35:
            best = rec
    return best


# --------------------------------------------------------------------- 对外
def state(include_recent: int = 5) -> dict:
    st = load()
    decay(st)
    save(st)
    recent = []
    try:
        for line in EVENTS_PATH.read_text(encoding="utf-8").splitlines()[-include_recent:]:
            recent.append(json.loads(line))
    except Exception:
        pass
    return {
        "values": {k: round(st["values"][k], 1) for k in KEYS},
        "display": display_values(st),
        "nt": bridge.levels() or {},
        "levels": bands(st),
        "band_names": {k: (CALM_BAND_NAMES[calm_level(display_value(k, st["values"][k]))]
                            if k == "calm" else BAND_NAMES[level(st["values"][k])])
                       for k in KEYS},
        "calm_home": round(calm_home_point(), 1),
        "calm_model": st.get("calm_model") or CALM_MODEL,
        "labels": {k: NAME[k] for k in KEYS},
        "types": TYPE,
        "order": {"basic": BASIC, "compound": COMPOUND, "baseline": BASELINE},
        "range": {"min": UNIT_MIN, "max": UNIT_MAX},
        "display_range": {"min": DISPLAY_MIN, "max": DISPLAY_MAX,
                          "calm_min": SAN_MIN, "calm_max": SAN_MAX},
        "started": bool(st.get("started")),
        "style": _style(),
        "mood": mood_word(),
        "gates": {k: round(v, 2) for k, v in gates().items()},
        "recent": recent,
        "events_today": int(st.get("events_today") or 0),
        "table": str(TABLE_PATH),
    }


def tick() -> dict:
    st = load()
    decay(st)
    try:
        lv = bridge.levels()
        if lv:
            for k, add in bridge.push(lv).items():
                if not add:
                    continue
                if k == "calm":
                    p = from_unit("calm", st["values"][k])
                    if abs(p) >= 60.0:
                        continue
                    add = max(-2.0, min(2.0, float(add)))
                dp = _clamp_display(k, from_unit(k, st["values"][k]) + add)
                st["values"][k] = to_unit(k, dp)
    except Exception as e:
        S.log(f"[emotion] 调质推力失败：{e!r}")
    save(st)
    out = {"ok": True}
    try:
        out.update(llm_refine())
    except Exception as e:
        out["refine_error"] = repr(e)
    return out


def reset(values: Optional[dict] = None) -> dict:
    st = _blank()
    if values:
        for k, v in values.items():
            if k in KEYS:
                st["values"][k] = _clamp(v)
    save(st)
    return state()
