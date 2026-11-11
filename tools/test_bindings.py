# -*- coding: utf-8 -*-
"""模组排他绑定：一个模组只属于一个智能体，换人必须显式解绑。"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from app.core import bindings  # noqa: E402

FAILS: list[str] = []
OKS = 0


def check(ok: bool, msg: str) -> None:
    global OKS
    if ok:
        OKS += 1
    else:
        FAILS.append(msg)


def main() -> int:
    keys = ("BAB_ROOT", "BAB_AGENT_ROOT", "BAB_AGENT_ID")
    old = {k: os.environ.get(k) for k in keys}
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.environ["BAB_ROOT"] = str(root)
            os.environ.pop("BAB_AGENT_ROOT", None)
            os.environ.pop("BAB_AGENT_ID", None)

            bindings.bind("qq_bridge", "xiaoyue")
            check(bindings.owner("qq_bridge") == "xiaoyue", "绑定应落盘")
            check((root / "modules.bindings.json").exists(), "绑定文件应在安装根")

            os.environ["BAB_AGENT_ID"] = "abai"
            try:
                bindings.ensure_free("qq_bridge")
                check(False, "abai 不应能启用绑定给 xiaoyue 的模组")
            except bindings.BindingError as exc:
                check("xiaoyue" in str(exc), "拒绝信息应带绑定者名字")
                check("绑定到" in str(exc), "拒绝信息应说清楚原因")

            try:
                bindings.bind("qq_bridge", "abai")
                check(False, "abai 不应能抢绑定")
            except bindings.BindingError:
                check(True, "")

            try:
                bindings.unbind("qq_bridge", "abai")
                check(False, "abai 不应能解别人的绑定")
            except bindings.BindingError:
                check(True, "")

            bindings.unbind("qq_bridge", "xiaoyue")
            check(bindings.owner("qq_bridge") == "", "解绑后应为空")
            bindings.bind("qq_bridge", "abai")
            check(bindings.owner("qq_bridge") == "abai", "解绑后别人可以绑定")

            got = bindings.reconcile(["xiaoyue"])
            check(got == ["qq_bridge"], "reconcile 应清掉已不存在智能体的绑定")
            check(bindings.owner("qq_bridge") == "", "reconcile 后绑定应清空")
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    print(f"\nPASS {OKS} / FAIL {len(FAILS)}")
    for f in FAILS:
        print("  FAIL", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
