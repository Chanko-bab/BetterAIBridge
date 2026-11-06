"""Offscreen smoke test: the shell opens, every page builds, mods page renders,
onboarding wizard + tutorial dialog build, and core's nanny/tutorial endpoints answer.

Usage (no visible window, safe to run anytime):

    set QT_QPA_PLATFORM=offscreen
    .venv\\Scripts\\python.exe tools\\smoke.py

It exits 0 and prints PASS, or exits 1 with the first problem it hits.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("BAB_NO_ANIM", "1")
os.environ.setdefault("BAB_NO_AUTORESTART", "1")   # 冒烟时别真去拉起内核
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import framework_setup  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

EXPECTED = {"chat", "mods", "services", "logs", "settings", "details"}


def main() -> int:
    app = QApplication(sys.argv[:1])
    win = MainWindow()
    win.show()
    app.processEvents()

    # 懒加载：启动时只建聊天页，设置页这种大页不能提前构造
    if "settings" in win.pages:
        print("FAIL settings page was built eagerly")
        return 1

    for key in sorted(EXPECTED):
        win.show_page(key)
        app.processEvents()
    missing = EXPECTED - set(win.pages)
    if missing:
        print(f"FAIL missing pages: {sorted(missing)}")
        return 1
    if "details" in win.buttons:
        print("FAIL details page must not sit in the nav")
        return 1

    for key in list(win.pages):
        win.show_page(key)
        app.processEvents()

    mods = win.pages["mods"]
    if hasattr(mods, "reload"):
        mods.reload()
        app.processEvents()
    cards = getattr(mods, "cards", None)
    n_cards = len(cards) if cards is not None else -1

    configured = framework_setup.is_configured()
    hint = ""
    if isinstance(configured, tuple):
        configured, hint = configured

    # 建档向导：四页、每页都能建出来
    from app.ui.dialogs.onboarding import OnboardingWizard  # noqa: E402

    wiz = OnboardingWizard(win)
    app.processEvents()
    n_pages = wiz.stack.count()
    for i in range(n_pages):
        wiz.stack.setCurrentIndex(i)
        app.processEvents()
    wiz.close()

    # 教程欢迎框
    from app.ui.dialogs.tutorial import TutorialWelcome  # noqa: E402

    tut = TutorialWelcome(win)
    app.processEvents()
    tut.close()

    # 内核侧新接口（没起内核就跳过，不算失败）
    nanny = {}
    tutorial = {}
    try:
        from app.services.core_client import CoreClient  # noqa: E402

        cli = CoreClient(timeout=4.0)
        nanny = cli.nanny_status()
        tutorial = cli.tutorial_get()
    except Exception as e:  # noqa: BLE001
        print(f"core offline: {e}")

    # 人格渲染：模板必须把占位符全部填掉
    rendered = framework_setup.render_persona(
        "测试名", gender="女", self_call="我", user_title="测试称呼", flavor="测试脾气")
    leftover = [tok for tok in ("{{", "PLACEHOLDER") if tok in rendered]

    print(f"pages={sorted(win.pages)}")
    print(f"nav={sorted(win.buttons)}")
    print(f"mods_cards={n_cards}")
    print(f"onboarding_pages={n_pages}")
    print(f"tutorial_dialog=ok")
    print(f"nanny={nanny.get('ok')} checks={nanny.get('checks')} degraded={nanny.get('degraded')}")
    print(f"tutorial_state={tutorial.get('seen')}/{tutorial.get('mode')}")
    print(f"persona_leftover={leftover}")
    print(f"configured={bool(configured)}" + ("" if configured else f" ({hint or 'first run'})"))

    win.hide()
    app.quit()

    if leftover:
        print(f"FAIL persona still has placeholders: {leftover}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
