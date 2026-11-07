"""聊天页右侧保姆栏的行为：记一条、开小屋/本体、收起动画、未读角标。

拆出来是为了让 chat.py 只管聊天流；这些方法依赖 ChatPage 的 nanny 控件。
"""
from __future__ import annotations

import logging
import os

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QVariantAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect

from ...core import config
from .. import fonts

log = logging.getLogger("xiaochen.chat_nanny")


class ChatNannyMixin:
    def _open_nanny_window(self) -> None:
        """点保姆栏标题：打开她自己的小屋（只读日志，独立窗口）。"""
        try:
            from ..dialogs.nanny_window import NannyWindow

            win = getattr(self, "_nanny_window", None)
            if win is not None and win.isVisible():
                win.raise_()
                win.activateWindow()
                win.refresh()
                return
            win = NannyWindow(parent=self.window())
            self._nanny_window = win
            win.show()
            win.raise_()
        except Exception as e:  # noqa: BLE001
            self.log.info("保姆小屋打不开：%s", e)

    def _open_nanny_chat(self) -> None:
        """叫出保姆本体：可对话、只读项目，不写智能体的记忆。"""
        try:
            from ..dialogs.nanny_chat import NannyChatWindow

            win = getattr(self, "_nanny_chat", None)
            if win is not None and win.isVisible():
                win.raise_()
                win.activateWindow()
                return
            win = NannyChatWindow(parent=self.window())
            self._nanny_chat = win
            win.show()
            win.raise_()
        except Exception as e:  # noqa: BLE001
            self.log.info("保姆本体叫不出来：%s", e)

    def _on_nanny_collapsed(self, on: bool) -> None:
        """收起时整列让给聊天区，只留右上角一颗浮层按钮；带 180ms 淡出/淡入。"""
        if os.environ.get("BAB_NO_ANIM"):
            self._apply_nanny_state(on)
            return
        self._stop_nanny_anim()

        effect = QGraphicsOpacityEffect(self.nanny)
        effect.setOpacity(1.0 if on else 0.0)
        self.nanny.setGraphicsEffect(effect)
        fade = QPropertyAnimation(effect, b"opacity", self)
        fade.setDuration(180)
        fade.setStartValue(1.0 if on else 0.0)
        fade.setEndValue(0.0 if on else 1.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)
        self._nanny_fade = fade

        start_r = 18 if on else 58
        end_r = 58 if on else 18
        slide = QVariantAnimation(self)
        slide.setDuration(180)
        slide.setStartValue(start_r)
        slide.setEndValue(end_r)
        slide.setEasingCurve(QEasingCurve.OutCubic)

        def _on_margin(v) -> None:
            self.outer.setContentsMargins(18, 10, int(v), 14)

        slide.valueChanged.connect(_on_margin)
        self._nanny_slide = slide

        if on:
            self.nanny.setVisible(True)
            self._refresh_nanny_tab()
            self._place_nanny_tab()
        else:
            self.nanny.setVisible(True)

        def _done() -> None:
            self._apply_nanny_state(on)
            self.nanny.setGraphicsEffect(None)
            self._nanny_fade = None

        fade.finished.connect(_done)
        fade.start()
        slide.start()

    def _stop_nanny_anim(self) -> None:
        for name in ("_nanny_fade", "_nanny_slide"):
            anim = getattr(self, name, None)
            if anim is not None:
                try:
                    anim.stop()
                except Exception:  # noqa: BLE001
                    log.debug("停止保姆栏动画失败", exc_info=True)
                setattr(self, name, None)

    def _apply_nanny_state(self, on: bool) -> None:
        if on:
            self.nanny.setFixedWidth(0)
            self.nanny.setVisible(False)
            self.outer.setContentsMargins(18, 10, 58, 14)
            self.nanny_tab.show()
            self._refresh_nanny_tab()
            self._place_nanny_tab()
            self.nanny_tab.raise_()
        else:
            self.outer.setContentsMargins(18, 10, 18, 14)
            self.nanny.setVisible(True)
            self.nanny_tab.hide()

    def _refresh_nanny_tab(self) -> None:
        n = self.nanny.unread() if hasattr(self, "nanny") else 0
        self.nanny_tab.setText(f"保{n}" if n else "保")
        self.nanny_tab.setFixedSize(fonts.ui_px(38 if n < 10 else 46), fonts.ui_px(32))
        if self.nanny.is_collapsed():
            self._place_nanny_tab()

    def _place_nanny_tab(self) -> None:
        x = max(8, self.stage.width() - self.nanny_tab.width() - 8)
        self.nanny_tab.move(x, 10)
    def _remember_nanny_state(self) -> None:
        """收起/展开记进配置，下次打开还是这样子。"""
        try:
            cfg = config.load(force=True)
            cfg.setdefault("ui", {})["nanny_collapsed"] = bool(self.nanny.is_collapsed())
            config.save(cfg)
        except Exception as e:  # noqa: BLE001
            self.log.info("没记住保姆栏的状态：%s", e)
