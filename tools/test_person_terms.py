"""称呼扫描：面向智能体的文字里只出现“对方”，不出现主人/用户/他/她。"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from WiseEntity.entity.core import (  # noqa: E402
    avatar, chat_core, drives, llm_box, presence, proactive,
    registry_box, sense, style_box, tool_bus, warehouse,
)

fails: list[str] = []
BAD = re.compile(r"主人|用户|(?<!其)他|她")


def check_text(where: str, text: str) -> None:
    hit = BAD.search(text or "")
    if hit:
        fails.append(f"{where}: {hit.group(0)} @ {text[:120]!r}")
        print(f"FAIL {where}: {hit.group(0)}")
    else:
        print(f"ok   {where}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="bab_terms_"))
    old = warehouse.ENTITY
    warehouse.ENTITY = tmp / "WiseEntity" / "entity"
    try:
        row = warehouse.put_bytes("owner", "猫.txt", b"cat", kind="document")
        warehouse.update_meta(row["id"], desc="一只猫的说明", tags=["猫", "示例"])
        warehouse.keep(row["id"], title="猫的说明", why="以后可能用得上")
        texts = {
            "presence": presence.fragment(),
            "avatar": avatar.fragment(),
            "sense": sense.fragment(),
            "style": style_box.fragment(),
            "registry": registry_box.pointer(),
            "drives": drives.fragment(),
            "warehouse": warehouse.fragment("猫"),
            "media_query": chat_core._media_query(
                "", {"id": row["id"], "name": "猫.txt", "kind": "document",
                     "bytes": 3, "library": warehouse.OWNER_LIB}),
            "who": proactive._who("朋友"),
            "expression": llm_box.EXPRESSION_RULES,
            "base_tools": llm_box.BASE_TOOLS,
            "self_rule": llm_box.SELF_RULE,
        }
        for k, v in texts.items():
            check_text(k, v)

        for item in tool_bus._builtin_tools().values():
            name = str(item.get("name") or "")
            blob = " ".join(str(item.get(k) or "") for k in ("desc", "hint", "module_name"))
            check_text(f"tool:{name}", blob)
    finally:
        warehouse.ENTITY = old

    print(f"\n{'FAIL' if fails else 'PASS'} ({len(fails)} failures)")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
