"""桥文档一致性：能力表和事件表必须由代码生成，不许手写。

背景（0.6.5 自查）：
    README 写"桥的 22 项能力"，bridge.py 里实际是 32 项；docs/BRIDGE.md
    的"能力清单（v1）"表只有 5 行（v1 刚落地时的首批能力），后来加了
    audio/warehouse/vision/persona 等一批，表没跟着长。模组作者照文档申请
    能力，就会一直 403 —— 这是文档漂移里代价最高的一种。

用法：
    python tools\\test_bridge_doc.py            # 检查（默认）
    python tools\\test_bridge_doc.py --write    # 按 bridge.py 重写能力表和事件表
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parent.parent
ENTITY = ROOT / "WiseEntity" / "entity"
BRIDGE_MD = ROOT / "docs" / "BRIDGE.md"
README = ROOT / "README.md"

SEC_CAPS = "## 四、能力清单（v1）"
SEC_EVENTS = "## 五、事件（v1）"

FAILED: List[str] = []
PASSED = 0


def check(ok: bool, label: str) -> None:
    global PASSED
    if ok:
        PASSED += 1
        print(f"  PASS {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL {label}")


def _caps():
    sys.path.insert(0, str(ENTITY))
    from core import bridge  # noqa: PLC0415

    return bridge.CAPS, list(bridge.EVENT_KINDS)


def _render_caps(caps) -> str:
    lines = ["| 能力 | 参数 | 说明 |", "|---|---|---|"]
    for name in sorted(caps):
        spec = caps[name]
        args = ", ".join(f"`{a}`" for a in (spec.get("args") or {})) or "—"
        desc = str(spec.get("desc") or "").strip() or "—"
        lines.append(f"| `{name}` | {args} | {desc} |")
    return "\n".join(lines)


def _render_events(events) -> str:
    return "、".join(f"`{e}`" for e in events)


def _splice(text: str, section: str, body: str, stop_at: str) -> str:
    start = text.index(section) + len(section)
    end = text.index(stop_at, start)
    return text[:start] + "\n\n" + body + "\n\n" + text[end:]


def write() -> int:
    caps, events = _caps()
    text = BRIDGE_MD.read_text(encoding="utf-8-sig")
    text = _splice(text, SEC_CAPS, _render_caps(caps), SEC_EVENTS)
    text = _splice(text, SEC_EVENTS, _render_events(events), "## 六、")
    BRIDGE_MD.write_text(text, encoding="utf-8")

    readme = README.read_text(encoding="utf-8-sig")
    readme = re.sub(r"桥的 \d+ 项能力", f"桥的 {len(caps)} 项能力", readme)
    README.write_text(readme, encoding="utf-8")
    print(f"  已重写 {BRIDGE_MD.name}（{len(caps)} 项能力 / {len(events)} 个事件）与 README 计数")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="桥文档一致性检查")
    ap.add_argument("--write", action="store_true", help="按代码重写文档里的能力表与事件表")
    args = ap.parse_args()
    if args.write:
        return write()

    caps, events = _caps()
    text = BRIDGE_MD.read_text(encoding="utf-8-sig")

    table = text.split(SEC_CAPS)[1].split(SEC_EVENTS)[0]
    documented = set(re.findall(r"^\| `([a-z][a-z0-9_.]*)` \|", table, flags=re.MULTILINE))
    check(
        documented == set(caps),
        "BRIDGE.md 能力表与代码一致"
        + (
            ""
            if documented == set(caps)
            else "：缺 " + "、".join(sorted(set(caps) - documented))
            + "；多 " + "、".join(sorted(documented - set(caps)))
        ),
    )

    events_doc = text.split(SEC_EVENTS)[1].split("## 六、")[0]
    documented_events = set(re.findall(r"`([a-z][a-z0-9_.]*)`", events_doc))
    check(
        documented_events == set(events),
        "BRIDGE.md 事件表与代码一致"
        + ("" if documented_events == set(events) else f"：差 {documented_events ^ set(events)}"),
    )

    readme_text = README.read_text(encoding="utf-8-sig")
    m = re.search(r"桥的 (\d+) 项能力", readme_text)
    check(
        bool(m) and int(m.group(1)) == len(caps),
        f"README 的能力数等于实际 {len(caps)} 项（文档写 {m.group(1) if m else '缺'}）",
    )

    if FAILED:
        print("\n失败：")
        for label in FAILED:
            print(" -", label)
        print("\n修法：python tools\\test_bridge_doc.py --write")
        return 1
    print(f"\n全部 {PASSED} 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
