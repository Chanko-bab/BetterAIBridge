"""模组合约：未知的第三方包，按最小合规集到底能不能被接住。

这不是测 M / routine，而是测“外壳对陌生模组的承诺”：
- `pbab.validate()` 能认最小三件套（module.json / introduce.md / connection.json）；
- `tools/new_module.py --check` 的静态体检能过（端口 env、工具↔端点、health）；
- 真起一次最小服务，`/health` 与 `/ping` 都能回；
- `docs/MODULES.md` 不再把 `ports[0]` 说成内核实际调用地址，并承认 `http` 健康检查。
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from app.core import pbab  # noqa: E402
import new_module  # noqa: E402

FIX = ROOT / "tools" / "fixtures" / "module_probe"
fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def get_json(port: int, path: str, timeout: float = 1.0) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def make_temp_copy(tmp: Path) -> Path:
    shutil.rmtree(FIX / "__pycache__", ignore_errors=True)
    dst = tmp / "program_probe.pbab"
    shutil.copytree(FIX, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return dst


def test_manifest(dst: Path) -> None:
    man = json.loads((dst / "module.json").read_text(encoding="utf-8"))
    check(man.get("format") == "pbab/1", "module.json format=pbab/1")
    check(man.get("id") == "probe", "id=probe")
    check((man.get("health") or {}).get("type") == "http", "health 用 http（不是只看端口）")
    check((man.get("ports") or []) == [40739], "清单端口只是作者默认值")
    raw = (dst / "start.cmd").read_bytes()
    check(raw.isascii(), "start.cmd 纯 ASCII")
    check(b"\r\n" in raw, "start.cmd 用 CRLF")
    check(b"BAB_MODULE_PORT" in raw, "start.cmd 读 BAB_MODULE_PORT")


def test_validate(dst: Path) -> None:
    v = pbab.validate(dst)
    check(v.get("manifest", {}).get("id") == "probe", "pbab.validate() 认出 id")
    check(v.get("payload_mode") == "embedded", "payload=embedded")
    check(int(v.get("members") or 0) >= 6, "成员数不少于 6")


def test_contract_check(dst: Path) -> None:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = new_module.check(dst)
    tail = buf.getvalue().strip().splitlines()[-1] if buf.getvalue().strip() else ""
    check(rc == 0, "tools/new_module.py --check 通过" + (f"（{tail}）" if tail else ""))


def test_smoke(dst: Path) -> None:
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, str(dst / "server.py"), "--port", str(port)],
        cwd=str(dst),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 8.0
        health = None
        while time.time() < deadline:
            try:
                health = get_json(port, "/health")
                if health.get("ok"):
                    break
            except OSError:
                time.sleep(0.2)
        check(bool(health and health.get("ok")), "最小服务 /health 返回 ok")
        ping = get_json(port, "/ping")
        check(bool(ping.get("pong")), "最小服务 /ping 返回 pong")
        check(int(ping.get("port") or 0) == port, "服务实际监听的是测试给的端口")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_docs() -> None:
    doc = (ROOT / "docs" / "MODULES.md").read_text(encoding="utf-8")
    check("`port`（TCP）、`process`（看 pid）或 `http`" in doc, "文档承认 health 有 http")
    check("取模组 `module.json` 的 `ports[0]`" not in doc, "文档不再把 ports[0] 当实际调用地址")
    check("runtime_port" in doc, "文档写明 runtime_port")
    check('"tools": ["tool_a"]' not in doc, "connection 示例不再是旧字符串数组")
    check('"name": "demo_ping"' in doc, "connection 示例给了可落地的工具对象")


def main() -> int:
    check(FIX.is_dir(), "fixture 目录存在")
    with tempfile.TemporaryDirectory(prefix="bab-contract-") as td:
        tmp = Path(td)
        dst = make_temp_copy(tmp)
        test_manifest(dst)
        test_validate(dst)
        test_contract_check(dst)
        test_smoke(dst)
    test_docs()
    print(f"\n{len(fails)} 个问题")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
