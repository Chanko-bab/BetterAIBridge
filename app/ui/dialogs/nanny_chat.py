"""保姆本体聊天窗：`/wake up bab_nanny` 叫出来的独立会话。

左边是保姆，右边是主人；会话落盘在内核，第二次打开还是上一次的内容。
她只读项目、不改文件，也不写智能体的记忆。
"""
from __future__ import annotations

import logging
import time
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from ...services.core_client import CoreClient
from ...services.worker import run_async
from .. import fonts

log = logging.getLogger("xiaochen.nanny_chat")

OPENING = (
    "虽然不清楚您是怎么找到这儿的，但不去和您的智能体聊天，也不去研究模组，"
    "反而把我找出来，一定是遇上了什么麻烦。您不妨说说。"
)


def _now() -> str:
    return time.strftime("%m-%d %H:%M")


class _Bubble(QFrame):
    def __init__(self, text: str, mine: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("UserMsg" if mine else "NannyMsg")
        self.setMaximumWidth(fonts.ui_px(430))
        self.setStyleSheet(
            "QFrame#UserMsg { background:#3b76d9; border-radius:10px; }"
            "QFrame#NannyMsg { background:#eef4ff; border-radius:10px; }"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lab = QLabel(str(text or ""))
        lab.setWordWrap(True)
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        try:
            need = lab.fontMetrics().horizontalAdvance(str(text or "")) + 30
        except Exception:  # noqa: BLE001
            need = 260
            self.setFixedWidth(max(fonts.ui_px(120), min(fonts.ui_px(430), need)))
        lab.setStyleSheet(
            f"color:#ffffff; font-size:{fonts.ui_px(13)}px; background:transparent;" if mine
            else f"color:#2b3343; font-size:{fonts.ui_px(13)}px; background:transparent;"
        )
        lay.addWidget(lab)


class NannyChatWindow(QDialog):
    def __init__(self, client: Any | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NannyChat")
        self.setWindowTitle("保姆程序")
        self.resize(fonts.ui_px(680), fonts.ui_px(580))
        self._client = client
        self.session = ""
        self._busy = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("保姆程序", objectName="NannyChatTitle")
        title.setStyleSheet(f"font-size:{fonts.ui_px(15)}px; font-weight:600; color:#22304a;")
        head.addWidget(title)
        head.addStretch(1)
        lay.addLayout(head)

        self.scroll = QScrollArea(objectName="NannyChatScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.host = QWidget(objectName="NannyChatHost")
        self.host.setStyleSheet("background:transparent;")
        self.log = QVBoxLayout(self.host)
        self.log.setContentsMargins(4, 4, 4, 4)
        self.log.setSpacing(10)
        self.log.addStretch(1)
        self.scroll.setWidget(self.host)
        self.scroll.setStyleSheet("QScrollArea, QWidget#NannyChatHost { background:transparent; }")
        lay.addWidget(self.scroll, 1)

        row = QHBoxLayout()
        self.ed = QLineEdit(objectName="NannyChatInput")
        self.ed.setPlaceholderText("问点什么…（Enter 发送）")
        self.ed.returnPressed.connect(self.send)
        row.addWidget(self.ed, 1)
        self.btn_send = QPushButton("发送", objectName="Primary")
        self.btn_send.setFixedWidth(fonts.ui_px(72))
        self.btn_send.clicked.connect(self.send)
        row.addWidget(self.btn_send)
        lay.addLayout(row)

        self._open()

    def _row(self, text: str, mine: bool, ts: str = "") -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        v.addWidget(_Bubble(text, mine))
        stamp = QLabel(ts or _now())
        stamp.setStyleSheet(
            f"color:#9aa4b2; font-size:{fonts.ui_px(11)}px; background:transparent;"
        )
        v.addWidget(stamp)
        v.setAlignment(Qt.AlignLeft)
        if mine:
            v.setAlignment(Qt.AlignRight)
            h.addStretch(1)
            h.addWidget(col)
        else:
            h.addWidget(col)
            h.addStretch(1)
        return row

    def _append(self, who: str, text: str, ts: str = "") -> None:
        row = self._row(str(text or ""), mine=(who == "user"), ts=ts)
        self.log.insertWidget(self.log.count() - 1, row)
        QTimer.singleShot(0, self._to_bottom)

    def _to_bottom(self) -> None:
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _open(self) -> None:
        client = self._client or CoreClient(timeout=20)
        run_async(lambda: client.nanny_chat_open(), on_ok=self._opened, on_err=self._open_failed)

    def _opened(self, data: dict) -> None:
        data = data or {}
        self.session = str(data.get("session") or "")
        msgs = data.get("msgs") or []
        for m in msgs:
            role = str(m.get("role") or "")
            text = str(m.get("content") or "").strip()
            if not text:
                continue
            self._append("nanny" if role == "assistant" else "user", text, str(m.get("ts") or ""))
        if not msgs:
            self._append("nanny", str(data.get("opening") or OPENING))
        if not self.session:
            self._append("nanny", "（我这边没连上内核。等它起来再问我。）")

    def _open_failed(self, exc: Any) -> None:
        why = exc if isinstance(exc, str) else type(exc).__name__
        self._append("nanny", f"（我这边没连上内核：{why or '不知道'}。等它起来再问我。）")

    def set_busy(self, on: bool) -> None:
        self._busy = bool(on)
        self.ed.setEnabled(not on)
        self.btn_send.setEnabled(not on)
        self.ed.setFocus()

    def send(self) -> None:
        if self._busy:
            return
        text = self.ed.text().strip()
        if not text:
            return
        self.ed.clear()
        self._append("user", text)
        self.set_busy(True)
        client = self._client or CoreClient(timeout=120)
        if not self.session:
            client = self._client or CoreClient(timeout=20)
            try:
                self._opened(client.nanny_chat_open())
            except Exception as e:  # noqa: BLE001
                self._open_failed(e)
                self.set_busy(False)
                return
        run_async(lambda: client.nanny_chat(self.session, text), on_ok=self._replied,
                  on_err=self._failed)

    def _replied(self, data: dict) -> None:
        data = data or {}
        reply = str(data.get("reply") or "").strip()
        if data.get("session"):
            self.session = str(data["session"])
        self._append("nanny", reply or "（她没说话。）", str(data.get("ts") or ""))
        self.set_busy(False)

    def _failed(self, exc: Any) -> None:
        why = exc if isinstance(exc, str) else type(exc).__name__
        self._append("nanny", f"（没回上：{why or '不知道'}。）")
        self.set_busy(False)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.session:
            client = self._client or CoreClient(timeout=5)
            try:
                client.nanny_chat_close(self.session)
            except Exception:  # noqa: BLE001
                log.debug("关闭保姆会话失败", exc_info=True)
        super().closeEvent(event)
