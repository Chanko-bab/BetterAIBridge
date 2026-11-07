"""更新确认/下载/重启对话框。"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout,
)

from ...core import config
from ...services import update


class _Download(QThread):
    tick = Signal(int, int)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, info: update.UpdateInfo, parent=None):
        super().__init__(parent)
        self.info = info

    def run(self) -> None:
        try:
            dest = Path(tempfile.gettempdir()) / f"BetterAIBridge-{self.info.version}-update.zip"
            update.download(
                self.info.update_url,
                dest,
                self.info.sha256,
                self.info.size,
                progress=lambda done, total: self.tick.emit(int(done), int(total)),
            )
            self.done.emit(str(dest))
        except (update.UpdateError, OSError, ValueError, TypeError, RuntimeError) as e:
            self.failed.emit(str(e))


class UpdateDialog(QDialog):
    def __init__(self, parent, info: update.UpdateInfo):
        super().__init__(parent)
        self.info = info
        self._worker: _Download | None = None
        self._closed = False
        self._wait_tries = 0
        self.setWindowTitle("更新 BetterAIBridge")
        self.setModal(True)
        self.setMinimumWidth(460)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        lay.addWidget(QLabel(f"正在下载 {info.version}…"))
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        lay.addWidget(self.bar)
        self.status = QLabel("准备下载…")
        self.status.setObjectName("Muted")
        lay.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn = QPushButton("取消", objectName="Ghost")
        self.btn.clicked.connect(self._cancel)
        row.addWidget(self.btn)
        lay.addLayout(row)

        self._worker = _Download(info, self)
        self._worker.tick.connect(self._tick)
        self._worker.done.connect(self._done)
        self._worker.failed.connect(self._failed)
        QTimer.singleShot(0, self._worker.start)

    def _tick(self, done: int, total: int) -> None:
        if total > 0:
            self.bar.setRange(0, total)
            self.bar.setValue(min(done, total))
            self.status.setText(f"{done / 1024 / 1024:.1f} / {total / 1024 / 1024:.1f} MB")
        else:
            self.status.setText(f"{done / 1024 / 1024:.1f} MB")

    def _cancel(self) -> None:
        # 下载不支持中途取消；关掉窗口，下载完也不会应用。
        self._closed = True
        self.reject()

    def _done(self, zip_path: str) -> None:
        if self._closed:
            Path(zip_path).unlink(missing_ok=True)
            return
        try:
            update.spawn_helper(Path(config.APP_DIR), Path(zip_path), self.info.version, os.getpid())
        except (OSError, ValueError, RuntimeError) as e:
            self._failed(f"启动更新程序失败：{e}")
            return
        self.status.setText("正在确认更新程序已经接手…")
        self.btn.setText("正在启动…")
        self.btn.setEnabled(False)
        self._wait_tries = 0
        QTimer.singleShot(100, self._check_helper)

    def _check_helper(self) -> None:
        if self._closed:
            return
        state = update.helper_state()
        if state in ("ready", "done"):
            self.status.setText("更新程序已接手，启动器即将退出…")
            self.accept()
            QTimer.singleShot(400, QApplication.quit)
            return
        if state == "failed":
            self._failed("更新程序启动失败，已保留当前版本；请手动下载安装包。")
            return
        self._wait_tries += 1
        if self._wait_tries >= 300:
            self._failed("更新程序没有响应，已保留当前版本；请手动下载安装包。")
            return
        QTimer.singleShot(100, self._check_helper)

    def _failed(self, text: str) -> None:
        if self._closed:
            return
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.status.setText(text)
        self.btn.setText("关闭")
        self.btn.clicked.disconnect()
        self.btn.clicked.connect(self.reject)
