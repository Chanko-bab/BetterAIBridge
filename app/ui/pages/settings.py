"""设置：模型/Key、路径一览、打开目录。

「更改 API Key」只改连接，不动人格；「查看详情」跳到 details 页。
"""
from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QComboBox,
    QCheckBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from ...core import config, framework_setup, local_tts, portable
from ...services import asr, sense, update
from ..widgets.see_through import see_through, see_through_widget
from .settings_archive import ArchiveActionsMixin
from .settings_bridge import BridgeActionsMixin
from .settings_voice import VoiceActionsMixin

log = logging.getLogger(__name__)

SHOW = [
    ("项目根目录", "project_root"),
    ("模组装卸区", "bundle_dir"),
    ("内核地址", "core_url"),
    ("启动脚本", "start_all"),
    ("停止脚本", "stop_all"),
    ("日志目录", "logs_dir"),
]


def preview_done_text(size_bytes: int, playing: bool) -> str:
    """试听按钮下面那行字：合成了多少、到底有没有放出声。

    0.3.4 之前这里只要合成请求 return 就写「试听放出来了」，播放失败也照写，
    用户看到的是「放出来了」，耳朵里什么都没有。
    """
    kb = max(1, round(size_bytes / 1024)) if size_bytes else 0
    head = f"合成好了（{kb} KB）" if kb else "合成好了"
    return f"{head}，正在播放" if playing else f"{head}，但没出声（设备或音量？）"


