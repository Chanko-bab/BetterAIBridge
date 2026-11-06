"""启动器空闲行为：隐藏到托盘/切页后应停止轮询，回来再恢复。"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["BAB_NO_UNINSTALL"] = "1"
os.environ["BAB_NO_AUTORESTART"] = "1"
os.environ["BAB_NO_PERSIST"] = "1"
os.environ["BAB_NO_ANIM"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402

from app.services import probe as _probe  # noqa: E402
import app.ui.main_window as mw  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def pump(seconds: float = 0.25) -> None:
    end = time.time() + seconds
    while time.time() < end:
        QApplication.processEvents()
        time.sleep(0.01)


class FakeClient:
    def __init__(self, *a, **k) -> None:
        pass

    def health(self): return {"ok": True, "version": "test", "root": str(ROOT)}
    def state(self): return {}
    def brain_state(self): return {}
    def drives(self): return {}
    def stomach(self): return {}
    def emotions(self): return {}
    def set_presence(self, *_a, **_k): return {"ok": True}
    def set_grant(self, *_a, **_k): return {"ok": True}


def main() -> int:
    app = QApplication.instance() or QApplication([])
    mw.CoreClient = FakeClient
    _probe.summary = lambda: {"ports": {"core": True}, "detail": {}}
    win = mw.MainWindow()
    win.show()
    pump(0.6)
    check(win.timer_state.isActive(), "显示时状态轮询在跑")
    check(win.timer_ports.isActive(), "显示时端口探测在跑")
    win.hide()
    pump(0.3)
    check(not win.timer_state.isActive(), "隐藏后状态轮询停了")
    check(not win.timer_ports.isActive(), "隐藏后端口探测停了")
    if hasattr(win, "timer_bridge"):
        check(not win.timer_bridge.isActive(), "隐藏后界面桥停了")
    chat = win.pages["chat"]
    check(not chat.poll_timer.isActive(), "隐藏后聊天轮询停了")
    win.show()
    pump(0.4)
    check(win.timer_state.isActive(), "回来状态轮询恢复")
    check(win.timer_ports.isActive(), "回来端口探测恢复")
    win.show_page("logs")
    pump(0.3)
    logs = win.pages["logs"]
    check(logs.timer.isActive(), "日志页显示时在贴尾")
    check(not chat.poll_timer.isActive(), "切到日志后聊天轮询停了")

    # 日志页上翻时不要被新日志拉回底部
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        lp = Path(td) / "scroll.log"
        lp.write_text("\n".join(f"line {i}" for i in range(240)), encoding="utf-8")
        logs.combo.addItem(str(lp))
        logs.combo.setCurrentIndex(logs.combo.count() - 1)
        logs.tail(force=True)
        pump(0.2)
        bar = logs.view.verticalScrollBar()
        check(bar.maximum() > 0, "日志页有可滚动内容")
        bar.setValue(0)
        before = bar.value()
        lp.write_text("\n".join(f"line {i}" for i in range(241)), encoding="utf-8")
        logs.tail(force=True)
        pump(0.1)
        check(bar.value() == before, "日志页上翻时位置不被重置")
        bar.setValue(bar.maximum())
        lp.write_text("\n".join(f"line {i}" for i in range(242)), encoding="utf-8")
        logs.tail(force=True)
        pump(0.1)
        check(bar.value() >= bar.maximum() - 4, "日志页在底部时继续贴底")

    # 保姆栏在底部时，新提醒应该真的滚到最新一条
    win.show_page("chat")
    pump(0.2)
    nanny = chat.nanny
    nanny.set_collapsed(False)
    for i in range(40):
        nanny.add(time.time() + i, f"滚动测试 {i}")
    pump(0.4)
    nbar = nanny.scroll.verticalScrollBar()
    check(nbar.value() >= nbar.maximum() - 4, "保姆栏新提醒滚动到底")

    win.show_page("chat")
    pump(0.3)
    check(chat.poll_timer.isActive(), "切回聊天后轮询恢复")
    check(not logs.timer.isActive(), "离开日志页后贴尾停了")
    win.tray.hide()
    if not QSystemTrayIcon.isSystemTrayAvailable():
        win.close()
        pump(0.2)
        check(win.isMinimized(), "托盘不可用时关闭改为最小化")
    win._quitting = True
    win.close()
    win.deleteLater()
    pump(0.2)
    print("PASS" if not fails else f"{len(fails)} FAILED")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
