# -*- coding: utf-8 -*-
r"""胃（stomach）回归测试：口径、找 key、外壳读法。

跑法（venv）：
    .\.venv\Scripts\python.exe tools\test_stomach.py
退出码 0 = 全过。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT / "WiseEntity" / "capability" / "stomach" / "stomach.py"

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def load_stomach():
    """按文件路径加载，避免依赖包结构。"""
    spec = importlib.util.spec_from_file_location("xiaochen_stomach_test", CAP)
    assert spec and spec.loader, "stomach.py not found"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    st = load_stomach()

    # 1) 阈值口径：>=10 饱，<=3 饿，中间不饿
    check(st.level_of(10.0) == "full", "10.00 元 -> full（饱）")
    check(st.level_of(12.5) == "full", "12.50 元 -> full（饱）")
    check(st.level_of(9.99) == "normal", "9.99 元 -> normal（不饿）")
    check(st.level_of(3.01) == "normal", "3.01 元 -> normal（不饿）")
    check(st.level_of(3.0) == "hungry", "3.00 元 -> hungry（饿）")
    check(st.level_of(0.4) == "hungry", "0.40 元 -> hungry（饿）")

    # 2) 找 key：BAB 自己的 llm.json 优先（0.3.x 里没有 AstrBot 了）
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        llm = tmp / "llm.json"
        llm.write_text(json.dumps({"api_key": "  sk-bab-key  ", "model": "deepseek-chat"}),
                       encoding="utf-8")
        missing_astrbot = tmp / "nope.json"
        st.LLM_CFG = str(llm)
        st.CFG_PATH = str(missing_astrbot)
        check(st.api_key() == "sk-bab-key", "从 BAB 的 entity\\config\\llm.json 读 key（去掉空格）")

        # 3) llm.json 没有 key 时，退回旧的 AstrBot 配置
        llm.write_text(json.dumps({"api_key": "", "model": "deepseek-chat"}), encoding="utf-8")
        legacy = tmp / "cmd_config.json"
        legacy.write_text(json.dumps({"provider_sources": [{"api_key": ["sk-legacy"]}]}),
                          encoding="utf-8")
        st.CFG_PATH = str(legacy)
        check(st.api_key() == "sk-legacy", "BAB 没配 key 时退回 AstrBot 的 cmd_config.json")

        # 4) 两个都没有 -> 空串（调用方据此写 unknown）
        llm.write_text(json.dumps({"api_key": ""}), encoding="utf-8")
        st.CFG_PATH = str(missing_astrbot)
        check(st.api_key() == "", "两处都没 key -> 空串")

    # 5) 外壳读法：内核 /stomach 回的是 {"state": {...}, "fragment": ...}
    sys.path.insert(0, str(ROOT))
    from app.ui.pages.details import stomach_state  # noqa: E402

    nested = {"state": {"level": "normal", "balance": 9.8}, "fragment": "肚子：不饿"}
    got = stomach_state({"ok": True, "stomach": nested})
    check(got.get("level") == "normal" and got.get("balance") == 9.8,
          "嵌套的 {\"state\": ...} 能解开（这是详情页一直显示 — 的原因）")

    flat = {"level": "hungry", "balance": 2.1}
    check(stomach_state({"ok": True, "stomach": flat}).get("level") == "hungry",
          "旧的扁平写法仍然认")

    check(stomach_state({}) == {}, "没这个字段时返回空 dict，不抛")
    check(stomach_state({"stomach": None}) == {}, "stomach 为 null 时也不抛")

    # 6) 分界可配：entity\config\stomach.json
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cfg = tmp / "stomach.json"
        st.CFG = str(cfg)

        cfg.write_text(json.dumps({"full_at": 5.0, "hungry_at": 2.0}), encoding="utf-8")
        check(st.thresholds() == (5.0, 2.0), "读到自定义分界 (5.0, 2.0)")
        check(st.level_of(5.0) == "full", "自定义：5.00 元 -> full（饱）")
        check(st.level_of(2.0) == "hungry", "自定义：2.00 元 -> hungry（饿）")
        check(st.level_of(3.0) == "normal", "自定义：3.00 元 -> normal（不饿）")

        cfg.write_text(json.dumps({"full_at": 1.0, "hungry_at": 3.0}), encoding="utf-8")
        check(st.thresholds() == (st.DEFAULT_FULL_AT, st.DEFAULT_HUNGRY_AT),
              "饱线 <= 饿线的坏配置 -> 退回默认 (10, 3)")

        cfg.write_text("{ 这不是 json", encoding="utf-8")
        check(st.thresholds() == (st.DEFAULT_FULL_AT, st.DEFAULT_HUNGRY_AT),
              "文件坏了 -> 退回默认，不抛")

        cfg.unlink()
        check(st.thresholds() == (st.DEFAULT_FULL_AT, st.DEFAULT_HUNGRY_AT),
              "文件不存在 -> 默认")

    # 7) 掉到「饿」时往保姆栏报一次（只报一次）
    sys.path.insert(0, str(ROOT / "WiseEntity" / "entity"))
    import core.chat_core as chat_core  # noqa: E402
    import core.stomach_box as sb  # noqa: E402

    pushed: list[str] = []
    orig_push = chat_core.push_notice
    chat_core.push_notice = lambda session, text, kind="nanny": pushed.append(text)
    want = {"level": "normal"}
    prev = {"level": "normal"}          # 模拟 stomach.json 里上一次的结果

    class FakeMod:
        CFG = str(ROOT / "WiseEntity" / "entity" / "config" / "stomach.json")

        def poll(self):
            out = {"level": want["level"], "balance": 1.5, "error": ""}
            prev["level"] = out["level"]      # poll 会写文件
            return out

    orig_mod, orig_state = sb._mod, sb.state
    sb._mod = FakeMod()
    sb.state = lambda: dict(prev)
    try:
        want["level"] = "hungry"
        sb.poll()
        check(len(pushed) == 1 and "肚子饿了" in pushed[0] and "1.50" in pushed[0],
              "从「不饿」掉到「饿」-> 保姆栏报一条（带余额）")
        sb.poll()
        check(len(pushed) == 1, "还是饿着 -> 不重复刷")
        want["level"] = "normal"
        sb.poll()
        want["level"] = "hungry"
        sb.poll()
        check(len(pushed) == 2, "回饱之后再饿 -> 再报一次")
    finally:
        chat_core.push_notice = orig_push
        sb._mod, sb.state = orig_mod, orig_state

    print()
    if fails:
        print(f"FAILED {len(fails)} / {len(fails) + 16 - 0}")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS 胃的口径、找 key、外壳读法都对")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
