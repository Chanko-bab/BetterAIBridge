# -*- coding: utf-8 -*-
"""自定义性格：本地兜底分析、脸谱规格、应用/恢复、桥能力。"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "WiseEntity"))

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def main() -> int:
    from entity.core import bridge, llm_box, style_box

    tmp = Path(tempfile.mkdtemp(prefix="bab-style-"))
    style_box.PATH = tmp / "custom_style.json"
    style_box.PROFILE_PATH = tmp / "emotion_profile.json"
    style_box.LLM_PATH = tmp / "llm.json"

    async def _boom(*_a, **_k):
        raise llm_box.NotConfigured("没 Key")

    llm_box._ask = _boom  # type: ignore[assignment]

    doc = asyncio.run(style_box.analyze("她嘴硬心软，被夸会脸紅，生气时先沉默。"))
    check(doc["engine"] == "local", "没有 Key 时走本地兜底")
    check(set(doc["seeds"]) == set(style_box.KEYS), "13 个 seed 都在")
    check(-10 <= doc["seeds"]["joy"] <= 100, "seed 量程合法")
    check(0.2 <= doc["delta"]["anger"] <= 1.4, "delta 量程合法")
    check(bool(doc["summary"]), "有 summary")

    raw = {"seeds": {"joy": 999, "calm": -999}, "delta": {"joy": 99}, "half_life": {"joy": 0}}
    n = style_box.normalize(raw)
    check(n["seeds"]["joy"] == 100 and n["seeds"]["calm"] == -10, "seed 超界被夹")
    check(n["delta"]["joy"] == 1.4 and n["half_life"]["joy"] == 0.7, "delta/half_life 超界被夹")

    warm = style_box.face_spec({"seeds": {"love": 50, "joy": 30}, "delta": {}})
    cool = style_box.face_spec({"seeds": {"anger": 40, "disgust": 30, "love": 0}, "delta": {}})
    check(warm["warmth"] > cool["warmth"], "暖性格脸更暖")
    check(warm["mouth"] == "smile", "暖性格是笑嘴")
    check(cool["mouth"] in ("flat", "pout"), "冷性格不笑")
    check(warm["hair"].startswith("#") and len(warm["hair"]) == 7, "发色是 #rrggbb")
    check(style_box.face_spec(warm) == style_box.face_spec(warm), "同一份规格脸谱一致")

    style_box.apply(doc)
    check(style_box.PATH.is_file(), "apply 写了 custom_style.json")
    prof = json.loads(style_box.PROFILE_PATH.read_text(encoding="utf-8"))
    check("自定义" in prof.get("styles", {}), "profile 里有自定义的 delta")
    check("自定义" in prof.get("seeds", {}), "profile 里有自定义的 seeds")
    llm = json.loads(style_box.LLM_PATH.read_text(encoding="utf-8"))
    check(llm.get("style") == "自定义", "llm.json 的 style 改成自定义")
    check(style_box.active(), "active() 为真")
    frag = style_box.fragment()
    check("我的性格" in frag and doc["summary"][:6] in frag, "提示词里有性格段")

    info = bridge._persona_style_get("m_test")
    check(info["ok"] and info["style"]["summary"] == doc["summary"], "桥 persona.style.get")
    fc = bridge._persona_face_get("m_test")
    check(fc["ok"] and 0 <= fc["warmth"] <= 1, "桥 persona.face.get")
    check("persona.style.get" in bridge.CAPS and "persona.face.get" in bridge.CAPS,
          "CAPS 里有性格和脸谱")

    style_box.clear()
    check(not style_box.active(), "clear 后不再 active")
    prof = json.loads(style_box.PROFILE_PATH.read_text(encoding="utf-8"))
    check("自定义" not in prof.get("styles", {}), "clear 移除了 profile 自定义项")
    llm = json.loads(style_box.LLM_PATH.read_text(encoding="utf-8"))
    check(llm.get("style") == "温柔共情", "clear 把性格退回温柔共情")

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if fails:
        print(f"FAILED {len(fails)}")
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
