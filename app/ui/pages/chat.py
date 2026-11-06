"""聊天（首页）：跟 TA 说的话 + TA 主动找你说的话；右上角是「您的状态」。"""
from __future__ import annotations

import time
from datetime import datetime

import os

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal, QVariantAnimation
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ...core import config, framework_setup, logger
from ...services import worker as worker_mod
from ...services import audio, speech_time
from ...services.core_client import CoreClient
from ...services.worker import run_async
from .. import action_text, fonts
from ..widgets.nanny_panel import NannyPanel
from .chat_nanny import ChatNannyMixin


class ChatInput(QPlainTextEdit):
    """聊天输入：Enter 发送，Shift+Enter 换行。

    默认一行；每多一行长高一行（按字体行高，不按像素瞎猜），
    最多 8 行，超过就在框里滚动——不把整个页面顶上去。
    """

    submitted = Signal()

    MAX_LINES = 8

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTabChangesFocus(True)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setFixedHeight(self._one_line_h())
        self.document().contentsChanged.connect(self._fit_height)
        self.textChanged.connect(lambda: self._fit_height())

    def _line_h(self) -> int:
        return max(12, int(self.fontMetrics().lineSpacing()))

    def _one_line_h(self) -> int:
        # 9px 上下内边距 + 一行字
        return max(40, self._line_h() + 22)

    def keyPressEvent(self, ev) -> None:  # noqa: N802
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter) and not (ev.modifiers() & Qt.ShiftModifier):
            self.submitted.emit()
            ev.accept()
            return
        super().keyPressEvent(ev)
        self._fit_height()

    def _visual_lines(self) -> int:
        """按排版后的行数算（自动换行也算一行），不用 QTextDocument.size()——
        那玩意在 QPlainTextEdit 里按"行数"报，不按像素，长高会永远算错。"""
        n = 0
        block = self.document().begin()
        while block.isValid():
            lay = block.layout()
            n += max(1, lay.lineCount()) if lay is not None else 1
            block = block.next()
        return max(1, n)

    def _fit_height(self) -> None:
        line_h = self._line_h()
        shown = min(self.MAX_LINES, self._visual_lines())
        h = max(self._one_line_h(), line_h * shown + 22)
        if h != self.height():
            self.setFixedHeight(h)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._fit_height()

    # 兼容原来当 QLineEdit 用的地方（send() 读 text()、清空用 clear()）
    def text(self) -> str:  # noqa: A003
        return self.toPlainText()


