"""控制台弹窗审计：从 GUI 进程调控制台工具时，不许漏掉 CREATE_NO_WINDOW。

0.6.5 测试里出现过“频繁黑窗”：看门狗每 20 秒跑一次 tasklist，启停模组又跑
taskkill/where/mklink，服务页每 5 秒跑一次 netstat。它们本身都是对的，错在
没有隐藏窗口。这个测试做两件事：

1. 静态扫描 app/ 下的 subprocess.run/Popen，除资源管理器/记事本这类故意可见的，
   都必须带 creationflags；
2. 行为检查 winproc.run 真的塞了 CREATE_NO_WINDOW，看门狗优先走 psutil。
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import pbab_process, winproc  # noqa: E402

APP = ROOT / "app"
VISIBLE = ("explorer", "notepad")  # 这些是用户主动打开、应该看得见的窗口


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _console_calls(path: Path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr in ("run", "Popen")):
            continue
        if not (isinstance(fn.value, ast.Name) and fn.value.id == "subprocess"):
            continue
        if any(k.arg == "creationflags" for k in node.keywords):
            continue
        seg = ast.get_source_segment(path.read_text(encoding="utf-8"), node) or ""
        if any(v in seg for v in VISIBLE):
            continue
        if path.name in ("winproc.py",):
            continue
        yield node.lineno, " ".join(seg.split())[:120]


def main() -> None:
    bad = []
    for path in sorted(APP.rglob("*.py")):
        for lineno, text in _console_calls(path):
            bad.append(f"{path.relative_to(ROOT)}:{lineno}: {text}")
    check(not bad, "这些子进程会闪控制台窗口，缺 CREATE_NO_WINDOW：\n" + "\n".join(bad))

    # winproc.run 必须真的塞 flags（Windows 上）
    calls = []
    orig = winproc.subprocess.run

    def fake(cmd, **kw):
        calls.append(kw)
        return None

    winproc.subprocess.run = fake  # type: ignore[assignment]
    try:
        winproc.run(["tasklist"])
    finally:
        winproc.subprocess.run = orig  # type: ignore[assignment]
    if os.name == "nt":
        check(calls and calls[0].get("creationflags") == winproc.NO_WINDOW,
              "winproc.run 没有默认加 CREATE_NO_WINDOW")

    # 看门狗查进程优先 psutil（不启动 tasklist）
    import types

    fake_psutil = types.SimpleNamespace(pid_exists=lambda pid: True)
    old = sys.modules.get("psutil")
    sys.modules["psutil"] = fake_psutil  # type: ignore[assignment]
    try:
        check(pbab_process._pid_alive(1234) is True, "看门狗应优先用 psutil.pid_exists")
        fake_psutil.pid_exists = lambda pid: False  # type: ignore[assignment]
        check(pbab_process._pid_alive(1234) is False, "psutil 说不存在时应返回 False")
    finally:
        if old is None:
            sys.modules.pop("psutil", None)
        else:
            sys.modules["psutil"] = old

    # QProcess 的两处必须挂隐藏修饰器
    for rel in ("app/ui/pages/services.py", "app/ui/main_window.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        check("hide_console(p)" in src, f"{rel} 的 QProcess 没有隐藏控制台")

    print("no_window: PASS")


if __name__ == "__main__":
    main()
