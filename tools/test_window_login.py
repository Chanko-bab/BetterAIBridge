# -*- coding: utf-8 -*-
"""人工窗口登录框：截图、captcha、置前降级、成功关闭（不连真模组）。"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["BAB_NO_UNINSTALL"] = "1"
os.environ["BAB_NO_AUTORESTART"] = "1"
os.environ["BAB_NO_PERSIST"] = "1"
os.environ["BAB_NO_ANIM"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui.dialogs.window_login import WindowLoginDialog  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def png_b64() -> str:
    pm = QPixmap(24, 24)
    pm.fill(Qt.white)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    pm.save(buf, "PNG")
    buf.close()
    return base64.b64encode(bytes(ba)).decode("ascii")


def main() -> int:
    QApplication.instance() or QApplication([])
    blk = png_b64()

    dlg = WindowLoginDialog(None, port=40736, title="登录抖音", hint="会弹浏览器窗口")
    dlg._auto_show = False
    check(dlg.windowTitle() == "登录抖音", "标题用模组的 label")
    check("浏览器窗口" in dlg.hint.text(), "顶部 hint 来自模组")
    check("不是二维码" in dlg.caption.text(), "截图有“不是二维码”的说明")
    check(hasattr(dlg, "btn_front") and dlg.btn_front.text() == "把窗口叫到前面",
          "有“把窗口叫到前面”按钮")
    check(hasattr(dlg, "refresh") and dlg.refresh.text() == "刷新截图",
          "有“刷新截图”按钮")

    dlg._on_start({"ok": True, "key": "k1", "png_b64": blk,
                   "hint": "窗口已打开，请在里面完成登录。"})
    check(dlg.key == "k1", "记住 poll key")
    check(dlg.timer.isActive(), "拿到 key 后开始轮询")
    check(dlg.shot.pixmap() is not None and not dlg.shot.pixmap().isNull(),
          "截图能显示")
    check("窗口已打开" in dlg.status.text(), "状态显示模组 hint")

    dlg._on_poll({"ok": True, "state": "captcha",
                  "hint": "弹了人机验证，请在浏览器窗口里完成。"})
    check("人机验证" in dlg.status.text(), "captcha 状态显示准话")
    check("b45309" in dlg.status.styleSheet(), "captcha 用警示色")
    check(dlg.timer.isActive(), "captcha 时继续轮询")

    dlg._on_poll({"ok": True, "state": "waiting"})
    check(dlg.status.styleSheet() == "", "回到 waiting 清掉警示色")
    check("浏览器窗口" in dlg.status.text(), "waiting 提示去浏览器窗口")

    dlg._on_show({"ok": False, "missing": True})
    check(not dlg.btn_front.isEnabled(), "模组不支持 /login/show 时按钮禁用")
    check("任务栏" in dlg.status.text(), "缺 /login/show 时给任务栏兜底")

    dlg._on_poll({"ok": True, "state": "ok", "uname": "小号"})
    check(dlg._finished, "ok 后标记完成")
    check(not dlg.timer.isActive(), "ok 后停止轮询")
    check("登录成功" in dlg.status.text(), "ok 后显示成功")

    dlg2 = WindowLoginDialog(None, port=40736)
    dlg2._auto_show = False
    dlg2._on_start({"ok": True, "key": "k2", "hint": "窗口已打开"})
    dlg2._on_poll({"ok": True, "state": "expired", "hint": "窗口关了"})
    check(not dlg2.timer.isActive(), "expired 停止轮询")
    check(dlg2.refresh.isEnabled(), "expired 允许刷新重开")
    check("刷新截图" in dlg2.status.text(), "expired 提示刷新")

    src = (ROOT / "app" / "ui" / "pages" / "mods.py").read_text(encoding="utf-8")
    check('kind == "window"' in src, "on_login 按 login.type 分流")
    check("WindowLoginDialog" in src, "on_login 引用了人工窗口登录框")

    print("PASS" if not fails else f"FAIL {len(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
