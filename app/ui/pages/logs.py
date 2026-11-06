"""日志：看项目 runtime\\logs 与本程序 logs，自动贴尾。"""
from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from ...core import config, logger


class LogsPage(QWidget):
    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        self.log = logger.get()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 16, 22, 16)
        outer.setSpacing(8)

        head = QHBoxLayout()
        head.addWidget(QLabel("日志", objectName="CardValue"))
        head.addSpacing(12)
        self.combo = QComboBox()
        self.combo.setMinimumWidth(260)
        self.combo.currentTextChanged.connect(lambda _: self.tail())
        head.addWidget(self.combo)
        btn = QPushButton("刷新", objectName="Ghost")
        btn.clicked.connect(self.reload_files)
        head.addWidget(btn)
        btn2 = QPushButton("打开目录", objectName="Ghost")
        btn2.clicked.connect(self.open_dir)
        head.addWidget(btn2)
        head.addStretch(1)
        outer.addLayout(head)

        outer.setContentsMargins(22, 16, 22, 16)
        outer.setSpacing(10)

        self.view = QPlainTextEdit()
        self.view.setMinimumHeight(260)
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(4000)
        outer.addWidget(self.view, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tail)
        self._last_path = ""
        self._last_mtime = 0.0

        self.reload_files()

    def _dirs(self) -> list[Path]:
        return [Path(str(config.get("logs_dir"))), Path(config.APP_DIR) / "logs"]

    def reload_files(self) -> None:
        cur = self.combo.currentText()
        self.combo.blockSignals(True)
        self.combo.clear()
        names: list[str] = []
        for d in self._dirs():
            if not d.exists():
                continue
            for f in sorted(d.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True):
                names.append(str(f))
        self.combo.addItems(names)
        if cur in names:
            self.combo.setCurrentText(cur)
        self.combo.blockSignals(False)
        self.tail()

    def showEvent(self, ev):  # noqa: N802
        super().showEvent(ev)
        self.timer.start(3000)
        self.tail(force=True)

    def hideEvent(self, ev):  # noqa: N802
        self.timer.stop()
        super().hideEvent(ev)

    def tail(self, force: bool = False) -> None:
        path = self.combo.currentText()
        if not path:
            self.view.setPlainText("（没有日志文件）")
            return
        try:
            p = Path(path)
            st = p.stat()
            if not force and path == self._last_path and st.st_mtime == self._last_mtime:
                return
            self._last_path = path
            self._last_mtime = st.st_mtime
            size = st.st_size
            with p.open("rb") as fh:
                if size > 160_000:
                    fh.seek(size - 160_000)
                data = fh.read()
            text = data.decode("utf-8", "replace")
            bar = self.view.verticalScrollBar()
            was_bottom = bar.value() >= bar.maximum() - 4
            old_value = bar.value()
            self.view.setPlainText(text[-80_000:])
            # setPlainText 之后布局/滚动条范围要到下一次事件循环才更新；
            # 立即 setValue 用的是旧 maximum，底部会差几行。
            if was_bottom:
                QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))
            else:
                # 用户正在往上翻时别把他拽回底部
                QTimer.singleShot(0, lambda: bar.setValue(min(old_value, bar.maximum())))
        except Exception as e:  # noqa: BLE001
            self.view.setPlainText(f"读取失败：{e}")

    def open_dir(self) -> None:
        subprocess.Popen(["explorer.exe", str(self._dirs()[0])])

    def on_show(self) -> None:
        self.reload_files()
