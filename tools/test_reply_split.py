# -*- coding: utf-8 -*-
"""长回复分条：换行不是句号，硬切不能把半句话劈开（0.4.22 之前的早期 bug）。

用户截图：同一条回复被拆成「…背对着」和「坐。」两条气泡。
根因是 _SENT_END 带了换行、且攒满 42 字就无标点硬切。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTITY = ROOT / "WiseEntity" / "entity"


def entity_python() -> Path | None:
    for rel in ("Scripts/python.exe", "bin/python"):
        p = ENTITY / ".venv" / rel
        if p.exists():
            return p
    return None


def main() -> int:
    fails: list[str] = []

    def check(ok: bool, msg: str) -> None:
        print(("ok   " if ok else "FAIL ") + msg)
        if not ok:
            fails.append(msg)

    py = entity_python()
    if py is None:
        print("skip 内核：没有 WiseEntity/entity/.venv")
        return 0

    script = r'''
import json, sys
sys.path.insert(0, r"%s")
from core import chat_core as cc

shot = ("看到了，您正对着镜头，戴眼镜、穿蓝外套，后面是床铺和书桌，"
        "旁边还有个白衣的人背对着\n坐。")
plain42 = "这是一个刚好超过四十二个字但没有句号的长句子用来检查硬切边界看看会不会把半句话劈开"
long_punct = "第一句写得很长很长，长到需要分条才放得下，后面还有第二句。第二句也不短，继续说下去，再补一点内容。"
act = "〖抬了下眼皮〗您这段时间到底在忙些什么呢，我瞧着您好像一直没停下来过，要不要先歇一会儿？"
many = "这是一段没有句号只有逗号的很长文字，" * 6 + "最后收住。"

def norm(s):
    return s.replace("\n", "").replace(" ", "")

out = {
    "shot": cc.split_reply(shot),
    "plain42": cc.split_reply(plain42),
    "long_punct": cc.split_reply(long_punct),
    "act": cc.split_reply(act),
    "many": cc.split_reply(many),
}
out["shot_norm_equal"] = norm("".join(out["shot"])) == norm(shot)
out["plain_norm_equal"] = norm("".join(out["plain42"])) == norm(plain42)
out["punct_norm_equal"] = norm("".join(out["long_punct"])) == norm(long_punct)
out["many_norm_equal"] = norm("".join(out["many"])) == norm(many)
out["act_balanced"] = all(p.count("〖") == p.count("〗") for p in out["act"])
print(json.dumps(out, ensure_ascii=False))
''' % str(ENTITY)

    proc = subprocess.run([str(py), "-X", "utf8", "-c", script], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        check(False, f"调内核分条失败：{(proc.stderr or '').strip()[-500:]}")
    else:
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        shot = out["shot"]
        check(len(shot) == 1, f"带换行的截图句不拆条（实际 {len(shot)} 条：{shot}）")
        check(all(p.strip() != "坐。" for p in shot), "不会出现孤零零的「坐。」")
        check(out["shot_norm_equal"], "截图句分条后正文没丢字")

        p42 = out["plain42"]
        check(len(p42) == 1, f"四十几字、无句号不硬切（实际 {len(p42)} 条）")
        check(out["plain_norm_equal"], "四十几字分条后正文没丢字")

        lp = out["long_punct"]
        check(len(lp) <= 3, f"长句最多三条（实际 {len(lp)} 条）")
        check(out["punct_norm_equal"], "长句按句号分条、正文没丢字")
        check(all(len(p) <= 60 for p in lp), f"每条不超过 60 字（实际 {[len(p) for p in lp]}）")
        check(not any(len(p) < 6 for p in lp), f"没有过短残句（实际 {lp}）")

        check(out["act_balanced"], "动作〖…〗不会被劈成两半")
        check(out["many_norm_equal"], "超长无句号文本分条后正文没丢字")

    print(f"\n{len(fails)} 条失败" if fails else "\nPASS")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
