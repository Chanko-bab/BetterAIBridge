# -*- coding: utf-8 -*-
r"""原地重装：覆盖文件、保留设置与记忆，找不到原包就拒绝。

    .venv\Scripts\python.exe tools\test_reinstall.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from app.core import pbab, registry  # noqa: E402

FAILS: list[str] = []
OKS = 0


def check(ok: bool, msg: str) -> None:
    global OKS
    if ok:
        OKS += 1
    else:
        FAILS.append(msg)


def write_src(base: Path, mid: str, version: str, intro: str = "v1") -> Path:
    d = base / f"program_{mid}.pbab"
    d.mkdir(parents=True, exist_ok=True)
    man = {"format": "pbab/1", "api": 1, "id": mid, "name": "重装测试",
           "version": version, "memory": {"program": "program_reinst"}}
    (d / "module.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    (d / "introduce.md").write_text(f"# 重装测试 {intro}\n", encoding="utf-8")
    (d / "connection.json").write_text(json.dumps({"version": 1, "provides": {"tools": []}}),
                                      encoding="utf-8")
    return d


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="bab-reinstall-"))
    bundle = tmp / "bundle"
    bundle.mkdir()
    src = write_src(tmp / "dist", "reinstall_test", "0.1.0")
    keep_bd, keep_path, keep_notify = pbab.bundle_dir, registry.path, pbab.notify_nanny
    keep_modules = pbab.config.get("modules_dir")
    pbab.bundle_dir = lambda: bundle
    registry.path = lambda: bundle / "registry.json"
    pbab.notify_nanny = lambda *a, **k: None
    pbab.config._cfg["modules_dir"] = str(tmp / "cache")  # type: ignore[attr-defined]
    try:
        rec = pbab.install(src)
        check(rec.get("dir") and Path(rec["dir"]).is_dir(), "第一次安装应成功")
        check(Path(str(rec.get("source") or "")) == src.resolve(),
              f"应记住安装包来源（实际 {rec.get('source')}）")

        registry.patch("reinstall_test", settings={"note_category": "手账"}, state="disabled")
        # 换一版源码再重装
        write_src(tmp / "dist", "reinstall_test", "0.1.1", "v2")
        rec2 = pbab.reinstall("reinstall_test")
        check(str(rec2.get("version")) == "0.1.1", f"重装后应是新版本（实际 {rec2.get('version')}）")
        check((rec2.get("settings") or {}).get("note_category") == "手账",
              f"设置要保留（实际 {rec2.get('settings')}）")
        intro = (Path(rec2["dir"]) / "introduce.md").read_text(encoding="utf-8")
        check("v2" in intro, "模组文件要被新包覆盖")

        # 原包没了 → 拒绝，让界面去问用户要包
        src2 = tmp / "dist" / "program_reinstall_test.pbab"
        import shutil

        shutil.rmtree(src2)
        try:
            pbab.reinstall("reinstall_test")
            check(False, "原包没了应该拒绝重装")
        except pbab.PbabError as exc:
            check("找不到原来的安装包" in str(exc), f"缺原包的报错要清楚（实际 {exc}）")

        # 没装过的 → 拒绝
        try:
            pbab.reinstall("never_installed")
            check(False, "没装过的模组不能重装")
        except pbab.PbabError as exc:
            check("没装过" in str(exc), f"没装过的报错要清楚（实际 {exc}）")
    finally:
        pbab.bundle_dir = keep_bd
        registry.path = keep_path
        pbab.notify_nanny = keep_notify
        pbab.config._cfg["modules_dir"] = keep_modules  # type: ignore[attr-defined]
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)

    print("")
    if FAILS:
        print(f"失败 {len(FAILS)} 条：")
        for f in FAILS:
            print("  - " + f)
        return 1
    print(f"全过（{OKS} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
