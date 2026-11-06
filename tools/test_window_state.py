"""窗口位置：坏坐标要夹回可见区，正常坐标下次原样回来。"""
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

from PySide6.QtWidgets import QApplication  # noqa: E402

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


def main() -> int:
    QApplication.instance() or QApplication([])
    saved: dict = {
        "ui.window_size": [700, 600],
        # 一块已经不存在的屏幕的位置
        "ui.window_pos": [-9000, -9000],
    }
    old_get, old_set = mw.config.get, mw.config.set_value
    mw.config.get = lambda key, default=None: saved.get(key, default)
    mw.config.set_value = lambda key, value: saved.__setitem__(key, value)
    mw.CoreClient = FakeClient
    _probe.summary = lambda: {"ports": {"core": True}, "detail": {}}

    win = mw.MainWindow()
    win.show()
    pump(0.35)
    screen = QApplication.primaryScreen().availableGeometry()
    hit = win.frameGeometry().intersected(screen)
    check(hit.width() >= 160 and hit.height() >= 80, "坏坐标被夹回可见区")

    # 保存位置/大小（测试里临时关掉 NO_PERSIST 守卫）
    os.environ.pop("BAB_NO_PERSIST", None)
    win.move(40, 50)
    win.resize(1000, 700)
    win._save_window_size()
    check(saved.get("ui.window_size") == [1000, 700], "窗口大小被保存")
    check(saved.get("ui.window_pos") == [40, 50], "窗口位置被保存")

    win._quitting = True
    win.close()
    win.deleteLater()
    pump(0.15)
    mw.config.get, mw.config.set_value = old_get, old_set
    print("PASS" if not fails else f"{len(fails)} FAILED")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
