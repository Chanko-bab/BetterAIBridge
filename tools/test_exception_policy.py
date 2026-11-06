"""异常策略：宽泛捕获不能悄悄变多，关键模块不能静默吞。

这是一条“防回流”测试，不追求把宽泛捕获一次清零：
它只要求总量不高于当前基线，并禁止入口/启动器核心/进程清理再出现
`except Exception: pass` 这类无声失败。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
MAIN = ROOT / "main.py"

# 2026-11-07 审计基线。修掉一处就调低；新增宽泛捕获必须说明原因并抬线。
BASELINE_BROAD = 247
BASELINE_SILENT = 0
BASELINE_PASS = 0

# 这些文件里不允许再把异常直接吞掉；要么记日志，要么把错误交给上层。
CRITICAL = (
    "main.py",
    "app/core/local_tts.py",
    "app/services/core_client.py",
    "app/core/pbab_process.py",
    "app/ui/main_window.py",
    "app/services/sense.py",
    "app/ui/pages/settings.py",
)

FAILED: List[str] = []
PASSED = 0


def check(ok: bool, label: str) -> None:
    global PASSED
    if ok:
        PASSED += 1
        print(f"  PASS {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL {label}")


def _is_broad(node: ast.AST | None) -> bool:
    if node is None:
        return True
    if isinstance(node, ast.Name):
        return node.id in ("Exception", "BaseException")
    if isinstance(node, ast.Attribute):
        return node.attr in ("Exception", "BaseException")
    if isinstance(node, ast.Tuple):
        return any(_is_broad(x) for x in node.elts)
    return False


def _silent_kind(body: List[ast.stmt]) -> str:
    if all(isinstance(x, ast.Pass) for x in body):
        return "pass"
    if all(isinstance(x, (ast.Pass, ast.Continue, ast.Break)) for x in body):
        return "passcont"
    if (
        len(body) == 1
        and isinstance(body[0], ast.Return)
        and (
            body[0].value is None
            or (isinstance(body[0].value, ast.Constant) and body[0].value.value is None)
        )
    ):
        return "returnNone"
    return "other"


def scan(paths: List[Path]) -> List[Tuple[Path, int, bool, str]]:
    rows: List[Tuple[Path, int, bool, str]] = []
    for p in paths:
        tree = ast.parse(p.read_text(encoding="utf-8-sig"), filename=str(p))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                rows.append((p, node.lineno, _is_broad(node.type), _silent_kind(node.body)))
    return rows


def main() -> int:
    rows = scan(sorted(APP.rglob("*.py")))
    main_rows = scan([MAIN])

    broad = [r for r in rows if r[2]]
    silent = [r for r in broad if r[3] != "other"]
    pass_only = [r for r in broad if r[3] == "pass"]

    print(f"  app: {len(rows)} except / {len(broad)} 宽泛 / {len(silent)} 静默 / {len(pass_only)} 只 pass")
    check(len(broad) <= BASELINE_BROAD, f"宽泛捕获不高于基线 {BASELINE_BROAD}（实际 {len(broad)}）")
    check(len(silent) <= BASELINE_SILENT, f"静默宽泛不高于基线 {BASELINE_SILENT}（实际 {len(silent)}）")
    check(len(pass_only) <= BASELINE_PASS, f"只 pass 不高于基线 {BASELINE_PASS}（实际 {len(pass_only)}）")

    main_silent = [r for r in main_rows if r[2] and r[3] != "other"]
    check(not main_silent, f"main.py 无静默宽泛捕获（实际 {len(main_silent)}）")

    by_name: Dict[str, List[Tuple[Path, int, bool, str]]] = {}
    for r in rows:
        rel = r[0].relative_to(ROOT).as_posix()
        by_name.setdefault(rel, []).append(r)
    for rel in CRITICAL:
        if rel == "main.py":
            bad = [r for r in main_rows if r[2] and r[3] == "pass"]
        else:
            bad = [r for r in by_name.get(rel, []) if r[2] and r[3] == "pass"]
        check(not bad, f"{rel} 无宽泛 except: pass（实际 {len(bad)}）")

    if FAILED:
        print("\n失败：")
        for label in FAILED:
            print(" -", label)
        print("\n宽泛捕获/静默数量上升时，请改窄异常类型、补日志，或更新基线并说明原因。")
        return 1
    print(f"\n全部 {PASSED} 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
