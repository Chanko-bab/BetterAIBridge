# -*- coding: utf-8 -*-
"""自定义性格：把一段文字分析成 13 维情绪参数，并给出一张“脸谱”的规格。

存两处：
- `entity/config/custom_style.json`：这份性格本身（summary / logic / seeds / delta / half_life）；
- `entity/config/emotion_profile.json` 里加一个 `自定义` 的 styles/seeds 段，情绪引擎直接读它；
- `entity/config/llm.json` 的 `style` 改成 `自定义`，提示词与情绪都跟着走。

没有模型 Key 时用本地关键词兜底（挑最接近的 16 套底表），保证功能可用。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

from . import settings as S
from .persona_styles import KEYS, STYLES

PATH = S.ENTITY / "config" / "custom_style.json"
PROFILE_PATH = S.ENTITY / "config" / "emotion_profile.json"
LLM_PATH = S.ENTITY / "config" / "llm.json"
NAME = "自定义"

EMO_CN = {
    "joy": "开心", "calm": "理智", "love": "喜欢", "pride": "自豪",
    "anger": "生气", "anxiety": "焦虑", "fear": "害怕", "sadness": "难过",
    "shame": "羞耻", "disgust": "厌恶", "envy": "嫉妒", "surprise": "惊讶",
    "confusion": "困惑",
}

# 本地兜底：关键词 -> 16 套里最接近的一套
_LOCAL_HINTS = [
    (("傲娇", "嘴硬", "别扭", "不坦率"), "傲娇"),
    (("雌小鬼", "挑衅", "捉弄", "小鬼"), "雌小鬼"),
    (("软萌", "撒娇", "粘人", "夹子"), "软萌夹子"),
    (("腹黑", "算计", "看戏"), "腹黑"),
    (("毒舌", "吐槽", "刻薄"), "毒舌"),
    (("小恶魔", "顽皮", "恶作剧"), "小恶魔"),
    (("温柔", "体贴", "共情", "照顾"), "温柔共情"),
    (("清冷", "理性", "冷淡", "疏离"), "清冷理智"),
    (("活泼", "开朗", "乐观", "热烈"), "热烈乐天"),
    (("敏感", "多想", "不安", "自卑"), "内敛敏感"),
    (("暴躁", "直率", "火爆", "冲动"), "直率火爆"),
    (("佛系", "淡然", "懒", "无所谓"), "佛系淡然"),
    (("自律", "强势", "克制", "计划"), "强势自律"),
    (("病娇", "占有", "偏执的爱"), "病娇"),
    (("悲观", "厌世", "丧"), "悲观厌世"),
    (("研究", "求知", "钻牛角尖"), "偏执研究者"),
]


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _num(v: Any, lo: float, hi: float, default: float) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except Exception:
        return default


def normalize(raw: Dict[str, Any]) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    seeds = raw.get("seeds") if isinstance(raw.get("seeds"), dict) else {}
    delta = raw.get("delta") if isinstance(raw.get("delta"), dict) else {}
    half = raw.get("half_life") if isinstance(raw.get("half_life"), dict) else {}
    out = {
        "version": 1,
        "name": str(raw.get("name") or NAME)[:12],
        "summary": str(raw.get("summary") or "").strip()[:400],
        "logic": str(raw.get("logic") or "").strip()[:300],
        "source": str(raw.get("source") or "").strip()[:2000],
        "created_at": str(raw.get("created_at") or time.strftime("%Y-%m-%d %H:%M:%S")),
        "engine": str(raw.get("engine") or ""),
        "seeds": {k: round(_num(seeds.get(k), -10, 100, 0), 1)
                  for k in KEYS},
        "delta": {k: round(_num(delta.get(k), 0.2, 1.4, 0.7), 2) for k in KEYS},
        "half_life": {k: round(_num(half.get(k), 0.7, 1.2, 1.0), 2) for k in KEYS},
    }
    return out


def load() -> Optional[Dict[str, Any]]:
    doc = _read(PATH, None)
    if not isinstance(doc, dict):
        return None
    return normalize(doc)


def active() -> bool:
    return load() is not None


def face_spec(doc: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    d = doc or load() or normalize({})
    s = d.get("seeds") or {}

    def g(k: str) -> float:
        try:
            return float(s.get(k, 0) or 0)
        except Exception:  # noqa: BLE001
            return 0.0

    def c(v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    warmth = c((g("love") + g("joy") * 0.55 - g("anger") * 0.8 - g("disgust") * 0.8) / 55.0)
    energy = c((g("joy") + g("surprise") + g("pride") * 0.5 - g("calm") * 0.35 + 12) / 85.0)
    order = c((g("calm") - g("confusion") * 0.8 + 18) / 85.0)
    sensitivity = c((g("anxiety") + g("fear") + g("sadness") + g("shame") + 10) / 85.0)

    def mix(a: str, b: str, t: float) -> str:
        ar, ag, ab = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
        br, bg, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
        return "#%02x%02x%02x" % (
            round(ar + (br - ar) * t), round(ag + (bg - ag) * t), round(ab + (bb - ab) * t))

    hair = mix("#7aa7ff", "#ff9d7a", warmth)
    accent = mix("#8fd3ff", "#ffcf6b", energy)
    mouth = "smile" if warmth >= 0.58 else ("flat" if warmth >= 0.35 else "pout")
    eyes = "round" if energy >= 0.6 else "soft"
    return {
        "name": d.get("name") or NAME,
        "summary": d.get("summary") or "",
        "logic": d.get("logic") or "",
        "warmth": round(warmth, 3),
        "energy": round(energy, 3),
        "order": round(order, 3),
        "sensitivity": round(sensitivity, 3),
        "hair": hair,
        "accent": accent,
        "skin": "#ffe6d6",
        "eyes": eyes,
        "mouth": mouth,
        "blush": sensitivity >= 0.55,
        "style": NAME if active() else "",
        "delta": {k: round(float((d.get("delta") or {}).get(k, 0.7) or 0.7), 2) for k in KEYS},
    }


def local(text: str) -> Dict[str, Any]:
    """不联网的关键词兜底：给自定义底子先配一套可用的 13 维参数。"""
    return _local(text)


def _local(text: str) -> Dict[str, Any]:
    t = str(text or "")
    picked = "温柔共情"
    for words, name in _LOCAL_HINTS:
        if any(w in t for w in words):
            picked = name
            break
    base = STYLES[picked]
    summary = t.strip().splitlines()[0][:120] if t.strip() else f"按「{picked}」的底子理解你写下的性格。"
    row = {
        "name": NAME, "summary": summary,
        "logic": f"参考「{picked}」的底表，按你写下的描述微调。",
        "seeds": base["seeds"], "delta": base["delta"], "half_life": base["half_life"],
        "source": t[:2000], "engine": "local",
    }
    return normalize(row)


_PROMPT = """你是一个性格参数分析器。把用户写下的性格描述，转成 13 个情绪维度的数值。

