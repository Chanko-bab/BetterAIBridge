"""模组管理：注册表驱动；外部导入 .pbab、启用/停用、模组设置、完全卸载。"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ...core import config, logger, pbab, registry
from ...services.worker import run_async
from ..dialogs.module_requires import RequiresDialog
from ..widgets.see_through import see_through, see_through_widget
from ..dialogs.module_settings import ModuleSettingsDialog

# 模组市场还没上线，先用这个占位串；上线后只改这一行。
MARKET_URL = "https://example.com/bab/modules"
MARKET_HINT = "模组市场还没上线，现在打开的是占位地址；有了会把链接换成真的。"

STATE_DOT = {
    "enabled": ("●", "#2e9e5b", "运行中"),
    "disabled": ("●", "#b07d2b", "已停用"),
    "installed": ("●", "#8a8f98", "已安装（未启用）"),
    "broken": ("●", "#c0392b", "异常"),
    "not_installed": ("○", "#9aa0a6", "未安装"),
}


def _tail(path: Path, limit: int = 40_000) -> str:
    """读一个日志文件的尾巴（不整个读进来，模组日志可能很大）。"""
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > limit:
                fh.seek(size - limit)
            data = fh.read()
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _module_events(mid: str, limit: int = 8) -> list[str]:
    """保姆那边记的安装/启用/停用流水（只有这个模组的）。"""
    try:
        path = Path(config.bundle_dir()).parent / "WiseEntity" / "entity" / "state" / "module_events.jsonl"
        if not path.exists():
            return []
        rows: list[str] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except (ValueError, TypeError):
                continue
            if str(row.get("id") or "") != mid:
                continue
            ts = row.get("ts") or row.get("at") or ""
            state = row.get("state") or row.get("event") or "?"
            stamp = ""
            try:
                stamp = time.strftime("%m-%d %H:%M:%S", time.localtime(float(ts)))
            except Exception:
                stamp = str(ts)[:19]
            rows.append(f"{stamp}  {state}")
        return rows[-limit:]
    except Exception:
        return []


def module_log_text(mod: dict, limit: int = 40_000) -> str:
    """把一个模组的日志/状态拼成一段人能读的文字（给「看日志」用）。"""
    mid = str(mod.get("id") or "?")
    name = str(mod.get("name") or mid)
    state = str(mod.get("state") or "未知")
    port = mod.get("runtime_port")
    pid = mod.get("pid")

    head = [f"{name}（{mid}）", f"状态：{state}"]
    if port:
        head.append(f"端口：{port}")
    if pid:
        head.append(f"pid：{pid}")
    if mod.get("error"):
        head.append(f"错误：{mod.get('error')}")

    events = _module_events(mid)
    if events:
        head.append("")
        head.append("保姆记的流水（最近 8 条）：")
        head.extend(f"  {e}" for e in events)

    base = Path(str(mod.get("dir") or mod.get("payload") or ""))
    logs = sorted((base / "logs").glob("*.log")) if base.is_dir() else []
    body: list[str] = []
    if logs:
        newest = max(logs, key=lambda p: p.stat().st_mtime)
        body.append("")
        body.append(f"模组日志：{newest.name}（最后 {limit // 1000} KB）")
        body.append("-" * 60)
        body.append(_tail(newest, limit).rstrip() or "（这个文件是空的）")
    else:
        body.append("")
        body.append(
            "还没有日志。可能刚装上、还没跑过；或者它启动就退出了——"
            "点「重启」再看一次，还是没有的话，模组目录里应该没有 logs。"
        )

    return "\n".join(head + body)


class ModuleLogDialog(QDialog):
    """看日志：只读、可复制、能直接打开模组目录。"""

    def __init__(self, parent: QWidget, mod: dict) -> None:
        super().__init__(parent)
        self.mod = mod
        self.setWindowTitle(f"看日志 · {mod.get('name') or mod.get('id')}")
        self.resize(820, 560)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        self.view = QPlainTextEdit(objectName="LogView")
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.view.setMinimumHeight(360)
        lay.addWidget(self.view, 1)

        row = QHBoxLayout()
        self.hint = QLabel("", objectName="Muted")
        row.addWidget(self.hint, 1)
        self.btn_refresh = QPushButton("刷新", objectName="Ghost")
        self.btn_refresh.clicked.connect(self.reload)
        self.btn_dir = QPushButton("打开模组目录", objectName="Ghost")
        self.btn_dir.clicked.connect(self.open_dir)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.accept)
        row.addWidget(self.btn_refresh)
        row.addWidget(self.btn_dir)
        row.addWidget(self.btn_close)
        lay.addLayout(row)

        self.reload()

    def reload(self) -> None:
        try:
            live = registry.get(str(self.mod.get("id") or "")) or self.mod
        except Exception:
            live = self.mod
        self.view.setPlainText(module_log_text(live))
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.hint.setText(f"{len(self.view.toPlainText())} 字")

    def open_dir(self) -> None:
        base = Path(str(self.mod.get("dir") or self.mod.get("payload") or ""))
        if base.is_dir():
            subprocess.Popen(["explorer", str(base)])
        else:
            self.hint.setText("模组目录不在了（可能已经卸载）")


class ModuleCard(QFrame):
    def __init__(self, page: "ModsPage", mod: dict) -> None:
        super().__init__(objectName="Card")
        self.page = page
        self.mod = mod
        mid = mod.get("id")
        state = str(mod.get("state") or "not_installed")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        top = QHBoxLayout()
        dot, color, label = STATE_DOT.get(state, STATE_DOT["not_installed"])
        name = QLabel(f"{mod.get('name') or mid}", objectName="CardTitle")
        ver = QLabel(f"v{mod.get('version') or '?'}", objectName="CardVer")
        chip = QLabel(f"{dot} {label}")
        chip.setStyleSheet(f"color: {color}; font-weight: 600;")
        top.addWidget(name)
        top.addWidget(ver)
        top.addStretch(1)
        top.addWidget(chip)
        lay.addLayout(top)

        author = str(mod.get("author") or "").strip()
        meta = QLabel(
            f"开发者：{author or '未标注'}　·　{mod.get('kind') or 'bridge'}　·　api {mod.get('api') or 1}",
            objectName="Muted",
        )
        if mod.get("homepage"):
            meta.setText(meta.text() + f"　·　{mod.get('homepage')}")
        lay.addWidget(meta)

        summary = mod.get("summary") or ""
        if summary:
            lay.addWidget(QLabel(summary, objectName="Muted", wordWrap=True))

        payload = (mod.get("payload") or {}).get("path") or ""
        folder = mod.get("folder") or (mod.get("dir") or "").split("\\")[-1]
        detail = f"模组文件夹：program_bundle\\{folder}" if folder else "尚未安装"
        if payload:
            detail += f"　·　重资产：{payload}"
        lay.addWidget(QLabel(detail, objectName="Muted", wordWrap=True))

        # 外置依赖：缺第三方客户端/运行时/素材时，卡片上先说清楚
        self.reqs: list[dict] = []
        if state != "not_installed":
            try:
                self.reqs = pbab.require_status(mid)
            except Exception:  # noqa: BLE001
                self.reqs = []
        self.dep_hint: QLabel | None = None
        if self.reqs:
            miss = [r for r in self.reqs if not r.get("ok")]
            if miss:
                names = "、".join(str(r.get("name") or r.get("id")) for r in miss[:3])
                text = f"依赖：还缺 {len(miss)} 项（{names}）——缺着启用会失败"
                self.dep_hint = QLabel(text, objectName="Muted", wordWrap=True)
                self.dep_hint.setStyleSheet("color: #c2402f;")
            else:
                self.dep_hint = QLabel(f"依赖：{len(self.reqs)} 项都就绪", objectName="Muted")
            lay.addWidget(self.dep_hint)

        # 端口 / 能力：一眼看到它实际占了什么、申请了什么
        try:
            live = registry.get(mid) or {}
        except Exception:  # noqa: BLE001
            live = {}
        port = int(live.get("runtime_port") or 0)
        try:
            wants = [str(x) for x in ((pbab.manifest(mid).get("bridge") or {}).get("wants") or [])]
        except Exception:  # noqa: BLE001
            wants = []
        bits: list[str] = []
        if port:
            bits.append(f"实际端口 {port}")
        elif state != "not_installed":
            bits.append("端口：还没分配（启用后才有）")
        if wants:
            shown = "、".join(wants[:4]) + (f" 等 {len(wants)} 项" if len(wants) > 4 else "")
            bits.append(f"申请能力：{shown}")
        if bits:
            lay.addWidget(QLabel("　·　".join(bits), objectName="Muted", wordWrap=True))

        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.toggle = QPushButton("停用" if state == "enabled" else "启用")
        self.toggle.setEnabled(state in ("enabled", "disabled", "installed", "broken"))
        self.toggle.clicked.connect(self.on_toggle)
        settings_btn = QPushButton("模组设置", objectName="Ghost")
        settings_btn.setEnabled(state != "not_installed")
        settings_btn.clicked.connect(self.on_settings)
        uninstall_btn = QPushButton("完全卸载", objectName="Danger")
        uninstall_btn.setEnabled(state != "not_installed")
        uninstall_btn.clicked.connect(self.on_uninstall)
        btns.addWidget(self.toggle)
        login_btn = None
        try:
            lg = (pbab.manifest(mid) or {}).get("login") or {}
        except Exception:
            lg = {}
        if lg.get("port") and state == "enabled":
            login_btn = QPushButton(str(lg.get("label") or "扫码登录"))
            login_btn.clicked.connect(self.on_login)
            btns.addWidget(login_btn)
            wait_btn = QPushButton("待批", objectName="Ghost")
            wait_btn.setToolTip("她想点赞/收藏/私信时，会先排在这里，等你点头")
            wait_btn.clicked.connect(self.on_pending)
            btns.addWidget(wait_btn)
        btns.addWidget(settings_btn)
        if self.reqs:
            dep_btn = QPushButton("依赖…", objectName="Ghost")
            dep_btn.setToolTip("第三方客户端/运行时/素材：从官方来源装好，壳只登记路径")
            dep_btn.clicked.connect(self.on_requires)
            btns.addWidget(dep_btn)
        self.log_btn = QPushButton("看日志", objectName="Ghost")
        self.log_btn.setEnabled(state != "not_installed")
        self.log_btn.clicked.connect(self.on_log)
        self.restart_btn = QPushButton("重启", objectName="Ghost")
        self.restart_btn.setEnabled(state in ("enabled", "broken"))
        self.restart_btn.setToolTip("先停用再启用一次，模组卡住时用")
        self.restart_btn.clicked.connect(self.on_restart)
        btns.addWidget(self.log_btn)
        btns.addWidget(self.restart_btn)
        self.reinstall_btn = QPushButton("重装…", objectName="Ghost")
        self.reinstall_btn.setEnabled(state in ("enabled", "disabled", "installed", "broken"))
        self.reinstall_btn.setToolTip("用原来的安装包（或你选的新包）覆盖模组文件；设置和记忆保留")
        self.reinstall_btn.clicked.connect(self.on_reinstall)
        btns.addWidget(self.reinstall_btn)
        btns.addWidget(uninstall_btn)
        btns.addStretch(1)
        lay.addLayout(btns)

    # --- 按钮 -------------------------------------------------------

    def on_toggle(self) -> None:
        mid = self.mod["id"]
        if str(self.mod.get("state")) == "enabled":
            self.page.call(pbab.disable, mid, f"{self.mod.get('name')} 已停用")
        else:
            def missing(exc) -> bool:
                if isinstance(exc, pbab.PbabMissingRequires):
                    self.page.hint.setText("还缺依赖，已打开依赖框；装好后回来再点启用。")
                    QTimer.singleShot(0, self.on_requires)
                    return True
                return False

            self.page.call(pbab.enable, mid, f"{self.mod.get('name')} 已启用",
                           on_err=missing)

    def on_log(self) -> None:
        dlg = ModuleLogDialog(self, self.mod)
        dlg.exec()

    def on_requires(self) -> None:
        dlg = RequiresDialog(self, str(self.mod.get("id") or ""), str(self.mod.get("name") or ""))
        dlg.exec()
        if dlg.changed:
            self.page.reload()

    def on_restart(self) -> None:
        """先停后启：卡在 broken 的时候，一次点击把进程重来一遍。"""
        mid = self.mod["id"]
        name = self.mod.get("name") or mid
        self.page.call(
            pbab.disable, mid, f"{name} 已停用，正在重启…",
            after=lambda _res: self.page.call(pbab.enable, mid, f"{name} 已重启"),
        )

    def on_reinstall(self) -> None:
        """原地重装：覆盖模组文件，设置和记忆别动。"""
        mid = str(self.mod.get("id") or "")
        name = self.mod.get("name") or mid
        rec = registry.get(mid) or {}
        src = str(rec.get("source") or "")
        if not src or not Path(src).exists():
            src, _ = QFileDialog.getOpenFileName(
                self, f"选一个「{name}」的模组包", str(config.get("modules_dir")),
                "模组包 (*.pbab)")
            if not src:
                return
        yes = QMessageBox.question(
            self, "重装模组",
            f"用这个包重装「{name}」？\n\n{src}\n\n"
            "模组文件会被覆盖；设置和记忆保留。",
        )
        if yes != QMessageBox.Yes:
            return
        self.page.call(lambda m: pbab.reinstall(m, src), mid, f"{name} 已重装")

    def _live_port(self) -> int:
        """模组真在听的端口。

        清单里的 `login.port` 只是"作者想要的端口"；外壳启用时会换成池端口
        （`pbab.enable()` 的 base+5..base+19），所以得先看 registry 里的
        runtime_port，否则扫码框/待批框会连到一个没人听的端口上。
        """
        try:
            lg = (pbab.manifest(self.mod["id"]) or {}).get("login") or {}
        except Exception:
            lg = {}
        try:
            live = int((registry.get(self.mod["id"]) or {}).get("runtime_port") or 0)
        except Exception:
            live = 0
        return live or int(lg.get("port") or 0)

    def on_login(self) -> None:
        port = self._live_port()
        if not port:
            return
        try:
            lg = (pbab.manifest(self.mod["id"]) or {}).get("login") or {}
        except Exception:
            lg = {}
        from ..dialogs.qr_login import QrLoginDialog

        dlg = QrLoginDialog(self, port=port,
                            title=str(lg.get("label") or "扫码登录"),
                            hint=str(lg.get("hint") or ""))
        ok = dlg.exec()
        self.page.reload()
        if ok:
            self._ask_owner(port)

    def _ask_owner(self, port: int) -> None:
        import httpx
        from ..dialogs.owner_mid import OwnerMidDialog

        mid = ""
        try:
            with httpx.Client(timeout=8.0) as c:
                mid = str((c.get(f"http://127.0.0.1:{port}/owner").json() or {}).get("owner_mid") or "")
        except Exception:
            mid = ""
        if mid:
            return
        d = OwnerMidDialog(self, port=port)
        d.exec()

    def on_pending(self) -> None:
        port = self._live_port()
        if not port:
            return
        from ..dialogs.pending import PendingDialog

        d = PendingDialog(self, port=port)
        d.exec()
        self.page.reload()

    def on_settings(self) -> None:
        dlg = ModuleSettingsDialog(self.mod["id"], self)
        dlg.exec()
        self.page.reload()

    def on_uninstall(self) -> None:
        mid = self.mod["id"]
        d = self.mod.get("dir") or str(pbab.module_dir(mid))
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("完全卸载")
        box.setText(f"完全卸载「{self.mod.get('name') or mid}」？")
        box.setInformativeText(
            f"会删除这个模组的全部文件和数据：\n{d}\n\n"
            "外部重资产（payload）不会被删，但注册信息会消失。\n这个操作不可撤销。"
        )
        box.setStandardButtons(QMessageBox.Cancel | QMessageBox.Yes)
        box.setDefaultButton(QMessageBox.Cancel)
        box.button(QMessageBox.Yes).setText("我确认，删掉")
        if box.exec() != QMessageBox.Yes:
            return
        self.page.call(pbab.uninstall, mid, f"{self.mod.get('name')} 已完全卸载", after=lambda _res: None)


class ModsPage(QWidget):
    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        self.log = logger.get()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 16, 22, 16)
        outer.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(QLabel("模组管理", objectName="CardValue"))
        head.addStretch(1)
        market = QPushButton("模组市场", objectName="Ghost")
        market.setToolTip(MARKET_HINT)
        market.clicked.connect(self.open_market)
        imp = QPushButton("导入 .pbab")
        imp.clicked.connect(self.on_import)
        imp_dir = QPushButton("导入文件夹", objectName="Ghost")
        imp_dir.clicked.connect(self.on_import_dir)
        open_dir = QPushButton("打开模组目录", objectName="Ghost")
        open_dir.clicked.connect(lambda: subprocess.Popen(["explorer.exe", str(config.bundle_dir())]))
        refresh = QPushButton("刷新", objectName="Ghost")
        refresh.clicked.connect(self.reload)
        head.addWidget(market)
        head.addWidget(imp)
        head.addWidget(imp_dir)
        head.addWidget(open_dir)
        head.addWidget(refresh)
        outer.addLayout(head)

        self.hint = QLabel("", objectName="Muted")
        outer.addWidget(self.hint)

        self.scroll = QScrollArea()
        see_through(self.scroll)
        self.scroll.setWidgetResizable(True)
        self.holder = QWidget()
        self.list = QVBoxLayout(self.holder)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(10)
        self.list.addStretch(1)
        self.scroll.setWidget(self.holder)
        see_through_widget(self.holder)
        outer.addWidget(self.scroll, 1)

        self.cards: list[ModuleCard] = []
        self.reload()

    # --- 数据 -------------------------------------------------------

    def open_market(self) -> None:
        """打开模组市场。链接还是占位串（真市场没上线），先照实打开。"""
        self.log.info("打开模组市场：%s", MARKET_URL)
        try:
            ok = QDesktopServices.openUrl(QUrl(MARKET_URL))
            if not ok:
                self.log.warning("打开市场链接失败：%s", MARKET_URL)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("打开市场链接炸了：%s", exc)

    def reload(self) -> None:
        while self.list.count() > 1:
            item = self.list.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.cards = []
        mods = sorted(registry.modules(), key=lambda m: (m.get("state") != "enabled", m.get("name") or m.get("id")))
        if not mods:
            self.list.insertWidget(0, QLabel(
                "还没有装任何模组。点右上角「导入 .pbab」；安装包带的模组包就在 program_cache 里。",
                objectName="Muted"))
        for m in mods:
            card = ModuleCard(self, m)
            self.cards.append(card)
            self.list.insertWidget(self.list.count() - 1, card)

        # 本地还没装的包（安装包会把 .pbab 放在 program_cache 里，给人一键装）
        have = {str(m.get("id")) for m in mods}
        local = [(p, man) for p, man in self._local_packages() if str(man.get("id")) not in have]
        if local:
            self.list.insertWidget(self.list.count() - 1, QLabel(
                f"本地还有 {len(local)} 个模组包没装（{config.get('modules_dir')}）", objectName="Muted"))
            for pkg, man in local:
                self.list.insertWidget(self.list.count() - 1, self._package_row(pkg, man))
        self.hint.setText(f"注册表：{registry.path()}　·　模组目录：{config.bundle_dir()}")

    def _local_packages(self, root: Path | None = None) -> list[tuple[Path, dict]]:
        """`modules_dir` 里能装、还没装的包。坏包直接跳过，不打扰人。"""
        out: list[tuple[Path, dict]] = []
        try:
            base = Path(root) if root is not None else Path(str(config.get("modules_dir")))
            if not base.is_dir():
                return []
            for pkg in sorted(base.glob("*.pbab")):
                if not pkg.is_file():
                    continue
                try:
                    meta = pbab.validate(pkg)
                except (OSError, ValueError, KeyError, TypeError, pbab.PbabError):
                    continue
                man = meta.get("manifest") or {}
                if man.get("id"):
                    out.append((pkg, man))
        except Exception:  # noqa: BLE001
            return []
        return out

    def _package_row(self, pkg: Path, man: dict) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        label = QLabel(f"{man.get('name') or pkg.stem}　v{man.get('version')}　·　{pkg.name}", objectName="Muted")
        lay.addWidget(label, 1)
        btn = QPushButton("装这个包")
        btn.clicked.connect(lambda _=False, p=str(pkg): self._install_path(p))
        lay.addWidget(btn)
        return row

    # --- 导入 -------------------------------------------------------

    def _install_path(self, path: str) -> None:
        try:
            meta = pbab.validate(path)
            if str((meta.get("manifest") or {}).get("kind") or "") == pbab.KIND_PRE:
                yes = QMessageBox.question(
                    self, "这是前置模组",
                    "前置模组启用后会直接修改程序文件和代码，可以建目录、写任何文件。\n\n"
                    "不再逐次弹窗确认；每次落盘前会整包备份，并记 pre_audit.jsonl。\n"
                    "只安装你完全信得过的包。\n\n继续安装吗？",
                    QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
                if yes != QMessageBox.Yes:
                    self.hint.setText("已取消安装前置模组")
                    return
        except Exception as exc:  # noqa: BLE001
            self.hint.setText("导入失败")
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        self.hint.setText(f"正在校验并安装：{Path(path).name} …")

        def ok(mod):
            self.hint.setText(f"已安装 {mod.get('name')} v{mod.get('version')}")
            QMessageBox.information(self, "导入成功", f"已安装「{mod.get('name')}」v{mod.get('version')}，点「启用」才会跑起来。")
            self.reload()

        def err(e):
            self.hint.setText("导入失败")
            QMessageBox.warning(self, "导入失败", str(e))

        run_async(lambda: pbab.install(path), on_ok=ok, on_err=err)

    def on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择模组包", str(config.get("modules_dir")), "模组包 (*.pbab)")
        if path:
            self._install_path(path)

    def on_import_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择模组文件夹（里面要有 module.json）", str(config.get("modules_dir")))
        if path:
            self._install_path(path)

    # --- 通用动作 ---------------------------------------------------

    def call(self, fn, mid: str, ok_text: str, after=None, on_err=None) -> None:
        self.hint.setText("处理中…")

        def ok(_res):
            self.hint.setText(ok_text)
            self.reload()
            if after is not None:
                try:
                    after(_res)
                except Exception as exc:  # noqa: BLE001
                    logger.get().warning("模组后续动作失败：%s", exc)

        def err(e):
            self.hint.setText("操作失败")
            msg = str(e)
            if on_err is not None:
                try:
                    if on_err(e):
                        return
                except Exception as exc:  # noqa: BLE001
                    logger.get().warning("模组错误处理失败：%s", exc)
            QMessageBox.warning(self, "操作失败", msg)

        run_async(lambda: fn(mid), on_ok=ok, on_err_obj=err)
