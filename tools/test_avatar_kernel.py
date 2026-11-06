"""内核侧头像：提示词片段、桥能力 avatar.get、工具 avatar_see。

不碰真实 entity/config：把 avatar.config_dir 指到临时目录。
    WiseEntity\\entity\\.venv\\Scripts\\python.exe tools\\test_avatar_kernel.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "WiseEntity"))

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def main() -> int:
    from entity.core import avatar, bridge, tool_bus

    tmp = Path(tempfile.mkdtemp(prefix="bab-avatar-k-"))
    avatar.config_dir = lambda: tmp  # type: ignore[assignment]
    try:
        one = avatar.info()
        check(not one["custom"], "临时目录里没有自定义头像")
        frag = avatar.fragment()
        check("默认的灰发头像" in frag, "提示词说清楚现在用的是默认头像")
        check("avatar_see" in frag, "提示词告诉她可以调 avatar_see")

        shutil.copyfile(ROOT / "assets" / "bab-256.png", tmp / "avatar.png")
        (tmp / "avatar.json").write_text(json.dumps({
            "updated_at": "2026-11-03 12:34",
            "updated_by": "主人",
            "source": "mine.png",
        }, ensure_ascii=False), encoding="utf-8")
        one = avatar.info()
        check(one["custom"], "放了 avatar.png 之后 custom=True")
        frag = avatar.fragment()
        check("换过头像" in frag and "2026-11-03 12:34" in frag,
              "提示词带上更换时间与来历")

        got = bridge._avatar_get("m_framework")
        check(got.get("custom") is True and got.get("updated_at") == "2026-11-03 12:34",
              f"桥 avatar.get 返回路径与时间（{got}）")
        check("avatar.get" in bridge.CAPS, "桥注册了 avatar.get 能力")
        check(bridge.CAPS["avatar.get"].get("args") == {}, "avatar.get 不需要参数")

        names = tool_bus.tools()
        check("avatar_see" in names, "工具列表里有 avatar_see")
        desc = tool_bus.describe()
        check("avatar_see" in desc, "工具说明里写了 avatar_see")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if fails:
        print(f"失败 {len(fails)} 条：")
        for f in fails:
            print(" - " + f)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
