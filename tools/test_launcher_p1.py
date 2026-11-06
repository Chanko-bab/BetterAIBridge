"""启动器 P1：连接复用、线程池上限、气泡上限、设置页任务去重。"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["BAB_NO_UNINSTALL"] = "1"
os.environ["BAB_NO_AUTORESTART"] = "1"
os.environ["BAB_NO_PERSIST"] = "1"
os.environ["BAB_NO_ANIM"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QHBoxLayout  # noqa: E402

from app.services import core_client, worker  # noqa: E402
from app.ui.pages.chat import ChatPage  # noqa: E402
from app.ui.pages.settings import SettingsPage  # noqa: E402

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


def main() -> int:
    QApplication.instance() or QApplication([])

    # 同一个 base 必须复用同一个 Client；关掉后能重建。
    a = core_client._shared_client("http://127.0.0.1:9")
    b = core_client._shared_client("http://127.0.0.1:9")
    check(a is b, "相同 base 复用 httpx.Client")
    a.close()
    c = core_client._shared_client("http://127.0.0.1:9")
    check(c is not a and not c.is_closed, "Client 关闭后自动重建")

    check(worker._pool().maxThreadCount() <= 6, "后台线程池有上限（<=6）")
    check(worker._pool() is worker._pool(), "线程池只建一次")

    # 窗口销毁导致信号发不出去时，任务也不能永久留在 _ALIVE 里。
    task = worker._Task(lambda: 1)
    worker._ALIVE.add(task)

    class BadSignal:
        def emit(self, *_a) -> None:
            raise RuntimeError("window deleted")

    task._emit(BadSignal(), 1)
    check(task not in worker._ALIVE, "信号失败时释放 _ALIVE 引用")

    # 聊天气泡超过上限时从头部淘汰。
    page = ChatPage(FakeWin())
    page._max_bubbles = 5
    for _ in range(9):
        page._add_row(QHBoxLayout())
    check(len(page._bubble_rows) == 5, "聊天气泡只留最近 5 条（测试值）")
    check(page.msg_lay.count() == 6, "消息布局只留 5 行 + 末尾弹簧")

    # 同一调用点的 _spawn 只跑一条；结束后释放 key，可以再次触发。
    st = SettingsPage.__new__(SettingsPage)
    st._spawn_lock = threading.Lock()
    st._spawn_keys = set()
    done: list = []

    def emit(payload) -> None:
        cb, val = payload
        cb(val)

    st._emit = emit
    started = threading.Event()
    release = threading.Event()
    calls = {"n": 0}

    def work():
        calls["n"] += 1
        started.set()
        release.wait(3)
        return 7

    st._spawn(work, on_ok=done.append)
    started.wait(1)
    st._spawn(work, on_ok=done.append)
    time.sleep(0.05)
    check(calls["n"] == 1, "同一调用点重复 _spawn 被去重")
    release.set()
    for _ in range(50):
        if done:
            break
        time.sleep(0.02)
    check(done == [7], "去重后原任务仍回调结果")
    check(not st._spawn_keys, "任务结束后释放去重 key")

    if fails:
        print(f"\n{len(fails)} 条失败")
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
