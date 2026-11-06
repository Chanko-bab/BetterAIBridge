# -*- coding: utf-8 -*-
"""从 templates/pbab-template 生成一个新模组，并顺手做静态体检（--check）与试跑（--smoke）。

用法：
    python tools\\new_module.py reminder --name 提醒 --short "到点提醒你"
    python tools\\new_module.py reminder --check
    python tools\\new_module.py reminder --smoke      # 真起一次服务、打 /health

只生成源码目录，不写 registry、不碰 program_bundle——装不装由外壳决定。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "pbab-template"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,39}$")
PLACEHOLDERS = ("__ID__", "__NAME__", "__PORT__", "__SHORT__")


def _fail(msg: str) -> int:
    print(f"[new_module] {msg}")
    return 1


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def create(target: Path, ident: str, name: str, short: str, port: int, force: bool = False) -> int:
    if not TEMPLATE.is_dir():
        return _fail(f"找不到模板目录：{TEMPLATE}")
    if not ID_RE.match(ident):
        return _fail(f"id 不合法：{ident!r}（小写字母/数字/_/-，1~40 位）")
    if target.exists() and any(target.iterdir()):
        if not force:
            return _fail(f"目标目录不是空的：{target}（要覆盖加 --force）")
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    for src in sorted(TEMPLATE.rglob("*")):
        if not src.is_file():
            continue
        dst = target / src.relative_to(TEMPLATE)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix == ".cmd":
            text = src.read_bytes().decode("ascii")
        else:
            text = src.read_text(encoding="utf-8")
        text = (text.replace("__ID__", ident)
                    .replace("__NAME__", name)
                    .replace("__PORT__", str(port))
                    .replace("__SHORT__", short))
        if src.suffix == ".cmd":
            dst.write_bytes(text.replace("\r\n", "\n").replace("\n", "\r\n").encode("ascii"))
        else:
            dst.write_text(text, encoding="utf-8")
    print(f"[new_module] 生成好了：{target}（{len(list(target.rglob('*')))} 项）")
    return check(target)


def resolve_tools(conn: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """复刻内核 tool_bus 的解析：endpoint → 工具名末段，都对不上就是丢掉。"""
    prov = conn.get("provides") or {}
    eps = {str(e.get("name")) for e in prov.get("endpoints") or []}
    ok: List[str] = []
    lost: List[str] = []
    for tool in prov.get("tools") or []:
        name = str(tool.get("name") or "")
        ep = tool.get("endpoint")
        cand = str(ep) if ep is not None else ""
        if cand in eps:
            ok.append(name)
            continue
        cand = name.rsplit("_", 1)[-1]
        (ok if cand in eps else lost).append(name)
    return ok, lost


def check(target: Path) -> int:
    fails: List[str] = []

    def ck(cond: bool, msg: str) -> None:
        if not cond:
            fails.append(msg)

    man_path = target / "module.json"
    if not man_path.is_file():
        return _fail(f"没有 module.json：{target}")
    man = json.loads(man_path.read_text(encoding="utf-8"))
    mid = str(man.get("id") or "")
    ck(man.get("format") == "pbab/1", "module.json 的 format 必须是 pbab/1")
    ck(man.get("api") == 1, "api 必须是 1")
    ck(bool(ID_RE.match(mid)), f"id 不合法：{mid!r}")
    ck(bool(str(man.get("name") or "").strip()), "name 不能为空")
    ck(bool(str(man.get("version") or "").strip()), "version 不能为空")
    ck(bool(str(man.get("summary") or "").strip()), "summary 不能为空（模组卡上就显示这句）")

    entry = str((man.get("entry") or {}).get("start") or "")
    ck(bool(entry), "entry.start 没写")
    ck((target / entry).is_file() if entry else False, f"entry.start 指向的文件不存在：{entry}")

    ports = [int(p) for p in (man.get("ports") or []) if str(p).isdigit()]
    hport = int((man.get("health") or {}).get("port") or 0)
    ck(hport in ports, f"health.port={hport} 不在 ports={ports} 里")

    prog = str((man.get("memory") or {}).get("program") or "")
    ck(bool(prog), "memory.program 没写（记忆抽屉会按 id 现算，但建议写明）")

    conn_path = target / "connection.json"
    ck(conn_path.is_file(), "没有 connection.json")
    if conn_path.is_file():
        conn = json.loads(conn_path.read_text(encoding="utf-8"))
        ok, lost = resolve_tools(conn)
        ck(not lost, f"这些工具对不上 endpoints[]，会被内核静默丢掉：{lost}")
        for e in (conn.get("provides") or {}).get("endpoints") or []:
            path = str(e.get("path") or "")
            ck(path.startswith("/"), f"endpoint {e.get('name')} 的 path 要以 / 开头（实际 {path!r}）")
            ck(str(e.get("method")).upper() in {"GET", "POST"},
               f"endpoint {e.get('name')} 的 method 只能是 GET/POST")

    intro = target / "introduce.md"
    ck(intro.is_file() and intro.stat().st_size > 20, "introduce.md 太短或不存在")

    start = (target / entry) if entry else (target / "start.cmd")
    if start.is_file():
        raw = start.read_bytes()
        ck(raw.isascii(), "start.cmd 必须是纯 ASCII（中文会让 cmd 解析失败）")
        ck(b"\r\n" in raw, "start.cmd 要用 CRLF 换行")
        ck(b"BAB_MODULE_PORT" in raw, "start.cmd 要读 BAB_MODULE_PORT，别把端口写死")

    for bad in target.rglob("__pycache__"):
        fails.append(f"别把字节码带进包：{bad}")
    for p in target.rglob("*.pyc"):
        fails.append(f"别把字节码带进包：{p}")

    for text_file in list(target.glob("*.json")) + list(target.glob("*.md")):
        body = text_file.read_text(encoding="utf-8")
        left = [ph for ph in PLACEHOLDERS if ph in body]
        ck(not left, f"{text_file.name} 里还有没替换的占位符：{left}")

    print(f"[new_module] 检查 {target.name}：{len(fails)} 个问题")
    for f in fails:
        print("  ✗", f)
    if not fails:
        print("  ✓ 清单、工具↔端点、启动脚本都对")
    return 1 if fails else 0


def health_ok(port: int, timeout: float = 1.0) -> Dict[str, Any] | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def smoke(target: Path) -> int:
    man = json.loads((target / "module.json").read_text(encoding="utf-8"))
    entry = str((man.get("entry") or {}).get("start") or "start.cmd")
    port = free_port()
    env = dict(os.environ)
    env["BAB_MODULE_PORT"] = str(port)
    proc = subprocess.Popen(["cmd", "/c", entry], cwd=str(target), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 20
        data = None
        while time.time() < deadline:
            data = health_ok(port)
            if data and data.get("ok"):
                break
            time.sleep(0.4)
        if not (data and data.get("ok")):
            log = target / "logs" / "server.log"
            tail = log.read_text(encoding="utf-8", errors="replace")[-600:] if log.is_file() else ""
            print(f"[new_module] 试跑失败：{port} 上没等到 /health\n{tail}")
            return 1
        print(f"[new_module] 试跑通过：127.0.0.1:{port} /health -> {data}")
        return 0
    finally:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成并体检一个 BAB 模组")
    ap.add_argument("ident", help="模组 id（小写字母/数字/_/-）")
    ap.add_argument("--dir", default="", help="生成到哪个目录（默认 %%TEMP%%\\babmods\\<id>）")
    ap.add_argument("--name", default="", help="显示名（默认用 id）")
    ap.add_argument("--short", default="", help="一句话说明（模组卡上显示）")
    ap.add_argument("--port", type=int, default=0, help="清单里写的端口（默认随机空端口）")
    ap.add_argument("--force", action="store_true", help="目标目录非空时覆盖")
    ap.add_argument("--check", action="store_true", help="只体检已有目录")
    ap.add_argument("--smoke", action="store_true", help="体检之后再真起一次")
    args = ap.parse_args(argv)

    target = Path(args.dir) if args.dir else Path(os.environ.get("TEMP", ".")) / "babmods" / args.ident
    if args.check or args.smoke:
        rc = check(target)
        if rc == 0 and args.smoke:
            rc = smoke(target)
        return rc
    return create(target, args.ident, args.name or args.ident,
                  args.short or f"{args.name or args.ident}：装上之后她多一件能做的事。",
                  args.port or free_port(), force=args.force)


if __name__ == "__main__":
    sys.exit(main())
