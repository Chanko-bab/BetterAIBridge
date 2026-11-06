# -*- coding: utf-8 -*-
"""待批队列：智能体想赞/藏/私信，得使用者在这里点头。"""
from __future__ import annotations

import httpx
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ...services.worker import run_async

ACTION_CN = {"like": "点赞", "fav": "收藏", "dm": "发私信"}


class PendingDialog(QDialog):
    def __init__(self, parent, *, port: int, title: str = "等她动手之前") -> None:
        super().__init__(parent)
        self.base = f"http://127.0.0.1:{int(port)}"
        self.items: list[dict] = []

        self.setWindowTitle(title)
        self.setMinimumSize(560, 420)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 14)
        lay.setSpacing(10)

        lay.addWidget(QLabel("保姆程序", objectName="CardTitle"))
        self.tip = QLabel("TA 排队想做的事。你点头才会真的做；拒绝就丢掉。", wordWrap=True)
        lay.addWidget(self.tip)

        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.box = QWidget()
        self.list_lay = QVBoxLayout(self.box)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(8)
        self.list_lay.addStretch(1)
        self.area.setWidget(self.box)
        lay.addWidget(self.area, 1)

        btns = QHBoxLayout()
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self.reload)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.reject)
        btns.addWidget(self.btn_refresh)
        btns.addStretch(1)
        btns.addWidget(self.btn_close)
        lay.addLayout(btns)

        self.reload()

    # ------------------------------------------------------------ 数据
    def reload(self) -> None:
        self.tip.setText("读取中…")

        def work():
            with httpx.Client(timeout=15.0) as c:
                r = c.get(f"{self.base}/pending")
                r.raise_for_status()
                return r.json()

        run_async(work, on_ok=self._on_list, on_err=self._on_err)

    def _on_list(self, res) -> None:
        res = res or {}
        if not res.get("ok"):
            self._on_err(res.get("error") or res)
            return
        self.items = list(res.get("items") or [])
        while self.list_lay.count() > 1:
            it = self.list_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        if not self.items:
            self.tip.setText("眼下没有排队的。")
            return
        self.tip.setText(f"有 {len(self.items)} 件等她动手，你点头才会真的做。")
        for row in self.items:
            self.list_lay.insertWidget(self.list_lay.count() - 1, self._row(row))

    def _row(self, it: dict) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:#fff;border:1px solid #e3e7ee;border-radius:8px;")
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)

        action = str(it.get("action") or "")
        p = it.get("payload") or {}
        head = ACTION_CN.get(action, action)
        what = p.get("title") or p.get("bvid") or (f"mid {p.get('mid')}" if p.get("mid") else "")
        v.addWidget(QLabel(f"{head}：{what}", wordWrap=True))
        if p.get("text"):
            v.addWidget(QLabel(f"内容：{p.get('text')}", wordWrap=True))
        if it.get("reason"):
            v.addWidget(QLabel(f"理由：{it.get('reason')}", wordWrap=True))
        v.addWidget(QLabel(f"排队时间：{it.get('created') or ''}", wordWrap=True))

        row = QHBoxLayout()
        yes = QPushButton("批准")
        no = QPushButton("拒绝", objectName="Ghost")
        yes.clicked.connect(lambda _c=False, i=it: self._act(i, True))
        no.clicked.connect(lambda _c=False, i=it: self._act(i, False))
        row.addStretch(1)
        row.addWidget(no)
        row.addWidget(yes)
        v.addLayout(row)
        return w

    def _act(self, it: dict, allow: bool) -> None:
        qid = str(it.get("id") or "")
        self.tip.setText("执行中…")

        def work():
            with httpx.Client(timeout=45.0) as c:
                r = c.post(f"{self.base}/pending", json={"id": qid, "allow": bool(allow)})
                r.raise_for_status()
                return r.json()

        run_async(work, on_ok=self._on_act, on_err=self._on_err)

    def _on_act(self, res) -> None:
        res = res or {}
        if not res.get("ok"):
            self.tip.setText(f"没做成：{res.get('error') or res}")
            return
        self.tip.setText("拒了。" if res.get("denied") else "做了。")
        self.reload()

    def _on_err(self, err) -> None:
        self.tip.setText(f"出错：{err}")
