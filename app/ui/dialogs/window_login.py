# -*- coding: utf-8 -*-
"""人工窗口登录：模组自己开浏览器，启动器只负责截图、说明、把窗口叫到前面。

模块契约（都可选）：
  POST /login/qr      -> {ok,key,manual,kind,hint,png_b64}
  GET  /login/poll    -> {ok,state,hint,...}  state 支持 waiting/captcha/scanned/ok/expired
  POST /login/show    -> {ok}                  把浏览器窗口叫到前面
"""
from __future__ import annotations

import base64
import binascii

import httpx
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from ...services.worker import run_async

MAX_IMAGE_BYTES = 8 * 1024 * 1024
_CAPTCHA_STYLE = "color: #b45309;"


class WindowLoginDialog(QDialog):
    """给“自己开浏览器、要人工过验证码”的模组用的登录框。"""

    def __init__(self, parent, *, port: int, title: str = "登录", hint: str = "") -> None:
        super().__init__(parent)
        self.port = int(port)
        self.base = f"http://127.0.0.1:{self.port}"
        self.key = ""
        self._finished = False
        self._auto_show = True
        self._captcha = False

        self.setWindowTitle(title)
        self.setMinimumWidth(420)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)

        head = QLabel("保姆程序", objectName="CardTitle")
        lay.addWidget(head)

        self.hint = QLabel(hint or "点下面的按钮打开登录窗口，在窗口里完成扫码或验证。", wordWrap=True)
        lay.addWidget(self.hint)

        self.shot = QLabel("正在打开登录窗口…", alignment=Qt.AlignCenter)
        self.shot.setFixedSize(360, 260)
        self.shot.setStyleSheet(
            "border: 1px solid #d9dde3; border-radius: 10px; background: #fff; color: #6b7280;"
        )
        lay.addWidget(self.shot, 0, Qt.AlignHCenter)

        self.caption = QLabel("浏览器窗口截图（不是二维码）", alignment=Qt.AlignHCenter)
        self.caption.setStyleSheet("color: #6b7280; font-size: 12px;")
        lay.addWidget(self.caption)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        btns = QHBoxLayout()
        self.btn_front = QPushButton("把窗口叫到前面", objectName="Ghost")
        self.btn_front.clicked.connect(self._call_show)
        self.refresh = QPushButton("刷新截图", objectName="Ghost")
        self.refresh.clicked.connect(self.start)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self._bye)
        btns.addWidget(self.btn_front)
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
        self._captcha = False
        self.status.setStyleSheet("")
        self.status.setText("正在打开登录窗口…")
        self.shot.setPixmap(QPixmap())
        self.shot.setText("正在打开登录窗口…")
        self.refresh.setEnabled(False)
        self.btn_front.setEnabled(True)

        def work():
            with httpx.Client(timeout=75.0) as c:
                r = c.post(f"{self.base}/login/qr")
                r.raise_for_status()
                return r.json()

        run_async(work, on_ok=self._on_start, on_err=self._on_err)

    def _on_start(self, res) -> None:
        res = res or {}
        self.refresh.setEnabled(True)
        if not res.get("ok"):
            self._on_err(res.get("error") or "没打开登录窗口")
            return
        self.key = str(res.get("key") or "")
        raw = str(res.get("png_b64") or "")
        data = b""
        if raw:
            try:
                data = base64.b64decode(raw, validate=False)
            except (binascii.Error, ValueError):
                data = b""
        if data and len(data) <= MAX_IMAGE_BYTES:
            pm = QPixmap()
            if pm.loadFromData(data):
                self.shot.setPixmap(
                    pm.scaled(348, 248, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
            else:
                self.shot.setText("模块没给可显示的截图\n请看浏览器窗口")
        else:
            self.shot.setText("模块没给截图\n请看浏览器窗口")
        self.status.setText(str(res.get("hint") or "浏览器窗口已打开，请在这个窗口里完成登录。"))
        self.timer.start()
        if self._auto_show:
            QTimer.singleShot(80, self._call_show)

    def _call_show(self) -> None:
        if self._finished or not self.key:
            return

        def work():
            with httpx.Client(timeout=8.0) as c:
                r = c.post(f"{self.base}/login/show")
                if r.status_code == 404:
                    return {"ok": False, "missing": True}
                r.raise_for_status()
                return r.json()

        run_async(work, on_ok=self._on_show, on_err=self._on_show_err)

    def _on_show(self, res) -> None:
        res = res or {}
        if res.get("missing"):
            self.btn_front.setEnabled(False)
            self.btn_front.setToolTip("这个模组没有 /login/show，请到任务栏点浏览器窗口")
            if not self._captcha:
                self.status.setStyleSheet("")
                self.status.setText("请到任务栏点开浏览器窗口完成登录（这个模组不支持自动置前）。")
            return
        if not res.get("ok"):
            if not self._captcha:
                self.status.setStyleSheet("")
                self.status.setText(str(res.get("error") or "没抢到前台，请到任务栏点浏览器窗口。"))
            return
        if not self._captcha:
            self.status.setStyleSheet("")
            self.status.setText("窗口已经叫到前面；如果没看见，请到任务栏点一下浏览器窗口。")

    def _on_show_err(self, err) -> None:
        self.btn_front.setEnabled(False)
        self.btn_front.setToolTip("这个模组没有 /login/show，请到任务栏点浏览器窗口")

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
        hint = str(res.get("hint") or "")
        if state in ("waiting", "manual", ""):
            self._captcha = False
            self.status.setStyleSheet("")
            self.status.setText(hint or "请在浏览器窗口里完成登录（扫码、输验证码都可以）。")
        elif state == "captcha":
            self._captcha = True
            self.status.setStyleSheet(_CAPTCHA_STYLE)
            self.status.setText(hint or "弹了人机验证：请在浏览器窗口里拖滑块/完成验证。")
        elif state == "scanned":
            self._captcha = False
            self.status.setStyleSheet("")
            self.status.setText(hint or "确认了，正在等登录凭据…")
        elif state == "ok":
            self._captcha = False
            self._finished = True
            self.timer.stop()
            self.status.setStyleSheet("")
            who = res.get("uname") or res.get("mid") or ""
            self.status.setText(f"登录成功：{who}")
            QTimer.singleShot(900, self.accept)
        elif state == "expired":
            self._captcha = False
            self.timer.stop()
            self.refresh.setEnabled(True)
            self.status.setStyleSheet("")
            self.status.setText((hint + " " if hint else "") + "点「刷新截图」重新打开。")
        elif state == "need_retry":
            self._captcha = False
            self.timer.stop()
            self.refresh.setEnabled(True)
            self.status.setStyleSheet("")
            self.status.setText((hint + " " if hint else "") + "点「刷新截图」重来。")
        else:
            self._captcha = False
            self.status.setStyleSheet("")
            self.status.setText(hint or state)

    def _on_err(self, err) -> None:
        self.timer.stop()
        self.refresh.setEnabled(True)
        self.status.setStyleSheet("")
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
