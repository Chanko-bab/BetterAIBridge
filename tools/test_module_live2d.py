"""立绘自检（转发到模组自己的测试，源码不在就跳过）。

真实测试在模组源码目录里：`<LIVE2D_SRC>\\tools\\test_module_live2d.py`。
默认找 `D:\\Program for BAB\\program_live2d_bridge.pbab`，也可以用环境变量
`LIVE2D_SRC` 指到别处。
"""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

SRC = Path(os.environ.get("LIVE2D_SRC") or r"D:\Program for BAB\program_live2d_bridge.pbab")
TEST = SRC / "tools" / "test_module_live2d.py"

if not TEST.is_file():
    print("skip: 没找到立绘源码（%s），跳过这一套" % TEST)
    sys.exit(0)

sys.argv = [str(TEST)]
runpy.run_path(str(TEST), run_name="__main__")
