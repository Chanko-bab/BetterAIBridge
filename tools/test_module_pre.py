# -*- coding: utf-8 -*-
"""前置模组模板 pre 0.2.0 的契约测试。

只查模板本身：命名、清单、入口、一次性、token 说明、文档、包校验。
不启动启动器，不写用户数据；`--dry-run` 只打印 ops。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = Path(r"D:\BAB-release\pre-program_pre_id.pbab")


def _find_src() -> Path | None:
    direct = Path(r"D:\BAB-release\pre\pre-program_pre_id.pbab")
    if direct.is_dir():
        return direct
    builds = Path(r"D:\BAB-release\module-builds")
    if builds.is_dir():
        found = [p for p in builds.glob("*/src-before/pre-program_pre_id.pbab") if p.is_dir()]
        if found:
            return max(found, key=lambda p: p.stat().st_mtime)
    return None


def _find_pkg() -> Path | None:
    for candidate in (PKG,
                      Path(r"D:\BAB-release\pre\pre-program_pre_id.pbab")):
        if candidate.is_file():
            return candidate
    return None


SRC = _find_src()
PKG = _find_pkg()
CHECKS = 0
FAILS: list[str] = []


def check(ok: bool, why: str) -> None:
    global CHECKS
    CHECKS += 1
    if not ok:
        FAILS.append(why)


def main() -> int:
    if SRC is None:
        print("SKIP 源码目录不存在（可能已打包或清理）")
        return 0
    if PKG is None:
        print("SKIP 包不存在（可能已打包或清理）")
        return 0

    check(SRC.name == "pre-program_pre_id.pbab", f"目录名必须带 pre- 前缀：{SRC.name}")
    man = json.loads((SRC / "module.json").read_text(encoding="utf-8-sig"))
    check(man.get("format") == "pbab/1" and man.get("api") == 1, "module.json 的 format/api 不对")
    check(man.get("id") == "pre_id", f"id 应为 pre_id：{man.get('id')}")
    check(man.get("kind") == "pre", f"kind 应为 pre：{man.get('kind')}")
    check(str(man.get("version") or "") >= "0.2.0", f"version 应 >= 0.2.0：{man.get('version')}")
    check(man.get("name") and man.get("summary"), "缺 name/summary")
    check(not (man.get("health") or {}), "一次性前置不应写 health")
    check(not (man.get("ports") or []), "前置不应占监听端口，ports 应为空")
    entry = (man.get("entry") or {}).get("start") or ""
    check(entry == "start.cmd" and (SRC / entry).is_file(), f"entry.start 应是存在的 start.cmd：{entry}")
    wants = list((man.get("bridge") or {}).get("wants") or [])
    check("project.apply" in wants, "bridge.wants 里缺 project.apply")
    check(isinstance(man.get("requires"), list), "requires 应是数组（没有依赖写 []）")

    conn = json.loads((SRC / "connection.json").read_text(encoding="utf-8-sig"))
    provides = conn.get("provides")
    check(isinstance(provides, dict), "connection.json 的 provides 应是对象")
    if isinstance(provides, dict):
        caps = [str(x) for x in (provides.get("capabilities") or [])]
        check("project.apply" in caps, "connection.provides.capabilities 里应声明 project.apply")

    schema = (SRC / "settings.schema.json").read_text(encoding="utf-8-sig")
    check("每次弹窗" not in schema and "仍然每次" not in schema,
          "settings.schema.json 还写着旧的“每次弹窗确认”")
    check("0.2.0" in (SRC / "README.md").read_text(encoding="utf-8-sig"),
          "README.md 没写 0.2.0")
    intro = (SRC / "introduce.md").read_text(encoding="utf-8-sig")
    check("0.2.0" in intro, "introduce.md 没写 0.2.0")
    check("BAB_BRIDGE_TOKEN" in (SRC / "README.md").read_text(encoding="utf-8-sig"),
          "README.md 没讲 bridge token")
    check("一次性" in intro or "跑一次" in intro, "introduce.md 没讲一次性")

    raw = (SRC / "start.cmd").read_bytes()
    check(not raw.startswith(b"\xef\xbb\xbf"), "start.cmd 不应带 UTF-8 BOM")
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        text = ""
        check(False, "start.cmd 必须是纯 ASCII")
    check(text.count("\r\n") >= 4 and "\n\n" not in text.replace("\r\n", "\n"),
          "start.cmd 应是 CRLF 行尾")
    check(("tools" + chr(92) + "pre.py") in text, "start.cmd 没调用预置脚本")
    check("BAB_MODULE_PORT" not in text, "pre 是一次性前置，不应依赖 BAB_MODULE_PORT")

    dry = subprocess.run(
        [sys.executable, "-X", "utf8", str(SRC / "tools" / "pre.py"), "--dry-run"],
        cwd=str(SRC), capture_output=True, text=True, timeout=30,
    )
    check(dry.returncode == 0, f"pre.py --dry-run 失败：{dry.stderr[-300:]}")
    try:
        ops = json.loads(dry.stdout)
    except Exception:  # noqa: BLE001
        ops = []
    check(isinstance(ops, list) and len(ops) >= 2, "pre.py --dry-run 应输出至少两条 ops")
    paths = [str(o.get("path") or "") for o in ops if isinstance(o, dict)]
    check(all(p.startswith("WiseEntity/entity/") for p in paths),
          f"模板示例只应写 entity/ 下：{paths}")
    check(any(o.get("op") == "mkdir" for o in ops if isinstance(o, dict)),
          "模板示例应包含 mkdir")
    check(any(o.get("op") == "write" for o in ops if isinstance(o, dict)),
          "模板示例应包含 write")

    check(PKG.is_file(), f"包不存在：{PKG}")
    if PKG.is_file():
        sys.path.insert(0, str(ROOT))
        from app.core import pbab  # noqa: PLC0415
        try:
            got = pbab.validate(str(PKG))
        except Exception as exc:  # noqa: BLE001
            got = {}
            check(False, f"pbab.validate 失败：{exc}")
        m = (got or {}).get("manifest") or {}
        check(m.get("id") == "pre_id" and m.get("kind") == "pre", f"包清单不对：{m.get('id')}/{m.get('kind')}")
        check(str(m.get("version") or "") >= "0.2.0", f"包版本应 >= 0.2.0：{m.get('version')}")

    junk = [p for p in SRC.rglob("*") if p.name in ("__pycache__",) or "logs" in p.parts]
    check(not junk, f"源码里混进了缓存/日志：{[str(p) for p in junk]}")

    if FAILS:
        print(f"FAIL {len(FAILS)} 条：")
        for why in FAILS:
            print("  -", why)
        return 1
    print(f"PASS {CHECKS} 条：命名、清单、入口、一次性、token、文档、包校验都对。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
