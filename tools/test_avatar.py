"""头像服务 + 侧栏头像卡：默认图、裁剪、元信息、坏图拒绝。

    .venv\\Scripts\\python.exe tools\\test_avatar.py
退出码 0 = 全过；1 = 有断言失败。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def main() -> int:
    app = QApplication(sys.argv[:1])

    from app.services import avatar
    from app.ui.widgets.avatar_card import AvatarCard, rounded_pixmap

    check(avatar.default_path().is_file(), "默认头像 bab-256.png 在 assets 里")
    avatar.reset()
    one = avatar.info()
    check(not one["custom"], "没自定义时 info.custom=False")
    check(one["path"].endswith("bab-256.png"), f"没自定义时路径回默认图（{one['path']}）")
    check(not avatar.pixmap(96).isNull(), "默认图能读成 QPixmap")

    dst = avatar.set_from_file(avatar.default_path())
    one = avatar.info()
    check(one["custom"] and dst.is_file(), "换头像后写进 entity/config/avatar.png")
    img = QImage(str(dst))
    check((img.width(), img.height()) == (256, 256),
          f"自定义头像裁成 256×256（实际 {img.width()}×{img.height()}）")
    check(bool(one["updated_at"]), "avatar.json 记了更换时间")
    check(one["updated_by"] == "主人", f"记了谁换的（{one['updated_by']}）")

    card = AvatarCard("小雨", 96)
    check(card.name_label.text() == "小雨", "头像卡名字在下面")
    check(card.pic.pixmap() is not None and not card.pic.pixmap().isNull(), "头像卡有图")
    check(rounded_pixmap(avatar.pixmap(96), 96).size().width() == 96, "圆角方图尺寸对")

    bad = Path(os.environ.get("TEMP", ".")) / "bab-avatar-bad.txt"
    bad.write_text("not an image", encoding="utf-8")
    try:
        avatar.set_from_file(bad)
        check(False, "非图片应当被拒绝")
    except ValueError:
        check(True, "非图片会被拒绝（ValueError）")
    finally:
        try:
            bad.unlink()
        except OSError:
            pass

    avatar.reset()
    check(not avatar.info()["custom"], "恢复默认后 info.custom=False")
    check(not avatar.custom_path().exists(), "恢复默认会删掉 avatar.png")

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
