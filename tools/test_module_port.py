"""模组端口契约的回归测试（离屏、无 Qt、退出码 0/1）。

为什么需要它：外壳的 `pbab.enable()` 会给模组分配"池端口"（base+5..base+19），
并通过环境变量 `BAB_MODULE_PORT` 告诉模组；内核侧所有调用点（tool_bus / bridge /
app）都优先用 `runtime_port`。所以模组的入口脚本**必须**听 `BAB_MODULE_PORT`，
否则谁机器上清单里的端口被占（开发树、第二个安装副本、别的软件），
模组就会"装得上、开不了"，被判成 broken。

这个脚本检查两件事：
  1) 源目录里的 start.cmd 是纯 ASCII + CRLF，并且读 `BAB_MODULE_PORT`；
  2) 真跑一次：给一个随机空闲端口，确认服务确实在那个端口上起来了。
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "program_cache" / "_modsrc" / "web_bridge"
FALLBACK_PORT = 40730

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def port_open(port: int, timeout: float = 0.35) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex(("127.0.0.1", int(port))) == 0


def wait_port(port: int, seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if port_open(port):
            return True
        time.sleep(0.2)
    return False


def kill_tree(pid: int) -> None:
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    if not SRC.exists():
        # 旧模组已移出开发树（要基于 M 重做），没有源码就没什么可量的
        print(f"skip: 没有 {SRC}（旧模组已移出，等基于 M 重做）")
        return 0
    start = SRC / "start.cmd"
    check(start.exists(), f"模组源里的 start.cmd 存在（{start}）")
    if not start.exists():
        return 1

    raw = start.read_bytes()
    check(b"\r\n" in raw and b"\n\n" not in raw.replace(b"\r\n", b"\n"), "start.cmd 用 CRLF 换行")
    check(all(b < 128 for b in raw), "start.cmd 是纯 ASCII（cmd 按 ANSI 读中文会拆行）")
    text = raw.decode("ascii", "replace")
    check("BAB_MODULE_PORT" in text, "start.cmd 读 BAB_MODULE_PORT（外壳分配池端口时会传）")

    # 真跑一次：拷到临时目录，塞一个随机端口，看服务是不是真在那个端口上
    port = free_port()
    work = Path(tempfile.mkdtemp(prefix="bab_modport_")) / "web_bridge"
    try:
        shutil.copytree(SRC, work, ignore=shutil.ignore_patterns("__pycache__", "logs"))
    except Exception as exc:  # noqa: BLE001
        check(False, f"拷贝模组到临时目录失败：{exc!r}")
        return 1

    env = dict(os.environ)
    env["BAB_MODULE_PORT"] = str(port)
    env["PYTHONUTF8"] = "1"
    proc = None
    try:
        proc = subprocess.Popen(
            ["cmd", "/c", str(work / "start.cmd")],
            cwd=str(work),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        up = wait_port(port, 25)
        check(up, f"服务在分配的端口 {port} 上起来了（不该去抢 {FALLBACK_PORT}）")
        if up:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
                    doc = json.loads(resp.read().decode("utf-8", "replace"))
                check(resp.status == 200 and doc.get("ok") is True, f"/health 回 ok=true（拿到 {doc}）")
                check(str(doc.get("version") or "") == "0.2.3", f"版本自报 0.2.3（拿到 {doc.get('version')!r}）")
            except Exception as exc:  # noqa: BLE001
                check(False, f"/health 打不通：{exc!r}")
    finally:
        if proc is not None:
            kill_tree(proc.pid)
        shutil.rmtree(work.parent, ignore_errors=True)

    print()
    if fails:
        print(f"{len(fails)} 条失败")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
