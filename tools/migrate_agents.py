"""一次性迁移：旧单智能体 install -> agents/<slug>/ 结构。

用法：
    python tools/migrate_agents.py                 # 迁移当前安装
    python tools/migrate_agents.py --dry-run       # 只看计划
    python tools/migrate_agents.py --root D:\\x    # 迁移指定安装

默认只跑一次：已有任何 agents/<slug> 时不会动手。迁移会先备份
WiseEntity/entity 到 backups/pre-agents-<时间>.zip，失败自动回滚。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移旧安装到 agents/<slug>/")
    parser.add_argument("--root", default="", help="安装根；默认当前项目根")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不移动文件")
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else ROOT
    os.environ["BAB_ROOT"] = str(root)
    from app.core import agents

    plan = agents.migrate_legacy(root, dry_run=args.dry_run)
    if not plan:
        print("不需要迁移：没有旧 entity，或 agents/ 已经有智能体。")
        return 0
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    if args.dry_run:
        print("（dry-run，没有移动任何文件）")
    else:
        print("迁移完成。旧 entity 已经转为 agents/<slug>/entity。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
