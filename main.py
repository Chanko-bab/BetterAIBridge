"""BetterAIBridge —— 入口。

跑法：
    .venv\\Scripts\\python.exe main.py
调试：
    set QT_QPA_PLATFORM=offscreen   （不弹窗口，用于冒烟）
    set BAB_NO_GUI=1                （失败时不弹 MessageBox，只写日志）
"""

from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
from pathlib import Path

# 允许 `python main.py` 直接跑（把项目根加进 sys.path）
ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("bab.launcher")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def report_fatal(title: str, detail: str) -> None:
    """不依赖 Qt / PyYAML 的失败上报：写 logs\\startup-error.log + 原生 MessageBoxW。

    必须先能看见错误，再谈修错误——pythonw 没有控制台，静默退出等于让用户猜。
    """
    try:
        log_dir = ROOT / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with (log_dir / "startup-error.log").open("a", encoding="utf-8") as fh:
            fh.write(f"\n===== {stamp} {title} =====\n{detail}\n{traceback.format_exc()}\n")
    except Exception:
        LOG.debug("无法写入 startup-error.log", exc_info=True)
    try:
        import os

        if os.environ.get("BAB_NO_GUI") == "1":
            return
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, detail, "BetterAIBridge", 0x10)
    except Exception:
        LOG.debug("无法弹出启动错误对话框", exc_info=True)


# ---- 依赖检查必须早于任何 Qt/app 导入，且失败时不能静默 ----
try:
    from PySide6.QtCore import QLockFile, QTimer, Qt  # noqa: E402
    from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
except Exception as exc:  # noqa: BLE001
    report_fatal(
        "缺少运行依赖",
        "这个程序还缺依赖，没法启动。\n\n"
        "请在程序目录里双击 setup.cmd，等它跑完（要下载约 400MB）。\n"
        "装完再双击桌面快捷方式。\n\n"
        f"（技术细节：{exc}）",
    )
    raise SystemExit(1)

try:
    from app.core import config, logger, perf  # noqa: E402

    perf.mark("main.import")
except Exception as exc:  # noqa: BLE001
    report_fatal(
        "缺少运行依赖",
        "依赖没有装全（缺 PyYAML 或程序文件不完整）。\n\n"
        "请在程序目录里双击 setup.cmd 重新安装。\n\n"
        f"（技术细节：{exc}）",
    )
    raise SystemExit(1)


def load_theme(app: QApplication) -> None:
    try:
        from app.ui import fonts

        fonts.apply(app)
    except Exception:  # noqa: BLE001
        LOG.warning("主题字体加载失败，继续用默认字体", exc_info=True)


def os_env_smoke() -> bool:
    import os

    return os.environ.get("XIAOCHEN_SMOKE") == "1"


def _set_app_id() -> None:
    """让任务栏认这是一个独立程序（否则显示 python / pythonw 的图标）。"""
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BetterAIBridge.Launcher")
    except Exception:
        LOG.debug("设置 AppUserModelID 失败", exc_info=True)


