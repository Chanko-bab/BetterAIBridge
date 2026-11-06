# -*- coding: utf-8 -*-
"""重置启动器：清用户数据与模组，保留程序、内核代码和安装信息。

非 pytest，退出码 0/1。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import reset  # noqa: E402

FAILS: list[str] = []
OKS = 0


def check(ok: bool, msg: str) -> None:
    global OKS
    if ok:
        OKS += 1
    else:
        FAILS.append(msg)


def touch(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "app"
        ent = base / "WiseEntity" / "entity"
        bun = base / "program_bundle"
        cache = base / "program_cache"
        cfg = base / "config"
        logs = base / "logs"

        keep = [
            ent / ".venv" / "python.exe",
            ent / "core" / "kernel.py",
            ent / "brain" / "brain_rules.md",
            ent / "brain" / "flybrain_core.py",
            ent / "emotion" / "intensity_table.json",
            ent / "persona" / "persona.placeholder.md",
            ent / "config" / "llm.placeholder.json",
            cfg / "install.json",
            cfg / "app.yaml.template",
            logs / "app.log",
        ]
        for p in keep:
            touch(p, "keep")

        gone = [
            ent / "persona" / "persona.md",
            ent / "memory" / "bridge_token.json",
            ent / "memory" / "internal" / "web_owner" / "a.txt",
            ent / "self" / "evidence.jsonl",
            ent / "self" / "versions" / "1",
            ent / "state" / "core_token",
            ent / "state" / "sessions.json",
            ent / "registry" / "programs.json",
            ent / "emotion" / "state.json",
            ent / "config" / "llm.json",
            ent / "config" / "sense.json",
            ent / "config" / "stomach.json",
            ent / "config" / "face.png",
            ent / "brain" / "flybrain_state.json",
            cfg / "sense.json",
            cfg / "bridge_grants.json",
            bun / "plugins" / "p.pbab",
            cache / "pkg" / "a.pbab",
        ]
        for p in gone:
            touch(p, "data")

        cfg.joinpath("install.json").write_text(json.dumps(
            {"install_id": "t", "core": 40991, "asr": 40966, "version": "test"}),
            encoding="utf-8")
        cfg.joinpath("app.yaml.template").write_text(
            "project_root: {{APP_DIR}}\\WiseEntity\n"
            "core_url: http://127.0.0.1:{{CORE_PORT}}\n"
            "ports:\n  core: {{CORE_PORT}}\n  asr: {{ASR_PORT}}\n",
            encoding="utf-8")

        out = reset.reset_launcher_data(
            app_dir=base, entity=ent, bundle=bun, cache=cache,
            stop=False, reload=False)

        check(out.get("ok"), f"重置应成功（errors={out.get('errors')}）")
        check(out.get("removed", 0) >= 15, f"应删掉一批文件（实际 {out.get('removed')}）")
        for p in gone:
            check(not p.exists(), f"应删掉 {p.relative_to(base)}")
        for p in keep:
            check(p.exists(), f"应保留 {p.relative_to(base)}")

        app_yaml = cfg / "app.yaml"
        check(app_yaml.exists(), "应重建 config/app.yaml（launch.vbs 需要）")
        if app_yaml.exists():
            text = app_yaml.read_text(encoding="utf-8")
            check("40991" in text and "40966" in text, "app.yaml 应沿安装端口 40991/40966")
            check(str(base) in text, "app.yaml 应写临时安装目录")
        reg = bun / "registry.json"
        check(reg.exists(), "应写回空注册表")
        if reg.exists():
            data = json.loads(reg.read_text(encoding="utf-8"))
            check(data.get("modules") == {}, "注册表应为空")
        check(not any(cache.rglob("*")) if cache.exists() else True,
              "模组缓存应清空")

    if FAILS:
        for f in FAILS:
            print("FAIL", f)
        print(f"{OKS} ok / {len(FAILS)} failed")
        return 1
    print(f"PASS {OKS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
