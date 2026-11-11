# -*- coding: utf-8 -*-
"""智能体档案：创建、索引、导出（默认不含 Key）、回收站 7 天、构建排除 agents/。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from app.core import agents  # noqa: E402

FAILS: list[str] = []
OKS = 0


def check(ok: bool, msg: str) -> None:
    global OKS
    if ok:
        OKS += 1
    else:
        FAILS.append(msg)


def main() -> int:
    keys = ("BAB_ROOT", "BAB_AGENTS_ROOT", "BAB_AGENT_ROOT", "BAB_ENTITY", "BAB_AGENT_ID")
    old = {k: os.environ.get(k) for k in keys}
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.environ["BAB_ROOT"] = str(root)
            for k in ("BAB_AGENTS_ROOT", "BAB_AGENT_ROOT", "BAB_ENTITY", "BAB_AGENT_ID"):
                os.environ.pop(k, None)

            a = agents.create_agent("小玥", api_key="sk-test-agent")
            slug = a["slug"]
            check(slug.startswith("agent-"), "中文名字应退化为 agent-<hash>")
            check((root / "agents" / slug / "agent.json").exists(), "agent.json 应存在")
            check((root / "agents" / slug / "entity" / "config" / "llm.json").exists(),
                  "独立 Key 应写进自己的 entity/config")
            check((root / "agents.json").exists(), "索引应落盘")
            idx = json.loads((root / "agents.json").read_text(encoding="utf-8"))
            check(len(idx.get("agents") or []) == 1, "索引应只有 1 个智能体")
            check(idx["agents"][0]["name"] == "小玥", "索引应带显示名")

            b = agents.create_agent("小玥")
            check(b["slug"] != slug, "同名应自动加后缀，不覆盖")
            check(len(agents.scan()) == 2, "scan 应看到两个智能体")

            out = root / "x.babpak"
            agents.export_agent(slug, out, include_key=False)
            key_rel = "/".join(("agent", "entity", "config", "llm.json"))
            agent_rel = "/".join(("agent", "agent.json"))
            with zipfile.ZipFile(out) as zf:
                names = zf.namelist()
            check(key_rel not in names, "默认导出不应含 API Key")
            check(agent_rel in names, "导出应含 agent.json")
            out2 = root / "x-key.babpak"
            agents.export_agent(slug, out2, include_key=True)
            with zipfile.ZipFile(out2) as zf:
                check(key_rel in zf.namelist(), "显式勾选才导出 Key")

            trash = agents.trash_agent(slug)
            check((trash / "deleted.json").exists(), "回收站应有删除元数据")
            check(agents.owner_index_has(slug) is False if hasattr(agents, "owner_index_has")
                  else all(x["slug"] != slug for x in agents.load_index()["agents"]),
                  "删除后索引不应再有它")
            restored = agents.restore_agent(trash)
            check(restored["slug"] == slug, "恢复应回到原 slug")
            check((root / "agents" / slug).exists(), "恢复后目录应存在")

            trash2 = agents.trash_agent(slug)
            meta = json.loads((trash2 / "deleted.json").read_text(encoding="utf-8"))
            meta["deleted_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 8 * 86400))
            (trash2 / "deleted.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            removed = agents.purge_trash(7)
            check(trash2.name in removed, "过期回收站应被清理")
            check(not trash2.exists(), "清理后目录应消失")

            build = (ROOT / "packaging" / "build.ps1").read_text(encoding="utf-8-sig")
            check("'agents'" in build or "\"agents\"" in build, "出包应跳过 agents/")
            check("agents.json" in build and "modules.bindings.json" in build,
                  "出包不应带索引/绑定表")
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
