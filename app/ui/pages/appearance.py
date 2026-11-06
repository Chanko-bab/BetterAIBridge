"""外观：字体、字号、聊天区动态背景。

字体/字号重启后生效；背景是即时的，铺满整列聊天区。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from ..widgets.see_through import see_through, see_through_widget
from ...core import config
from .. import fonts
from ..backdrop import SOURCES, Backdrop, cfg as bg_cfg, save as bg_save

EFFECT_LABELS = [("gradient", "呼吸渐变"), ("blobs", "漂浮光斑"), ("dots", "点阵")]
FOLLOW_LABELS = [("off", "关"), ("glow", "柔光"), ("trail", "拖尾"), ("particles", "粒子")]
SOURCE_LABELS = [("effects", "动态效果"), ("image", "本地图片"), ("video", "本地视频")]
IMAGE_FILTER = "图片 (*.png *.jpg *.jpeg *.bmp *.webp *.gif)"
VIDEO_FILTER = "视频 (*.mp4 *.webm *.mov *.mkv *.avi *.wmv)"


class AppearancePage(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._loading = False
        shell = QVBoxLayout(self)
        shell.setContentsMargins(18, 10, 18, 14)
        shell.setSpacing(10)
        shell.addWidget(QLabel("外观", objectName="PageTitle"))

        scroll = QScrollArea(objectName="SettingsScroll")
        see_through(scroll)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 8, 8)
        lay.setSpacing(12)

        # ---- 字体 ----
        ucard = QFrame(objectName="Card")
        ubox = QVBoxLayout(ucard)
        ubox.setContentsMargins(16, 14, 16, 14)
        ubox.setSpacing(8)
        ubox.addWidget(QLabel("字体", objectName="CardTitle"))
        ubox.addWidget(QLabel("换字体或字号后，重启程序生效。", objectName="Muted"))
        urow = QHBoxLayout()
        urow.setSpacing(8)
        urow.addWidget(QLabel("字体", objectName="Muted"))
        self.cb_font_family = QComboBox()
        self.cb_font_family.setMinimumWidth(260)
        urow.addWidget(self.cb_font_family)
        urow.addSpacing(16)
        urow.addWidget(QLabel("字号", objectName="Muted"))
        self.cb_font_size = QSpinBox()
        self.cb_font_size.setRange(fonts.MIN_SIZE, fonts.MAX_SIZE)
        self.cb_font_size.setSuffix(" px")
        urow.addWidget(self.cb_font_size)
        urow.addStretch(1)
        ubox.addLayout(urow)
        self.lbl_font_preview = QLabel("这是预览：它说话的时候，大概就是这个样子。", objectName="Muted")
        self.lbl_font_preview.setWordWrap(True)
        ubox.addWidget(self.lbl_font_preview)
        ubox.addWidget(QLabel("字号太大时，个别窗口可能会挤；建议 13–16。", objectName="Muted"))
        self.cb_font_family.currentIndexChanged.connect(self.on_font_changed)
        self.cb_font_size.valueChanged.connect(self.on_font_changed)
        lay.addWidget(ucard)

        # ---- 背景 ----
        bcard = QFrame(objectName="Card")
        bbox = QVBoxLayout(bcard)
        bbox.setContentsMargins(16, 14, 16, 14)
        bbox.setSpacing(8)
        bbox.addWidget(QLabel("聊天区背景", objectName="CardTitle"))
        bbox.addWidget(QLabel(
            "铺满整个窗口（标题栏、操作台、聊天区都盖到）；卡片保持白底，关掉就是原来的浅灰底。",
            objectName="Muted"))
        self.cb_bg_on = QCheckBox("显示动态背景")
        bbox.addWidget(self.cb_bg_on)

        row0 = QHBoxLayout()
        row0.setSpacing(8)
        row0.addWidget(QLabel("底图", objectName="Muted"))
        self.cb_bg_source = QComboBox()
        for key, label in SOURCE_LABELS:
            self.cb_bg_source.addItem(label, key)
        row0.addWidget(self.cb_bg_source)
        self.btn_bg_media = QPushButton("选择文件…", objectName="Ghost")
        row0.addWidget(self.btn_bg_media)
        self.btn_bg_default = QPushButton("内置默认", objectName="Ghost")
        row0.addWidget(self.btn_bg_default)
        self.ed_bg_media = QLineEdit()
        self.ed_bg_media.setReadOnly(True)
        self.ed_bg_media.setPlaceholderText("留空 = 用内置白底图")
        self.ed_bg_media.setMinimumWidth(220)
        row0.addWidget(self.ed_bg_media, 1)
        bbox.addLayout(row0)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(QLabel("背景", objectName="Muted"))
        self.cb_bg_effect = QComboBox()
        for key, label in EFFECT_LABELS:
            self.cb_bg_effect.addItem(label, key)
        row1.addWidget(self.cb_bg_effect)
        row1.addSpacing(14)
        row1.addWidget(QLabel("跟随", objectName="Muted"))
        self.cb_bg_follow = QComboBox()
        for key, label in FOLLOW_LABELS:
            self.cb_bg_follow.addItem(label, key)
        row1.addWidget(self.cb_bg_follow)
        row1.addSpacing(14)
        row1.addWidget(QLabel("点击", objectName="Muted"))
        self.cb_bg_click = QComboBox()
        self.cb_bg_click.addItem("扩散圈", "ripple")
        self.cb_bg_click.addItem("双环", "double")
        self.cb_bg_click.addItem("星火", "spark")
        self.cb_bg_click.addItem("气泡", "bubble")
        self.cb_bg_click.addItem("关", "off")
        row1.addWidget(self.cb_bg_click)
        row1.addStretch(1)
        bbox.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(QLabel("浓淡", objectName="Muted"))
        self.sl_bg_opacity = QSlider(Qt.Horizontal)
        self.sl_bg_opacity.setRange(40, 100)
        self.sl_bg_opacity.setFixedWidth(160)
        row2.addWidget(self.sl_bg_opacity)
        row2.addSpacing(14)
        row2.addWidget(QLabel("速度", objectName="Muted"))
        self.sl_bg_speed = QSlider(Qt.Horizontal)
        self.sl_bg_speed.setRange(50, 200)
        self.sl_bg_speed.setFixedWidth(160)
        row2.addWidget(self.sl_bg_speed)
        row2.addStretch(1)
        bbox.addLayout(row2)

        self.preview = Backdrop(self)
        self.preview.setMinimumHeight(120)
        self.preview.setMaximumHeight(140)
        bbox.addWidget(self.preview)

        for w in (self.cb_bg_on, self.cb_bg_effect, self.cb_bg_follow, self.cb_bg_click):
            w.toggled.connect(self._save_bg) if isinstance(w, QCheckBox) else w.currentIndexChanged.connect(self._save_bg)
        self.cb_bg_source.currentIndexChanged.connect(self._on_bg_source)
        self.btn_bg_media.clicked.connect(self._pick_media)
        self.btn_bg_default.clicked.connect(self._use_default_bg)
        self.sl_bg_opacity.valueChanged.connect(self._save_bg)
        self.sl_bg_speed.valueChanged.connect(self._save_bg)
        lay.addWidget(bcard)
        lay.addStretch(1)

        scroll.setWidget(body)
        see_through_widget(body)
        shell.addWidget(scroll, 1)
        from .. import wheel_guard  # noqa: PLC0415

        wheel_guard.install(self, scroll)

    # ---------------------------------------------------------------- 刷新
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        self._loading = True
        try:
            cur = str(config.get("ui.font_family") or "")
            try:
                names = fonts.families()
            except Exception:  # noqa: BLE001
                names = []
            self.cb_font_family.clear()
            self.cb_font_family.addItem("系统默认（微软雅黑）", "")
            for name in names:
                if name == fonts.DEFAULT_FAMILY:
                    continue
                self.cb_font_family.addItem(name, name)
            idx = self.cb_font_family.findData(cur) if cur else 0
            self.cb_font_family.setCurrentIndex(idx if idx >= 0 else 0)
            self.cb_font_size.setValue(fonts.size())

            conf = bg_cfg()
            self.cb_bg_on.setChecked(bool(conf["enabled"]))
            self._select(self.cb_bg_effect, conf["effect"])
            self._select(self.cb_bg_follow, conf["follower"])
            self._select(self.cb_bg_click,
                         str(conf.get("click_style") or "ripple")
                         if conf.get("click", True) else "off")
            self._select(self.cb_bg_source, str(conf.get("source") or "effects"))
            self.ed_bg_media.setText(str(conf.get("media") or ""))
            self._sync_media_row()
            self.sl_bg_opacity.setValue(int(round(float(conf["opacity"]) * 100)))
            self.sl_bg_speed.setValue(int(round(float(conf["speed"]) * 100)))
        finally:
            self._loading = False
        self._update_font_preview()
        self._sync_preview()

    @staticmethod
    def _select(combo: QComboBox, value: str) -> None:
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    # ---------------------------------------------------------------- 字体
    def on_font_changed(self, *_args) -> None:
        if self._loading:
            return
        config.set_value("ui.font_family", str(self.cb_font_family.currentData() or ""))
        config.set_value("ui.font_size", int(self.cb_font_size.value()))
        self._update_font_preview()

    def _update_font_preview(self) -> None:
        fam = str(self.cb_font_family.currentData() or "") or fonts.DEFAULT_FAMILY
        f = QFont(fam)
        f.setPointSize(max(8, round(9 * int(self.cb_font_size.value()) / fonts.BASE_SIZE)))
        self.lbl_font_preview.setFont(f)

    # ---------------------------------------------------------------- 背景
    def _bg_values(self) -> dict:
        return {
            "enabled": self.cb_bg_on.isChecked(),
            "effect": str(self.cb_bg_effect.currentData() or "blobs"),
            "follower": str(self.cb_bg_follow.currentData() or "glow"),
            "click": str(self.cb_bg_click.currentData() or "ripple") != "off",
            "click_style": (str(self.cb_bg_click.currentData())
                            if str(self.cb_bg_click.currentData()) != "off" else "ripple"),
            "source": str(self.cb_bg_source.currentData() or "effects"),
            "media": str(self.ed_bg_media.text() or "").strip(),
            "opacity": int(self.sl_bg_opacity.value()) / 100.0,
            "speed": int(self.sl_bg_speed.value()) / 100.0,
        }

    def _sync_media_row(self) -> None:
        source = str(self.cb_bg_source.currentData() or "effects")
        dynamic = source == "effects"
        self.btn_bg_media.setEnabled(not dynamic)
        self.btn_bg_default.setEnabled(source == "image")
        self.ed_bg_media.setEnabled(not dynamic)
        if source == "image":
            self.ed_bg_media.setPlaceholderText("留空 = 用内置白底图")
        else:
            self.ed_bg_media.setPlaceholderText("没选文件时会退回动态效果")

    def _on_bg_source(self, *_args) -> None:
        self._sync_media_row()
        self._save_bg()

    def _pick_media(self) -> None:
        source = str(self.cb_bg_source.currentData() or "effects")
        if source == "effects":
            return
        flt = IMAGE_FILTER if source == "image" else VIDEO_FILTER
        title = "选一张背景图片" if source == "image" else "选一段背景视频"
        path, _ = QFileDialog.getOpenFileName(self, title, "", flt)
        if not path:
            return
        self.ed_bg_media.setText(path)
        self._save_bg()

    def _use_default_bg(self) -> None:
        self.ed_bg_media.clear()
        self._save_bg()

    def _save_bg(self, *_args) -> None:
        if self._loading:
            return
        vals = self._bg_values()
        bg_save(vals)
        self._sync_preview()
        self.changed.emit()

    def _sync_preview(self) -> None:
        vals = dict(self._bg_values())
        vals["enabled"] = True
        self.preview.set_config(vals)
