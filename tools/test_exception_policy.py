"""异常策略：宽泛捕获不能悄悄变多，关键模块不能静默吞。

这是一条“防回流”测试，不追求把宽泛捕获一次清零：
它只要求总量不高于当前基线，并禁止入口/启动器核心/进程清理再出现
`except Exception: pass` 这类无声失败。

0.6.5 起扩到内核侧（内核与启动器是两个进程、两套代码，此前只扫 app，
内核里 56 处静默捕获一直没人管）。内核用的是"按文件给额度、只许减"的
基线：提示词拼装这类地方容错是对的，但静默吞掉会让"她少了一段"无法
追查，所以额度只用来冻结现状，改动必须让它往下走。
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
# 2026-11-08：语音消息新增录音设备启停/清理（winmm 调用没有稳定的异常类型）
# 与 Qt 槽兜底，宽泛捕获 247 → 261；静默/只 pass 仍保持 0。
# 2026-11-08：朗读口型的送事件线程兜底（钩子可能来自内核 HTTP，异常类型不稳定），261 → 262。
BASELINE_BROAD = 262
BASELINE_SILENT = 0
BASELINE_PASS = 0

# ---- 内核侧基线（2026-11-10 盘出 311 处宽泛、56 处静默）----
KERNEL_DIRS = (
    ROOT / "WiseEntity" / "entity" / "core",
    ROOT / "WiseEntity" / "entity" / "brain",
    ROOT / "WiseEntity" / "capability",
)
KERNEL_BASELINE_BROAD = 311
# 每个文件允许的「except: pass」上限，只许减不许增；不在表里的一律为 0。
KERNEL_SILENT_BUDGET: Dict[str, int] = {
    "WiseEntity/entity/core/drives.py": 8,
    "WiseEntity/entity/core/emotion_core.py": 7,
    "WiseEntity/entity/core/chat_core.py": 5,
    "WiseEntity/entity/core/self_store.py": 5,
    "WiseEntity/entity/core/settings.py": 5,
    "WiseEntity/entity/core/voice_store.py": 4,
    "WiseEntity/capability/voice/asr/server.py": 3,
    "WiseEntity/entity/core/tts.py": 3,
    "WiseEntity/entity/core/brain_box.py": 2,
    "WiseEntity/entity/core/bridge.py": 2,
    "WiseEntity/entity/core/nanny.py": 2,
    "WiseEntity/capability/stomach/stomach.py": 1,
    "WiseEntity/entity/brain/flybrain_core.py": 1,
    "WiseEntity/entity/core/event_bus.py": 1,
    "WiseEntity/entity/core/followup.py": 1,
    "WiseEntity/entity/core/maintenance.py": 1,
    "WiseEntity/entity/core/memory_store.py": 1,
    "WiseEntity/entity/core/module_cfg.py": 1,
    "WiseEntity/entity/core/nanny_chat.py": 1,
    "WiseEntity/entity/core/sense.py": 1,
    "WiseEntity/entity/core/style_box.py": 1,
}

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

    # ---- 内核侧：宽泛总量不涨 + 按文件冻结静默捕获 ----
    kernel_paths = sorted(
        {p for d in KERNEL_DIRS for p in d.rglob("*.py") if "__pycache__" not in p.parts}
    )
    kernel_rows = scan(kernel_paths)
    kernel_broad = [r for r in kernel_rows if r[2]]
    kernel_silent: Dict[str, int] = {}
    for r in kernel_broad:
        if r[3] == "pass":
            rel = r[0].relative_to(ROOT).as_posix()
            kernel_silent[rel] = kernel_silent.get(rel, 0) + 1
    total_silent = sum(kernel_silent.values())
    print(f"  kernel: {len(kernel_rows)} except / {len(kernel_broad)} 宽泛 / {total_silent} 静默")
    check(
        len(kernel_broad) <= KERNEL_BASELINE_BROAD,
        f"内核宽泛捕获不高于基线 {KERNEL_BASELINE_BROAD}（实际 {len(kernel_broad)}）",
    )
    over = []
    for rel, n in sorted(kernel_silent.items()):
        cap = KERNEL_SILENT_BUDGET.get(rel, 0)
        if n > cap:
            over.append(f"{rel}({n}>{cap})")
    check(not over, "内核静默捕获未超按文件额度" + ("：" + "、".join(over) if over else ""))

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
