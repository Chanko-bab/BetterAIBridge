# -*- coding: utf-8 -*-
"""保姆补登记：扫码之后问一句「你的 B 站 UID 是多少」。"""
from __future__ import annotations

import httpx
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from ...services.worker import run_async


class OwnerMidDialog(QDialog):
    def __init__(self, parent, *, port: int, title: str = "补登记：你的 B 站 UID") -> None:
        super().__init__(parent)
        self.base = f"http://127.0.0.1:{int(port)}"
        self.saved = False

        self.setWindowTitle(title)
        self.setMinimumWidth(420)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)

        lay.addWidget(QLabel("保姆程序", objectName="CardTitle"))
        tip = QLabel(
            "最后一步：填写你自己的 B 站 UID（纯数字，能跳过）。\n"
            "我只用它认人：哪条私信是你、谁算「认识」。之后在「设置」里也能改。",
            wordWrap=True)
        lay.addWidget(tip)

        self.ed = QLineEdit()
        self.ed.setPlaceholderText("例如 3690991145978511")
        lay.addWidget(self.ed)

        self.msg = QLabel("")
        self.msg.setWordWrap(True, )
        lay.addWidget(self.msg)

        btns = QHBoxLayout()
        self.btn_skip = QPushButton("跳过")
        self.btn_skip.clicked.connect(self._skip)
        self.btn_ok = QPushButton("保存")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._save)
        btns.addWidget(self.btn_skip)
        btns.addStretch(1)
        btns.addWidget(self.btn_ok)
        lay.addLayout(btns)

        self.ed.textChanged.connect(lambda _t: self._check())

    def _check(self) -> bool:
        txt = self.ed.text().strip()
        if txt and not txt.isdigit():
            self.msg.setText("UID 只能是数字。")
            self.btn_ok.setEnabled(False)
            return False
        self.msg.setText("")
        self.btn_ok.setEnabled(bool(txt))
        return bool(txt)

    def _skip(self) -> None:
        self.saved = False
        self.reject()

    def _save(self) -> None:
        if not self._check():
            return
        mid = self.ed.text().strip()
        self.btn_ok.setEnabled(False)
        self.msg.setText("保存中…")

        def work():
            with httpx.Client(timeout=15.0) as c:
                r = c.post(f"{self.base}/owner", json={"mid": mid})
                r.raise_for_status()
                return r.json()

        run_async(work, on_ok=self._on_ok, on_err=self._on_err)

    def _on_ok(self, res) -> None:
        res = res or {}
        self.btn_ok.setEnabled(True)
        if not res.get("ok"):
            self.msg.setText(f"没存上：{res.get('error') or res}")
            return
        self.saved = True
        self.msg.setText("记下了。")
        self.accept()

    def _on_err(self, err) -> None:
        self.btn_ok.setEnabled(True)
        self.msg.setText(f"没存上：{err}")
