"""仓库 UI：附件按钮、待发条、图片/文件气泡（不连内核）。"""
from __future__ import annotations

import base64
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["BAB_NO_UNINSTALL"] = "1"
os.environ["BAB_NO_AUTORESTART"] = "1"
os.environ["BAB_NO_PERSIST"] = "1"
os.environ["BAB_NO_ANIM"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from app.ui.pages.chat import ChatPage  # noqa: E402
from app.ui.widgets.media_bubble import MediaBubble  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


class FakeWin:
    def __init__(self) -> None:
        self.pages: dict = {}

    def show_page(self, *_a, **_k) -> None:
        pass


def labels(w) -> list[str]:
    return [x.text() for x in w.findChildren(QLabel)]


def main() -> int:
    QApplication.instance() or QApplication([])
    page = ChatPage(FakeWin())
    check(hasattr(page, "btn_file"), "输入行有附件按钮")
    check(hasattr(page, "media_bar") and page.media_bar.isHidden(), "待发条默认收起")
    check(page._attach is None, "默认没有待发附件")

    tmp = Path(tempfile.mkdtemp(prefix="bab_wh_ui_"))
    img = tmp / "猫.png"
    img.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="))
    row = {"id": "abc123", "name": "猫.png", "kind": "image", "bytes": 68,
           "path": str(img), "source": "owner"}
    page._attach = row
    page.media_label.setText("图片：猫.png（1 KB）")
    page.media_bar.show()
    check(not page.media_bar.isHidden(), "选完附件待发条出现")
    page._clear_attachment()
    check(page._attach is None and page.media_bar.isHidden(), "取消后待发条收起")

    page.media_bubble("me", row, "看看这个")
    boxes = page.findChildren(MediaBubble)
    check(len(boxes) == 1, "聊天里能画附件气泡")
    if boxes:
        check(boxes[0].objectName() == "MediaBubbleMe", "自己的附件在右侧样式")
        check("猫.png" in labels(boxes[0]) and "看看这个" in labels(boxes[0]),
              "气泡带文件名与附言")

    gone = {"id": "x", "name": "旧.pdf", "kind": "document", "bytes": 2048,
            "path": str(tmp / "nope.pdf"), "source": "owner"}
    b = MediaBubble(gone, "", "her")
    check(b.objectName() == "MediaBubbleHer", "对方的附件在左侧样式")
    check(any("不在仓库" in x for x in labels(b)), "文件缺失时写明不在仓库")

    page.close()
    print(f"\n{'ALL PASS' if not fails else 'FAILED ' + str(len(fails))}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
