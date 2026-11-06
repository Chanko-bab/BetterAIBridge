# -*- coding: utf-8 -*-
"""保姆代扫：把模组给的二维码摆出来，替使用者盯着登录状态。"""
from __future__ import annotations

import base64

import httpx
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from ...services.worker import run_async


class QrLoginDialog(QDialog):
    """通用扫码登录框：只认模组的三个接口 /login/qr、/login/poll。"""

    def __init__(self, parent, *, port: int, title: str = "扫码登录", hint: str = "") -> None:
        super().__init__(parent)
        self.port = int(port)
        self.base = f"http://127.0.0.1:{self.port}"
        self.key = ""
        self._finished = False

        self.setWindowTitle(title)
        self.setMinimumWidth(380)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)

        head = QLabel("保姆程序", objectName="CardTitle")
        lay.addWidget(head)

        self.hint = QLabel(hint or "用手机扫这个码，扫完在手机上点「确认登录」。", wordWrap=True)
        lay.addWidget(self.hint)

        self.qr = QLabel("正在要二维码…", alignment=Qt.AlignCenter)
        self.qr.setFixedSize(280, 280)
        self.qr.setStyleSheet("border: 1px solid #d9dde3; border-radius: 10px; background: #fff;")
        lay.addWidget(self.qr, 0, Qt.AlignHCenter)

        self.setWindowFlag(Qt.WindowCloseButtonHint, True)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        btns = QHBoxLayout()
        self.refresh = QPushButton("换一张", objectName="Ghost")
        self.refresh.clicked.connect(self.start)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self._bye)
        btns.addWidget(self.refresh)
        btns.addStretch(1)
        btns.addWidget(self.btn_close)
        lay.addLayout(btns)

        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.poll)

    # ------------------------------------------------------------ 流程
    def start(self) -> None:
        self.key = ""
        self._finished = False
        self.status.setText("")
        self.qr.setText("正在要二维码…")
        self.refresh.setEnabled(False)

        def work():
            with httpx.Client(timeout=25.0) as c:
                r = c.post(f"{self.base}/login/qr")
                r.raise_for_status()
                return r.json()

        run_async(work, on_ok=self._on_qr, on_err=self._on_err)

    def _on_qr(self, res) -> None:
        res = res or {}
        self.refresh.setEnabled(True)
        if not res.get("ok"):
            self._on_err(res.get("error") or "没要到二维码")
            return
        self.key = str(res.get("key") or "")
        raw = base64.b64decode(str(res.get("png_b64") or ""))
        pm = QPixmap()
        if not pm.loadFromData(raw, "PNG"):
            self._on_err("二维码图片坏了")
            return
        self.qr.setPixmap(pm.scaled(268, 268, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.status.setText("等你扫码…")
        self.timer.start()

    def poll(self) -> None:
        if not self.key or self._finished:
            return
        key = self.key

        def work():
            with httpx.Client(timeout=15.0) as c:
                r = c.get(f"{self.base}/login/poll", params={"key": key})
                r.raise_for_status()
                return r.json()

        run_async(work, on_ok=self._on_poll, on_err=self._on_err)

    def _on_poll(self, res) -> None:
        res = res or {}
        if not res.get("ok"):
            self._on_err(res.get("error") or "轮询失败")
            return
        state = str(res.get("state") or "")
        if state == "waiting":
            self.status.setText("等你扫码…")
        elif state == "scanned":
            self.status.setText("扫到了，在手机上点「确认登录」")
        elif state == "ok":
            self._finished = True
            self.timer.stop()
            who = res.get("uname") or res.get("mid") or ""
            self.status.setText(f"登录成功：{who}")
            QTimer.singleShot(900, self.accept)
        elif state == "expired":
            self.timer.stop()
            self.status.setText("二维码过期了，点「换一张」")
        elif state == "need_retry":
            self.timer.stop()
            self.refresh.setEnabled(True)
            self.status.setText(str(res.get("hint") or "手机确认了，但没拿到凭据，点「换一张」重扫"))
        else:
            self.status.setText(str(res.get("hint") or state))

    def _on_err(self, err) -> None:
        self.timer.stop()
        self.refresh.setEnabled(True)
        self.status.setText(f"出错：{err}")

    def _bye(self) -> None:
        self._finished = True
        self.timer.stop()
        self.reject()

    def closeEvent(self, event):  # noqa: N802
        self._finished = True
        self.timer.stop()
        event.accept()
        super().closeEvent(event)
