"""查死链：代码里写死的路径，到底还存不存在。

起因：`maintenance.digest()` 一直调 `source_code/tools/memory_digest.py`，
那个文件早就不在了，于是「整理记忆」静默失效了几个月没人发现。

用法：
    python tools\\lint_refs.py              # 扫 app / WiseEntity / tools
    python tools\\lint_refs.py --verbose    # 连"跳过的"也打出来
退出码：0 = 没发现死链；1 = 有。
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ["app", "WiseEntity/entity", "WiseEntity/source_code/tools", "tools"]
SKIP_DIRS = {".venv", "__pycache__", "site-packages", "node_modules", "logs", "runtime"}
EXTS = (".py", ".json", ".md", ".yaml", ".yml", ".cmd", ".vbs", ".ps1", ".txt", ".pbab", ".html")
# 这些是运行时才出现的东西，静态查不到很正常
RUNTIME_PREFIXES = (
    "logs/", "runtime/", "state/", "memory/", "program_bundle/", "program_cache/",
    "config/app.yaml", "config/install.json", "capability/",

    "entity/state/", "entity/config/", "entity/persona/", "entity/memory/",
    "entity/brain/", "entity/core/static/",)
PATH_RE = re.compile(r"^[\w./\\\-]+$")


def looks_like_path(text: str) -> bool:
    if len(text) < 5 or len(text) > 220:
        return False
    if text.startswith(("http://", "https://", "file://")):
        return False
    if text.startswith(("\\", "/")):
        return False  # 只是拼在别人后面的一段路径，单独看没有意义
    if "{" in text or "}" in text or "%s" in text or " " in text or "\n" in text:
        return False
    if not text.lower().endswith(EXTS):
        return False
    if "/" not in text and "\\" not in text:
        return False
    return bool(PATH_RE.match(text))


def resolve(text: str, src: Path) -> list[Path]:
    rel = text.replace("\\", "/")
    cands = [Path(rel), ROOT / rel, ROOT / "WiseEntity" / rel, src.parent / rel]
    out: list[Path] = []
    for c in cands:
        try:
            out.append(c.resolve())
        except Exception:
            continue
    return out


def is_runtime(rel: str) -> bool:
    low = rel.replace("\\", "/").lstrip("./")
    return any(low.startswith(p) for p in RUNTIME_PREFIXES)


def scan_file(path: Path) -> tuple[list[tuple[int, str]], bool]:
    try:
        src = path.read_text(encoding="utf-8-sig", errors="replace")
        tree = ast.parse(src)
    except SyntaxError:
        return [], False
    except Exception:
        return [], False
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value.strip()
            if looks_like_path(text):
                hits.append((int(getattr(node, "lineno", 0)), text))
    return hits, True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="检查代码里写死的路径还在不在")
    ap.add_argument("--verbose", action="store_true", help="把跳过的也打出来")
    args = ap.parse_args(argv)

    checked = 0
    dead: list[str] = []
    skipped: list[str] = []
    unparsed: list[str] = []
    for rel_dir in SCAN_DIRS:
        base = ROOT / rel_dir
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.name.startswith("_"):
                continue  # tools\_xxx.py 这类一次性补丁脚本，用完就删，不查
            checked += 1
            hits, parsed = scan_file(path)
            if not parsed:
                unparsed.append(str(path.relative_to(ROOT)))
            for lineno, text in hits:
                if is_runtime(text):
                    if args.verbose:
                        skipped.append(f"{path.relative_to(ROOT)}:{lineno}  {text}  （运行时生成）")
                    continue
                if any(c.exists() for c in resolve(text, path)):
                    continue
                dead.append(f"{path.relative_to(ROOT)}:{lineno}  {text}")

    print(f"[lint] 扫了 {checked} 个 .py")
    if unparsed:
        print(f"[lint] 有 {len(unparsed)} 个文件没解析成功（查不到里面的路径）：")
        for name in unparsed:
            print("  ? " + name)
    if args.verbose and skipped:
        print(f"[lint] 跳过 {len(skipped)} 条运行时路径")
        for line in skipped:
            print("  · " + line)
    if dead:
        print(f"[lint] 发现 {len(dead)} 条死链：")
        for line in dead:
            print("  ✗ " + line)
        return 1
    print("[lint] 没发现死链")
    return 0


if __name__ == "__main__":
    sys.exit(main())
