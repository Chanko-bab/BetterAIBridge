"""设置页检查更新：按钮状态、没有新版/有新版分支、开发目录保护。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton  # noqa: E402

from app.services import update  # noqa: E402
from app.ui.pages import settings_update as su  # noqa: E402

FAILED = []


def check(ok: bool, msg: str) -> None:
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        FAILED.append(msg)


class Host(su.UpdateActionsMixin):
    def __init__(self):
        self.btn_update = QPushButton("检查更新")
        self.spawned = []
        self.offered = []

    def _spawn(self, fn, on_ok=None, on_err=None, key=None, dedupe=True):
        self.spawned.append(key)
        try:
            on_ok(fn())
        except Exception as e:  # noqa: BLE001
            on_err(str(e))

    def _offer_update(self, info):
        # 不覆盖基类：只记录版本，然后让基类弹确认框
        self.offered.append(info.version)
        return super()._offer_update(info)


def main() -> int:
    app = QApplication.instance() or QApplication([])

    old_installed, old_check, old_version = update.installed, update.check, update.version
    old_info, old_question = su.QMessageBox.information, su.QMessageBox.question
    old_warning = su.QMessageBox.warning
    infos = []
    warnings = []
    questions = []

    su.QMessageBox.information = lambda *a, **k: infos.append(a[2] if len(a) > 2 else "")
    su.QMessageBox.question = lambda *a, **k: (questions.append(a[2]), QMessageBox.No)[1]
    su.QMessageBox.warning = lambda *a, **k: warnings.append(a[2] if len(a) > 2 else "")
    try:
        # 开发目录：不请求 GitHub
        update.installed = lambda: False
        h = Host()
        h.check_update()
        check(not h.spawned and "开发目录" in infos[-1], "开发目录不检查更新")

        # 已是最新
        update.installed = lambda: True
        update.version = lambda: "0.5.9"
        update.check = lambda: None
        h = Host()
        h.check_update()
        check(h.spawned == ["update.check"], "安装版会发起检查")
        check(h.btn_update.isEnabled() and h.btn_update.text() == "检查更新", "检查后按钮恢复")
        check("最新版" in infos[-1], "没有新版提示最新")

        # 有新版，用户选否
        info = update.UpdateInfo("0.6.0", "notes", "https://example/u.zip", "a" * 64, 10)
        update.check = lambda: info
        h = Host()
        h.check_update()
        check(h.offered == ["0.6.0"], "有新版进入确认")
        check(len(questions) == 1 and "0.6.0" in questions[0], "确认框带版本")

        # 失败恢复按钮
        def boom():
            raise update.UpdateError("网络炸了")

        update.check = boom
        h = Host()
        h.check_update()
        check(h.btn_update.isEnabled() and h.btn_update.text() == "检查更新", "失败后按钮恢复")
        check("检查更新失败" in warnings[-1], "失败提示")
    finally:
        update.installed, update.check, update.version = old_installed, old_check, old_version
        su.QMessageBox.information, su.QMessageBox.question = old_info, old_question
        su.QMessageBox.warning = old_warning

    if FAILED:
        print(f"\n{len(FAILED)} 项失败")
        return 1
    print("\n检查更新 UI 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
