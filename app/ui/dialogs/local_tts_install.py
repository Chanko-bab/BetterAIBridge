"""下载本地语音包（MOSS-TTS-Nano）的小窗口。

第一次装要拉独立 venv + torch + 约 760MB 模型，几分钟到十几分钟；进度只做参考，
不承诺网速。装完顺手把服务拉起来，失败给出日志末尾。
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextEdit, QVBoxLayout,
)

from ...core import local_tts


class _Worker(QThread):
    progress = Signal(int, str)
    done = Signal(dict)
    failed = Signal(str)

    def run(self) -> None:  # noqa: D401
        try:
            doc = local_tts.install(lambda p, m: self.progress.emit(int(p), str(m)))
            self.progress.emit(97, "启动本地语音服务…")
            local_tts.start()
            self.done.emit(doc)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc).strip() or type(exc).__name__)


class LocalTtsInstallDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("下载本地语音包")
        self.setModal(True)
        self.resize(580, 430)
        self._worker: _Worker | None = None
        self.ok = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)
        title = QLabel("本地 MOSS-TTS-Nano", objectName="CardTitle")
        lay.addWidget(title)
        tip = QLabel(
            "它完全在本机合成，不再走网络。第一次要下载独立运行环境和约 760MB 模型，"
            "装在安装目录的 local_tts 里；下载完才能选这个声音。中途关掉会保留已下载的部分，"
            "下次接着来。", objectName="Muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        lay.addWidget(self.bar)
        self.lbl = QLabel("准备好了就点「开始下载」。", objectName="Muted")
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(180)
        self.log.setPlaceholderText("下载日志会显示在这里。")
        lay.addWidget(self.log, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_start = QPushButton("开始下载", objectName="Primary")
        self.btn_start.clicked.connect(self.start_install)
        self.btn_close = QPushButton("关闭", objectName="Ghost")
        self.btn_close.clicked.connect(self.reject)
        row.addWidget(self.btn_close)
        row.addWidget(self.btn_start)
        lay.addLayout(row)

    def start_install(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.btn_start.setEnabled(False)
        self.btn_close.setEnabled(False)
        self.btn_start.setText("下载中…")
        self.ok = False
        self.log.clear()
        self.bar.setValue(0)
        self.lbl.setText("正在准备…")
        w = _Worker(self)
        w.progress.connect(self.on_progress)
        w.done.connect(self.on_done)
        w.failed.connect(self.on_failed)
        w.finished.connect(self._on_finished)
        self._worker = w
        w.start()

    def on_progress(self, pct: int, msg: str) -> None:
        self.bar.setValue(max(0, min(100, int(pct))))
        self.lbl.setText(msg)
        self.log.append(msg)

    def on_done(self, doc: dict) -> None:
        self.ok = True
        self.bar.setValue(100)
        self.lbl.setText("装好了，本地语音服务已经起来。")
        self.log.append(f"完成：{doc.get('version') or 'moss-tts-nano'}")
        self.btn_start.setText("已装好")
        self.btn_close.setEnabled(True)
        self.btn_close.setText("关闭")
        self.accept()

    def on_failed(self, why: str) -> None:
        self.lbl.setText("没装成。可以看下面的日志，再点「重试」。")
        self.log.append("失败：" + why)
        self.btn_start.setText("重试")
        self.btn_start.setEnabled(True)
        self.btn_close.setEnabled(True)

    def _on_finished(self) -> None:
        if self.ok:
            return
        self.btn_start.setEnabled(True)
        self.btn_close.setEnabled(True)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._worker is not None and self._worker.isRunning():
            self.lbl.setText("还在下载，等它跑完再关；现在关掉会中断。")
            event.ignore()
            return
        super().closeEvent(event)