维度：joy 开心、calm 理智、love 喜欢、pride 自豪、anger 生气、anxiety 焦虑、fear 害怕、
sadness 难过、shame 羞耻、disgust 厌恶、envy 嫉妒、surprise 惊讶、confusion 困惑。

规则：
- seeds 是初始值：calm 取 -100~100，其余 -10~100；普通人在 0~20 之间，极端性格才更高。
- delta 是敏感度：0.2 极弱、0.4 弱、0.7 中、1.0 强、1.4 极强。
- half_life 是回落乘子：强/极强填 0.7（退得快），弱/极弱填 1.2（退得慢），中填 1.0。
- summary 一句话概括，logic 一句话说明这个性格在什么情况下会怎么反应。
- 只输出 JSON，不要代码块、不要解释。格式：
{"summary":"...","logic":"...","seeds":{"joy":0,...13 个},"delta":{"joy":0.7,...13 个},"half_life":{"joy":1.0,...13 个}}
"""


async def analyze(text: str) -> Dict[str, Any]:
    t = str(text or "").strip()
    if not t:
        raise ValueError("先写一段性格描述")
    if len(t) > 4000:
        t = t[:4000]
    try:
        from . import llm_box as _llm
        raw = await _llm._ask(
            [{"role": "system", "content": _PROMPT},
             {"role": "user", "content": t}],
            temperature=0.25, max_tokens=900)
    except Exception as e:  # noqa: BLE001 — 没 Key / 网络断，走本地
        S.log(f"[style] 分析回退本地：{e!r}")
        return _local(t)
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return _local(t)
    try:
        doc = json.loads(m.group(0))
    except Exception:
        return _local(t)
    doc.update({"name": NAME, "source": t, "engine": "llm"})
    return normalize(doc)


def apply(doc: Dict[str, Any]) -> Dict[str, Any]:
    d = normalize(doc)
    _write(PATH, d)
    # 情绪引擎读 profile；把自定义那一段写进去（不动其它 16 套）
    prof = _read(PROFILE_PATH, {})
    if not isinstance(prof, dict):
        prof = {}
    prof.setdefault("styles", {})[NAME] = {"delta": d["delta"], "half_life": d["half_life"]}
    prof.setdefault("seeds", {})[NAME] = d["seeds"]
    _write(PROFILE_PATH, prof)
    # 让她真的用这套性格
    llm = _read(LLM_PATH, {})
    if not isinstance(llm, dict):
        llm = {}
    llm["style"] = NAME
    llm["style_summary"] = d["summary"]
    _write(LLM_PATH, llm)
    S.log(f"[style] 应用自定义性格：{d['summary'][:40]}")
    return d


def clear() -> None:
    try:
        PATH.unlink()
    except FileNotFoundError:
        pass
    prof = _read(PROFILE_PATH, {})
    if isinstance(prof, dict):
        for part in ("styles", "seeds"):
            try:
                prof.get(part, {}).pop(NAME, None)
            except Exception:
                pass
        _write(PROFILE_PATH, prof)
    llm = _read(LLM_PATH, {})
    if isinstance(llm, dict) and str(llm.get("style") or "") == NAME:
        llm["style"] = "温柔共情"
        llm.pop("style_summary", None)
        _write(LLM_PATH, llm)


def fragment() -> str:
    d = load()
    if not d:
        return ""
    seeds = "、".join(f"{EMO_CN[k]}{d['seeds'][k]:.0f}" for k in KEYS)
    return (
        "## 我的性格（主人写的，按这个来）\n"
        f"{d['summary'] or '（没有一句话概括）'}\n"
        f"机制：{d['logic'] or '按上面的描述来。'}\n"
        f"情绪底子：{seeds}。\n"
        "不要自称“我有人格参数”，只按这个性格说话；被问起就用自己的话讲。"
    )
