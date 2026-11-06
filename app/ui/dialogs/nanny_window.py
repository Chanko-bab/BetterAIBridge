"""保姆的小屋：她自己的独立日志与看门状态（只读彩蛋窗口）。

不写智能体的记忆，也不改人格；只是把她做过的事摊开给主人看。
"""
from __future__ import annotations

import time
from typing import Any, Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ...services.core_client import CoreClient

KIND_LABEL = {
    "notice": "提醒",
    "degraded": "掉线",
    "recovered": "回来了",
    "analyze": "建档",
    "note": "记录",
}


class NannyWindow(QDialog):
    def __init__(self, client: Any | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NannyWindow")
        self.setWindowTitle("保姆的小屋")
        self.resize(760, 560)
        self._client = client

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(8)

        title = QLabel("保姆的小屋", objectName="NannyHouseTitle")
        lay.addWidget(title)
        sub = QLabel("这是保姆自己的记录，不写进智能体的记忆。", objectName="Muted")
        lay.addWidget(sub)

        self.lbl_stats = QLabel("正在读取…", objectName="NannyStats")
        self.lbl_stats.setWordWrap(True)
        lay.addWidget(self.lbl_stats)

        self.scroll = QScrollArea(objectName="NannyHouseScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.list_lay = QVBoxLayout(self.body)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(6)
        self.list_lay.addStretch(1)
        self.scroll.setWidget(self.body)
        lay.addWidget(self.scroll, 1)

        row = QHBoxLayout()
        self.lbl_hint = QLabel("", objectName="Muted")
        row.addWidget(self.lbl_hint, 1)
        self.btn_refresh = QPushButton("刷新", objectName="Ghost")
        self.btn_refresh.clicked.connect(self.refresh)
        row.addWidget(self.btn_refresh)
        self.btn_close = QPushButton("关闭", objectName="Ghost")
        self.btn_close.clicked.connect(self.close)
        row.addWidget(self.btn_close)
        lay.addLayout(row)

        self.refresh()

    def _rows(self) -> list[QWidget]:
        return [w for w in self.body.findChildren(QFrame) if w.objectName() == "NannyLogRow"]

    def refresh(self) -> None:
        client = self._client or CoreClient(timeout=20)
        try:
            data = client.nanny_panel(160) or {}
        except Exception as e:  # noqa: BLE001
            self.lbl_stats.setText(f"内核没回话：{type(e).__name__}")
            self.lbl_hint.setText("等内核起来再点刷新。")
            return
        if not data.get("ok", True):
            self.lbl_stats.setText(str(data.get("error") or "读取失败"))
            return
        self._render(data)

    def _render(self, data: Dict[str, Any]) -> None:
        checks = int(data.get("checks") or 0)
        last = float(data.get("last_check") or 0)
        degraded = data.get("degraded") or []
        when = time.strftime("%H:%M:%S", time.localtime(last)) if last else "还没查过"
        modules = len(data.get("modules") or [])
        state = f"{len(degraded)} 个没响应" if degraded else "都在"
        self.lbl_stats.setText(
            f"看门 {checks} 次 · 上次 {when} · 已登记 {modules} 个模组 · {state}"
        )

        for w in self._rows():
            w.setParent(None)

        rows = data.get("log") or []
        if not rows:
            self.lbl_hint.setText("还没有记录。她安静的时候什么也不写。")
            return
        self.lbl_hint.setText(f"最近 {len(rows)} 条 · 只读")
        for rec in rows:
            if not isinstance(rec, dict):
                continue
            ts = float(rec.get("ts") or 0)
            log_ts = time.strftime("%m-%d %H:%M:%S", time.localtime(ts)) if ts else ""
            kind = str(rec.get("kind") or "note")
            frame = QFrame(objectName="NannyLogRow")
            lay = QHBoxLayout(frame)
            lay.setContentsMargins(8, 5, 8, 5)
            lay.setSpacing(8)
            t = QLabel(log_ts, objectName="NannyLogTime")
            t.setFixedWidth(96)
            lay.addWidget(t)
            k = QLabel(KIND_LABEL.get(kind, kind), objectName="NannyLogKind")
            k.setFixedWidth(52)
            lay.addWidget(k)
            text = QLabel(str(rec.get("text") or ""), objectName="NannyLogText")
            text.setWordWrap(True)
            lay.addWidget(text, 1)
            self.list_lay.insertWidget(self.list_lay.count() - 1, frame)
