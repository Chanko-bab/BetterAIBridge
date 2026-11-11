# -*- coding: utf-8 -*-
"""旧单智能体安装迁移：dry-run 只出计划，真迁移可回滚并保留备份。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from app.core import agents, bindings  # noqa: E402

FAILS: list[str] = []
OKS = 0


def check(ok: bool, msg: str) -> None:
    global OKS
    if ok:
        OKS += 1
    else:
        FAILS.append(msg)


def make_legacy(root: Path) -> None:
    ent = root / "WiseEntity" / "entity"
    (ent / "persona").mkdir(parents=True)
    (ent / "config").mkdir(parents=True)
    (ent / "memory").mkdir(parents=True)
    (ent / "persona" / "persona.md").write_text(
        "# 小玥\n\n一个旧安装里的智能体。\n", encoding="utf-8"
    )
    (ent / "config" / "llm.json").write_text(
        json.dumps({"api_key": "sk-legacy"}, ensure_ascii=False), encoding="utf-8"
    )
    reg = root / "program_bundle" / "registry.json"
    reg.parent.mkdir(parents=True)
    reg.write_text(
        json.dumps(
            {
                "modules": {
                    "qq_bridge": {"state": "enabled"},
                    "bili_bridge": {"state": "installed"},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def main() -> int:
    keys = ("BAB_ROOT", "BAB_AGENTS_ROOT", "BAB_AGENT_ROOT", "BAB_ENTITY", "BAB_AGENT_ID")
    old = {k: os.environ.get(k) for k in keys}
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.environ["BAB_ROOT"] = str(root)
            for k in ("BAB_AGENTS_ROOT", "BAB_AGENT_ROOT", "BAB_ENTITY", "BAB_AGENT_ID"):
                os.environ.pop(k, None)
            make_legacy(root)

            plan = agents.migrate_legacy(root, dry_run=True)
            check(plan is not None, "dry-run 应给出迁移计划")
            assert plan is not None
            check(plan["name"] == "小玥", "应从 persona 读出名字")
            check(plan["slug"].startswith("agent-"), "中文名生成安全 slug")
            check((root / "WiseEntity" / "entity" / "persona" / "persona.md").exists(),
                  "dry-run 不应移动任何文件")
            check(not (root / "agents" / plan["slug"]).exists(), "dry-run 不应建档案")
            check(plan["modules"] == ["qq_bridge"], "只迁移 enabled 模组")

            done = agents.migrate_legacy(root)
            assert done is not None
            slug = done["slug"]
            agent_dir = root / "agents" / slug
            check(agent_dir.exists(), "真迁移应建 agents/<slug>/")
            check((agent_dir / "entity" / "persona" / "persona.md").exists(),
                  "人格应迁进智能体")
            check((agent_dir / "entity" / "config" / "llm.json").exists(),
                  "Key 应随旧 entity 一起迁走")
            check((agent_dir / "program_bundle" / "registry.json").exists(),
                  "旧 registry 应迁到智能体")
            check(not (root / "program_bundle" / "registry.json").exists(),
                  "旧位置 registry 应移走")
            check(not (root / "WiseEntity" / "entity").exists(), "旧 entity 应移走")
            check(bindings.owner("qq_bridge") == slug, "enabled 模组应绑到迁移出的智能体")
            check(bindings.owner("bili_bridge") == "", "未启用模组不应绑")
            doc = json.loads((agent_dir / "agent.json").read_text(encoding="utf-8"))
            check(doc.get("name") == "小玥", "agent.json 应带名字")
            check((root / "agents.json").exists(), "迁移后应写索引")
            backup = Path(str(done.get("backup") or ""))
            check(backup.is_file(), "迁移前应有备份")
            with zipfile.ZipFile(backup) as zf:
                check("WiseEntity/entity/persona/persona.md" in zf.namelist(),
                      "备份应含旧人格")
            check(agents.migrate_legacy(root) is None, "已有 agents/ 时不应重复迁移")
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    print(f"\nPASS {OKS} / FAIL {len(FAILS)}")
    for f in FAILS:
        print("  FAIL", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
