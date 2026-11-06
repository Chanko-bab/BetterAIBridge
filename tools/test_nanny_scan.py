# -*- coding: utf-8 -*-
"""保姆按需扫描：只读列目录/读文件/找关键词，且不能出程序目录。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "WiseEntity" / "entity"))

from core import nanny_scan  # noqa: E402


def check(ok: bool, name: str) -> None:
    print(("ok " if ok else "FAIL ") + name)
    if not ok:
        raise AssertionError(name)


def test_scan() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="bab-nanny-scan-"))
    try:
        (tmp / "app").mkdir()
        (tmp / "app" / "a.py").write_text("needle = 1\nprint('hello')\n", encoding="utf-8")
        (tmp / "notes.md").write_text("# 记录\n这里有 needle 2\n", encoding="utf-8")
        (tmp / "data.bin").write_bytes(b"\x00\x01")
        nanny_scan.S = SimpleNamespace(APP_ROOT=tmp)

        tree = nanny_scan.list_dir("")
        check("a.py" not in tree and "app/" in tree, "列目录能看到子目录")

        deep = nanny_scan.list_dir("app", depth=2)
        check("a.py" in deep, "列目录能看到文件")

        rel = str(Path("app") / "a.py")
        got = nanny_scan.read_file(rel)
        check("needle = 1" in got, "读文本文件")

        binary = nanny_scan.read_file("data.bin")
        check("二进制" in binary, "不读二进制")

        hits = nanny_scan.search("needle")
        check("a.py" in hits and "notes.md" in hits, "关键词能找到两个文件")

        ctx = nanny_scan.context_for("帮我看一下 " + rel)
        check("needle = 1" in ctx, "带路径的按需扫描")

        ctx2 = nanny_scan.context_for("扫描一下 needle")
        check("notes.md" in ctx2, "按关键词扫描")

        check(nanny_scan.context_for("今天天气怎么样") == "", "普通闲聊不扫项目")

        outside = nanny_scan.read_file(str(Path("..") / "outside.py"))
        check("目录外面" in outside, "程序目录外拒绝读取")
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_scan()
    print("PASS 保姆按需扫描")
