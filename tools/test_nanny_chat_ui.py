# -*- coding: utf-8 -*-
"""保姆本体窗口：左右气泡、发送、假回复、busy 复位、历史回填。"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("BAB_NO_PERSIST", "1")
os.environ.setdefault("BAB_NO_ANIM", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from app.ui.dialogs import nanny_chat as nc  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def pump(ms: int = 60) -> None:
    end = time.time() + ms / 1000
    while time.time() < end:
        QApplication.processEvents()
        time.sleep(0.005)


def bubbles(win) -> list[str]:
    out = []
    for b in win.host.findChildren(nc._Bubble):
        lab = b.findChild(QLabel)
        out.append(lab.text() if lab else "")
    return out


class FakeClient:
    def __init__(self) -> None:
        self.said: list[tuple[str, str]] = []
        self.closed: list[str] = []

    def nanny_chat_open(self) -> dict:
        return {"ok": True, "session": "abcdef123456", "opening": nc.OPENING, "msgs": []}

    def nanny_chat(self, session: str, text: str) -> dict:
        self.said.append((session, text))
        return {"ok": True, "reply": "你装了一个日常事务模组。", "session": session, "ts": "11-05 10:20"}

    def nanny_chat_close(self, session: str) -> dict:
        self.closed.append(session)
        return {"ok": True}


app = QApplication.instance() or QApplication(sys.argv)
fake = FakeClient()
win = nc.NannyChatWindow(client=fake)
pump(200)

texts = bubbles(win)
check(any(nc.OPENING in t for t in texts), "窗口里先显示原话开场白")
check(win.session == "abcdef123456", "打开了会话")
check(not hasattr(win, "lbl_state"), "没有“只读·不写记忆”的标题字")
check(not any(t in ("她", "你") for t in texts), "没有“她/你”标签")

win.ed.setText("我加了哪些模组？")
win.send()
pump(300)
texts = bubbles(win)
check(any("我加了哪些模组" in t for t in texts), "用户这句进了记录")
check(any("日常事务" in t for t in texts), "她的回复进了记录")
check(len(texts) >= 3, "开场白、用户、回复都在")
check(fake.said and fake.said[0][0] == "abcdef123456", "带 session 调内核")
check(win.ed.isEnabled() and win.btn_send.isEnabled(), "回完恢复输入")
check(win.ed.text() == "", "发完清空输入框")

# 空文本不发
win.send()
pump(50)
check(len(fake.said) == 1, "空文本不发请求")

# 历史回填：上次的消息带时间显示，不再重复开场白
win2 = nc.NannyChatWindow(client=type("Old", (), {
    "nanny_chat_open": lambda self: {
        "ok": True, "session": "old1",
        "msgs": [
            {"role": "user", "content": "上次说到哪", "ts": "11-04 22:00"},
            {"role": "assistant", "content": "说到存档了", "ts": "11-04 22:01"},
        ],
    },
})())
pump(150)
texts2 = bubbles(win2)
check(any("上次说到哪" in t for t in texts2), "重新打开带回上次用户消息")
check(any("说到存档了" in t for t in texts2), "重新打开带回上次保姆消息")
check(not any("虽然不清楚" in t for t in texts2), "有历史不重复开场白")

# 失败显示原因、不卡 busy
win3 = nc.NannyChatWindow(client=type("Bad", (), {
    "nanny_chat_open": lambda self: {"ok": True, "session": "s1", "opening": nc.OPENING, "msgs": []},
    "nanny_chat": lambda self, s, t: (_ for _ in ()).throw(RuntimeError("boom")),
})())
pump(150)
win3.ed.setText("在吗")
win3.send()
pump(300)
check("没回上" in "".join(bubbles(win3)), "失败时告诉她没回上")
check("boom" in "".join(bubbles(win3)), "失败时把原因带回来")
check(win3.btn_send.isEnabled(), "失败后按钮也能再点")

win.close()
win2.close()
win3.close()
print()
if fails:
    print(f"FAILED {len(fails)}")
    sys.exit(1)
print("PASS")
