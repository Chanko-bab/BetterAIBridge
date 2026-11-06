"""保姆程序栏：聊天右侧那条流水。

只放保姆的提醒（对方主动开口、对方在找您、对方被打断、模组掉线……），每条带时间。
聊天窗里不再插这些，观感交给这一栏负责。

两档：展开（320）与收起（34 的窄边，显示未读数）。没有拖拽调宽——档位少一点，坑就少一点。
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .. import fonts
from .see_through import see_through

COL_WIDTH = 320
STRIP_WIDTH = 38
MAX_ROWS = 200


class _ClickLabel(QLabel):
    clicked = Signal()

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(str(self.text() or "可点击"))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class NannyPanel(QFrame):
    collapsed_changed = Signal(bool)
    opened = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NannyCol")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        # 半透明底只在本面板上挂，避免被全局样式里的不透明底盖掉
        self.setStyleSheet(
            "QFrame#NannyCol { background: transparent; }")
        self.setFixedWidth(fonts.ui_px(COL_WIDTH))
        self._rows: list[QWidget] = []
        self._seen: set[tuple[float, str]] = set()
        self._unread = 0
        self._collapsed = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(6)

        # ---- 展开时的标题行 ----
        self.header = QWidget()
        head = QHBoxLayout(self.header)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        self.title = _ClickLabel("保姆程序", objectName="NannyTitle")
        self.title.setCursor(Qt.PointingHandCursor)
        self.title.setToolTip("点一下，看看保姆自己的记录")
        self.title.setAccessibleName("保姆程序：打开保姆小屋")
        self.title.clicked.connect(self.opened.emit)
        head.addWidget(self.title)
        head.addStretch(1)
        self.btn_clear = QPushButton("清空", objectName="NannyBtn")
        self.btn_clear.setFixedSize(fonts.ui_px(52), fonts.ui_px(24))
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.setToolTip("只清空这一栏，内核那边的记录不动")
        self.btn_clear.setAccessibleName("清空保姆提醒")
        self.btn_clear.clicked.connect(self.clear)
        head.addWidget(self.btn_clear)
        self.btn_toggle = QPushButton("收起", objectName="NannyBtn")
        self.btn_toggle.setFixedSize(52, 24)
        self.btn_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_toggle.setToolTip("收起保姆程序的提醒")
        self.btn_toggle.clicked.connect(lambda: self.set_collapsed(True))
        head.addWidget(self.btn_toggle)
        outer.addWidget(self.header)

        # ---- 收起时的那根窄边 ----
        self.strip = QWidget()
        sl = QVBoxLayout(self.strip)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(6)
        self.btn_open = QPushButton("保", objectName="NannyBadge")
        self.btn_open.setFixedSize(34, 32)
        self.btn_open.setCursor(Qt.PointingHandCursor)
        self.btn_open.setToolTip("展开保姆程序的提醒")
        self.btn_open.clicked.connect(lambda: self.set_collapsed(False))
        sl.addWidget(self.btn_open)
        sl.addStretch(1)
        outer.addWidget(self.strip, 1)
        self.strip.setVisible(False)

        # ---- 正文 ----
        self.scroll = QScrollArea(objectName="NannyScroll")
        see_through(self.scroll)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget(objectName="NannyBody")
        self.list_lay = QVBoxLayout(self.body)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(6)
        self.list_lay.addStretch(1)
        self.scroll.setWidget(self.body)
        outer.addWidget(self.scroll, 1)

        self.empty = QLabel("还没有提醒。", objectName="Muted")
        self.empty.setWordWrap(True)
        outer.addWidget(self.empty)

        self._refresh_empty()

        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(self._to_bottom)

    # ---- 对外 ----

    def add(self, ts: float, text: str) -> None:
        """记一条提醒。ts 是 epoch 秒，0 表示"就现在"。"""
        text = str(text or "").strip()
        if not text:
            return
        stamp = float(ts or time.time())
        key = (round(stamp, 3), text)
        if key in self._seen:
            return
        self._seen.add(key)

        frame = QFrame(objectName="NannyItem")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(2)
        when = QLabel(time.strftime("%H:%M:%S", time.localtime(stamp)), objectName="NannyTime")
        lay.addWidget(when)
        body = QLabel(text, objectName="NannyText")
        body.setWordWrap(True)
        lay.addWidget(body)

        at_bottom = self._at_bottom()
        self.list_lay.insertWidget(self.list_lay.count() - 1, frame)
        self._rows.append(frame)
        while len(self._rows) > MAX_ROWS:
            old = self._rows.pop(0)
            old.setParent(None)
            old.deleteLater()
        if self._collapsed:
            self._unread += 1
            self._refresh_badge()
        if at_bottom:
            # 布局把新行算进高度有延迟；0ms 会赶在布局之前，单次 30ms 在慢机器上也不稳。
            # 先试一次，再在 120ms 补一次（只影响“本来就在底部”的情况）。
            self._scroll_timer.start(0)
            QTimer.singleShot(120, self._to_bottom)
        self._refresh_empty()

    def clear(self) -> None:
        """只清这一栏的界面；内核的 notices.jsonl 不动（它自己滚动）。"""
        for row in self._rows:
            row.setParent(None)
        self._rows.clear()
        self._seen.clear()
        self._unread = 0
        self._refresh_badge()
        self._refresh_empty()

    def paintEvent(self, event) -> None:  # noqa: N802
        # QSS 的 rgba 在这块 QFrame 上会被画成实白，干脆自己铺一层半透明
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(255, 255, 255, 150))
        p.setPen(QColor(227, 232, 240))
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        p.end()

    def set_collapsed(self, on: bool) -> None:
        self._collapsed = bool(on)
        self.setFixedWidth(fonts.ui_px(STRIP_WIDTH if self._collapsed else COL_WIDTH))
        pad = fonts.ui_px(2 if self._collapsed else 10)
        self.layout().setContentsMargins(pad, fonts.ui_px(10), pad, fonts.ui_px(10))
        self.header.setVisible(not self._collapsed)
        self.scroll.setVisible(not self._collapsed)
        self.strip.setVisible(self._collapsed)
        if not self._collapsed:
            self._unread = 0
        self._refresh_badge()
        self._refresh_empty()
        self.collapsed_changed.emit(self._collapsed)

    def unread(self) -> int:
        return int(self._unread)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def count(self) -> int:
        return len(self._rows)

    def texts(self) -> list[str]:
        out: list[str] = []
        for row in self._rows:
            for lbl in row.findChildren(QLabel):
                if lbl.objectName() == "NannyText":
                    out.append(lbl.text())
        return out

    def times(self) -> list[str]:
        out: list[str] = []
        for row in self._rows:
            for lbl in row.findChildren(QLabel):
                if lbl.objectName() == "NannyTime":
                    out.append(lbl.text())
        return out

    # ---- 内部 ----

    def _at_bottom(self) -> bool:
        bar = self.scroll.verticalScrollBar()
        return bar.value() >= bar.maximum() - 4

    def _to_bottom(self) -> None:
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _refresh_empty(self) -> None:
        self.empty.setVisible(not self._rows and not self._collapsed)

    def _refresh_badge(self) -> None:
        if self._unread:
            self.btn_open.setText(f"保{self._unread if self._unread < 10 else '9+'}")
            self.btn_open.setToolTip(f"保姆程序有 {self._unread} 条新提醒，点开看看")
        else:
            self.btn_open.setText("保")
            self.btn_open.setToolTip("展开保姆程序的提醒")