def main() -> int:
    _set_app_id()
    log = logger.setup()
    app = QApplication(sys.argv)
    perf.mark("qt.app")
    try:
        from PySide6.QtGui import QIcon

        ico = ROOT / "assets" / "bab.ico"
        if ico.exists():
            app.setWindowIcon(QIcon(str(ico)))
    except Exception:
        LOG.debug("设置窗口图标失败", exc_info=True)
    app.setApplicationName("BetterAIBridge")
    # 关窗只是收进托盘，不能因为最后一个窗口隐藏就退出
    app.setQuitOnLastWindowClosed(False)
    try:
        from app.ui.dialog_bg import install as install_dialog_bg

        install_dialog_bg(app)
    except Exception:  # noqa: BLE001
        LOG.warning("对话框背景安装失败，继续用默认背景", exc_info=True)

    def _stop_local_tts() -> None:
        try:
            from app.core import local_tts

            local_tts.stop()
        except Exception:  # noqa: BLE001
            LOG.warning("退出时停止本地语音失败", exc_info=True)

    # 不管从哪个出口退出，都别把本地语音子进程留在后台。
    app.aboutToQuit.connect(_stop_local_tts)
    load_theme(app)
    perf.mark("ui.theme")

    # 0.6.4：旧稳定入口 BetterAIBridge.lnk 改名一次（自动更新不跑安装器）。
    try:
        from app.services.shortcut import migrate_old_shortcut

        migrate_old_shortcut()
    except Exception:  # noqa: BLE001
        LOG.warning("快捷方式改名失败（不影响启动）", exc_info=True)

    # 单实例：锁文件放在程序目录，进程退出自动释放；残留锁 30 秒后视为过期
    lock_path = config.DATA_DIR / "launcher.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(30_000)
    if not lock.tryLock(100):
        if not os_env_smoke():
            QMessageBox.information(None, "BetterAIBridge", "已经有一个窗口在跑了。")
        return 0

    # 改过名的模组（0.4.0：m -> m_framework）：先迁 registry 和安装目录，再建界面
    try:
        from app.core import pbab as _pbab

        _migrated = _pbab.migrate_legacy_ids()
        if _migrated:
            log.info("启动时迁移旧模组 id：%s", "、".join(_migrated))
        _gone = _pbab.prune_missing()
        if _gone:
            log.info("启动时清理失效模组记录：%s", "、".join(_gone))
    except Exception:  # noqa: BLE001
        log.warning("模组 id 迁移失败（不影响启动）", exc_info=True)

    from app.core import framework_setup

    first_run = (not os_env_smoke()) and (not framework_setup.is_configured())
    splash = None
    if not first_run and not os_env_smoke():
        try:
            from app.ui.splash import Splash

            splash = Splash()
            splash.start()
            app.processEvents()
        except Exception:  # noqa: BLE001
            splash = None
            log.warning("启动动画没弹出来（不影响启动）", exc_info=True)

    # 首次启动：先建档，建档成功后才建主界面。主窗口、七个页面都不提前构造。
    if first_run:
        log.info("首次启动：先建档，界面暂不显示")
        perf.mark("onboarding.begin")
        try:
            from app.ui.dialogs.onboarding import OnboardingWizard

            dlg = OnboardingWizard(None)
            saved = bool(dlg.exec()) and bool(dlg.saved)
        except Exception as exc:  # noqa: BLE001
            detail = traceback.format_exc()
            log.error("首次建档失败：\n%s", detail)
            QMessageBox.critical(
                None,
                "建档失败",
                "第一次运行的建档没成功，所以程序没有启动。\n\n"
                f"原因：{exc}\n\n"
                "常见原因：程序目录里的 config\\app.yaml 指向了不存在的路径。\n"
                f"当前配置指向：{framework_setup.project()}\n\n"
                "详细错误已写到 logs\\startup-error.log。",
            )
            lock.unlock()
            return 1
        if not saved:
            log.info("建档未完成，退出（不显示主界面）")
            QMessageBox.information(
                None, "BetterAIBridge", "没有完成建档，程序不会启动。下次打开会重新引导你。"
            )
            lock.unlock()
            return 0
        log.info("首次建档已写入")
        perf.mark("onboarding.end")

    perf.mark("main.ready")
    try:
        from app.ui.main_window import MainWindow  # 首次建档时不白建整个窗口

        win = MainWindow()
        app.setWindowIcon(win.windowIcon())
    except Exception:
        detail = traceback.format_exc()
        log.error("窗口启动失败：\n%s", detail)
        report_fatal("程序启动失败", "窗口没能建起来，详见程序目录 logs\\app.log。\n\n" + detail[-1200:])
        lock.unlock()
        return 1

    perf.mark("ui.window.show")
    win.show()
    if splash is not None:
        splash.finish()
    win.show_page("chat")
    perf.mark("ui.first_page")
    chat = win.pages.get("chat")
    if chat is not None and hasattr(chat, "refresh_setup"):
        chat.refresh_setup()
    log.info("窗口已显示")
    log.info("启动耗时：%s", perf.summary())

    # 已启用的模组随启动拉起：前置模组先跑完，普通模组再跑（不挡界面）
    if not os_env_smoke():
        def _start_modules() -> None:
            try:
                from app.core import pbab

                rows = pbab.start_enabled()
                log.info("启动模组：%s", rows)
            except Exception:  # noqa: BLE001
                log.warning("启动已启用模组失败（不影响主界面）", exc_info=True)

        threading.Thread(target=_start_modules, name="bab-mod-start", daemon=True).start()

        # 上次选的是本地 MOSS 时，后台把 sidecar 拉起来；没装/没选就不占内存
        def _start_local_tts() -> None:
            try:
                import json

                from app.core import config as app_config
                from app.core import local_tts

                doc = json.loads((app_config.APP_DIR / "WiseEntity" / "entity" / "config" / "tts.json")
                                 .read_text(encoding="utf-8-sig"))
                if str(doc.get("engine") or "") != "local" and str(doc.get("preview_engine") or "") != "local":
                    return
                if local_tts.is_ready():
                    local_tts.start()
                    log.info("本地语音服务已启动")
            except Exception:  # noqa: BLE001
                log.warning("启动本地语音服务失败（不影响聊天）", exc_info=True)

        threading.Thread(target=_start_local_tts, name="bab-local-tts", daemon=True).start()

    # 冒烟模式：设置 XIAOCHEN_SMOKE=1 时 1.5 秒后自动退出
    if os_env_smoke():
        QTimer.singleShot(1500, app.quit)
    code = app.exec()
    lock.unlock()
    log.info("退出（%s）", code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
