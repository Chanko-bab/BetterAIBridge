"""聊天里的语音气泡：播放/暂停、进度、时长，转写默认收起。"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout,
)

from ...services import audio
from .. import fonts


def _clock(ms: int) -> str:
    sec = max(0, int(round(ms / 1000.0)))
    return f"{sec // 60}:{sec % 60:02d}"


class VoiceBubble(QFrame):
    """一条语音消息。voice 里认 id/path/ms/dur_ms/deleted。"""

    def __init__(self, voice: dict, text: str = "", who: str = "me", parent=None) -> None:
        super().__init__(parent)
        self.voice = dict(voice or {})
        self.path = str(self.voice.get("path") or "")
        self.total_ms = int(self.voice.get("ms") or self.voice.get("dur_ms") or 0)
        self.deleted = bool(self.voice.get("deleted")) or not self.path or not Path(self.path).is_file()
        self.setObjectName("VoiceBubbleMe" if who == "me" else "VoiceBubbleHer")
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Minimum)
        self.setMaximumWidth(fonts.ui_px(420))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 12, 7)
        lay.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.btn = QPushButton("▶", objectName="VoicePlay")
        self.btn.setFixedSize(fonts.ui_px(30), fonts.ui_px(30))
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setToolTip("播放这条语音")
        self.btn.clicked.connect(self.toggle)
        self.btn.setEnabled(not self.deleted)
        top.addWidget(self.btn)

        self.bar = QProgressBar(objectName="VoiceBar")
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(fonts.ui_px(6))
        self.bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        top.addWidget(self.bar, 1)

        self.time = QLabel("已清除" if self.deleted else _clock(self.total_ms),
                           objectName="VoiceTime")
        self.time.setMinimumWidth(fonts.ui_px(40))
        self.time.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self.time)
        lay.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        tip = QLabel("点击播放" if not self.deleted else "音频已清除，转写还在",
                     objectName="VoiceHint")
        bottom.addWidget(tip)
        bottom.addStretch(1)
        self.tr_btn = QPushButton("转写", objectName="VoiceToggle")
        self.tr_btn.setCheckable(True)
        self.tr_btn.setCursor(Qt.PointingHandCursor)
        self.tr_btn.setVisible(bool((text or "").strip()))
        self.tr_btn.toggled.connect(self._toggle_text)
        bottom.addWidget(self.tr_btn)
        lay.addLayout(bottom)

        self.tr = QLabel((text or "").strip(), objectName="VoiceText")
        self.tr.setWordWrap(True)
        self.tr.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.tr.setVisible(False)
        lay.addWidget(self.tr)

        self._t0 = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------ 行为
    def toggle(self) -> None:
        if self.deleted:
            return
        if audio.player.playing_path == self.path:
            audio.player.stop()
            self._reset()
            return
        if not audio.player.play(self.path):
            self.time.setText("放不出")
            return
        self._t0 = time.monotonic()
        self.btn.setText("❚❚")
        self._timer.start()

    def _reset(self) -> None:
        self._timer.stop()
        self.btn.setText("▶")
        self.bar.setValue(0)
        self.time.setText("已清除" if self.deleted else _clock(self.total_ms))

    def _tick(self) -> None:
        if audio.player.playing_path != self.path:
            self._reset()
            return
        elapsed = (time.monotonic() - self._t0) * 1000.0
        total = max(1, self.total_ms)
        self.bar.setValue(int(min(1.0, elapsed / total) * 1000))
        self.time.setText(_clock(min(elapsed, total)))

    def _toggle_text(self, on: bool) -> None:
        self.tr.setVisible(bool(on))
        self.tr_btn.setText("收起" if on else "转写")
