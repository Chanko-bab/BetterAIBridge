# -*- coding: utf-8 -*-
"""保姆小屋：统计行、日志行渲染、刷新。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("BAB_NO_AUTORESTART", "1")
os.environ.setdefault("BAB_NO_ANIM", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from app.ui.dialogs.nanny_window import NannyWindow  # noqa: E402

app = QApplication.instance() or QApplication([])
fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


class Fake:
    def __init__(self) -> None:
        self.rows = [
            {"ts": 1_700_000_000, "kind": "notice", "text": "第一次看门"},
            {"ts": 1_700_000_060, "kind": "degraded", "text": "模组没响应"},
        ]

    def nanny_panel(self, limit: int = 160):
        return {
            "ok": True,
            "checks": 3,
            "last_check": 1_700_000_120,
            "modules": [{"id": "routine"}],
            "degraded": [],
            "log": self.rows[-limit:],
        }


fake = Fake()
win = NannyWindow(client=fake)
check(win.windowTitle() == "保姆的小屋", "窗口标题")
stats = win.lbl_stats.text()
check("3 次" in stats and "1 个模组" in stats, f"统计行：{stats}")
check(len(win._rows()) == 2, "两条日志行")
kinds = [w.text() for w in win.body.findChildren(QLabel) if w.objectName() == "NannyLogKind"]
check(kinds == ["提醒", "掉线"], f"kind 翻译：{kinds}")
texts = [w.text() for w in win.body.findChildren(QLabel) if w.objectName() == "NannyLogText"]
check(texts[0] == "第一次看门", "正文渲染")

fake.rows = [{"ts": 1_700_000_300, "kind": "recovered", "text": "又回来了"}]
win.refresh()
check(len(win._rows()) == 1, "刷新后只剩一条")
check("还没有记录" not in win.lbl_hint.text(), "有记录时不显示空提示")

fake.rows = []
win.refresh()
check(len(win._rows()) == 0, "空日志没有行")
check("还没有记录" in win.lbl_hint.text(), "空日志给提示")


class Dead:
    def nanny_panel(self, limit: int = 160):
        raise RuntimeError("boom")

win2 = NannyWindow(client=Dead())
check("没回话" in win2.lbl_stats.text(), "内核失败时给说明")

print()
if fails:
    print(f"FAIL {len(fails)}")
    sys.exit(1)
print("PASS")
