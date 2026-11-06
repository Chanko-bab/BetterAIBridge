"""启动动画：一块无边框的小卡片，头像 + logging…，每次启动都先看到它。

不是进度条：内核/服务都还没起来，这里只表达"在启动"。
最短露 1600ms，主窗口显示后淡出；冒烟/测试模式不弹（避免挡住自动化）。
"""
from __future__ import annotations

import time

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QLabel, QVBoxLayout, QWidget,
)

from ..core import framework_setup
from ..services import avatar
from .widgets.avatar_card import rounded_pixmap

MIN_MS = 1600


class Splash(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFixedSize(380, 300)
        self._started = time.time()
        self._dots = 0
        self._closing = False

        card = QFrame(objectName="SplashCard")
        card.setGraphicsEffect(self._shadow())
        lay = QVBoxLayout(card)
        lay.setContentsMargins(28, 26, 28, 22)
        lay.setSpacing(10)

        self.pic = QLabel()
        self.pic.setFixedSize(96, 96)
        self.pic.setAlignment(Qt.AlignCenter)
        pm = avatar.pixmap(96)
        if not pm.isNull():
            self.pic.setPixmap(rounded_pixmap(pm, 96))
        lay.addWidget(self.pic, 0, Qt.AlignHCenter)

        self.name = QLabel(framework_setup.display_name(), objectName="SplashName")
        self.name.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.name)

        lay.addStretch(1)

        self.stage = QLabel("正在启动", objectName="SplashLog")
        self.stage.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.stage)

        self.brand = QLabel("Better AI Bridge Launcher", objectName="SplashBrand")
        self.brand.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.brand)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)

        self._timer = QTimer(self)
        self._timer.setInterval(260)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    @staticmethod
    def _shadow() -> QGraphicsDropShadowEffect:
        eff = QGraphicsDropShadowEffect()
        eff.setBlurRadius(28)
        eff.setOffset(0, 8)
        eff.setColor(QColor(0, 0, 0, 55))
        return eff

    def _tick(self) -> None:
        self._dots = (self._dots + 1) % 4
        self.stage.setText("正在启动" + "." * self._dots)

    def start(self) -> None:
        self._center()
        self.setWindowOpacity(0.0)
        self.show()
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(320)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.start()
        self._fade_in = anim

    def _center(self) -> None:
        screen = self.screen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(geo.center().x() - self.width() // 2,
                  geo.center().y() - self.height() // 2 - 40)

    def finish(self) -> None:
        """主窗口已经能看了：补足最短时间，再淡出。"""
        if self._closing:
            return
        self._closing = True
        wait = max(0, MIN_MS - int((time.time() - self._started) * 1000))
        QTimer.singleShot(wait, self._fade_out)

    def _fade_out(self) -> None:
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(380)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        anim.finished.connect(self.close)
        anim.start()
        self._fade_out_anim = anim
