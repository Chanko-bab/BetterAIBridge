"""本地语音包后台安装任务：关窗继续、进度、失败、重开接上。"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import app.services.local_tts_job as mod  # noqa: E402
from app.core import local_tts  # noqa: E402
from app.ui.dialogs.local_tts_install import LocalTtsInstallDialog  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _wait_until(pred, timeout=6.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        _app.processEvents()
        if pred():
            return True
        time.sleep(0.02)
    _app.processEvents()
    return bool(pred())


def test_job_progress_and_done():
    seen = []
    mod.job.progress.connect(lambda p, m: seen.append((p, m)))
    old_install, old_start = local_tts.install, local_tts.start

    def fake_install(cb):
        cb(5, "创建独立运行环境")
        cb(45, "下载中文语音模型")
        return {"version": "fake-moss"}

    local_tts.install = fake_install
    local_tts.start = lambda: None
    try:
        assert mod.job.start() is True
        assert mod.job.start() is False, "已经在跑时不应重复开线程"
        # 进度信号是跨线程排队的：等任务结束之外，还要等最后一条进度送到主线程，
        # 否则会在“已经结束、但 45% 还没 processEvents”的窗口里误判。
        assert _wait_until(lambda: not mod.job.running and len(seen) >= 2), (mod.job.state(), seen)
        st = mod.job.state()
        assert st["ok"] and st["pct"] == 100, st
        assert any("下载中文语音模型" == m for _p, m in seen), seen
    finally:
        local_tts.install = old_install
        local_tts.start = old_start


def test_job_failure_keeps_message():
    old_install = local_tts.install

    def bad(_cb):
        raise RuntimeError("模拟下载失败")

    local_tts.install = bad
    try:
        assert mod.job.start() is True
        assert _wait_until(lambda: not mod.job.running)
        st = mod.job.state()
        assert st["ok"] is False
        assert "模拟下载失败" in st["error"], st
    finally:
        local_tts.install = old_install


def test_dialog_close_keeps_job_running():
    old_install, old_start = local_tts.install, local_tts.start

    def slow(_cb):
        time.sleep(0.45)
        return {"version": "slow"}

    local_tts.install = slow
    local_tts.start = lambda: None
    try:
        dlg = LocalTtsInstallDialog(None)
        dlg.start_install()
        assert _wait_until(lambda: mod.job.running)
        dlg.close()
        _app.processEvents()
        assert not dlg.isVisible()
        assert mod.job.running, "关窗不应取消安装"
        assert _wait_until(lambda: not mod.job.running)
        assert mod.job.state()["ok"]
    finally:
        local_tts.install = old_install
        local_tts.start = old_start


def test_dialog_syncs_running_job_on_reopen():
    old_install, old_start = local_tts.install, local_tts.start

    def slow(_cb):
        time.sleep(0.35)
        return {"version": "again"}

    local_tts.install = slow
    local_tts.start = lambda: None
    try:
        assert mod.job.start() is True
        dlg = LocalTtsInstallDialog(None)
        assert not dlg.btn_start.isEnabled()
        assert dlg.btn_close.text() == "后台继续"
        assert _wait_until(lambda: not mod.job.running)
        _app.processEvents()
        assert dlg.ok
    finally:
        local_tts.install = old_install
        local_tts.start = old_start


if __name__ == "__main__":
    test_job_progress_and_done()
    test_job_failure_keeps_message()
    test_dialog_close_keeps_job_running()
    test_dialog_syncs_running_job_on_reopen()
    print("local_tts_job: all passed")
