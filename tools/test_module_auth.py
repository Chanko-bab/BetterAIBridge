"""模组鉴权回归：直接调内核 /chat 的模组必须带本机 token。"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import pbab  # noqa: E402

BILI_SRC = Path(r"D:\BAB-release\Bilibili_bridge\src\server.py")
BILI_PKG = Path(r"D:\BAB-release\Bilibili_bridge\program_bili_bridge.pbab")
QQ_SRC = Path(r"D:\Program for BAB\program_qq_bridge.pbab\server.py")
QQ_PKG = Path(r"D:\BAB-release\QQ_bridge\program_qq_bridge.pbab")

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def source_ok(path: Path) -> None:
    if not path.is_file():
        print(f"skip: 没有 {path}")
        return
    s = path.read_text(encoding="utf-8", errors="ignore")
    check("BAB_CORE_TOKEN" in s, f"{path.name} 读 BAB_CORE_TOKEN")
    check("x-bab-core-token" in s, f"{path.name} 发 x-bab-core-token")
    if '"/chat"' in s:
        i = s.find("def core_chat")
        chunk = s[i:i + 2200] if i >= 0 else s
        check("x-bab-core-token" in chunk, f"{path.name} 的 core_chat 带 token")


def package_ok(path: Path) -> None:
    if not path.is_file():
        print(f"skip: 没有 {path}")
        return
    try:
        with zipfile.ZipFile(path) as z:
            body = z.read("server.py")
            check(b"x-bab-core-token" in body, f"{path.name} 里的 server.py 带 token")
            check("checksums.json" in z.namelist(), f"{path.name} 有 checksums")
    except Exception as exc:  # noqa: BLE001
        check(False, f"{path.name} 读不了：{exc}")
        return
    try:
        info = pbab.validate(path)
        check(info.get("manifest", {}).get("id") in {"bili_bridge", "qq_bridge"}, f"{path.name} 能过 pbab.validate")
    except Exception as exc:  # noqa: BLE001
        check(False, f"{path.name} pbab.validate 失败：{exc}")


def main() -> int:
    p = (ROOT / "app" / "core" / "pbab.py").read_text(encoding="utf-8")
    check("BAB_CORE_TOKEN" in p, "pbab 给模组注入 BAB_CORE_TOKEN")
    source_ok(BILI_SRC)
    source_ok(QQ_SRC)
    package_ok(BILI_PKG)
    package_ok(QQ_PKG)
    print("PASS" if not fails else f"{len(fails)} FAILED")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
