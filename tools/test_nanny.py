"""保姆看门狗（nanny）的端口口径回归测试。

背景（0.3.6 实测踩到）：外壳 0.2.0 起就不给模组它清单里写的那个端口，改为池端口
（`pbab.enable()` 挑一个空闲口，写进 registry 的 `runtime_port`）。`tool_bus`、`mods.py`
都已经改成优先读 `runtime_port`，但 `nanny.check_once()` 还在探清单里的 `ports`：
于是两个健康模组（40725/40726 在听）被记成 `degraded: ports down [40730]`，
`/nanny/status` 也跟着报假警——而真正的崩溃反而永远发现不了。

这里钉住三条：
  1) registry 里有 `runtime_port` 时，只探它；
  2) 没有 `runtime_port` 时（老 registry / 手写清单），退回清单里的 ports；
  3) 探到的端口在听就算 ok、连两次不通才算 degraded。

跑法：python tools\\test_nanny.py   （退出码 0/1，非 pytest）
"""

from __future__ import annotations

import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "WiseEntity" / "entity"))

from core import nanny  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def _reserve() -> tuple[socket.socket, int]:
    """占一个空闲端口（listen 着，但没 accept，TCP 探测会成功）。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(4)
    return s, s.getsockname()[1]


def _dead_port() -> int:
    """拿一个当前没人听的端口号（绑一下就关，尽量不复用）。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _run(module: dict, tmp: Path) -> dict:
    nanny._state = {}
    nanny.STATE_PATH = tmp / "nanny.json"
    nanny._registry = lambda: {"modules": {"m": module}}  # type: ignore[assignment]
    nanny.check_once()
    nanny.check_once()  # 连两次，够 degraded 阈值
    return nanny.status()


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        live, live_port = _reserve()
        dead = _dead_port()
        try:
            # 1) 有 runtime_port：只认它
            st = _run({"id": "m", "state": "enabled", "ports": [dead],
                       "runtime_port": live_port}, tmp)
            mod = st["modules"][0]
            check(mod["state"] == "ok",
                  f"runtime_port={live_port} 在听 -> state=ok（实际 {mod['state']}）")
            check(st["degraded"] == [], f"degraded 列表为空（实际 {st['degraded']}）")
            check(list(mod["ports"].keys()) == [str(live_port)],
                  f"只探 runtime_port，不碰清单端口（探了 {list(mod['ports'].keys())}）")

            # 2) 没有 runtime_port：退回清单 ports
            live2, live2_port = _reserve()
            st = _run({"id": "m", "state": "enabled", "ports": [live2_port]}, tmp)
            check(st["modules"][0]["state"] == "ok",
                  f"没有 runtime_port 时用清单端口 {live2_port}（实际 {st['modules'][0]['state']}）")
            live2.close()

            # 3) 真挂了：两次不通 -> degraded
            st = _run({"id": "m", "state": "enabled", "ports": [dead],
                       "runtime_port": _dead_port()}, tmp)
            mod = st["modules"][0]
            check(mod["state"] == "degraded", f"端口不通 -> state=degraded（实际 {mod['state']}）")
            check(mod["fails"] >= nanny.FAILS_TO_DEGRADED,
                  f"fails 达到阈值（{mod['fails']} >= {nanny.FAILS_TO_DEGRADED}）")
            check("m" in st["degraded"], f"degraded 列表里点到了它（实际 {st['degraded']}）")
        finally:
            live.close()

    print()
    if fails:
        print(f"{len(fails)} 条失败")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
