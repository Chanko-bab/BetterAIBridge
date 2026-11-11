# -*- coding: utf-8 -*-
"""多智能体路径契约：BAB_ROOT 仍是程序根，数据根由 BAB_AGENT_ROOT 决定。"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from app.core import agent_paths  # noqa: E402

FAILS: list[str] = []
OKS = 0


def check(ok: bool, msg: str) -> None:
    global OKS
    if ok:
        OKS += 1
    else:
        FAILS.append(msg)


def main() -> int:
    keys = ("BAB_ROOT", "BAB_AGENTS_ROOT", "BAB_AGENT_ROOT", "BAB_ENTITY", "BAB_BUNDLE", "BAB_AGENT_ID")
    old = {k: os.environ.get(k) for k in keys}
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for k in keys:
                os.environ.pop(k, None)
            os.environ["BAB_ROOT"] = str(root)
            check(agent_paths.install_root() == root, "BAB_ROOT 应指向安装根")
            check(agent_paths.entity_root() == root / "WiseEntity" / "entity",
                  "没有智能体时应回退旧 entity 路径")
            check(not agent_paths.has_agent(), "没有 BAB_AGENT_ROOT 时 has_agent=False")
            check(agent_paths.module_env() == {}, "旧模式不注入智能体环境变量")

            os.environ["BAB_AGENT_ROOT"] = str(root / "agents" / "xiaoyue")
            check(agent_paths.install_root() == root, "BAB_ROOT 不应被智能体根替换")
            check(agent_paths.agent_root() == root / "agents" / "xiaoyue", "agent_root 读 BAB_AGENT_ROOT")
            check(agent_paths.entity_root() == root / "agents" / "xiaoyue" / "entity", "entity 默认在 agent 下")
            env = agent_paths.module_env()
            check(env.get("BAB_AGENT_ROOT") == str(root / "agents" / "xiaoyue"), "模组环境带 agent root")
            check(env.get("BAB_BUNDLE") == str(root / "program_bundle"), "模组环境带共享 bundle")

            os.environ["BAB_ENTITY"] = str(root / "custom-entity")
            check(agent_paths.entity_root() == root / "custom-entity", "BAB_ENTITY 优先")

            os.environ["BAB_BUNDLE"] = str(root / "shared-bundle")
            check(agent_paths.bundle_root() == root / "shared-bundle", "BAB_BUNDLE 可覆盖")

            check(agent_paths.slugify("My Agent") == "my-agent", "ASCII 名字应可读")
            cn = agent_paths.slugify("小玥")
            check(cn.startswith("agent-") and agent_paths.valid_slug(cn), "中文名字退化为安全 slug")
            check(agent_paths.slugify("app") == "agent-app", "保留名要加前缀")
            check(not agent_paths.valid_slug("App"), "大写/保留名不合法")
            check(agent_paths.valid_slug("xiaoyue_1"), "合法 slug 应通过")
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
