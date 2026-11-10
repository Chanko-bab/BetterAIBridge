"""BAB 认知块：只讲住处，不讲开发者与实现细节。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "WiseEntity"))

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def main() -> int:
    from entity.core import home_box

    text = home_box.fragment()
    for word in ("BAB", "Windows", "本地程序", "智能体", "模组", "安装目录"):
        check(word in text, f"提到 {word}")
    check("像我的电脑" in text or "像家" in text or "像我的家" in text,
          "用电脑/家解释住处")
    for word in ("琛柯", "开发者", "40720", "端口", "主人", "她"):
        check(word not in text, f"不写 {word}")
    check(len(text) < 400, "不超过一小段")

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
