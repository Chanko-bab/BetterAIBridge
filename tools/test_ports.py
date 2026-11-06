# -*- coding: utf-8 -*-
r"""端口诊断：谁占了端口、能不能安全结束。

    .venv\Scripts\python.exe tools\test_ports.py
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from app.ui.pages import services  # noqa: E402

FAILS: list[str] = []
OKS = 0


def check(ok: bool, msg: str) -> None:
    global OKS
    if ok:
        OKS += 1
    else:
        FAILS.append(msg)


def main() -> int:
    check(isinstance(services.install_base(), int) and services.install_base() >= 1024,
          f"install_base 应是端口数（实际 {services.install_base()}）")
    check(services.port_owner(0) == (0, ""), "端口 0 没有归属")
    check(services.port_owner(1) == (0, "") or True, "低位端口查询不应抛异常")

    # 自己开一个监听端口，扫描应认出来（psutil 或 netstat 至少一个可用）
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        owners = {}
        for _ in range(10):
            owners = services.listening_map()
            if port in owners:
                break
            time.sleep(0.2)
        check(port in owners, f"自己监听的 {port} 应出现在端口表里")
        if port in owners:
            pid, name = owners[port]
            check(pid == os.getpid(), f"占用者 PID 应是当前进程（实际 {pid}）")
    finally:
        srv.close()

    # 安全边界：绝不杀自己 / 空 PID
    check(services.kill_pid(0) is False, "kill_pid(0) 必须拒绝")
    check(services.kill_pid(os.getpid()) is False, "kill_pid(自己) 必须拒绝")

    # 0.4.17：起停脚本只认这份安装，不再按命令行通配杀别的实例
    scripts = ROOT / "WiseEntity" / "source_code" / "scripts"
    stop = (scripts / "stop-all.ps1").read_text(encoding="utf-8-sig")
    start = (scripts / "start-all.ps1").read_text(encoding="utf-8-sig")
    check("install.json" in stop, "stop-all 应按 install.json 找端口")
    check("install.json" in start, "start-all 应按 install.json 找端口")
    check("*core.app*" not in stop, "stop-all 不能再按通配命令行杀进程")
    asr_src = (ROOT / "app" / "services" / "asr.py").read_text(encoding="utf-8")
    check("BAB_ASR_PORT" in asr_src, "ASR 启动应把端口传给服务")

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