class SettingsPage(ArchiveActionsMixin, VoiceActionsMixin, BridgeActionsMixin, QWidget):
    open_details = Signal()
    ports_ready = Signal(object)
    task_done = Signal(object)
    bridge_ready = Signal(object)

    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        self._spawn_lock = threading.Lock()
        self._spawn_keys = set()
        self._grant_seq = {}
        self._grant_locks = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 16, 22, 16)
        outer.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(QLabel("设置", objectName="PageTitle"))
        head.addStretch(1)
        self.btn_details = QPushButton("查看详情", objectName="Primary")
        self.btn_details.setToolTip("情绪、肚子、记忆、脑龄、各程序是否在线")
        self.btn_details.clicked.connect(self.open_details.emit)
        self.task_done.connect(self._run_task_cb)
        self.ports_ready.connect(self._apply_ports)
        self.bridge_ready.connect(self._apply_bridge)
        head.addWidget(self.btn_details)
        self.btn_update = QPushButton("检查更新", objectName="Ghost")
        self.btn_update.setToolTip(
            f"当前版本 {update.version() or '未知'}；打开下载页看看有没有新版本"
        )
        self.btn_update.clicked.connect(lambda: update.open_download(self))
        head.addWidget(self.btn_update)
        outer.addLayout(head)

        self.scroll = QScrollArea()
        see_through(self.scroll)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        body = QVBoxLayout(holder)
        body.setContentsMargins(0, 0, 6, 0)
        body.setSpacing(10)
        self.scroll.setWidget(holder)
        see_through_widget(holder)
        outer.addWidget(self.scroll, 1)

        # ---- 模型与 Key ----
        mcard = QFrame(objectName="Card")
        mgrid = QGridLayout(mcard)
        mgrid.setContentsMargins(16, 14, 16, 14)
        mgrid.setHorizontalSpacing(16)
        mgrid.setVerticalSpacing(8)
        mgrid.addWidget(QLabel("模型与 Key", objectName="CardTitle"), 0, 0, 1, 2)

        self.lbl_model = QLabel("")
        self.lbl_base = QLabel("")
        self.lbl_key = QLabel("")
        self.lbl_rel = QLabel("")
        self.lbl_rel_title = QLabel("你与智能体的关系", objectName="CardTitle")
        rows = [
            ("模型", self.lbl_model),
            ("API 地址", self.lbl_base),
            ("API Key", self.lbl_key),
            (None, self.lbl_rel),
        ]
        for r, (title, widget) in enumerate(rows, start=1):
            label = self.lbl_rel_title if title is None else QLabel(title, objectName="CardTitle")
            mgrid.addWidget(label, r, 0)
            widget.setTextInteractionFlags(Qt.TextSelectableByMouse)
            widget.setWordWrap(True)
            mgrid.addWidget(widget, r, 1)

        self.btn_key = QPushButton("更改 API Key")
        self.btn_key.setToolTip("只改模型连接，不会重写人格")
        self.btn_key.clicked.connect(self.change_key)
        krow = QHBoxLayout()
        krow.addWidget(self.btn_key)
        krow.addStretch(1)
        mgrid.addLayout(krow, len(rows) + 1, 0, 1, 2)
        mgrid.setColumnStretch(1, 1)
        body.addWidget(mcard)

        # ---- 路径 ----
        card = QFrame(objectName="Card")
        grid = QGridLayout(card)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        grid.addWidget(QLabel("路径", objectName="CardTitle"), 0, 0, 1, 2)
        cfg = config.load()
        for i, (title, key) in enumerate(SHOW, start=1):
            grid.addWidget(QLabel(title, objectName="CardTitle"), i, 0)
            val = QLabel(str(cfg.get(key, "")))
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(val, i, 1)
        grid.setColumnStretch(1, 1)
        body.addWidget(card)

        # ---- 端口（这个安装的地图） ----
        pcard = QFrame(objectName="Card")
        pbox = QVBoxLayout(pcard)
        pbox.setContentsMargins(16, 14, 16, 14)
        pbox.setSpacing(6)
        pbox.addWidget(QLabel("端口", objectName="CardTitle"))
        self.lbl_ports = QLabel("…")
        self.lbl_ports.setWordWrap(True)
        self.lbl_ports.setTextInteractionFlags(Qt.TextSelectableByMouse)
        pbox.addWidget(self.lbl_ports)
        body.addWidget(pcard)

        # ---- 桥权限（模组能拿什么、现在开没开） ----
        bcard = QFrame(objectName="Card")
        bbox = QVBoxLayout(bcard)
        bbox.setContentsMargins(16, 14, 16, 14)
        bbox.setSpacing(6)
        bbox.addWidget(QLabel("桥权限", objectName="CardTitle"))
        bbox.addWidget(QLabel("勾上＝允许它通过「桥」碰这些东西；取消＝立刻断掉。", objectName="Muted"))
        self.bridge_box = QVBoxLayout()
        self.bridge_box.setSpacing(4)
        bbox.addLayout(self.bridge_box)
        body.addWidget(bcard)

        # ---- 声音（朗读用） ----
        vcard = QFrame(objectName="Card")
        vbox = QVBoxLayout(vcard)
        vbox.setContentsMargins(16, 14, 16, 14)
        vbox.setSpacing(8)
        vbox.addWidget(QLabel("声音", objectName="CardTitle"))
        vbox.addWidget(QLabel("聊天页右上角勾「朗读」后，智能体用这个声音念出来。",
                              objectName="Muted"))
        self._loading_voice = False

        erow = QHBoxLayout()
        erow.setSpacing(8)
        self.cb_engine = QComboBox()
        self.cb_engine.addItem("edge-tts（免费，跟手）", "edge")
        self.cb_engine.addItem("BreezeBlue（慢，要自己的 Key）", "breezeblue")
        self.cb_engine.addItem("本地 MOSS（需下载，CPU）", "local")
        self.cb_engine.setMinimumWidth(230)
        self.cb_engine.currentIndexChanged.connect(lambda _i: self.on_engine_changed())
        erow.addWidget(QLabel("朗读", objectName="Muted"))
        erow.addWidget(self.cb_engine)
        erow.addStretch(1)
        vbox.addLayout(erow)

        # 试听单独选引擎：聊天朗读留在 edge，想听 BreezeBlue 的声音就点这里
        prow = QHBoxLayout()
        prow.setSpacing(8)
        self.cb_prev_engine = QComboBox()
        self.cb_prev_engine.addItem("edge-tts（免费，跟手）", "edge")
        self.cb_prev_engine.addItem("BreezeBlue（慢，要自己的 Key）", "breezeblue")
        self.cb_prev_engine.addItem("本地 MOSS（需下载，CPU）", "local")
        self.cb_prev_engine.setMinimumWidth(230)
        self.cb_prev_engine.currentIndexChanged.connect(lambda _i: self.on_engine_changed())
        self.btn_prev = QPushButton("试听", objectName="Ghost")
        self.btn_prev.setFixedWidth(72)
        self.btn_prev.clicked.connect(self.preview_voice)
        prow.addWidget(QLabel("试听", objectName="Muted"))
        prow.addWidget(self.cb_prev_engine)
        prow.addWidget(self.btn_prev)
        prow.addStretch(1)
        vbox.addLayout(prow)

        self.lbl_engine_hint = QLabel(
            "BreezeBlue 实测比实时慢 4–10 倍（3 秒的话要 15–25 秒），所以聊天朗读走 edge，"
            "它只用来试听/偶尔听好声音；同一句合成过会缓存，第二次快。", objectName="Muted")
        self.lbl_engine_hint.setWordWrap(True)
        self.lbl_engine_hint.setVisible(False)
        vbox.addWidget(self.lbl_engine_hint)

        # edge-tts：音色 / 语速 / 试听
        self.row_edge = QWidget()
        vrow = QHBoxLayout(self.row_edge)
        vrow.setContentsMargins(0, 0, 0, 0)
        vrow.setSpacing(8)
        self.cb_voice = QComboBox()
        self.cb_voice.setMinimumWidth(240)
        self.cb_rate = QComboBox()
        for r in ("+0%", "-10%", "+10%", "+20%"):
            self.cb_rate.addItem(r)
        self.cb_rate.setFixedWidth(90)
        self.cb_voice.currentIndexChanged.connect(lambda _i: self.save_voice())
        self.cb_rate.currentIndexChanged.connect(lambda _i: self.save_voice())
        vrow.addWidget(QLabel("音色", objectName="Muted"))
        vrow.addWidget(self.cb_voice, 1)
        vrow.addWidget(QLabel("语速", objectName="Muted"))
        vrow.addWidget(self.cb_rate)
        vrow.addStretch(1)
        vbox.addWidget(self.row_edge)

        # BreezeBlue / 任何 OpenAI 兼容 TTS：地址、Key、音色、模型
        self.box_bb = QWidget()
        bgrid = QGridLayout(self.box_bb)
        bgrid.setContentsMargins(0, 0, 0, 0)
        bgrid.setHorizontalSpacing(10)
        bgrid.setVerticalSpacing(6)
        self.ed_bb_base = QLineEdit()
        self.ed_bb_base.setPlaceholderText("https://api.breezeblue.ai/v1")
        self.ed_bb_key = QLineEdit()
        self.ed_bb_key.setEchoMode(QLineEdit.Password)
        self.ed_bb_key.setPlaceholderText("brz_…")
        self.ed_bb_voice = QLineEdit()
        self.ed_bb_voice.setPlaceholderText("音色名（看服务商文档）")
        self.ed_bb_model = QLineEdit()
        self.ed_bb_model.setPlaceholderText("breeze-tts-2")
        for i, (name, w) in enumerate((("地址", self.ed_bb_base), ("Key", self.ed_bb_key),
                                       ("音色", self.ed_bb_voice), ("模型", self.ed_bb_model))):
            bgrid.addWidget(QLabel(name, objectName="Muted"), i, 0)
            bgrid.addWidget(w, i, 1)
            w.editingFinished.connect(self.save_voice)
        bgrid.setColumnStretch(1, 1)
        vbox.addWidget(self.box_bb)
        self.box_bb.setVisible(False)   # 默认 edge；refresh/换引擎时再显示

        # 本地 MOSS：独立语音包，没装好之前不让保存
        self.box_local = QWidget()
        lgrid = QGridLayout(self.box_local)
        lgrid.setContentsMargins(0, 0, 0, 0)
        lgrid.setHorizontalSpacing(10)
        lgrid.setVerticalSpacing(6)
        self.cb_local_voice = QComboBox()
        for vid, label in (("Junhao", "俊豪 · 中文男声 A"), ("Zhiming", "志明 · 中文男声 B"),
                           ("Weiguo", "卫国 · 中文男声 C"), ("Xiaoyu", "小雨 · 中文女声 A"),
                           ("Yuewen", "月雯 · 中文女声 B"), ("Lingyu", "灵语 · 中文女声 C")):
            self.cb_local_voice.addItem(label, vid)
        self.cb_local_voice.currentIndexChanged.connect(lambda _i: self.save_voice())
        lgrid.addWidget(QLabel("音色", objectName="Muted"), 0, 0)
        lgrid.addWidget(self.cb_local_voice, 0, 1)
        self.ed_local_ref = QLineEdit()
        self.ed_local_ref.setPlaceholderText("可留空：留空用上面的内置音色")
        self.ed_local_ref.setReadOnly(True)
        self.btn_local_ref = QPushButton("选参考音频…", objectName="Ghost")
        self.btn_local_ref.setFixedWidth(112)
        self.btn_local_ref.clicked.connect(self.pick_local_ref)
        self.btn_local_clear = QPushButton("清空", objectName="Ghost")
        self.btn_local_clear.setFixedWidth(54)
        self.btn_local_clear.clicked.connect(self.clear_local_ref)
        lgrid.addWidget(QLabel("参考音频", objectName="Muted"), 1, 0)
        lgrid.addWidget(self.ed_local_ref, 1, 1)
        lgrid.addWidget(self.btn_local_ref, 1, 2)
        lgrid.addWidget(self.btn_local_clear, 1, 3)
        lgrid.setColumnStretch(1, 1)
        lrow = QHBoxLayout()
        lrow.setSpacing(8)
        self.lbl_local = QLabel("", objectName="Muted")
        self.lbl_local.setWordWrap(True)
        self.btn_local_install = QPushButton("下载本地语音包", objectName="Ghost")
        self.btn_local_install.clicked.connect(lambda _=False: self.install_local_tts())
        self.btn_local_check = QPushButton("检查", objectName="Ghost")
        self.btn_local_check.setFixedWidth(58)
        self.btn_local_check.clicked.connect(self.refresh_local_tts)
        lrow.addWidget(self.lbl_local, 1)
        lrow.addWidget(self.btn_local_check)
        lrow.addWidget(self.btn_local_install)
        lgrid.addLayout(lrow, 2, 0, 1, 4)
        vbox.addWidget(self.box_local)
        self.box_local.setVisible(False)

        self.lbl_voice = QLabel("", objectName="Muted")
        self.lbl_voice.setWordWrap(True)
        vbox.addWidget(self.lbl_voice)

        # 语音转写（ASR）：智能体要「听」得见，得先有个本机的听写服务
        asr_row = QHBoxLayout()
        asr_row.setSpacing(8)
        self.cb_asr = QCheckBox("语音转写（智能体能听见）")
        self.cb_asr.toggled.connect(self.toggle_asr)
        self.btn_asr_dir = QPushButton("模型与安装说明", objectName="Ghost")
        self.btn_asr_dir.setFixedWidth(132)
        self.btn_asr_dir.clicked.connect(self.open_asr_dir)
        asr_row.addWidget(self.cb_asr)
        asr_row.addWidget(self.btn_asr_dir)
        asr_row.addStretch(1)
        vbox.addLayout(asr_row)
        self.lbl_asr = QLabel("", objectName="Muted")
        self.lbl_asr.setWordWrap(True)
        vbox.addWidget(self.lbl_asr)
        body.addWidget(vcard)

        # ---- 耳目（看 / 听） ----
        ocard = QFrame(objectName="Card")
        obox = QVBoxLayout(ocard)
        obox.setContentsMargins(16, 14, 16, 14)
        obox.setSpacing(8)
        obox.addWidget(QLabel("耳目", objectName="CardTitle"))
        obox.addWidget(QLabel(
            "智能体可以偶尔偷看你一眼、偷听你一下（看摄像头，没有就看屏幕；听麦克风）。"
            "按需看一眼/听一下仍跟「智能体主动说话」那档走；下面两个「一直」是独立频率，"
            "拉动那条滑条不会改它们。",
            objectName="Muted"))
        self.cb_eyes = QCheckBox("允许对方主动偷看你")
        self.cb_eyes.toggled.connect(self.toggle_eyes)
        self.cb_ears = QCheckBox("允许对方主动偷听你")
        self.cb_ears.toggled.connect(self.toggle_ears)
        self.cb_watch = QCheckBox("允许对方一直看着你")
        self.cb_watch.toggled.connect(self.toggle_watch)
        self.cb_listen_always = QCheckBox("允许对方一直听着你")
        self.cb_listen_always.toggled.connect(self.toggle_listen_always)
        self.sp_watch_sec = QSpinBox()
        self.sp_watch_sec.setRange(30, 1800)
        self.sp_watch_sec.setSingleStep(30)
        self.sp_watch_sec.setSuffix(" 秒")
        self.sp_watch_sec.valueChanged.connect(self.save_sense_timing)
        self.sp_listen_sec = QSpinBox()
        self.sp_listen_sec.setRange(60, 3600)
        self.sp_listen_sec.setSingleStep(60)
        self.sp_listen_sec.setSuffix(" 秒")
        self.sp_listen_sec.valueChanged.connect(self.save_sense_timing)
        self.sp_listen_len = QSpinBox()
        self.sp_listen_len.setRange(1, 15)
        self.sp_listen_len.setSuffix(" 秒")
        self.sp_listen_len.valueChanged.connect(self.save_sense_timing)
        self.cb_announce = QCheckBox("看/听之前在保姆栏说一声（默认开）")
        self.cb_announce.toggled.connect(self.toggle_announce)
        obox.addWidget(self.cb_eyes)
        obox.addWidget(self.cb_ears)
        obox.addWidget(self.cb_watch)
        wrow = QHBoxLayout()
        wrow.setSpacing(6)
        wrow.addWidget(QLabel("频率：每", objectName="Muted"))
        wrow.addWidget(self.sp_watch_sec)
        wrow.addWidget(QLabel("看一眼", objectName="Muted"))
        wrow.addStretch(1)
        obox.addLayout(wrow)
        obox.addWidget(self.cb_listen_always)
        lrow = QHBoxLayout()
        lrow.setSpacing(6)
        lrow.addWidget(QLabel("频率：每", objectName="Muted"))
        lrow.addWidget(self.sp_listen_sec)
        lrow.addWidget(QLabel("听", objectName="Muted"))
        lrow.addWidget(self.sp_listen_len)
        lrow.addStretch(1)
        obox.addLayout(lrow)
        obox.addWidget(QLabel(
            "间隔越短、每次听得越久，模型和语音调用越频繁，费用与电量消耗越快。",
            objectName="Muted"))
        obox.addWidget(self.cb_announce)

        orow = QHBoxLayout()
        orow.setSpacing(8)
        orow.addWidget(QLabel("摄像头", objectName="Muted"))
        self.cb_cam = QComboBox()
        self.cb_cam.setMinimumWidth(220)
        self.cb_cam.currentIndexChanged.connect(self.on_cam_changed)
        orow.addWidget(self.cb_cam)
        self.btn_sense_refresh = QPushButton("刷新设备", objectName="Ghost")
        self.btn_sense_refresh.clicked.connect(lambda: self.refresh_sense(devices_only=True))
        orow.addWidget(self.btn_sense_refresh)
        orow.addStretch(1)
        obox.addLayout(orow)

        mrow = QHBoxLayout()
        mrow.setSpacing(8)
        mrow.addWidget(QLabel("麦克风", objectName="Muted"))
        self.cb_mic = QComboBox()
        self.cb_mic.setMinimumWidth(220)
        self.cb_mic.currentIndexChanged.connect(self.on_mic_changed)
        mrow.addWidget(self.cb_mic)
        mrow.addStretch(1)
        obox.addLayout(mrow)

        self.lbl_sense = QLabel("", objectName="Muted")
        self.lbl_sense.setWordWrap(True)
        obox.addWidget(self.lbl_sense)
        body.addWidget(ocard)

        # ---- 启动与后台 ----
        scard = QFrame(objectName="Card")
        sbox = QVBoxLayout(scard)
        sbox.setContentsMargins(16, 14, 16, 14)
        sbox.setSpacing(8)
        sbox.addWidget(QLabel("启动与后台", objectName="CardTitle"))
        sbox.addWidget(QLabel(
            "关窗口只是收进托盘，程序还在。这里管「开机要不要自己起来」和「内核掉了要不要拉一把」。",
            objectName="Muted"))
        self.cb_autostart = QCheckBox("开机自启（登录 Windows 后自动打开）")
        self.cb_autostart.toggled.connect(self.toggle_autostart)
        self.cb_auto_restart = QCheckBox("内核挂了自动拉起")
        self.cb_auto_restart.toggled.connect(self.toggle_auto_restart)
        sbox.addWidget(self.cb_autostart)
        sbox.addWidget(self.cb_auto_restart)
        self.lbl_startup = QLabel("", objectName="Muted")
        self.lbl_startup.setWordWrap(True)
        sbox.addWidget(self.lbl_startup)
        body.addWidget(scard)

        # ---- 智能体主动说话（插话） ----
        fcard = QFrame(objectName="Card")
        fbox = QVBoxLayout(fcard)
        fbox.setContentsMargins(16, 14, 16, 14)
        fbox.setSpacing(8)
        fbox.addWidget(QLabel("智能体主动说话", objectName="CardTitle"))
        fbox.addWidget(QLabel(
            "智能体说完一句、你还没回——隔一会儿它再补一句短的（最多一两句）。"
            "往右越黏人；最左边是关。", objectName="Muted"))
        self._loading_follow = False
        self._follow_levels: dict[int, dict] = {}
        frow = QHBoxLayout()
        frow.setSpacing(10)
        self.slider_follow = QSlider(Qt.Horizontal)
        self.slider_follow.setRange(0, 3)
        self.slider_follow.setSingleStep(1)
        self.slider_follow.setPageStep(1)
        self.slider_follow.setTickPosition(QSlider.TicksBelow)
        self.slider_follow.setTickInterval(1)
        self.slider_follow.setMaximumWidth(300)
        self.slider_follow.valueChanged.connect(self.on_follow_changed)
        self.btn_say_now = QPushButton("让智能体现在说一句", objectName="Ghost")
        self.btn_say_now.clicked.connect(self.say_now)
        frow.addWidget(self.slider_follow)
        frow.addWidget(self.btn_say_now)
        frow.addStretch(1)
        fbox.addLayout(frow)
        self.lbl_follow = QLabel("", objectName="Muted")
        self.lbl_follow.setWordWrap(True)
        fbox.addWidget(self.lbl_follow)
        body.addWidget(fcard)

        # ---- 肚子（API 余额的分界） ----
        stcard = QFrame(objectName="Card")
        stbox = QVBoxLayout(stcard)
        stbox.setContentsMargins(16, 14, 16, 14)
        stbox.setSpacing(8)
        stbox.addWidget(QLabel("肚子", objectName="CardTitle"))
        stbox.addWidget(QLabel(
            "智能体的「饱不饱」是按 API 余额算的：高于饱线就有底气，低于饿线会没力气、"
            "说话变短，还会在保姆栏提醒你一次。",
            objectName="Muted"))
        strow = QHBoxLayout()
        strow.setSpacing(8)
        self.sb_full = QDoubleSpinBox()
        self.sb_full.setRange(0.5, 10000.0)
        self.sb_full.setDecimals(1)
        self.sb_full.setSingleStep(1.0)
        self.sb_full.setSuffix(" 元")
        self.sb_full.setFixedWidth(110)
        self.sb_full.setValue(10.0)
        self.sb_hungry = QDoubleSpinBox()
        self.sb_hungry.setRange(0.0, 10000.0)
        self.sb_hungry.setDecimals(1)
        self.sb_hungry.setSingleStep(0.5)
        self.sb_hungry.setSuffix(" 元")
        self.sb_hungry.setFixedWidth(110)
        self.sb_hungry.setValue(3.0)
        self.sb_full.editingFinished.connect(self.save_stomach)
        self.sb_hungry.editingFinished.connect(self.save_stomach)
        strow.addWidget(QLabel("饱 ≥", objectName="Muted"))
        strow.addWidget(self.sb_full)
        strow.addSpacing(10)
        strow.addWidget(QLabel("饿 ≤", objectName="Muted"))
        strow.addWidget(self.sb_hungry)
        strow.addStretch(1)
        stbox.addLayout(strow)
        self.lbl_stomach = QLabel("", objectName="Muted")
        stbox.addWidget(self.lbl_stomach)
        body.addWidget(stcard)

        # ---- 记忆库（一天一个 .txt，超了就压缩） ----
        mcard = QFrame(objectName="Card")
        mbox = QVBoxLayout(mcard)
        mbox.setContentsMargins(16, 14, 16, 14)
        mbox.setSpacing(8)
        mbox.addWidget(QLabel("记忆库", objectName="CardTitle"))
        mbox.addWidget(QLabel(
            "智能体每天记一本：记忆库里按天放着「我做过什么」，聊天原文单独留一份供它回看。"
            "超过压缩阈值且过了保留天数，保姆会把旧的那几天概括成几行，原文打包收起来。",
            objectName="Muted"))
        mrow = QHBoxLayout()
        mrow.setSpacing(8)
        self.sb_mem_max = QDoubleSpinBox()
        self.sb_mem_max.setRange(0.1, 100.0)
        self.sb_mem_max.setDecimals(1)
        self.sb_mem_max.setSingleStep(0.5)
        self.sb_mem_max.setSuffix(" G")
        self.sb_mem_max.setFixedWidth(100)
        self.sb_mem_max.setValue(2.0)
        self.sb_mem_zip = QDoubleSpinBox()
        self.sb_mem_zip.setRange(0.1, 100.0)
        self.sb_mem_zip.setDecimals(1)
        self.sb_mem_zip.setSingleStep(0.5)
        self.sb_mem_zip.setSuffix(" G")
        self.sb_mem_zip.setFixedWidth(100)
        self.sb_mem_zip.setValue(0.5)
        self.sb_mem_days = QSpinBox()
        self.sb_mem_days.setRange(1, 3650)
        self.sb_mem_days.setSuffix(" 天")
        self.sb_mem_days.setFixedWidth(100)
        self.sb_mem_days.setValue(60)
        for w in (self.sb_mem_max, self.sb_mem_zip, self.sb_mem_days):
            w.editingFinished.connect(self.save_memory)
        mrow.addWidget(QLabel("上限", objectName="Muted"))
        mrow.addWidget(self.sb_mem_max)
        mrow.addSpacing(8)
        mrow.addWidget(QLabel("压缩阈值", objectName="Muted"))
        mrow.addWidget(self.sb_mem_zip)
        mrow.addSpacing(8)
        mrow.addWidget(QLabel("保留", objectName="Muted"))
        mrow.addWidget(self.sb_mem_days)
        mrow.addStretch(1)
        mbox.addLayout(mrow)
        self.lbl_memory = QLabel("", objectName="Muted")
        mbox.addWidget(self.lbl_memory)
        body.addWidget(mcard)

        body.addWidget(QLabel("端口与模组池由程序自己分配；要强制指定，编辑 config\\install.json 的 base。", objectName="Muted"))

        row = QHBoxLayout()
        for text, slot in [
            ("打开配置文件", self.open_config),
            ("打开程序目录", self.open_app),
            ("打开项目目录", self.open_root),
            ("打开日志目录", self.open_logs),
            ("导出诊断包", self.export_diagnostics),
            ("再看教程", self.show_tutorial),
        ]:
            b = QPushButton(text, objectName="Ghost")
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        body.addLayout(row)

        # 存档 / 卸载单独一行、跟上面那排一样左对齐：
        # 窗口拉到最窄时四个字换行也看得见，不会被挤到右边缘外面去。
        row2 = QHBoxLayout()
        self.btn_archive = QPushButton(f"存档「{framework_setup.display_name()}」")
        self.btn_archive.setToolTip("把人格、记忆、模型/声音/情绪配置和聊天记录打包成一个 .babpak")
        # clicked 会带一个 checked=False 进来，直接连 save_archive 会把 notify 顶成 False（就不弹窗了）
        self.btn_archive.clicked.connect(lambda: self.export_archive())
        self.btn_import = QPushButton("导入存档", objectName="Ghost")
        self.btn_import.setToolTip("从 .babpak 恢复人格、记忆和配置；会覆盖当前内容")
        self.btn_import.clicked.connect(lambda: self.import_archive(confirm=True))
        self.btn_uninstall = QPushButton("卸载程序", objectName="Danger")
        self.btn_uninstall.setToolTip("卸掉整个程序目录，方便装下一版；卸载前建议先存档")
        # 同上：不带 lambda 的话 confirm 会被 checked=False 顶掉，警告框直接被跳过
        self.btn_uninstall.clicked.connect(lambda: self.uninstall(confirm=True))
        self.btn_reset = QPushButton("重置启动器", objectName="Danger")
        self.btn_reset.setToolTip(
            "清掉人格、记忆、聊天记录、设置和已装模组，恢复刚装好的状态；程序本身保留")
        self.btn_reset.clicked.connect(lambda: self.reset_launcher(confirm=True))
        row2.addWidget(self.btn_archive)
        row2.addWidget(self.btn_import)
        row2.addWidget(self.btn_uninstall)
        row2.addWidget(self.btn_reset)
        row2.addStretch(1)
        body.addLayout(row2)

        self.lbl_archive = QLabel("", objectName="Muted")
        self.lbl_archive.setWordWrap(True)
        self.lbl_archive.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.addWidget(self.lbl_archive)
        body.addStretch(1)

        self.refresh_model()
        from .. import wheel_guard  # noqa: PLC0415

        wheel_guard.install(self, self.scroll)

    def showEvent(self, ev):  # noqa: N802
        super().showEvent(ev)
        self.refresh_model()
        self.refresh_ports()
        self.refresh_bridge()
        self.refresh_stomach()
        self.refresh_memory()
        self.refresh_voice()
        self.refresh_followup()
        self.refresh_startup()
        self.refresh_asr()
        self.refresh_sense()

    # ---------------------------------------------------------------- 语音转写

    def _asr_text(self, st) -> str:
        st = st or {}
        state = str(st.get("state") or "")
        port = st.get("port")
        detail = str(st.get("detail") or "")
        engine = str(st.get("engine") or "")
        model = str(st.get("model") or "")
        if state == "off":
            return ("没开。勾上以后，智能体能把它听来的语音变成字（本机听写，不上传）；"
                    "第一次要先装引擎，点右边。")
        if state == "no_engine":
            return f"找不到 start-asr.cmd，这份安装没带语音服务。（{detail}）"
        if state == "ok":
            if engine and not engine.startswith("ok"):
                return (f"服务在跑（端口 {port}），但引擎没装：{engine}。"
                        f"点右边「模型与安装说明」照着装一次。")
            return f"在跑：端口 {port}，模型 {model or '默认'}。"
        if state == "starting":
            return f"正在启动…（{detail or '等它应答'}）"
        if state == "failed":
            return f"没起来：{detail or '看 logs/asr-boot.log'}。"
        return f"状态未知（{state}）"

    def refresh_asr(self) -> None:
        self.cb_asr.blockSignals(True)
        self.cb_asr.setChecked(asr.enabled())
        self.cb_asr.blockSignals(False)
        self.lbl_asr.setText(self._asr_text(asr.status(probe=False)))

        def work():
            return asr.status()

        self._spawn(work, lambda st: self.lbl_asr.setText(self._asr_text(st)),
                    lambda e: self.lbl_asr.setText(f"（读不到语音服务：{e}）"))

    def toggle_asr(self, on: bool) -> None:
        asr.set_enabled(bool(on))
        self.lbl_asr.setText("正在启动…" if on else "正在停…")

        def work():
            return asr.start() if on else asr.stop()

        self._spawn(work, lambda st: self.lbl_asr.setText(self._asr_text(st)),
                    lambda e: self.lbl_asr.setText(f"（{e}）"))

    def open_asr_dir(self) -> None:
        d = Path(str(config.get("start_asr") or "")).parent
        if not d.is_dir():
            QMessageBox.information(self, "语音转写",
                                    "这份安装里没有 capability\\voice\\asr 目录。")
            return
        subprocess.Popen(["explorer", str(d)])

    # ---------------------------------------------------------------- 耳目

    def _sense_state_text(self) -> str:
        try:
            c = sense.cfg()
        except Exception as exc:  # noqa: BLE001
            return f"（读不到耳目配置：{exc}）"
        eyes, ears = bool(c.get("eyes")), bool(c.get("ears"))
        if not eyes and not ears:
            return "两个都关着：智能体不会自己看，也不会自己听。"
        parts = []
        if eyes:
            cam = str(c.get("camera") or "")
            if cam == "screen":
                parts.append("看：屏幕（只看屏幕）")
            else:
                parts.append("看：" + (f"摄像头「{cam}」" if cam else "自动（有摄像头就拍，没有看屏幕）"))
        if ears:
            mic = str(c.get("mic") or "")
            parts.append("听：" + (f"麦克风 {mic} 号" if mic else "系统默认麦克风"))
        if c.get("watch") and eyes:
            parts.append(f"一直看着：开（每 {int(c.get('watch_sec') or 120)} 秒看一眼）")
        if c.get("listen_always") and ears:
            parts.append(f"一直听着：开（每 {int(c.get('listen_sec') or 180)} 秒听 "
                         f"{int(c.get('listen_len') or 4)} 秒）")
        say = "看/听前会在保姆栏说一声。" if c.get("announce", True) else "看/听时不吭声。"
        return "；".join(parts) + "。" + say + " 主动/定时采样都受这里控制。"

    def refresh_sense(self, devices_only: bool = False) -> None:
        c = sense.cfg()
        self._loading_sense = True
        try:
            for box, val in ((self.cb_eyes, c.get("eyes")), (self.cb_ears, c.get("ears")),
                             (self.cb_watch, c.get("watch")),
                             (self.cb_listen_always, c.get("listen_always")),
                             (self.cb_announce, c.get("announce", True))):
                box.blockSignals(True)
                box.setChecked(bool(val))
                box.blockSignals(False)
            for spin, val, lo, hi in (
                    (self.sp_watch_sec, c.get("watch_sec"), 30, 1800),
                    (self.sp_listen_sec, c.get("listen_sec"), 60, 3600),
                    (self.sp_listen_len, c.get("listen_len"), 1, 15)):
                spin.blockSignals(True)
                spin.setValue(max(lo, min(hi, int(val or lo))))
                spin.blockSignals(False)
        finally:
            self._loading_sense = False
        eyes, ears = bool(c.get("eyes")), bool(c.get("ears"))
        self.cb_watch.setEnabled(eyes)
        self.cb_listen_always.setEnabled(ears)
        self.sp_watch_sec.setEnabled(eyes and bool(c.get("watch")))
        self.sp_listen_sec.setEnabled(ears and bool(c.get("listen_always")))
        self.sp_listen_len.setEnabled(ears and bool(c.get("listen_always")))
        self.lbl_sense.setText(self._sense_state_text())
        if self.cb_cam.count() == 0:
            self.cb_cam.addItem("不用摄像头（看屏幕）", "")
        if self.cb_mic.count() == 0:
            self.cb_mic.addItem("系统默认", "")

        def work():
            return sense.devices()

        self._spawn(work, self._apply_sense_devices,
                    lambda e: self.lbl_sense.setText(f"（读不到设备：{e}）"))

    def _apply_sense_devices(self, data) -> None:
        data = data if isinstance(data, dict) else {}
        c = sense.cfg()
        cur_cam = str(c.get("camera") or "")
        cur_mic = str(c.get("mic") or "")

        self.cb_cam.blockSignals(True)
        self.cb_cam.clear()
        self.cb_cam.addItem("自动（有摄像头就拍）", "")
        self.cb_cam.addItem("只看屏幕", "screen")
        for name in (data.get("cameras") or []):
            self.cb_cam.addItem(f"摄像头：{name}", str(name))
        idx = self.cb_cam.findData(cur_cam)
        self.cb_cam.setCurrentIndex(idx if idx >= 0 else 0)
        self.cb_cam.blockSignals(False)

        self.cb_mic.blockSignals(True)
        self.cb_mic.clear()
        self.cb_mic.addItem("系统默认", "")
        for m in (data.get("mics") or []):
            try:
                i = int(m.get("index"))
            except (TypeError, ValueError):
                continue
            self.cb_mic.addItem(f"第 {i} 个 · {m.get('name') or ''}", str(i))
        idx = self.cb_mic.findData(cur_mic)
        self.cb_mic.setCurrentIndex(idx if idx >= 0 else 0)
        self.cb_mic.blockSignals(False)
        self.lbl_sense.setText(self._sense_state_text())

    def toggle_eyes(self, on: bool) -> None:
        sense.save({"eyes": bool(on)})
        self.cb_watch.setEnabled(bool(on))
        self.sp_watch_sec.setEnabled(bool(on) and self.cb_watch.isChecked())
        self.lbl_sense.setText(self._sense_state_text())

    def toggle_ears(self, on: bool) -> None:
        sense.save({"ears": bool(on)})
        self.cb_listen_always.setEnabled(bool(on))
        on2 = bool(on) and self.cb_listen_always.isChecked()
        self.sp_listen_sec.setEnabled(on2)
        self.sp_listen_len.setEnabled(on2)
        self.lbl_sense.setText(self._sense_state_text())

    def toggle_watch(self, on: bool) -> None:
        sense.save({"watch": bool(on)})
        self.sp_watch_sec.setEnabled(bool(on) and self.cb_eyes.isChecked())
        self.lbl_sense.setText(self._sense_state_text())

    def toggle_listen_always(self, on: bool) -> None:
        sense.save({"listen_always": bool(on)})
        on2 = bool(on) and self.cb_ears.isChecked()
        self.sp_listen_sec.setEnabled(on2)
        self.sp_listen_len.setEnabled(on2)
        self.lbl_sense.setText(self._sense_state_text())

    def save_sense_timing(self, *_) -> None:
        if getattr(self, "_loading_sense", False):
            return
        sense.save({"watch_sec": int(self.sp_watch_sec.value()),
                    "listen_sec": int(self.sp_listen_sec.value()),
                    "listen_len": int(self.sp_listen_len.value())})
        self.lbl_sense.setText(self._sense_state_text())

    def toggle_announce(self, on: bool) -> None:
        sense.save({"announce": bool(on)})
        self.lbl_sense.setText(self._sense_state_text())

    def on_cam_changed(self) -> None:
        sense.save({"camera": str(self.cb_cam.currentData() or "")})
        self.lbl_sense.setText(self._sense_state_text())

    def on_mic_changed(self) -> None:
        sense.save({"mic": str(self.cb_mic.currentData() or "")})
        self.lbl_sense.setText(self._sense_state_text())

    # ---------------------------------------------------------------- 启动与后台

    def refresh_startup(self) -> None:
        try:
            from ...services import startup

            self.cb_autostart.blockSignals(True)
            self.cb_autostart.setChecked(startup.is_enabled())
            self.cb_autostart.blockSignals(False)
        except Exception as exc:  # noqa: BLE001
            self.lbl_startup.setText(f"（读不到开机自启：{exc}）")
        self.cb_auto_restart.blockSignals(True)
        self.cb_auto_restart.setChecked(bool(config.get("core.auto_restart", True)))
        self.cb_auto_restart.blockSignals(False)

    def toggle_autostart(self, on: bool) -> None:
        from ...services import startup

        try:
            if on:
                cmd = startup.enable()
                self.lbl_startup.setText(f"已设为开机自启：{cmd}")
            else:
                startup.disable()
                self.lbl_startup.setText("已取消开机自启")
        except Exception as exc:  # noqa: BLE001
            self.cb_autostart.blockSignals(True)
            self.cb_autostart.setChecked(not on)
            self.cb_autostart.blockSignals(False)
            self.lbl_startup.setText(f"（{exc}）")

    def toggle_auto_restart(self, on: bool) -> None:
        try:
            config.set_value("core.auto_restart", bool(on))
            self.lbl_startup.setText("内核挂了会自动拉起来" if on else "内核挂了不再自动拉")
        except Exception as exc:  # noqa: BLE001
            self.lbl_startup.setText(f"（保存失败：{exc}）")

    # ---------------------------------------------------------------- 主动说话

    def _follow_text(self, lv: int) -> str:
        spec = self._follow_levels.get(int(lv)) or {}
        name = str(spec.get("name") or "")
        label = str(spec.get("label") or "")
        if name and label:
            return f"{name}：{label}"
        return name or label or f"第 {lv} 档"

    def refresh_followup(self) -> None:
        def work():
            from ...services.core_client import CoreClient

            return CoreClient(timeout=8).followup_get()

        def ok(res):
            try:
                self._follow_levels = {int(x.get("level")): x
                                       for x in ((res or {}).get("levels") or [])}
                lv = int(((res or {}).get("config") or {}).get("level") or 0)
                self._loading_follow = True
                self.slider_follow.setValue(lv)
                self.lbl_follow.setText(self._follow_text(lv))
            except Exception as e:  # noqa: BLE001
                self.lbl_follow.setText(f"（读不到主动程度：{e}）")
            finally:
                self._loading_follow = False

        self._spawn(work, ok, lambda e: self.lbl_follow.setText(f"（内核没连上：{e}）"))

    def on_follow_changed(self, value: int) -> None:
        self.lbl_follow.setText(self._follow_text(int(value)))
        if getattr(self, "_loading_follow", False):
            return

        def work():
            from ...services.core_client import CoreClient

            return CoreClient(timeout=8).followup_set(int(value))

        def ok(_r):
            self.lbl_follow.setText(self._follow_text(int(value)) + "（已保存）")

        self._spawn(work, ok, lambda e: self.lbl_follow.setText(f"（保存失败：{e}）"))

    def say_now(self) -> None:
        self.btn_say_now.setEnabled(False)
        self.lbl_follow.setText("让智能体想想…")

        def work():
            from ...services.core_client import CoreClient

            return CoreClient(timeout=120).proactive_send(force=True)

        def done(res) -> None:
            t = str((res or {}).get("text") or "").strip()
            if t:
                self.lbl_follow.setText(f"智能体说了：{t}")
            else:
                self.lbl_follow.setText(f"智能体这次没说：{(res or {}).get('reason') or '没开口'}")
            self.btn_say_now.setEnabled(True)

        def err(e) -> None:
            self.lbl_follow.setText(f"（没连上内核：{e}）")
            self.btn_say_now.setEnabled(True)

        self._spawn(work, done, err)

    def _emit(self, payload) -> None:
        """从后台线程回 UI。窗口已经销毁（退出时）就安静放弃。"""
        try:
            self.task_done.emit(payload)
        except (RuntimeError, TypeError):  # Signal source has been deleted
            return

    def _spawn(self, fn, on_ok=None, on_err=None, key=None, dedupe: bool = True) -> None:
        """页面切换不能卡：请求丢后台线程。

        默认按调用点去重（同一个刷新按钮只跑一条）；带参数的请求可以显式给
        key 并关掉 dedupe，让每一次勾选/输入都真的落到服务端。
        """
        if key is None:
            code = getattr(fn, "__code__", None)
            key = getattr(fn, "__name__", "task")
            if code is not None:
                key = f"{code.co_filename}:{code.co_firstlineno}"
        if dedupe:
            with self._spawn_lock:
                if key in self._spawn_keys:
                    return
                self._spawn_keys.add(key)

        def runner() -> None:
            try:
                res = fn()
            except Exception as e:  # noqa: BLE001
                if on_err is not None:
                    self._emit((on_err, e))
            else:
                if on_ok is not None:
                    self._emit((on_ok, res))
            finally:
                self._emit((self._spawn_done, key))

        threading.Thread(target=runner, daemon=True).start()

    def _spawn_done(self, key) -> None:
        with self._spawn_lock:
            self._spawn_keys.discard(key)

    def _run_task_cb(self, payload) -> None:
        try:
            cb, val = payload
            cb(val)
        except Exception as e:  # noqa: BLE001
            log.warning("后台任务回调失败：%s", e)

    # ---------------------------------------------------------------- 肚子
    def refresh_stomach(self) -> None:
        def work():
            from ...services.core_client import CoreClient

            return CoreClient(timeout=8).stomach_config()

        def ok(res):
            d = res if isinstance(res, dict) else {}
            try:
                for box, key, fallback in ((self.sb_full, "full_at", 10.0),
                                           (self.sb_hungry, "hungry_at", 3.0)):
                    box.blockSignals(True)
                    box.setValue(float(d.get(key, fallback)))
                    box.blockSignals(False)
            except Exception as e:  # noqa: BLE001
                log.info("读胃配置失败：%s", e)

        self._spawn(work, ok, None)

    def save_stomach(self) -> None:
        full = float(self.sb_full.value())
        hungry = float(self.sb_hungry.value())
        if full <= hungry:
            self.lbl_stomach.setText("饱的分界要大于饿的分界，没保存")
            return

        def work():
            from ...services.core_client import CoreClient

            return CoreClient(timeout=20).stomach_set(full, hungry)

        def ok(_res):
            self.lbl_stomach.setText(
                f"已保存：≥ {full:.1f} 元算饱，≤ {hungry:.1f} 元算饿")

        def err(e):
            self.lbl_stomach.setText(f"没保存上：{e}")

        self._spawn(work, ok, err)

    # ---------------------------------------------------------------- 记忆库
    def refresh_memory(self) -> None:
        def work():
            from ...services.core_client import CoreClient

            return CoreClient(timeout=8).memory_stats()

        def ok(res):
            d = res if isinstance(res, dict) else {}
            stats = d.get("stats") or {}
            cfg = d.get("config") or {}
            used = float(stats.get("used_mb") or 0.0)
            files = int(stats.get("files") or 0)
            self.lbl_memory.setText(
                f"现在占 {used:.1f} MB（{files} 个文件）；超过压缩阈值后，"
                f"比保留天数更旧的记忆会被概括成几行。")
            try:
                for box, key, fallback in ((self.sb_mem_max, "max_gb", 2.0),
                                           (self.sb_mem_zip, "compress_gb", 0.5),
                                           (self.sb_mem_days, "keep_days", 60)):
                    box.blockSignals(True)
                    box.setValue(float(cfg.get(key, fallback)) if isinstance(box, QDoubleSpinBox)
                                 else int(cfg.get(key, fallback)))
                    box.blockSignals(False)
            except Exception as e:  # noqa: BLE001
                log.info("读记忆配置失败：%s", e)

        self._spawn(work, ok, None)

    def save_memory(self) -> None:
        max_gb = round(float(self.sb_mem_max.value()), 1)
        zip_gb = round(float(self.sb_mem_zip.value()), 1)
        days = int(self.sb_mem_days.value())
        if zip_gb > max_gb:
            self.lbl_memory.setText("压缩阈值不能大于上限，没保存")
            return

        def work():
            from ...services.core_client import CoreClient

            return CoreClient(timeout=10).memory_save(max_gb, zip_gb, days)

        def ok(_res):
            self.lbl_memory.setText(
                f"已保存：上限 {max_gb:.1f} G，超过 {zip_gb:.1f} G 开始压缩，保留 {days} 天")

        def err(e):
            self.lbl_memory.setText(f"没保存上：{e}")

        self._spawn(work, ok, err)

    # ---------------------------------------------------------------- 模型
    @staticmethod
    def _mask(key: str) -> str:
        key = (key or "").strip()
        if not key:
            return "（还没填）"
        if len(key) <= 10:
            return key[:2] + "…"
        return f"{key[:6]}…{key[-4:]}（{len(key)} 位）"

    def refresh_model(self) -> None:
        cfg = framework_setup.read_llm()
        self.lbl_model.setText(str(cfg.get("model") or "deepseek-chat"))
        self.lbl_base.setText(str(cfg.get("api_base") or "https://api.deepseek.com/v1"))
        self.lbl_key.setText(self._mask(str(cfg.get("api_key") or "")))
        self.lbl_rel.setText(str(cfg.get("relation") or "主人"))
        try:
            self.lbl_rel_title.setText("你是" + framework_setup.pronoun() + "的")
        except Exception:  # noqa: BLE001
            self.log.debug("更新关系称呼失败", exc_info=True)

    def change_key(self) -> None:
        from ..dialogs.key_dialog import KeyDialog

        dlg = KeyDialog(self.win)
        if dlg.exec() and dlg.saved:
            self.refresh_model()
            chat = getattr(self.win, "pages", {}).get("chat")
            if chat is not None and hasattr(chat, "refresh_setup"):
                chat.refresh_setup()

    # ---------------------------------------------------------------- 端口与桥
    def refresh_ports(self) -> None:
        from ...services.core_client import CoreClient

        def work():  # noqa: ANN202
            try:
                self.ports_ready.emit(CoreClient().ports_map())
            except Exception as e:  # noqa: BLE001
                self.ports_ready.emit({"ok": False, "error": str(e)})

        self._spawn(work)

    def _apply_ports(self, d: dict) -> None:
        if not d.get("ok"):
            self.lbl_ports.setText(f"（内核没连上：{d.get('error')}）")
            return
        iid = str(d.get("install_id") or "")[:10]
        lines = [f"安装 {iid}…　基址 {d.get('base')}",
                 f"内核 {d.get('core')}　语音 {d.get('asr')}"]
        for m in d.get("modules") or []:
            lines.append(f"模组 {m.get('name')}（{m.get('id')}）→ {m.get('port')}　{m.get('state')}")
        self.lbl_ports.setText("\n".join(lines))

    # ---------------------------------------------------------------- 目录
    def open_config(self) -> None:
        subprocess.Popen(["notepad.exe", str(config.CONFIG_PATH)])

    def open_app(self) -> None:
        subprocess.Popen(["explorer.exe", str(config.APP_DIR)])

    def open_root(self) -> None:
        subprocess.Popen(["explorer.exe", str(config.project_root())])

    def open_logs(self) -> None:
        try:
            config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            self.log.warning("创建日志目录失败，资源管理器可能打不开", exc_info=True)
        subprocess.Popen(["explorer.exe", str(config.LOG_DIR)])

    def show_tutorial(self) -> None:
        from ..dialogs.tutorial import TutorialWelcome
        TutorialWelcome(self).exec()
