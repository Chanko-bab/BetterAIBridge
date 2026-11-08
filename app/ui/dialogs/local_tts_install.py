"""下载本地语音包（MOSS-TTS-Nano）的小窗口。

第一次装要拉独立 venv + torch + 约 760MB 模型，几分钟到十几分钟；进度只做参考，
不承诺网速。装完顺手把服务拉起来，失败给出日志末尾。

真正的安装跑在进程级 `local_tts_job.job` 里，不挂在这个窗口上：点「关闭」或
「后台继续」只是不再看进度，下载、pip、启动服务都继续；下次打开窗口还能接上。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextEdit, QVBoxLayout,
)

from ...core import local_tts
from ...services.local_tts_job import job


class LocalTtsInstallDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("下载本地语音包")
        self.setModal(True)
        self.resize(580, 430)
        self.ok = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)
        title = QLabel("本地 MOSS-TTS-Nano", objectName="CardTitle")
        lay.addWidget(title)
        tip = QLabel(
            "它完全在本机合成，不再走网络。第一次要下载独立运行环境和约 760MB 模型，"
            "装在安装目录的 local_tts 里；下载完才能选这个声音。下载时可以关掉这个窗口，"
            "安装会在后台继续，下次打开还能看到进度。", objectName="Muted")
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

        job.progress.connect(self.on_progress)
        job.done.connect(self.on_done)
        job.failed.connect(self.on_failed)
        self._sync()

    # ---- 状态同步 -------------------------------------------------------
    def _sync(self) -> None:
        st = job.state()
        if st["running"]:
            self.ok = False
            self.bar.setValue(int(st["pct"]))
            self.lbl.setText(st["msg"] or "正在下载…")
            self.btn_start.setEnabled(False)
            self.btn_start.setText("下载中…")
            self.btn_close.setEnabled(True)
            self.btn_close.setText("后台继续")
            for line in st["lines"][-200:]:
                if line:
                    self.log.append(line)
            return
        if st["ok"] or local_tts.is_ready():
            self.ok = True
            self.bar.setValue(100)
            self.lbl.setText("装好了，本地语音服务已经起来。")
            self.btn_start.setEnabled(False)
            self.btn_start.setText("已装好")
            self.btn_close.setText("关闭")
            return
        if st["error"]:
            self.ok = False
            self.lbl.setText("上次没装成：可以看日志，再点「重试」。")
            self.log.append("失败：" + str(st["error"]))
            self.btn_start.setEnabled(True)
            self.btn_start.setText("重试")
            self.btn_close.setText("关闭")
            return
        self.ok = False
        self.bar.setValue(0)
        self.lbl.setText("准备好了就点「开始下载」。")
        self.btn_start.setEnabled(True)
        self.btn_start.setText("开始下载")
        self.btn_close.setText("关闭")

    def start_install(self) -> None:
        if not job.start():
            self._sync()
            return
        self.ok = False
        self.log.clear()
        self.bar.setValue(0)
        self.lbl.setText("正在准备…")
        self.btn_start.setEnabled(False)
        self.btn_start.setText("下载中…")
        self.btn_close.setEnabled(True)
        self.btn_close.setText("后台继续")

    def on_progress(self, pct: int, msg: str) -> None:
        self.bar.setValue(max(0, min(100, int(pct))))
        self.lbl.setText(msg)
        self.log.append(msg)

    def on_done(self, doc: dict) -> None:
        self.ok = True
        self.bar.setValue(100)
        self.lbl.setText("装好了，本地语音服务已经起来。")
        self.log.append(f"完成：{doc.get('version') or 'moss-tts-nano'}")
        self.btn_start.setEnabled(False)
        self.btn_start.setText("已装好")
        self.btn_close.setEnabled(True)
        self.btn_close.setText("关闭")
        if self.isVisible():
            self.accept()

    def on_failed(self, why: str) -> None:
        self.ok = False
        self.lbl.setText("没装成。可以看下面的日志，再点「重试」。")
        self.log.append("失败：" + why)
        self.btn_start.setText("重试")
        self.btn_start.setEnabled(True)
        self.btn_close.setEnabled(True)
        self.btn_close.setText("关闭")

    def closeEvent(self, event) -> None:  # noqa: N802
        # 安装不再绑在这个窗口上：关掉只是不看进度，任务继续跑。
        self.ok = bool(job.state()["ok"])
        super().closeEvent(event)
