# -*- coding: utf-8 -*-
"""0.4.19 数据目录：数据在安装目录，install.json 的 data_dir 不再生效。

非 pytest，退出码 0/1。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import config  # noqa: E402
from app.core import portable  # noqa: E402

FAILS: list[str] = []
OKS = 0


def check(ok: bool, msg: str) -> None:
    global OKS
    if ok:
        OKS += 1
    else:
        FAILS.append(msg)


def main() -> int:
    old_dir = config.CONFIG_DIR
    try:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            cfgdir = base / "config"
            cfgdir.mkdir()
            data = base / "data"
            (data / "entity").mkdir(parents=True)
            (base / "WiseEntity" / "entity").mkdir(parents=True)

            # 1. 没有 install.json：用程序目录
            config.CONFIG_DIR = cfgdir
            check(config.data_root() is None, "没有 install.json 时 data_root 应为 None")
            check(config.entity_dir() == config.project_root() / "entity",
                  f"旧安装应回退到 project_root/entity，实际 {config.entity_dir()}")

            # 2. 有 data_dir：0.4.19 起忽略，仍用程序目录
            (cfgdir / "install.json").write_text(json.dumps(
                {"install_id": "t", "base": 40720, "asr": 40715, "data_dir": str(data)}),
                encoding="utf-8")
            check(config.data_root() is None, "0.4.19 起 data_root 应忽略 data_dir")
            check(config.entity_dir() == config.project_root() / "entity",
                  "0.4.19 起 entity_dir 应始终是程序目录")

            # 3. 存档导出/导入也跟着走
            ent = config.entity_dir()
            (ent / "persona").mkdir(parents=True, exist_ok=True)
            (ent / "persona" / "persona.md").write_text("# 数据目录\n", encoding="utf-8")
            check(portable.entity_dir() == ent, "portable 应使用同一个数据目录")

            # 4. 内核 settings 同样忽略 data_dir（子进程，避免污染当前进程）
            root = base / "kernel"
            (root / "WiseEntity" / "entity").mkdir(parents=True)
            (root / "config").mkdir()
            (root / "config" / "install.json").write_text(json.dumps(
                {"install_id": "k", "base": 40720, "asr": 40715, "data_dir": str(data)}),
                encoding="utf-8")
            env = dict(os.environ, BAB_ROOT=str(root))
            code = ("from entity.core import settings as S;"
                    "print(S.ENTITY);print(S.BUNDLE);print(S.ASR_PORT)")
            r = subprocess.run([sys.executable, "-X", "utf8", "-c", code],
                               cwd=str(ROOT / "WiseEntity"), env=env,
                               capture_output=True, text=True)
            lines = r.stdout.strip().splitlines()
            check(r.returncode == 0 and lines and lines[0] == str(root / "WiseEntity" / "entity"),
                  f"内核 ENTITY 应在安装目录：{r.stdout} {r.stderr[-200:]}")
            check(len(lines) > 1 and lines[1] == str(root / "program_bundle"),
                  f"内核 BUNDLE 应在安装目录：{lines}")
            check(len(lines) > 2 and lines[2] == "40715", f"内核 ASR 端口应读 install.json：{lines}")

            # 5. install.json 里没 asr：回退到 app.yaml 的 ports.asr
            root2 = base / "kernel2"
            (root2 / "WiseEntity" / "entity").mkdir(parents=True)
            (root2 / "config").mkdir()
            (root2 / "config" / "install.json").write_text(json.dumps(
                {"install_id": "k2", "base": 40730}), encoding="utf-8")
            (root2 / "config" / "app.yaml").write_text(
                "ports:\n  core: 40730\n  asr: 40717\n", encoding="utf-8")
            env2 = dict(os.environ, BAB_ROOT=str(root2))
            r2 = subprocess.run([sys.executable, "-X", "utf8", "-c",
                                 "from entity.core import settings as S;print(S.ASR_PORT)"],
                                cwd=str(ROOT / "WiseEntity"), env=env2,
                                capture_output=True, text=True)
            check(r2.stdout.strip() == "40717",
                  f"install.json 缺 asr 时应读 app.yaml：{r2.stdout} {r2.stderr[-200:]}")
    finally:
        config.CONFIG_DIR = old_dir

    print(f"{OKS} ok, {len(FAILS)} fail")
    for f in FAILS:
        print("FAIL:", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
