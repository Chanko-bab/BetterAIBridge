"""内核侧头像：默认不描述、不给看；换过之后才进提示词/工具/桥。"""
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
    tool_bus._cache["at"] = 0
    try:
        one = avatar.info()
        check(not one["custom"], "临时目录里没有自定义头像")
        frag = avatar.fragment()
        check("还没换过" in frag and "看不到" in frag, "默认头像：没换过、看不到")
        for word in ("灰发", "像素", "小女孩", "avatar_see"):
            check(word not in frag, f"默认头像提示词不提 {word}")

        got = bridge._avatar_get("m_framework")
        check(got.get("custom") is False and got.get("viewable") is False,
              "默认头像：桥 viewable=false")
        check(got.get("path") == "", "默认头像：桥不给路径")

        names = tool_bus.tools()
        check("avatar_see" not in names, "默认头像：工具清单里没有 avatar_see")
        check("avatar_see" not in tool_bus.describe(), "默认头像：工具说明里没有 avatar_see")
        import asyncio

        seen = asyncio.run(tool_bus.call("avatar_see", {}))
        check(not seen.get("ok") and "还没换过" in str(seen.get("error")),
              "默认头像：直接调也拒绝")

        shutil.copyfile(ROOT / "assets" / "bab-256.png", tmp / "avatar.png")
        (tmp / "avatar.json").write_text(json.dumps({
            "updated_at": "2026-11-03 12:34",
            "updated_by": "对方",
            "source": "mine.png",
        }, ensure_ascii=False), encoding="utf-8")
        one = avatar.info()
        check(one["custom"], "放了 avatar.png 之后 custom=True")
        frag = avatar.fragment()
        check("换过头像" in frag and "2026-11-03 12:34" in frag,
              "自定义头像：提示词带上更换时间与来历")

        got = bridge._avatar_get("m_framework")
        check(got.get("custom") is True and got.get("viewable") is True,
              "自定义头像：桥 viewable=true")
        check(got.get("updated_at") == "2026-11-03 12:34", "桥返回更换时间")
        check(got.get("path", "").endswith("avatar.png"), "桥返回路径")
        check("avatar.get" in bridge.CAPS, "桥注册了 avatar.get 能力")
        check(bridge.CAPS["avatar.get"].get("args") == {}, "avatar.get 不需要参数")

        tool_bus._cache["at"] = 0
        names = tool_bus.tools()
        check("avatar_see" in names, "自定义头像：工具列表里有 avatar_see")
        check("avatar_see" in tool_bus.describe(), "自定义头像：工具说明里有 avatar_see")
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
