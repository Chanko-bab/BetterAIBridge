"""自我系统：证据、档案、经历/账本/校准、反思调度。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from WiseEntity.entity.core import self_store  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="bab_self_"))
    keys = ("SELF_DIR", "SELF_MD", "EVIDENCE", "EPISODES", "NARRATIVE", "LEDGER",
            "CALIBRATIONS", "VERSIONS", "REFLECT_STATE")
    orig = {k: getattr(self_store, k) for k in keys}
    try:
        self_store.SELF_DIR = tmp / "self"
        self_store.SELF_MD = self_store.SELF_DIR / "self.md"
        self_store.EVIDENCE = self_store.SELF_DIR / "evidence.jsonl"
        self_store.EPISODES = self_store.SELF_DIR / "episodes.md"
        self_store.NARRATIVE = self_store.SELF_DIR / "narrative.md"
        self_store.LEDGER = self_store.SELF_DIR / "ledger.md"
        self_store.CALIBRATIONS = self_store.SELF_DIR / "calibrations.md"
        self_store.VERSIONS = self_store.SELF_DIR / "versions"
        self_store.REFLECT_STATE = tmp / "reflect.json"
        self_store.ensure()

        check(not self_store.has_self(), "初始没有自我档案")
        block = self_store.evidence_block(["look_around", "avatar_see"])
        check("还没有真正试过" in block, "没证据时照实说")
        check("look_around" in block and "avatar_see" in block, "列出没试过的能力")

        self_store.record_tool("look_around", {"question": "在不在"},
                               {"ok": True, "result": {"text": "看到书桌和窗户"}})
        block = self_store.evidence_block(["look_around", "avatar_see"])
        check("我用过「look_around」" in block, "成功证据写进来")
        check("看到书桌和窗户" in block, "证据带摘要")
        check("avatar_see" in block, "未试过的仍在清单")

        self_store.record_tool("avatar_see", {}, {"ok": False, "error": "图太大"})
        block = self_store.evidence_block(["look_around", "avatar_see"])
        check("试过「avatar_see」" in block and "没成" in block, "失败也记，不冒充会")

        prompt = self_store.prompt_block(["look_around"])
        check("这是我自己写的" in prompt, "提示词标明作者权")
        check("证据" in prompt and "系统清单" in prompt, "证据与系统清单分开")

        ok, why = self_store.save_self("# 我是谁\n我是小雨。\n# 我认的\n我答应过不敷衍你。\n"
                                       "# 我正在学\n先问再看。\n# 最后更新\n2026-11-05")
        check(not ok and "你" in why, "档案里出现「你」被拒")
        good = ("# 我是谁\n我是小雨，住在这台电脑里。\n"
                "# 我认的\n答应过的事要记住。\n"
                "# 我正在学\n先问一句，再看。\n"
                "# 最后更新\n2026-11-05")
        ok, why = self_store.save_self(good, reason="test")
        check(ok, f"合法第一人称档案写入（{why}）")
        check(self_store.has_self(), "写入后可读")
        check("# 我是谁" in self_store.self_text(), "档案是全文")

        self_store.apply_reflection({
            "self_update": good + "\n我学会先看证据。",
            "episode": {"title": "第一次看", "body": "我选了看一眼，结果看到她在。"},
            "ledger_add": ["答应过：先问再看"],
            "calibration": "原以为她不在；其实她在；下次先问。",
        })
        check("第一次看" in self_store._read(self_store.EPISODES), "经历写入")
        check("先问再看" in self_store._read(self_store.LEDGER), "账本写入")
        check("原以为" in self_store._read(self_store.CALIBRATIONS), "校准写入")
        self_store.close_ledger("先问")
        check("先问再看" not in self_store._read(self_store.LEDGER), "账本可关闭")

        ok, why = self_store.save_narrative("我以前只会背清单，后来学会先看证据。")
        check(ok, "叙事可以写入")
        check("背清单" in self_store.prompt_block([]), "叙事进提示词")
        ok, why = self_store.save_narrative("你告诉我该怎么做。")
        check(not ok and "你" in why, "叙事里出现「你」被拒")

        self_store.observe_exchange("不对，你记错了，我说过别叫我小雨。",
                                    "我答应下次先叫您姐姐。")
        check("对方纠正我" in self_store._read(self_store.CALIBRATIONS), "纠正自动落校准")
        check("我答应过" in self_store._read(self_store.LEDGER), "答应自动落账本")

        self_store.apply_reflection({"narrative": "我从一次被纠正里学会先问再叫。"})
        check("先问再叫" in self_store.narrative_text(), "反思可更新叙事")
        check(self_store.status()["narrative"] > 0, "状态带叙事长度")

        self_store.REFLECT_STATE.unlink(missing_ok=True)
        check(not self_store.due(), "没有轮次不反思")
        for _ in range(self_store.REFLECT_EVERY):
            self_store.note_turn()
        check(self_store.due(), "到轮次后 due")
        self_store.mark_reflected()
        check(not self_store.due(), "反思后重置")
        check(self_store.status()["evidence"] >= 2, "status 带证据数")
    finally:
        for k, v in orig.items():
            setattr(self_store, k, v)
    print("\nPASS" if not fails else f"\n{len(fails)} 条失败")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
