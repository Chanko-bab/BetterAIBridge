"""主窗口：无边框 + 自绘标题栏 + 左侧导航 + 右侧页面栈 + 托盘。

关闭不退出：收进托盘，并把「您的状态」设成忙。
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from pathlib import Path
from typing import Dict

from PySide6.QtCore import (QEasingCurve, QEvent, QProcess, QPropertyAnimation,
                            QRect, QSize, Qt, QTimer)
from PySide6.QtGui import QAction, QColor, QCursor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
    QMainWindow, QMenu, QPushButton, QSizeGrip,
    QStackedLayout, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from ..core import config, framework_setup, logger
from ..core.events import bus
from ..services import probe, update
from ..services.core_client import CoreClient, CoreUnavailable
from ..services.worker import run_async
from . import fonts
from .backdrop import Backdrop
from .dialogs.avatar_dialog import AvatarDialog
from .widgets.avatar_card import AvatarCard
from .widgets.titlebar import TitleBar

NAV = [
    ("chat", "聊天"),
    ("mods", "模组"),
    ("services", "服务"),
    ("settings", "设置"),
]

# 放在最下面、紧挨「就绪」的那一条
NAV_BOTTOM = [("appearance", "外观"), ("logs", "日志")]


def asset(name: str) -> Path:
    return Path(__file__).resolve().parents[2] / "assets" / name


def make_icon() -> QIcon:
    """优先用 assets 里的白鲸图标，读不到再退回手绘。"""
    ico = asset("bab.ico")
    if ico.exists():
        icon = QIcon(str(ico))
        if not icon.isNull():
            return icon
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#3f7ce8"))
    p.setPen(Qt.NoPen)
    p.drawEllipse(2, 2, 60, 60)
    p.setBrush(QColor("#ffffff"))
    p.drawEllipse(22, 26, 8, 8)
    p.drawEllipse(38, 26, 8, 8)
    p.end()
    return QIcon(pm)


log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        from ..core import perf
        perf.mark("ui.window.init")
        self.log = logger.get()
        self.name = framework_setup.display_name()
        self.setWindowTitle(self.name)
        self.resize(1180, 780)
        self._restore_window_size()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setMinimumSize(QSize(980, 640))
        self.setWindowIcon(make_icon())
        self._tray_hint_shown = False
        self._quitting = False
        # 内核看门狗：连续几次探测不到才拉，别把抖动当故障
        self._core_down = 0
        self._last_core_restart = 0.0
        self._core_proc: QProcess | None = None
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        root = QFrame(objectName="Root")
        self.setCentralWidget(root)
        self._root = root
        self.root_lay = QStackedLayout(root)
        self.root_lay.setContentsMargins(0, 0, 0, 0)
        self.root_lay.setStackingMode(QStackedLayout.StackAll)
        self.backdrop = Backdrop(root)
        content = QWidget(objectName="RootContent")
        self._content = content
        outer = QVBoxLayout(content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---------- 自绘标题栏 ----------
        self.titlebar = TitleBar("Better AI Bridge Launcher", self)
        self.titlebar.minimize_clicked.connect(self.showMinimized)
        self.titlebar.close_clicked.connect(self.hide_to_tray)
        outer.addWidget(self.titlebar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # ---------- 左侧导航 ----------
        side = QFrame(objectName="Sidebar")
        side.setFixedWidth(fonts.ui_px(196))
        side_lay = QVBoxLayout(side)
        side_lay.setContentsMargins(0, 8, 0, 10)
        side_lay.setSpacing(0)
        self.avatar_card = AvatarCard(self.name, 96)
        self.avatar_card.clicked.connect(self.open_avatar_dialog)
        head = QHBoxLayout()
        head.setContentsMargins(12, 16, 12, 10)
        head.addWidget(self.avatar_card)
        side_lay.addLayout(head)

        self.buttons: Dict[str, QPushButton] = {}
        for key, title in NAV:
            btn = QPushButton(title, objectName="Nav")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self.show_page(k))
            side_lay.addWidget(btn)
            self.buttons[key] = btn
        side_lay.addStretch(1)
        for key, title in NAV_BOTTOM:
            btn = QPushButton(title, objectName="Nav")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, k=key: self.show_page(k))
            self.buttons[key] = btn
            side_lay.addWidget(btn)
        # 侧栏按钮按视觉顺序走 Tab，别让焦点乱跳。
        nav_order = [self.buttons[k] for k, _t in (NAV + NAV_BOTTOM) if k in self.buttons]
        for a, b in zip(nav_order, nav_order[1:]):
            QWidget.setTabOrder(a, b)
        self._nav_last = nav_order[-1] if nav_order else None

        # 「就绪」放在操作台最下面，上面单独一行版本号
        self.version_label = QLabel(update.version() or "版本未知", objectName="Muted")
        self.version_label.setContentsMargins(16, 4, 10, 0)
        self.version_label.setToolTip("当前启动器版本")
        side_lay.addWidget(self.version_label)
        self.foot_label = QLabel("就绪", objectName="Muted")
        self.foot_label.setContentsMargins(16, 0, 10, 8)
        side_lay.addWidget(self.foot_label)

        body.addWidget(side)

        # ---------- 右侧页面 ----------
        # 背景铺在整个窗口下面（含标题栏与操作台）；页面自己保持透明
        self.stack = QStackedWidget(objectName="PageStack")
        self.stack.setAttribute(Qt.WA_TranslucentBackground, True)
        # 页面按需构造：先只建聊天，其余第一次打开再建。
        # 设置页一个就有 349 个控件，全量预建是启动慢和内存高的主因。
        self._page_specs = {
            "chat": ("chat", "ChatPage"),
            "mods": ("mods", "ModsPage"),
            "services": ("services", "ServicesPage"),
            "appearance": ("appearance", "AppearancePage"),
            "logs": ("logs", "LogsPage"),
            "settings": ("settings", "SettingsPage"),
            "details": ("details", "DetailsPage"),
        }
        self.pages: Dict[str, QWidget] = {}
        self._ensure_page("chat")

        body.addWidget(self.stack, 1)
        outer.addLayout(body, 1)
        self.root_lay.addWidget(self.backdrop)
        self.root_lay.addWidget(content)
        self.root_lay.setCurrentWidget(content)
        self.main_stage = content  # 旧测试/旧代码里的名字，保留指向内容层

        # 前置模组改文件：由 sense_server 直接调用 pre_bridge，不再逐次弹窗
        self.reload_background()

        # 无边框窗口的右下角拖拽柄；没有底栏了，聊天背景可以一直铺到窗口底
        self.grip = QSizeGrip(self)
        self.grip.setFixedSize(16, 16)
        self.grip.raise_()

        # ---------- 托盘 ----------
        self.tray = QSystemTrayIcon(make_icon(), self)
        self.tray.setToolTip(self.name)
        menu = QMenu(self)
        act_open = QAction(f"打开{self.name}", self)
        act_open.triggered.connect(self.show_from_tray)
        self.act_open = act_open
        act_online = QAction("强制在线", self)
        act_online.setToolTip("不管窗口开着还是关着，都把您的状态改成「在线」——她才知道现在可以自然找你。")
        act_online.triggered.connect(lambda: self._set_presence("online"))
        act_quit = QAction("退出程序", self)
        act_quit.triggered.connect(self.quit_app)
        menu.addAction(act_open)
        menu.addAction(act_online)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        self.show_page(str(config.get("ui.start_page", "chat")))
        if self.stack.currentWidget() is not self.pages.get("chat"):
            self.show_page("chat")

        # ---------- 定时器 ----------
        self._state_busy = False
        self._ports_busy = False
        self.timer_ports = QTimer(self)
        self.timer_ports.timeout.connect(self.refresh_ports)
        self.timer_ports.start(int(config.get("ui.refresh_ports_ms", 5000)))

        self.timer_state = QTimer(self)
        self.timer_state.timeout.connect(self.refresh_state)
        self.timer_state.start(int(config.get("ui.refresh_state_ms", 5000)))

        # 收进托盘后，只拉「她最近主动说了什么」，用托盘小窗提示。
        self._tray_seen = 0.0
        self.timer_tray = QTimer(self)
        self.timer_tray.setInterval(20_000)
        self.timer_tray.timeout.connect(self._poll_proactive)

        # ---------- 耳目（看 / 听，启动器本体） ----------
        self._sense_busy = False
        self._sense_next_eye = 0.0
        self._sense_next_ear = 0.0
        if not os.environ.get("BAB_NO_AUTORESTART"):
            try:
                from ..services import sense_server

                threading.Thread(target=sense_server.start, name="sense-start", daemon=True).start()
            except Exception as exc:  # noqa: BLE001
                log.warning("耳目小服务没起来：%s", exc)
            self.timer_sense = QTimer(self)
            self.timer_sense.timeout.connect(self._sense_tick)
            self.timer_sense.start(60_000)

            # 界面桥：把鼠标位置喂给小门，并盯着模组改过的背景配置
            self._ui_rev = 0
            self.timer_bridge = QTimer(self)
            self.timer_bridge.timeout.connect(self._bridge_tick)
            self.timer_bridge.start(250)

        bus.ports_changed.connect(self.on_ports)
        bus.state_changed.connect(self.on_state)

        self.refresh_ports()
        self.refresh_state()
        perf.mark("ui.window.built")

        # 窗口一开就算「在线」：她才知道现在可以自然找你
        QTimer.singleShot(700, self._on_started)

    # ---------- 导航 ----------
    def refresh_identity(self) -> None:
        """名字变了（导入档案 / 改设置）就同步任务栏和侧栏头像卡。

        标题栏固定写 Better AI Bridge Launcher，不跟占位符走；
        任务栏/托盘/侧栏才用她的名字。
        """
        try:
            name = framework_setup.display_name()
        except Exception:  # noqa: BLE001
            name = self.name
        if name:
            self.name = name
            self.setWindowTitle(name)
            try:
                self.tray.setToolTip(name)
                self.act_open.setText(f"打开{name}")
            except Exception:  # noqa: BLE001
                self.log.debug("更新托盘文案失败", exc_info=True)
        try:
            self.avatar_card.refresh(self.name)
        except Exception:  # noqa: BLE001
            self.log.warning("刷新头像卡失败", exc_info=True)

    def open_avatar_dialog(self) -> None:
        try:
            dlg = AvatarDialog(self)
            dlg.changed.connect(self.refresh_identity)
            dlg.exec()
        finally:
            self.refresh_identity()

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        try:
            self.timer_tray.stop()
        except Exception:  # noqa: BLE001
            self.log.debug("显示时停止托盘轮询失败", exc_info=True)
        if not getattr(self, "_perf_shown", False):
            from ..core import perf
            perf.mark("window.shown")
            self._perf_shown = True
        self.refresh_identity()
        try:
            if hasattr(self, "timer_ports") and not self.timer_ports.isActive():
                self.timer_ports.start(int(config.get("ui.refresh_ports_ms", 5000)))
            if hasattr(self, "timer_state") and not self.timer_state.isActive():
                self.timer_state.start(int(config.get("ui.refresh_state_ms", 5000)))
            if hasattr(self, "timer_bridge") and not self.timer_bridge.isActive():
                self.timer_bridge.start(250)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("恢复定时器失败：%s", exc)
        if not self._state_busy:
            self.refresh_state()
        if not self._ports_busy:
            self.refresh_ports()

    def changeEvent(self, e) -> None:  # noqa: N802
        super().changeEvent(e)
        if e.type() != QEvent.WindowStateChange:
            return
        try:
            if self.isMinimized():
                self.timer_tray.start()
            elif self.isVisible():
                self.timer_tray.stop()
        except Exception:  # noqa: BLE001
            self.log.debug("切换最小化时更新托盘轮询失败", exc_info=True)

    def hideEvent(self, e) -> None:  # noqa: N802
        # 收进托盘后，界面不可见就不该继续轮询；只留耳目和内存里的桥。
        for name in ("timer_ports", "timer_state", "timer_bridge", "timer_tray"):
            t = getattr(self, name, None)
            if t is not None:
                try:
                    t.stop()
                except Exception:  # noqa: BLE001
                    self.log.debug("隐藏时停止 %s 失败", name, exc_info=True)
        super().hideEvent(e)

    def reload_background(self) -> None:
        """外观页改了背景就调这里：所有页面共用一层背景，左侧操作台不铺。"""
        try:
            from . import backdrop
            self.backdrop.set_config(backdrop.cfg())
        except Exception as e:  # noqa: BLE001
            log.info("背景没刷新：%s", e)

    def _ensure_page(self, key: str) -> QWidget | None:
        page = self.pages.get(key)
        if page is not None:
            return page
        spec = self._page_specs.get(key)
        if spec is None:
            return None
        mod_name, cls_name = spec
        module = importlib.import_module(f".pages.{mod_name}", __package__)
        page = getattr(module, cls_name)(self)
        self.pages[key] = page
        self.stack.addWidget(page)
        if key == "appearance":
            page.changed.connect(self.reload_background)
        if key == "settings":
            page.open_details.connect(lambda: self.show_page("details"))
        from ..core import perf
        perf.mark(f"page.{key}")
        return page

    def show_page(self, key: str) -> None:
        if key not in self._page_specs:
            return
        if self._ensure_page(key) is None:
            return
        for k, btn in self.buttons.items():
            btn.setChecked(k == key)
        self.stack.setCurrentWidget(self.pages[key])
        self._fade_in(self.pages[key])
        page = self.pages[key]
        if key == "chat" and self._nav_last is not None:
            def _wire_tab(p=page) -> None:
                try:
                    QWidget.setTabOrder(self._nav_last, p.input)
                    QWidget.setTabOrder(p.input, p.btn_send)
                    QWidget.setTabOrder(p.btn_send, p.nanny.btn_toggle)
                except Exception:  # noqa: BLE001
                    self.log.debug("设置聊天页 Tab 顺序失败", exc_info=True)
            QTimer.singleShot(0, _wire_tab)
        if hasattr(page, "on_show"):
            try:
                page.on_show()
            except Exception as e:  # noqa: BLE001
                self.log.warning("页面 %s 刷新失败：%s", key, e)

    # ---------- 窗口大小 / 页面过渡 ----------
    def _restore_window_size(self) -> None:
        """退出时记下的窗口大小/位置，下次原样回来；坏值就退回默认。"""
        try:
            size = config.get("ui.window_size") or []
            if not isinstance(size, (list, tuple)) or len(size) != 2:
                return
            w, h = int(size[0]), int(size[1])
            scr = QApplication.primaryScreen()
            if scr is not None:
                area = scr.availableGeometry()
                w = min(w, area.width())
                h = min(h, area.height())
            self.resize(max(980, w), max(640, h))
            self._restore_window_pos()
        except Exception as e:  # noqa: BLE001
            self.log.warning("窗口大小没读回来：%s", e)

    def _restore_window_pos(self) -> None:
        """位置只在仍落在某块屏幕的可见区时才恢复，否则居中。"""
        try:
            pos = config.get("ui.window_pos") or []
            if isinstance(pos, (list, tuple)) and len(pos) == 2:
                x, y = int(pos[0]), int(pos[1])
                want = QRect(x, y, self.width(), self.height())
                for scr in QApplication.screens():
                    area = scr.availableGeometry()
                    hit = want.intersected(area)
                    if hit.width() >= 160 and hit.height() >= 80:
                        self.move(x, y)
                        return
            scr = QApplication.primaryScreen()
            if scr is not None:
                area = scr.availableGeometry()
                self.move(
                    area.x() + max(0, (area.width() - self.width()) // 2),
                    area.y() + max(0, (area.height() - self.height()) // 2),
                )
        except Exception as e:  # noqa: BLE001
            self.log.warning("窗口位置没读回来：%s", e)

    def _save_window_size(self) -> None:
        if os.environ.get("XIAOCHEN_SMOKE") or os.environ.get("BAB_NO_PERSIST"):
            return
        try:
            if self.isMinimized():
                return
            geo = self.normalGeometry() if self.isMaximized() else self.geometry()
            w, h = int(geo.width()), int(geo.height())
            if w < 980 or h < 640:
                return
            if list(config.get("ui.window_size") or []) != [w, h]:
                config.set_value("ui.window_size", [w, h])
            pos = [int(geo.x()), int(geo.y())]
            if list(config.get("ui.window_pos") or []) != pos:
                config.set_value("ui.window_pos", pos)
        except Exception as e:  # noqa: BLE001
            self.log.warning("窗口大小没存上：%s", e)

    def _fade_in(self, page: QWidget) -> None:
        """切页时新页面淡入；测试/隐藏状态直接跳过，别拖慢断言。"""
        if os.environ.get("BAB_NO_ANIM") or not self.isVisible():
            return
        try:
            effect = QGraphicsOpacityEffect(page)
            page.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"opacity", self)
            anim.setDuration(240)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)

            def done() -> None:
                try:
                    page.setGraphicsEffect(None)
                except Exception:  # noqa: BLE001
                    self.log.debug("清理淡入特效失败", exc_info=True)

            anim.finished.connect(done)
            self._fade_anim = anim
            anim.start()
        except Exception as e:  # noqa: BLE001
            self.log.warning("页面淡入没做成：%s", e)

    # ---------- 状态 ----------
    def _on_started(self) -> None:
        chat = self.pages.get("chat")
        if chat is not None and hasattr(chat, "load_presence"):
            chat.load_presence()

    def _set_presence(self, state: str) -> None:
        def ok(_r) -> None:
            self.log.info("presence -> %s", state)
            # 托盘菜单里改的状态，页面上那颗小圆点要跟着变，否则用户以为没生效
            chat = self.pages.get("chat")
            if chat is not None and hasattr(chat, "load_presence"):
                chat.load_presence()

        run_async(lambda: CoreClient().set_presence(state), on_ok=ok,
                  on_err=lambda e: self.log.warning("presence 设置失败：%s", e))

    def _poll_proactive(self) -> None:
        def ok(data) -> None:
            data = data if isinstance(data, dict) else {}
            ts = float(data.get("ts") or 0)
            text = str(data.get("text") or "").strip()
            if ts <= self._tray_seen or not text:
                return
            self._tray_seen = ts
            try:
                self.tray.showMessage(self.name, text[:120],
                                      QSystemTrayIcon.Information, 6000)
            except Exception:  # noqa: BLE001
                self.log.debug("托盘主动消息弹窗失败", exc_info=True)

        run_async(lambda: CoreClient().proactive_last(), on_ok=ok,
                  on_err=lambda _e: None)

    def _tray_usable(self) -> bool:
        try:
            return QSystemTrayIcon.isSystemTrayAvailable() and self.tray.isVisible()
        except Exception:  # noqa: BLE001
            return False

    def hide_to_tray(self) -> None:
        if not self._tray_usable():
            # 托盘不可用时不能 hide，否则没有入口能把它叫回来
            self.log.warning("托盘不可用，改为最小化")
            self._set_presence("busy")
            self.showMinimized()
            return
        self._set_presence("busy")
        self.hide()
        try:
            self.timer_tray.start()
            QTimer.singleShot(1500, self._poll_proactive)
        except Exception:  # noqa: BLE001
            self.log.warning("托盘轮询启动失败，后台主动消息不会弹", exc_info=True)
        if not self._tray_hint_shown:
            self._tray_hint_shown = True
            try:
                self.tray.showMessage(f"{self.name}还在后台", "状态已切成「忙」，点托盘图标能叫我回来。",
                                      QSystemTrayIcon.Information, 4000)
            except Exception:  # noqa: BLE001
                self.log.debug("托盘提示弹窗失败", exc_info=True)

    def show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        page = self.pages.get("chat")
        if page is not None and hasattr(page, "load_presence"):
            page.load_presence()
        self.show_page("chat")

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_from_tray()

    def quit_app(self) -> None:
        self._quitting = True
        try:
            self.tray.hide()
        except Exception:  # noqa: BLE001
            self.log.debug("退出时隐藏托盘图标失败", exc_info=True)
        self._save_window_size()
        for name in ("timer_ports", "timer_state", "timer_bridge", "timer_tray"):
            t = getattr(self, name, None)
            if t is not None:
                try:
                    t.stop()
                except Exception:  # noqa: BLE001
                    self.log.debug("退出时停止 %s 失败", name, exc_info=True)
        # 退出前同步发一次离开状态：原来的异步请求会被 400ms 后的 quit 截断。
        try:
            CoreClient(timeout=1.2).set_presence("away")
        except Exception:  # noqa: BLE001
            self.log.warning("退出前发送离开状态失败", exc_info=True)
        # 本地 MOSS 是 Popen 子进程，不主动收会一直占 18084 和内存。
        try:
            from ..core import local_tts

            local_tts.stop()
        except Exception:  # noqa: BLE001
            self.log.warning("退出时停止本地语音失败", exc_info=True)
        try:
            from ..services import sense_server

            sense_server.stop()
        except Exception:  # noqa: BLE001
            self.log.warning("退出时停止耳目小门失败", exc_info=True)
        QTimer.singleShot(150, self.close)
        QTimer.singleShot(400, lambda: __import__("PySide6.QtWidgets", fromlist=["QApplication"]).QApplication.quit())

    def closeEvent(self, e) -> None:  # noqa: N802
        # 点 × 只收进托盘；真正退出走托盘菜单
        if self._quitting:
            e.accept()
            return
        if self._tray_usable():
            e.ignore()
            self.hide_to_tray()
        else:
            # 没有托盘时 hide 等于把窗口弄丢；最小化到任务栏，至少能点回来
            e.ignore()
            self.log.warning("托盘不可用，关闭改为最小化")
            self._set_presence("busy")
            self.showMinimized()

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        try:
            self.grip.move(self.width() - 22, self.height() - 22)
        except Exception:  # noqa: BLE001
            self.log.debug("移动缩放手柄失败", exc_info=True)
        try:
            from PySide6.QtGui import QPainterPath, QRegion

            path = QPainterPath()
            path.addRoundedRect(self.rect().adjusted(0, 0, 0, -1), 14.0, 14.0)
            self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        except Exception:  # noqa: BLE001
            self.log.debug("设置圆角窗口遮罩失败", exc_info=True)

    # ---------- 界面桥 ----------
    def _bridge_tick(self) -> None:
        try:
            from ..services import sense_server

            g = self.mapFromGlobal(QCursor.pos())
            inside = self.rect().contains(g)
            sense_server.set_mouse(g.x() if inside else 0, g.y() if inside else 0, inside)
            rev = sense_server.ui_rev()
            if rev != self._ui_rev:
                self._ui_rev = rev
                self.reload_background()
        except Exception:  # noqa: BLE001
            self.log.debug("界面桥 tick 失败", exc_info=True)

    # ---------- 耳目 ----------
    def _sense_tick(self) -> None:
        """一分钟看一次表；真要看/听就丢后台线程，别卡界面。"""
        if self._sense_busy:
            return
        self._sense_busy = True
        threading.Thread(target=self._sense_run, name="sense-tick", daemon=True).start()

    def _sense_run(self) -> None:
        try:
            from ..services import sense

            c = sense.cfg()
            if not (c.get("eyes") or c.get("ears")):
                self._sense_next_eye = self._sense_next_ear = 0.0
                return
            # “一直看着/一直听着”由内核按自己的间隔采样；这里再偷看会重复抓拍，所以直接让路。
            if c.get("watch") or c.get("listen_always"):
                self._sense_next_eye = self._sense_next_ear = 0.0
                return
            lv = sense.level()
            if lv <= 0:
                self._sense_next_eye = self._sense_next_ear = 0.0
                return
            now = time.time()
            if self._sense_next_eye <= 0:
                self._sense_next_eye = now + sense.next_gap(lv)
            if self._sense_next_ear <= 0:
                self._sense_next_ear = now + sense.next_gap(lv)
            try:
                st = str((CoreClient(timeout=4).presence() or {}).get("state") or "")
            except Exception:  # noqa: BLE001
                st = ""
            if st != "online":
                return
            if c.get("eyes") and now >= self._sense_next_eye:
                self._sense_next_eye = now + sense.next_gap(lv)
                res = sense.look(quiet=False)
                sense.tell(f"（你刚才偷偷看了一眼{res.get('what') or ''}："
                           f"{str(res.get('text') or '')[:600]}）")
            elif c.get("ears") and now >= self._sense_next_ear:
                self._sense_next_ear = now + sense.next_gap(lv)
                res = sense.listen(6.0, quiet=False)
                text = str(res.get("text") or "").strip()
                if text:
                    sense.tell(f"（你刚才偷偷听了一下，听到：{text[:600]}）")
        except Exception as exc:  # noqa: BLE001
            log.warning("耳目 tick 失败：%s", exc)
        finally:
            self._sense_busy = False

    # ---------- 轮询 ----------
    def refresh_ports(self) -> None:
        if self._ports_busy:
            return
        self._ports_busy = True

        def done(info):
            self._ports_busy = False
            bus.ports_changed.emit(info)

        def failed(e):
            self._ports_busy = False
            self.log.warning("端口探测失败：%s", e)

        run_async(probe.summary, on_ok=done, on_err=failed)

    def refresh_state(self) -> None:
        if self._state_busy:
            return
        self._state_busy = True

        def work() -> Dict[str, object]:
            c = CoreClient()
            out: Dict[str, object] = {"ok": False}
            try:
                out["health"] = c.health()
                out["state"] = c.state()
                out["brain"] = c.brain_state()
                out["drives"] = c.drives()
                out["stomach"] = c.stomach()
                try:
                    out["emotions"] = c.emotions()
                except Exception:  # 老内核没有这个接口也不该拖垮整页
                    out["emotions"] = {}
                out["ok"] = True
            except CoreUnavailable as e:
                out["error"] = str(e)
            return out

        def done(info):
            self._state_busy = False
            bus.state_changed.emit(info)

        def failed(e):
            self._state_busy = False
            self.log.warning("状态读取失败：%s", e)

        run_async(work, on_ok=done, on_err=failed)

    # ---------- 事件 ----------
    def on_ports(self, info: dict) -> None:
        def mark(label: QLabel, up: bool, name: str) -> None:
            label.setText(f"{name} {'●' if up else '○'}")
            label.setObjectName("DotUp" if up else "DotDown")
            label.style().unpolish(label)
            label.style().polish(label)

        details = self.pages.get("details")
        if details is not None and hasattr(details, "set_gates"):
            try:
                details.set_gates(info.get("ports") or {})
            except Exception as e:  # noqa: BLE001
                self.log.warning("门状态渲染失败：%s", e)
        self.foot_label.setText("就绪")
        self._watch_core(bool((info.get("ports") or {}).get("core")))

    def _watch_core(self, up: bool) -> None:
        """内核连续 3 次探测不到（约 9 秒）才拉起，120 秒内不重复拉。

        测试（离屏跑页面）和冒烟模式一律不自动拉起：否则测试期间会真的去
        `start_core.cmd` 起一个内核，把用例拖死。
        """
        if os.environ.get("BAB_NO_AUTORESTART") == "1" or os.environ.get("XIAOCHEN_SMOKE") == "1":
            self._core_down = 0
            return
        if not bool(config.get("core.auto_restart", True)):
            self._core_down = 0
            return
        if up:
            self._core_down = 0
            return
        self._core_down += 1
        if self._core_down < 3:
            return
        now = time.time()
        if now - self._last_core_restart < 120:
            return
        if self._core_proc is not None and self._core_proc.state() != QProcess.NotRunning:
            return
        target = str(config.get("start_core", ""))
        if not target or not Path(target).exists():
            self.log.warning("内核不在，但启动脚本不存在：%s", target)
            return
        self._last_core_restart = now
        self._core_down = 0
        self.log.warning("内核不在，自动拉起：%s", target)
        self.foot_label.setText("内核不在，正在自动拉起…")
        p = QProcess(self)
        p.setProgram("cmd.exe")
        p.setArguments(["/c", target])
        p.finished.connect(self._core_proc_done)
        p.start()
        self._core_proc = p

    def _core_proc_done(self, *_args) -> None:
        self._core_proc = None

    def on_state(self, info: dict) -> None:
        details = self.pages.get("details")
        if details is not None and hasattr(details, "apply_state"):
            try:
                details.apply_state(info)
            except Exception as e:  # noqa: BLE001
                self.log.warning("详情页渲染失败：%s", e)
