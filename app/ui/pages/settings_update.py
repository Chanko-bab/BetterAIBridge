"""设置页「检查更新」动作。"""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from ...services import update


class UpdateActionsMixin:
    def check_update(self) -> None:
        if not update.installed():
            QMessageBox.information(
                self, "检查更新",
                "这是开发目录，检查更新只在安装版里可用。",
            )
            return
        btn = getattr(self, "btn_update", None)
        if btn is not None:
            btn.setEnabled(False)
            btn.setText("检查中…")

        def done(info):
            if btn is not None:
                btn.setEnabled(True)
                btn.setText("检查更新")
            if info is None:
                QMessageBox.information(
                    self, "检查更新",
                    f"目前已是最新版（{update.version() or '未知'}）。",
                )
                return
            self._offer_update(info)

        def failed(text):
            if btn is not None:
                btn.setEnabled(True)
                btn.setText("检查更新")
            QMessageBox.warning(self, "检查更新", f"检查更新失败：{text}")

        self._spawn(lambda: update.check(), on_ok=done, on_err=failed, key="update.check", dedupe=False)

    def _offer_update(self, info: update.UpdateInfo) -> None:
        notes = (info.notes or "").strip()
        if len(notes) > 1200:
            notes = notes[:1200] + "\n…"
        text = f"发现新版本 {info.version}（当前 {update.version() or '未知'}）。"
        if notes:
            text += "\n\n" + notes
        text += "\n\n现在下载并重启更新吗？"
        ans = QMessageBox.question(
            self, "发现新版本", text,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if ans != QMessageBox.Yes:
            return
        from ..dialogs.update_dialog import UpdateDialog

        UpdateDialog(self, info).exec()