class ChatPage(ChatNannyMixin, QWidget):
    def __init__(self, win) -> None:
        super().__init__()
        self.setObjectName("ChatPage")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.win = win
        self.log = logger.get()
        self.session = str(config.get("chat.session", "web:owner"))
        self._cursor = 0
        self._notice_cursor = time.time()
        self._pending_echo = 0
        self._poll_busy = False
        self._last_me = ""
        self._pending = False

        # 左边是聊天，右边是保姆程序的流水（只记提醒，不参与聊天）
        self.cols = QHBoxLayout(self)
        self.cols.setContentsMargins(0, 0, 0, 0)
        self.cols.setSpacing(0)

        # 背景由主窗口统一铺在页面栈下面；聊天区保持透明，保姆栏在右边不受影响
        self.stage = QWidget(objectName="ChatStage")
        outer = QVBoxLayout(self.stage)
        outer.setContentsMargins(18, 10, 18, 14)
        outer.setSpacing(8)
        self.outer = outer
        self.cols.addWidget(self.stage, 1)

        # ---- 头：标题 + 她的名字 + 您的状态 ----
        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("聊天", objectName="PageTitle")
        head.addWidget(title)
        head.addSpacing(6)
        self.dot = QLabel("●", objectName="Muted")
        head.addWidget(self.dot)
        self.hint = QLabel("", objectName="Muted")
        self.hint.setVisible(False)
        head.addWidget(self.hint)
        self.notice = QLabel("还没配 API Key —— 去左侧「设置 → 更改 API Key」",
                             objectName="Warn")
        self.notice.setVisible(not framework_setup.is_configured())
        self.notice.setWordWrap(True)
        head.addStretch(1)

        self.speak = QCheckBox("朗读")
        self.speak.setObjectName("Speak")
        self.speak.setCursor(Qt.PointingHandCursor)
        self.speak.setToolTip("朗读时用系统声音念出来（edge-tts，需要联网）")
        self.speak.setChecked(bool(config.get("ui.tts_autoplay", False)))
        self.speak.toggled.connect(self._toggle_speak)
        head.addWidget(self.speak)
        head.addSpacing(6)
        head.addWidget(QLabel("您的状态", objectName="Muted"))
        self.btn_online = QPushButton("在线", objectName="Seg")
        self.btn_busy = QPushButton("忙碌", objectName="Seg")
        for b in (self.btn_online, self.btn_busy):
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(26)
        self.seg = QButtonGroup(self)
        self.seg.setExclusive(True)
        self.seg.addButton(self.btn_online, 0)
        self.seg.addButton(self.btn_busy, 1)
        self.btn_online.clicked.connect(lambda: self.set_presence("online"))
        self.btn_busy.clicked.connect(lambda: self.set_presence("busy"))
        head.addWidget(self.btn_online)
        head.addWidget(self.btn_busy)
        outer.addLayout(head)

        # 提示条单独占一行：字号放大时不跟标题、状态按钮抢那一点宽度
        outer.addWidget(self.notice)

        # ---- 消息区（背景在整列下面，滚动区透明显出来） ----
        self.scroll = QScrollArea(objectName="ChatScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.viewport().setAttribute(Qt.WA_TranslucentBackground, True)
        self.body = QWidget(objectName="ChatBody")
        self.body.setAutoFillBackground(False)
        self.body.setAttribute(Qt.WA_TranslucentBackground, True)
        self.msg_lay = QVBoxLayout(self.body)
        self.msg_lay.setContentsMargins(2, 4, 8, 4)
        self.msg_lay.setSpacing(8)
        self.msg_lay.addStretch(1)
        self.scroll.setWidget(self.body)
        outer.addWidget(self.scroll, 1)

        # ---- 输入 ----
        self.typing = QLabel("", objectName="Muted")
        outer.addWidget(self.typing)
        row = QHBoxLayout()
        self.input = ChatInput(objectName="ChatInput")
        self.apply_pronoun()
        self.input.submitted.connect(self.send)
        self.btn_send = QPushButton("发送", objectName="Primary")
        self.btn_send.setFixedWidth(fonts.ui_px(76))
        self.btn_send.setAccessibleName("发送消息")
        self.btn_send.setToolTip("发送（Enter）")
        self.btn_send.clicked.connect(self.send)
        row.addWidget(self.input, 1)
        row.addWidget(self.btn_send)
        outer.addLayout(row)

        # AI 生成标识：常驻在输入框下方，不参与滚动，也不挡对话
        self.ai_label = QLabel(self._ai_label_text(), objectName="AILabel")
        self.ai_label.setAlignment(Qt.AlignRight)
        outer.addWidget(self.ai_label)

        # ---- 保姆程序栏：提醒都走这边，聊天窗里不再插 ----
        self.nanny = NannyPanel(self)
        self.nanny.btn_toggle.clicked.connect(self._remember_nanny_state)
        self.nanny.btn_open.clicked.connect(self._remember_nanny_state)
        self.nanny.collapsed_changed.connect(self._on_nanny_collapsed)
        self.nanny.opened.connect(self._open_nanny_window)

        # 收起后只剩聊天区右上角这颗浮层小按钮，背景一直铺到窗口右缘
        self.nanny_tab = QPushButton("保", self.stage)
        self.nanny_tab.setObjectName("NannyTab")
        self.nanny_tab.setFixedSize(fonts.ui_px(38), fonts.ui_px(32))
        self.nanny_tab.setCursor(Qt.PointingHandCursor)
        self.nanny_tab.setToolTip("展开保姆程序的提醒")
        self.nanny_tab.clicked.connect(lambda: self.nanny.set_collapsed(False))
        self.nanny_tab.hide()

        self._nanny_tab_timer = QTimer(self)
        self._nanny_tab_timer.setInterval(800)
        self._nanny_tab_timer.timeout.connect(self._refresh_nanny_tab)
        self._nanny_tab_timer.start()

        self.nanny.set_collapsed(bool(config.get("ui.nanny_collapsed", False)))
        self.cols.addWidget(self.nanny, 0)

        self._dot = QTimer(self)
        self._dot.timeout.connect(self._blink)
        self._dot_n = 0

        # 气泡只留最近 200 条，长会话不会无限堆控件；滚动合并成一帧一次。
        self._bubble_rows = []
        self._max_bubbles = 200
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(20)
        self._scroll_timer.timeout.connect(self._scroll_bottom)

        # 内核重试只留一条链，避免多个 refresh_setup 叠出多条 singleShot。
        self._runtime_timer = QTimer(self)
        self._runtime_timer.setSingleShot(True)
        self._runtime_timer.timeout.connect(self.apply_runtime)
        # 内核还没起来的时候 feed 每 5 秒失败一次，只记第一条，别把日志刷满
        self._feed_err = False
        # 回复刚画完、游标还没对齐的这段时间，poll 一律让路（否则同一轮会被画两遍）
        self._resyncing = False
        # ---- 朗读队列：一句念完才念下一句，绝不叠着播 ----
        self._speech_queue: list[tuple[str, object]] = []
        self._speech_busy = False
        self._speech_epoch = 0
        self._deliver_state: tuple[list[str], int, int] | None = None
        # 一条回复的"逐句放出"链；被打断时 +1，旧链上的定时器全部作废
        self._deliver_epoch = 0
        # 当前语速（core 的 tts 配置，每轮回复前刷新）：关掉朗读时靠它算"这句多长"
        self._tts_rate = "+0%"

        # 轮询她主动说的话 + 你在别处（QQ/B站）说的
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll)
        self.poll_timer.start(5000)

        self.load_presence()
        QTimer.singleShot(300, self.poll)
        self.reload_background()

    # ---------- 气泡 ----------
    def bubble(self, who: str, text: str) -> None:
        if who == "system":
            frame = QFrame(objectName="BubbleSys")
            lay = QVBoxLayout(frame)
            lay.setContentsMargins(12, 6, 12, 6)
            lbl = QLabel(text, objectName="BubbleSysText")
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lay.addWidget(lbl)
            row = QHBoxLayout()
            frame.setMaximumWidth(fonts.ui_px(560))
            row.addStretch(1)
            row.addWidget(frame)
            row.addStretch(1)
            self._add_row(row)
            self._request_scroll()
            return
        frame = QFrame(objectName="BubbleMe" if who == "me" else "BubbleHer")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 8, 12, 7)
        lay.setSpacing(3)
        lbl = QLabel(objectName="BubbleText")
        lbl.setWordWrap(True)
        # 〖动作〗在气泡里缩小变灰，跟「说出来的话」区分开（见 app/ui/action_text.py）
        if who == "her" and action_text.has_action(text):
            lbl.setTextFormat(Qt.RichText)
            lbl.setText(action_text.to_html(text))
        else:
            lbl.setText(text)
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        lay.addWidget(lbl)
        meta = QLabel(datetime.now().strftime("%H:%M"), objectName="BubbleTime")
        lay.addWidget(meta)

        row = QHBoxLayout()
        frame.setMaximumWidth(fonts.ui_px(620))
        if who == "me":
            row.addStretch(1)
            row.addWidget(frame)
        else:
            row.addWidget(frame)
            row.addStretch(1)
        self._add_row(row)
        self._request_scroll()

    def _add_row(self, row) -> None:
        self.msg_lay.insertLayout(self.msg_lay.count() - 1, row)
        self._bubble_rows.append(row)
        while len(self._bubble_rows) > self._max_bubbles:
            old = self._bubble_rows.pop(0)
            try:
                self.msg_lay.removeItem(old)
                while old.count():
                    item = old.takeAt(0)
                    w = item.widget()
                    if w is not None:
                        w.setParent(None)
                        w.deleteLater()
            except Exception:  # noqa: BLE001
                self.log.debug("清理旧气泡失败", exc_info=True)

    def _request_scroll(self) -> None:
        if not self._scroll_timer.isActive():
            self._scroll_timer.start()

    def _scroll_bottom(self) -> None:
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _blink(self) -> None:
        self._dot_n = (self._dot_n + 1) % 4
        self.typing.setText(f"{framework_setup.display_name()}正在输入" + "·" * self._dot_n)

    # ---------- 状态 ----------
    @staticmethod
    def _presence_text(state: str) -> str:
        """「在线」/「忙碌」两个字对称，别一处写「忙」一处写「忙碌」。"""
        return "● 在线" if state == "online" else "● 忙碌"

    def load_presence(self) -> None:
        def ok(res):
            state = (res or {}).get("state", "busy")
            (self.btn_online if state == "online" else self.btn_busy).setChecked(True)
            self.dot.setText(self._presence_text(state))

        run_async(lambda: CoreClient().presence(), on_ok=ok,
                  on_err=lambda e: self.log.warning("presence 读取失败：%s", e))

    def set_presence(self, state: str) -> None:
        def ok(_res):
            self.dot.setText(self._presence_text(state))
            self.typing.setText("状态已改成：" + ("在线" if state == "online" else "忙碌"))
            QTimer.singleShot(2500, lambda: self.typing.setText(""))
            if state == "online" and getattr(self, "_tut_wait_online", False):
                self._tut_wait_online = False
                self._nanny_push("您先随便聊两句，我过一会儿再继续教您。")

        run_async(lambda: CoreClient().set_presence(state), on_ok=ok,
                  on_err=lambda e: self.typing.setText(f"状态没改成功：{e}"))

    # ---------- 发送 ----------
    def send(self) -> None:
        if self._pending:
            return
        text = self.input.text().strip()
        if not text:
            return
        # 她还在念、而且后面还有话没出口：掐掉声音，那几句算没说；只念一句就随它念完
        self._interrupt_speech()
        self.input.clear()
        self.bubble("me", text)
        self._last_me = text
        self._pending_echo += 1
        self._pending = True
        self.btn_send.setEnabled(False)
        self.input.setEnabled(False)
        self._dot.start(380)
        self.typing.setText(f"{framework_setup.display_name()}正在输入")

        run_async(lambda: CoreClient().chat(text, session=self.session), on_ok=self._on_ok,
                  on_err=self._on_err)

    def apply_pronoun(self) -> None:
        """输入框的「跟她说点什么」要跟着性别走；向导改完性别要能刷新。"""
        try:
            pron = framework_setup.pronoun()
        except Exception:  # noqa: BLE001
            pron = "TA"
        self.input.setPlaceholderText(f"跟{pron}说点什么…（Enter 发送，Shift+Enter 换行）")

    def reload_background(self) -> None:
        """背景已经挪到主窗口；聊天页只保持透明，这个方法留给外部调用。"""
        return

    def _typing_hold(self, _part: str = "") -> None:
        self.typing.setText(f"{framework_setup.display_name()}正在输入")
        self._dot.start(380)

    def refresh_setup(self) -> None:
        self.apply_pronoun()
        """向导或设置里改完 Key 之后调用：顶部提示跟着状态走，不再长期挂着旧按钮。"""
        if framework_setup.is_configured():
            self._maybe_tutorial()
        self.apply_runtime(start=True)

    def apply_runtime(self, start: bool = False) -> None:
        """内核状态跟着真实情况走：不在跑就自己拉起来，绝不要求用户去停别人的进程。"""
        from PySide6.QtCore import QTimer

        from app.services import asr, runtime

        if start:
            runtime.ensure_async()
            asr.ensure_async()
        st = runtime.status()
        state = st.get("state")

        if state in ("unknown", "failed") and not start:
            runtime.ensure_async()
            st = runtime.status()
            state = st.get("state")

        if state == "starting":
            self.notice.setText(st.get("detail") or "正在启动这一份的内核…")
            self.notice.setToolTip("第一次启动要几秒；日志在程序目录 logs\\core-boot.log")
            self.notice.setVisible(True)
            self._runtime_timer.start(1200)
            return

        if state == "ok":
            if framework_setup.is_configured():
                self.notice.setVisible(False)
            else:
                self.notice.setText("还没配 API Key —— 去左侧「设置 → 更改 API Key」")
                self.notice.setVisible(True)
            return

        self.notice.setText("内核没起来：" + str(st.get("detail") or "看左侧「日志」"))
        self.notice.setToolTip("程序会自动重试；也可以去「服务」页点「启动全部」。")
        self.notice.setVisible(True)
        self._runtime_timer.start(4000)

    def _toggle_speak(self, on: bool) -> None:
        try:
            cfg = config.load(force=True)
            cfg["ui"] = dict(cfg.get("ui") or {})
            cfg["ui"]["tts_autoplay"] = bool(on)
            config.save(cfg)
        except Exception as e:  # noqa: BLE001
            logger.get().warning("保存朗读开关失败：%s", e)
        self._refresh_ai_label()

    def _ai_label_text(self) -> str:
        on = bool(self.speak.isChecked()) if hasattr(self, "speak") else False
        return "对话内容由 AI 生成 · 语音由 AI 合成" if on else "对话内容由 AI 生成"

    def _refresh_ai_label(self) -> None:
        lbl = getattr(self, "ai_label", None)
        if lbl is not None:
            lbl.setText(self._ai_label_text())

    def _show_typing(self) -> None:
        """合成也好、等前一句念完也好，都得让用户看见「正在输入」，别像卡住。"""
        self.typing.setText(f"{framework_setup.display_name()}正在输入")
        self._dot.start(380)

    def _speaks_pending(self) -> bool:
        return self._speech_busy or bool(self._speech_queue)

    def _speak(self, text: str) -> None:
        """兼容旧调用：排进朗读队列。"""
        self._say(text)

    def _say(self, text: str, on_done=None) -> None:
        """把一句话排进朗读队列：上一句念完才念下一句，绝不叠着播。

        没开朗读就立刻回调 `on_done`，让调用方（一条条显示消息的那条链）照常往下走。
        动作（〖…〗）先删掉再送进合成——她的小动作不该被念出来；整句只有动作就不念。
        """
        spoken = action_text.spoken(text)
        if not spoken or not self.speak.isChecked():
            if callable(on_done):
                on_done()
            return
        self._speech_queue.append((spoken, on_done))
        if self._speech_busy:
            self._show_typing()  # 前一句还在念，她这边仍显示「正在输入」
            return
        self._pump_speech()

    def _pump_speech(self) -> None:
        if not self._speech_queue:
            self._speech_busy = False
            self._dot.stop()
            return
        text, on_done = self._speech_queue.pop(0)
        self._speech_busy = True
        epoch = self._speech_epoch

        def work() -> None:
            data = CoreClient(timeout=180).tts_say(text)
            path = audio.save_audio(data)
            played = audio.player.play_wait(path)  # 阻塞到这句真的念完
            if not played:
                logger.get().info("朗读放不出声：%s", path)

        def done(_res=None) -> None:
            if epoch != self._speech_epoch:
                return  # 已经被用户打断，别再往前推
            self._speech_busy = False
            if callable(on_done):
                on_done()
            self._pump_speech()

        def failed(e) -> None:
            logger.get().info("朗读失败：%s", e)
            done(None)

        run_async(work, on_ok=done, on_err=failed)

    def _refresh_tts_rate(self) -> None:
        """问内核现在把语速调到多少了 —— 关掉朗读时靠它算每句占多久。"""
        def ok(res):
            cfg = ((res or {}).get("config") or {}) if isinstance(res, dict) else {}
            rate = str(cfg.get("rate") or "").strip()
            if rate:
                self._tts_rate = rate

        run_async(lambda: CoreClient(timeout=6).tts_voices(), on_ok=ok,
                  on_err=lambda e: None)

    def _pending_parts(self) -> int:
        """还有几句排在她嘴上没说出来（正在念的那句不算，那句她已经说了）。"""
        state = self._deliver_state
        if not state:
            return 0
        _parts, i, total = state
        return max(0, int(total) - (int(i) + 1))

    def _withdraw_speech(self, n: int) -> None:
        """把 n 句没来得及出口的话咽回去：记进情绪，一次就够。

        开着朗读时她真的"话到嘴边被堵回去"，记满格；只文字时看不见嘴，轻一点。
        """
        if n <= 0:
            return
        strength = 1.0 if self.speak.isChecked() else 0.6

        def work():
            return CoreClient(timeout=8).emotion_stimulus("cut_off", strength)

        run_async(work, on_ok=lambda r: logger.get().info("[打断] %d 句咽回去", n),
                  on_err=lambda e: logger.get().info("[打断] 情绪没记上：%s", e))

    def _interrupt_speech(self, announce: bool = True) -> int:
        """用户开口了。

        - 她只说了/正在说一句，后面没排队 → 什么都不做，声音念完，你打字不受影响。
        - 她说好几句、后面还有没出口的 → 掐掉声音，那几句算「心里想了、嘴还没说」，
          情绪记一笔，保姆说「对方被打断」；被打断的这句算已经说了，不退回。

        返回被咽回去的句数（0 = 没打断任何东西）。
        """
        pending = self._pending_parts()
        if pending <= 0:
            return 0
        self._speech_epoch += 1
        self._deliver_epoch += 1
        self._speech_queue.clear()
        self._speech_busy = False
        self._deliver_state = None
        if self.speak.isChecked():
            # 只有真在出声时才有"掐掉"这回事；纯文字模式它根本没播
            try:
                audio.player.stop()
            except Exception:  # noqa: BLE001
                self.log.debug("停止朗读播放器失败", exc_info=True)
        self._dot.stop()
        if announce:
            self._nanny_push("对方被打断", persist=True)
        self._withdraw_speech(pending)
        return pending

    def _on_ok(self, res) -> None:
        # 从这一刻到游标对齐完，5 秒一次的 poll 一律别动手：它拿的是旧游标，
        # 会把刚刚直接画上屏的这一轮再画一遍（0.3.7 的"重复发出"就是这么来的）
        self._resyncing = True
        self._finish()
        self._refresh_tts_rate()
        res = res or {}
        reply = str(res.get("reply") or "").strip()
        parts = [str(x).strip() for x in (res.get("messages") or []) if str(x).strip()]
        if not parts and reply:
            parts = [reply]
        # 一条一条来：每条前面先显示「正在输入」；开着朗读时，下一句一定等上一句念完
        if parts:
            self._deliver_epoch += 1
            self._deliver(parts, 0, len(parts), self._deliver_epoch)
        else:
            # 模型那头断了（余额/网络/超时），必须让"没回上"这件事可见
            self.bubble("her", "（没回上：模型那头断了，再发一次试试）")
        # 内核回包带 total 时直接对齐，避免每次回复都 feed(0) 重传全部历史。
        total = int(res.get("total") or 0)
        if total:
            self._cursor = max(self._cursor, total)
            self._pending_echo = 0
            self._resyncing = False
        else:
            self._resync()

    def _deliver(self, parts: list[str], i: int, total: int, epoch: int = 0) -> None:
        """第 i 句：先显示「正在输入」，再冒泡、再念。念完才轮到下一句。"""
        if epoch and epoch != self._deliver_epoch:
            return  # 旧链上的定时器，用户已经打断过，别再往前放
        if i >= len(parts):
            self._deliver_state = None
            self._dot.stop()
            # 一段话放完就把「正在输入」收掉；还在念下一句（朗读队列没空）时留给它自己管
            if not self._speaks_pending():
                self.typing.setText("")
            return
        self._deliver_state = (parts, i, total)
        part = parts[i]
        self._typing_hold(part)
        # 冒泡前的"打字准备"：打字不是说话，语速影响不到这里；关掉朗读时不必等那么久
        if self.speak.isChecked():
            hold = max(650, min(1600, 300 + len(part) * 40))
        else:
            hold = max(180, min(500, 180 + len(part) * 20))
        QTimer.singleShot(int(hold), lambda: self._show_part(parts, i, total, epoch))

    def _show_part(self, parts: list[str], i: int, total: int, epoch: int = 0) -> None:
        if epoch and epoch != self._deliver_epoch:
            return
        if self._deliver_state is None:
            return
        part = parts[i]
        self.bubble("her", part)
        speech_epoch = self._speech_epoch

        def next_one() -> None:
            if speech_epoch != self._speech_epoch:
                return  # 声音这一层被打断了
            if epoch and epoch != self._deliver_epoch:
                return
            QTimer.singleShot(120, lambda: self._deliver(parts, i + 1, total, epoch))

        spoken = action_text.spoken(part)
        if self.speak.isChecked() and spoken:
            self._show_typing()
            self._say(part, on_done=next_one)
        elif self.speak.isChecked():
            # 这一条只有动作（〖…〗），没有话要念：冒个泡就往下走
            self._dot.stop()
            QTimer.singleShot(180, next_one)
        else:
            # 没开朗读：这句不念，但仍按"这句话要说多久"占一段，留给你插话的余地
            wait = int(speech_time.text_window_seconds(spoken, self._tts_rate) * 1000)
            QTimer.singleShot(max(220, wait), next_one)

    def _resync(self) -> None:
        """把游标对齐到内核的真实轮数（回复已经直接画上去了，不用再从 feed 里拿一遍）。"""
        def ok(res):
            total = int((res or {}).get("total") or 0)
            self._cursor = max(self._cursor, total)
            self._pending_echo = 0
            self._resyncing = False

        def failed(_e):
            self._resyncing = False  # 对不上也不能把 poll 永久钉死

        run_async(lambda: CoreClient().feed(self.session, max(0, self._cursor)),
                  on_ok=ok, on_err=failed)

    def _on_err(self, err: str) -> None:
        self._resyncing = False
        self._finish()
        self.bubble("her", f"（没连上内核：{err}）")
        try:
            port = CoreClient().base.rsplit(":", 1)[-1]
        except Exception:  # noqa: BLE001
            port = ""
        self.typing.setText(f"内核不可达，确认 {port} 在跑" if port else "内核不可达，先看看内核有没有起来")
        # 不立刻清 _pending_echo：这次 /chat 可能只是超时，消息已经在服务端落库。
        # 先对一次账；服务端确实没这条时再清，避免下一次 feed 把用户消息重画一遍。
        self._recover_echo()

    def _recover_echo(self) -> None:
        """发送失败后对账：服务端没有新用户轮次，才清掉乐观计数。"""
        cursor = int(self._cursor)

        def ok(res):
            turns = (res or {}).get("turns") or []
            # 服务端没有这条用户消息（哪怕期间她主动说了别的），才清乐观计数；
            # 有用户消息就交给下一次 poll 按 _pending_echo 去重。
            if not any(str(t.get("role") or "") == "user" for t in turns):
                self._pending_echo = 0

        run_async(lambda: CoreClient().feed(self.session, cursor),
                  on_ok=ok, on_err=lambda _e: None)

    def _finish(self) -> None:
        self._pending = False
        self._dot.stop()
        self.btn_send.setEnabled(True)
        self.input.setEnabled(True)
        self.input.setFocus()

    # ---------- 教程 ----------
    def _maybe_tutorial(self, first_time: bool = False) -> None:
        if not framework_setup.is_configured():
            return
        if getattr(self, "_tut_asked", False):
            return
        self._tut_asked = True

        def ok(st):
            st = st or {}
            self._tut_mode = st.get("mode")
            self._tut_since = st.get("pending_since")
            if st.get("seen"):
                self._tut_mode = "done"
                return
            from ..dialogs.tutorial import TutorialWelcome
            dlg = TutorialWelcome(self)
            if not dlg.exec():
                return
            action = dlg.mode or "skip"
            turn = int(getattr(self, "_turns_seen", 0) or 0)

            def done(res):
                self._tut_mode = (res or {}).get("mode")
                self._tut_since = (res or {}).get("pending_since")
                if action == "skip":
                    # 折叠着的时候也要让用户看见这次提醒
                    try:
                        if self.nanny.is_collapsed():
                            self.nanny.set_collapsed(False)
                    except Exception:  # noqa: BLE001
                        self.log.debug("展开保姆栏失败", exc_info=True)
                    self._nanny_push("好，那就不讲了。「设置」里能查看状态和改部分配置。")
                elif action == "finish":
                    self._nanny_push("教程看完了。「设置」里能查看状态和改部分配置。")
                else:
                    name = framework_setup.display_name()
                    self._tut_wait_online = True
                    self._nanny_push("右上角是您的状态，请您先选择【在线】——它决定「"
                                     + name + "」能不能在这里和您畅聊。")
                    self._nanny_push("关闭此窗口后，默认您处于忙碌状态。")

            run_async(lambda: CoreClient().tutorial_update(action, turn),
                      on_ok=done, on_err=lambda e: None)

        run_async(lambda: CoreClient().tutorial_get(), on_ok=ok, on_err=lambda e: None)

    def _tutorial_maybe_fire(self, total: int) -> None:
        if getattr(self, "_tut_mode", None) != "deferred":
            return
        since = int(getattr(self, "_tut_since", 0) or 0)
        if total - since < 6 and not getattr(self, "_tut_proactive", False):
            return
        name = framework_setup.display_name()
        self._nanny_push("您聊着，我补几句。")
        self._nanny_push(f"{name} 是个 AI，靠您选的模型说话；左侧「模组」是给 TA 装能力的地方，"
                         f"装了 QQ 才有 QQ。")
        self._nanny_push("Ta 只是个 AI，请不要投入过重感情；如果还有需要，"
                         "您可以在「设置」里查到更多信息。")
        self._tut_mode = "done"

        def done(_res):
            pass

        run_async(lambda: CoreClient().tutorial_update("finish"), on_ok=done,
                  on_err=lambda e: None)

    # ---------- 拉取 ----------
    def poll(self, force: bool = False) -> None:
        if self._resyncing:
            return  # 正在对齐游标，这一下画了必重
        if self._pending and not force:
            return
        if self._poll_busy:
            return  # 上一次 feed 还没回来；再发一次会把同一批消息画两遍

        self._poll_busy = True
        req_cursor = int(self._cursor)

        def ok(res):
            self._poll_busy = False
            if req_cursor != self._cursor:
                return  # 期间被回复/重同步推进了游标，这次结果已过期
            turns = (res or {}).get("turns") or []
            total = int((res or {}).get("total") or 0)
            # 第一次打开只补最近 20 条，别把几百条历史一次全堆上来
            if req_cursor == 0 and len(turns) > 20:
                turns = turns[-20:]
            for t in turns:
                role = t.get("role")
                text = str(t.get("text") or "").strip()
                if not text:
                    continue
                if role == "user":
                    if self._pending_echo > 0:
                        self._pending_echo -= 1
                        continue
                    self.bubble("me", text)
                else:
                    # 主动说话就是她说了一句，不加任何标签：聊天界面只放对话本身。
                    # 「她/对方在找您」这种提醒属于保姆栏（而且只在忙碌/离开时才提示）。
                    self.bubble("her", text)
                    # 主动说的话也要念出来：以前只有点发送后的回复走朗读链，
                    # feed 里冒出来的这句被静音了（内测反馈的 bug）。
                    # 首次打开会补最近 20 条历史，那时候不念，免得一开窗就念一串旧话。
                    if self.speak.isChecked() and req_cursor > 0:
                        self._say(text)
            if total >= self._cursor:
                self._cursor = total
            self._turns_seen = total
            if any(t.get("proactive") for t in turns):
                self._tut_proactive = True
            self._tutorial_maybe_fire(total)
            self._feed_err = False

        def fail(e):
            self._poll_busy = False
            if not self._feed_err:
                self._feed_err = True
                self.log.warning("feed 失败：%s", e)

        run_async(lambda: CoreClient().feed(self.session, req_cursor), on_ok=ok, on_err=fail)
        self._poll_notices()

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        if hasattr(self, "nanny_tab"):
            self._place_nanny_tab()

    def _nanny_push(self, text: str, ts: float = 0.0, persist: bool = False) -> None:
        """往右侧保姆栏记一条；persist=True 时同时落盘到内核的 notices.jsonl。"""
        text = str(text or "").strip()
        if not text:
            return
        # 保姆栏只记「事情本身」；历史 logs 里带过旧前缀，顺手剥掉。
        for old in ("保姆程序：", "保姆程序:"):
            if text.startswith(old):
                text = text[len(old):].lstrip()
        self.nanny.add(ts or time.time(), text)
        if persist:
            run_async(lambda: CoreClient(timeout=6).notice_push(text),
                      on_ok=lambda r: None,
                      on_err=lambda e: self.log.info("保姆提醒没落盘：%s", e))

    def _poll_notices(self) -> None:
        """保姆播报：对方主动发言 / 在找您 / 选择沉默 —— 进右边那一栏，不插进聊天。

        例外：模组用 notice.push 且明确要"在聊天里说一句"（kind=chat），
        这句才会落进聊天流——不然她正聊着，模组的提醒会把话头打断。
        """
        def ok(rows):
            for row in rows or []:
                text = str(row.get("text") or "").strip()
                if not text:
                    continue
                ts = float(row.get("ts") or 0) or time.time()
                if str(row.get("kind") or "") == "chat":
                    self.bubble("system", text)
                else:
                    self._nanny_push(text, ts=ts)
                self._notice_cursor = max(self._notice_cursor, ts)
        run_async(lambda: CoreClient().notices(self.session, self._notice_cursor), on_ok=ok,
                  on_err=lambda e: None)

    def showEvent(self, ev):  # noqa: N802
        super().showEvent(ev)
        try:
            self.poll_timer.start(5000)
            self._nanny_tab_timer.start(800)
        except Exception:  # noqa: BLE001
            self.log.debug("启动聊天轮询/保姆页签计时失败", exc_info=True)

    def hideEvent(self, ev):  # noqa: N802
        # 切到别的页就停轮询，别让后台一直拉 feed/notices。
        try:
            self.poll_timer.stop()
            self._nanny_tab_timer.stop()
        except Exception:  # noqa: BLE001
            self.log.debug("停止聊天轮询失败", exc_info=True)
        super().hideEvent(ev)

    def on_show(self) -> None:
        self.input.setFocus()
        try:
            self.poll_timer.start(5000)
            self._nanny_tab_timer.start(800)
        except Exception:  # noqa: BLE001
            self.log.debug("启动聊天轮询/保姆页签计时失败", exc_info=True)
        self.load_presence()
        self.poll(force=True)
        self._maybe_tutorial()
