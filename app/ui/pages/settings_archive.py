"""设置页的存档 / 诊断 / 卸载动作。

从 settings.py 拆出来：这些方法只碰 portable 和对话框，和设置页的控件初始化无关。
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from ...core import config, framework_setup, portable

log = logging.getLogger(__name__)


class ArchiveActionsMixin:

    def export_diagnostics(self) -> None:
        """把版本、系统信息、日志打成一个 zip，方便使用者发过来排错。"""
        from PySide6.QtWidgets import QMessageBox

        from ...services import diagnostics

        try:
            path = diagnostics.export_zip()
        except Exception as exc:                      # 磁盘满 / 桌面不可写
            QMessageBox.warning(self, "导出失败", "没能写出诊断包：\n" + str(exc))
            return
        box = QMessageBox(self)
        box.setWindowTitle("诊断包已导出")
        box.setText("已导出：\n" + str(path))
        box.setInformativeText(
            "里面只有版本、系统信息和最近的日志，API Key 已经打码。\n"
            "把它发给开发者就行；不想发可以随时删掉。"
        )
        open_btn = box.addButton("打开所在文件夹", QMessageBox.ActionRole)
        box.addButton("好", QMessageBox.AcceptRole)
        box.exec()
        if box.clickedButton() is open_btn:
            import subprocess

            subprocess.Popen(["explorer", "/select,", str(path)])

    def import_archive(self, confirm: bool = True) -> None:
        """从 .babpak 恢复人格、记忆和配置，覆盖当前 entity 里的同名文件。"""
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, "选择存档", str(portable.archive_dir()), "BAB 存档 (*.babpak)")
        if not path:
            return
        if confirm:
            ans = QMessageBox.question(
                self, "导入存档",
                "会用存档里的人格、记忆和配置覆盖当前内容。\n"
                "想保留现在这一份，先点「存档」。\n\n继续导入吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans != QMessageBox.Yes:
                return
        try:
            info = portable.read_archive(Path(path))
            if not info.get("ok"):
                QMessageBox.warning(self, "导入失败", str(info.get("error") or "这个存档不可用"))
                return
            key = ""
            if not info.get("has_api_key"):
                from ..dialogs.archive_key import ask_missing_key
                go, key = ask_missing_key(self)
                if not go:
                    return
            res = portable.restore_archive(Path(path), portable.entity_dir(), api_key=key)
        except Exception as exc:  # noqa: BLE001
            log.warning("导入存档失败：%s", exc)
            QMessageBox.warning(self, "导入失败", f"{exc}")
            return
        if not res.get("ok"):
            QMessageBox.warning(self, "导入失败", str(res.get("error") or "这个存档不可用"))
            return
        QMessageBox.information(
            self, "导入完成",
            f"恢复了 {res.get('files', 0)} 个文件（记忆 {res.get('memory', 0)} 条）。\n"
            "重启程序后生效。")
        self.lbl_archive.setText(f"已从存档导入：{path}")

    def export_archive(self) -> None:
        """导出前先问一句：带不带 Key。"""
        from ..dialogs.archive_key import ask_include_key

        go, include_key = ask_include_key(self)
        if not go:
            return
        self.save_archive(notify=True, include_key=include_key)

    def save_archive(self, notify: bool = True, include_key: bool = False) -> dict | None:
        """把人格、记忆、配置、聊天记录打成一个 .babpak。

        notify=False 时不弹窗（测试和静默存档用）；include_key=False 时存档不带 Key。
        返回 portable.write_archive 的结果（失败返回 None），重置前要用它判断能不能继续。
        """
        try:
            res = portable.write_archive(portable.entity_dir(), framework_setup.display_name(),
                                         include_key=bool(include_key))
        except Exception as exc:  # noqa: BLE001
            log.warning("存档失败：%s", exc)
            self.lbl_archive.setText(f"存档失败：{exc}")
            return None
        if not res.get("ok"):
            self.lbl_archive.setText(f"没存成：{res.get('error') or '未知原因'}")
            return None
        kb = max(1, int(res.get("bytes", 0)) // 1024)
        text = (f"已存档：{res['path']}\n"
                f"打包了 {res['files']} 个文件（其中记忆 {res['memory']} 个），{kb} KB。")
        self.lbl_archive.setText(
            text
            + "\n存档不在程序目录里，卸载不会动它。"
            + ("\n存档里带了 API Key，别随手发人。"
               if res.get("has_api_key") else "\n存档没带 API Key，换电脑要重填。")
        )
        log.info("存档完成 %s（%s 文件 / %s KB）", res["path"], res["files"], kb)

        if not notify:
            return
        box = QMessageBox(self)
        box.setWindowTitle("存档好了")
        box.setText(f"已存到：\n{res['path']}")
        box.setInformativeText(
            "存档不在程序目录里，卸载程序不会删掉它。\n"
            + ("存档里带了 API Key，别随手发人。"
               if res.get("has_api_key") else "存档没带 API Key，换电脑要重填。")
        )
        open_btn = box.addButton("打开存档目录", QMessageBox.ActionRole)
        box.addButton("好", QMessageBox.AcceptRole)
        box.exec()
        if box.clickedButton() is open_btn:
            subprocess.Popen(["explorer.exe", str(Path(res["path"]).parent)])
        return res

    def uninstall(self, confirm: bool = True) -> None:
        """卸载整个程序目录（为了装下一版）；前一步最好先存档。

        confirm=False 时不问（测试用）。
        """
        plan = portable.uninstall_script(config.APP_DIR)
        if not plan.get("ok"):
            QMessageBox.warning(self, "没法卸载", str(plan.get("reason") or "路径不对"))
            return
        if confirm:
            choice = self._ask_uninstall(plan)
            if choice == "archive":
                log.info("用户选了「先去存档」")
                self.save_archive(notify=True)
                return
            if choice != "remove":
                log.info("卸载被取消")
                return
        res = portable.spawn_uninstall(plan)
        if not res.get("ok"):
            QMessageBox.warning(self, "没卸成", str(res.get("error") or "未知原因"))
            return
        log.info("卸载脚本已起：%s", res.get("script"))
        self.lbl_archive.setText("正在卸载：程序马上会关掉，几秒后目录被删除。")
        self._finish_uninstall()

    def reset_launcher(self, confirm: bool = True) -> None:
        """清掉人格、记忆、模组和配置，恢复刚装好的状态；程序本身保留。"""
        choice = self._ask_reset() if confirm else "reset"
        if choice == "cancel":
            log.info("重置被取消")
            return
        if choice == "archive":
            res = self.save_archive(notify=False, include_key=True)
            if not res or not res.get("ok"):
                QMessageBox.warning(
                    self, "重置已取消",
                    "存档没有成功，先不重置，免得把现在的数据清掉。\n"
                    + self.lbl_archive.text())
                return
        self.lbl_archive.setText("正在停止内核、清理数据…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            from ...services import reset as reset_service

            out = reset_service.reset_launcher_data()
        except Exception as exc:  # noqa: BLE001
            log.warning("重置失败：%s", exc)
            QMessageBox.warning(self, "重置没做成", f"{exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        if not out.get("ok"):
            QMessageBox.warning(
                self, "重置没做完",
                "有些文件没清掉（可能还被占用）：\n"
                + "\n".join(out.get("errors") or [])[:900])
            return
        log.info("启动器已重置，删除 %s 个文件", out.get("removed"))
        QMessageBox.information(
            self, "重置完成",
            "启动器已恢复初始状态。\n程序会重新打开，重新走一遍建档向导。")
        self._restart_after_reset()

    def _ask_reset(self) -> str:
        """重置前的警告框：存档并重置 / 直接重置 / 取消。"""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("重置启动器")
        box.setText("把启动器恢复到刚装好、还没建档的状态？")
        box.setInformativeText(
            "会清掉：人格、记忆、聊天记录、API Key、情绪和状态、耳目设置、外观和窗口设置，"
            "以及已装/已启用的全部模组。\n"
            "会保留：程序本身、Python 依赖、内核代码和安装信息。\n\n"
            "和「卸载程序」不同：卸载会删掉整个程序目录，重置只清数据。\n"
            "重置前建议先存档；存档里可以带 API Key，之后导入就能恢复。"
        )
        b_archive = box.addButton("存档并重置", QMessageBox.AcceptRole)
        b_direct = box.addButton("直接重置", QMessageBox.DestructiveRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(b_archive)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_archive:
            return "archive"
        if clicked is b_direct:
            return "reset"
        return "cancel"

    def _restart_after_reset(self) -> None:
        """先退出，等单实例锁释放后再重新打开。"""
        app_dir = config.APP_DIR
        vbs = app_dir / "launch.vbs"
        if vbs.is_file():
            inner = f'ping -n 3 127.0.0.1 >nul & wscript.exe "{vbs}"'
        else:
            import sys

            exe = Path(sys.executable).with_name("pythonw.exe")
            if not exe.is_file():
                exe = Path(sys.executable)
            inner = f'ping -n 3 127.0.0.1 >nul & "{exe}" "{app_dir / "main.py"}"'
        try:
            subprocess.Popen(
                ["cmd.exe", "/c", inner], cwd=str(app_dir),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("重置后自动重开失败：%s", exc)
            QMessageBox.information(self, "请手动打开", f"重置好了，但没能自动重开：\n{exc}")
            return
        self.lbl_archive.setText("正在重新打开…")
        self._finish_uninstall(500)

    def _ask_uninstall(self, plan: dict) -> str:
        """卸载前的警告框：先去存档 / 完全卸载。返回 archive | remove | cancel。"""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("卸载程序")
        box.setText("您要删除这个程序吗？")
        box.setInformativeText(
            "删掉整个程序目录后，人格和记忆也会一起没有——您的智能体可以先存档保留。\n\n"
            f"程序目录：{plan.get('app_dir')}\n"
            f"存档位置：{portable.archive_dir()}（在程序目录外面，卸载不会动它）"
        )
        b_archive = box.addButton("先去存档", QMessageBox.AcceptRole)
        b_remove = box.addButton("完全卸载", QMessageBox.DestructiveRole)
        box.setDefaultButton(b_archive)  # 默认落在安全的那一个上
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_archive:
            return "archive"
        if clicked is b_remove:
            return "remove"
        return "cancel"

    def _finish_uninstall(self, delay_ms: int = 400) -> None:
        """给界面一点时间把提示画出来，再退出（测试里会被替换掉）。"""
        QTimer.singleShot(delay_ms, lambda: QApplication.instance().quit())
