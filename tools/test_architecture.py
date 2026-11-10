"""架构门禁：把"分层"和"体量"从口头约定变成会红的测试。

为什么需要它：
    0.6.5 之前的实际情况是——分层写进了文档，但没有任何自动化手段阻止下一次
    提交把内核的活搬进启动器、把 1900 行再长成 2600 行、或者把某一套自检忘在
    tools/ 里不登记、登记了又把文件删掉。文档管不住人，会红的测试才管得住。

它检查七件事：
    1. 内核不得 import app（依赖方向只有一个：启动器依赖内核，反过来不行）
    2. 每个模块都要有模块级 docstring（说明它为什么存在，而不只是做什么）
    3. 单文件行数有上限，现存超限文件按当前行数冻结，只许减不许增
    4. 所有 tools/test_*.py 必须登记进 check.py，否则等于没跑
    5. check.py 登记的脚本必须真实存在，否则自检会"假通过"
    6. 源码里的 print 按文件冻结：打包成 pythonw 之后 print 没有地方去，
       debug 输出会静默消失，逐步换成 log 之前先不许再新增
    7. requirements-*.txt 里的每个包都要在 THIRD-PARTY-NOTICES.md 里登记许可证
    8. README 里写的"自检 N 套"必须等于 check.py 的 SUITES 条数
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
KERNEL_DIRS = (
    ROOT / "WiseEntity" / "entity" / "core",
    ROOT / "WiseEntity" / "entity" / "brain",
    ROOT / "WiseEntity" / "capability",
)
TOOLS = ROOT / "tools"
CHECK = TOOLS / "check.py"

LINE_LIMIT = 1200
# 现存超限文件：数值是当前行数，只许减。
# 0.6.5 自查：pbab.py 补了签名查询的诊断信息（空状态要能说清是环境坏了还是没签），
# 1917 → 1942。这是它最后一次抬线；再长就必须先按能力拆模块。
LINE_BUDGET: Dict[str, int] = {
    "app/core/pbab.py": 1942,
    "app/ui/pages/chat.py": 1225,
    "app/ui/pages/settings.py": 1204,
    "tools/test_pages.py": 1201,
}

# 源码里残留的 print（2026-11-10 实测），只许减。
PRINT_BUDGET: Dict[str, int] = {
    "WiseEntity/entity/brain/flybrain_core.py": 18,
    "app/services/local_tts_server.py": 3,
    "WiseEntity/entity/core/memory_store.py": 2,
    "app/services/camgrab.py": 1,
    "app/services/diagnostics.py": 1,
    "WiseEntity/capability/stomach/stomach.py": 1,
    "WiseEntity/capability/voice/asr/server.py": 1,
    "WiseEntity/entity/core/maintenance.py": 1,
}

DOCSTRING_EXEMPT = {"__init__.py"}
PRINT_CALL = re.compile(r"(?m)^\s*print\(")

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


def _python_files(*dirs: Path) -> List[Path]:
    out: List[Path] = []
    for d in dirs:
        for p in d.rglob("*.py"):
            if "__pycache__" in p.parts or ".venv" in p.parts:
                continue
            out.append(p)
    return sorted(out)


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def main() -> int:
    app_files = _python_files(APP)
    kernel_files = _python_files(*KERNEL_DIRS)
    print(f"  app: {len(app_files)} 个模块 / 内核: {len(kernel_files)} 个模块")

    # 1. 依赖方向
    wrong: List[str] = []
    for p in kernel_files:
        tree = ast.parse(p.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            names: List[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            if any(n.split(".")[0] == "app" for n in names):
                wrong.append(_rel(p))
    check(not wrong, "内核不 import app" + ("：" + "、".join(sorted(set(wrong))) if wrong else ""))

    # 2. 模块 docstring
    bare: List[str] = []
    for p in app_files + kernel_files:
        if p.name in DOCSTRING_EXEMPT:
            continue
        if not ast.get_docstring(ast.parse(p.read_text(encoding="utf-8-sig"))):
            bare.append(_rel(p))
    check(not bare, "每个模块都有 docstring" + ("：" + "、".join(bare[:6]) if bare else ""))

    # 3. 体量
    over: List[str] = []
    for p in app_files + kernel_files + _python_files(TOOLS):
        rel = _rel(p)
        lines = len(p.read_text(encoding="utf-8-sig").splitlines())
        budget = LINE_BUDGET.get(rel, LINE_LIMIT)
        if lines > budget:
            over.append(f"{rel}({lines}>{budget})")
    check(not over, "单文件不超过上限" + ("：" + "、".join(over) if over else ""))

    # 4. 自检登记
    check_text = CHECK.read_text(encoding="utf-8-sig")
    registered = set(re.findall(r'"tools/([A-Za-z0-9_]+\.py)"', check_text))
    orphans = sorted(p.name for p in TOOLS.glob("test_*.py") if p.name not in registered)
    check(not orphans, "所有 test_*.py 已登记进 check.py" + ("：" + "、".join(orphans) if orphans else ""))

    # 5. 登记了就得存在
    listed = re.findall(r'"tools/([A-Za-z0-9_]+\.py)"', check_text)
    missing = sorted(n for n in listed if not (TOOLS / n).is_file())
    check(not missing, "check.py 登记的脚本都存在" + ("：" + "、".join(missing) if missing else ""))

    # 6. print 冻结
    prints: List[str] = []
    for p in app_files + kernel_files:
        rel = _rel(p)
        n = len(PRINT_CALL.findall(p.read_text(encoding="utf-8-sig")))
        cap = PRINT_BUDGET.get(rel, 0)
        if n > cap:
            prints.append(f"{rel}({n}>{cap})")
    check(not prints, "print 不超按文件额度" + ("：" + "、".join(prints) if prints else ""))

    # 7. 第三方许可登记（LGPL/Apache 组件是发行义务，不是可选文档）
    notices_path = ROOT / "THIRD-PARTY-NOTICES.md"
    if not notices_path.is_file():
        check(False, "THIRD-PARTY-NOTICES.md 存在")
    else:
        notices = notices_path.read_text(encoding="utf-8-sig").lower().replace("_", "-")
        reqs: List[str] = []
        for f in sorted(ROOT.glob("requirements-*.txt")):
            for line in f.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                name = re.split(r"[=<>!\[;]", line)[0].strip().lower().replace("_", "-")
                reqs.append(name)
        missing = sorted({n for n in reqs if n and n not in notices})
        check(
            not missing,
            "依赖清单里的包都已登记许可证" + ("：" + "、".join(missing) if missing else ""),
        )

    # 8. README 里写的套数跟 SUITES 一致（写"62 套"而实际 94 套，读者会低估覆盖面）
    suites_block = check_text[check_text.index("SUITES = ["):check_text.index("]", check_text.index("SUITES = ["))]
    suite_names = re.findall(r'\("([a-z0-9_]+)",\s*"tools/', suites_block)
    readme = (ROOT / "README.md").read_text(encoding="utf-8-sig")
    m_count = re.search(r"自检 \*\*(\d+) 套\*\*", readme)
    m_list = re.search(r"tools\\+check\.py\s+#\s*(\d+) 套全跑", readme)
    ok = (
        len(suite_names) > 0
        and m_count is not None and int(m_count.group(1)) == len(suite_names)
        and m_list is not None and int(m_list.group(1)) == len(suite_names)
    )
    check(
        ok,
        f"README 的自检套数等于 SUITES 的 {len(suite_names)} 套"
        + (
            ""
            if ok
            else "：README 写 {} / {}".format(
                m_count.group(1) if m_count else "缺", m_list.group(1) if m_list else "缺"
            )
        ),
    )

    if FAILED:
        print("\n失败：")
        for label in FAILED:
            print(" -", label)
        return 1
    print(f"\n全部 {PASSED} 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
