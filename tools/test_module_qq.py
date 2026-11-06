"""QQ 桥自检（转发到模组自己的测试，源码不在就跳过）。

真实测试在模组源码目录里：`<QQ_BRIDGE_SRC>\\tools\\test_module_qq.py`。
默认找 `D:\\Program for BAB\\program_qq_bridge.pbab`，也可以用环境变量
`QQ_BRIDGE_SRC` 指到别处（比如解包后的临时目录）。
"""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

SRC = Path(os.environ.get("QQ_BRIDGE_SRC") or r"D:\Program for BAB\program_qq_bridge.pbab")
TEST = SRC / "tools" / "test_module_qq.py"
if not TEST.exists():
    print(f"skip: 没有 QQ 桥源码（{SRC}）")
    raise SystemExit(0)

os.environ["QQ_BRIDGE_SRC"] = str(SRC)
sys.argv = [str(TEST)] + sys.argv[1:]
runpy.run_path(str(TEST), run_name="__main__")
