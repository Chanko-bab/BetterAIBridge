"""自绘标题栏：拖窗 + 内部按钮（收起 / 收到托盘），没有系统三键。"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from pathlib import Path
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class TitleBar(QWidget):
    minimize_clicked = Signal()
    close_clicked = Signal()

    def set_title(self, text: str) -> None:
        """改标题文字（档案导入 / 改名后立刻生效）。"""
        self.title_label.setText(str(text or ""))

    def __init__(self, title: str = "无名", parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(46)
        self.setObjectName("TitleBar")
        self._drag_pos: QPoint | None = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 10, 0)
        lay.setSpacing(10)

        logo = QLabel(objectName="TitleLogo")
        _pm = QPixmap(str(Path(__file__).resolve().parents[3] / "assets" / "bab-64.png"))
        if not _pm.isNull():
            logo.setPixmap(_pm.scaled(18, 18, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        logo.setStyleSheet("font-size:18px;color:#3f7ce8;")
        lay.addWidget(logo)
        self.title_label = QLabel(title, objectName="TitleText")
        lay.addWidget(self.title_label)
        self.subtitle = QLabel("", objectName="Muted")
        lay.addWidget(self.subtitle)
        lay.addStretch(1)

        self.btn_min = QPushButton("—", objectName="TitleBtn")
        self.btn_min.setToolTip("收到任务栏")
        self.btn_min.setAccessibleName("最小化窗口")
        self.btn_min.setFixedSize(34, 26)
        self.btn_min.clicked.connect(self.minimize_clicked.emit)

        self.btn_close = QPushButton("×", objectName="TitleBtn")
        self.btn_close.setToolTip("收进托盘（默认忙）")
        self.btn_close.setAccessibleName("收进托盘")
        self.btn_close.setFixedSize(34, 26)
        self.btn_close.clicked.connect(self.close_clicked.emit)

        lay.addWidget(self.btn_min)
        lay.addWidget(self.btn_close)

    # ---- 拖动（无边框） ----
    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._drag_pos is not None and e.buttons() & Qt.LeftButton:
            self.window().move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._drag_pos = None
        e.accept()

    def set_subtitle(self, text: str) -> None:
        self.subtitle.setText(text)
