"""模组的外置依赖（requires）：检测、引导、下载、登记路径。

重资产不随包发：这里只做四件事——
  1. 检测（壳按清单里的 env/paths/where 找现成的）；
  2. 告知（来源、许可、大小都摆出来，由用户点）；
  3. 取得（官方页面打开 / 官方源下载并校验 sha256）；
  4. 回填（记下路径，启用时注入 BAB_REQ_*）。
绝不静默安装、不代勾第三方协议、不复制用户自己装的软件。
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

log = logging.getLogger("xiaochen.module_requires")

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
    QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from ...core import pbab
from ...services.worker import run_async

KIND_TEXT = {"app": "第三方软件", "runtime": "运行时", "asset": "素材/模型"}

# 正在下载的依赖：key=(mid, rid)。放模块级，关掉对话框再打开还能看到进度。
_ACTIVE: dict[tuple[str, str], dict] = {}


class _Sig(QObject):
    tick = Signal(int, int)
    stage = Signal(str)


def _mb(n: int) -> str:
    if not n:
        return ""
    return f"{n / 1024 / 1024:.1f} MB" if n >= 1024 * 1024 else f"{n / 1024:.0f} KB"


class RequiresDialog(QDialog):
    """一张依赖表：缺什么、从哪来、点一下怎么装。"""

    def __init__(self, parent: QWidget, mid: str, name: str = "") -> None:
        super().__init__(parent)
        self.mid = mid
        self.changed = False
        self._rows: dict[str, tuple[QProgressBar, QLabel, QPushButton, QPushButton]] = {}
        self._install_btns: dict[str, QPushButton] = {}
        self.setWindowTitle(f"依赖 · {name or mid}")
        self.resize(760, 480)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        tip = QLabel(
            "这个模组要用的第三方软件/运行时/素材不随包分发，只在这里登记。"
            "请从官方来源取得；壳不会替你静默安装，卸载时也不会删你自己装的东西。",
            objectName="Muted", wordWrap=True,
        )
        lay.addWidget(tip)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.body = QWidget()
        self.rows = QVBoxLayout(self.body)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(8)
        self.rows.addStretch(1)
        self.scroll.setWidget(self.body)
        lay.addWidget(self.scroll, 1)

        foot = QHBoxLayout()
        self.hint = QLabel("", objectName="Muted")
        foot.addWidget(self.hint, 1)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        foot.addWidget(close)
        lay.addLayout(foot)

        # 进度条的值由 _ACTIVE 驱动；定时刷新让「关掉再开」也能看到同一份进度。
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

        # 安装程序是用户自己点的；这里只负责等安装结果，最长 15 分钟。
        self._watch = QTimer(self)
        self._watch.setInterval(2000)
        self._watch.timeout.connect(self._check_installing)
        self._watch_started = 0.0

        self.reload()

    # ---------------------------------------------------------------- 刷新

    def reload(self) -> None:
        self._rows.clear()
        self._install_btns.clear()
        while self.rows.count() > 1:
            item = self.rows.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        try:
            items = pbab.require_status(self.mid)
        except Exception as exc:  # noqa: BLE001
            items = []
            self.hint.setText(f"读不到这个模组的依赖：{exc}")
        if not items:
            self.hint.setText("这个模组没有外置依赖，装上代码就能用。")
            return
        ready = sum(1 for r in items if r.get("ok"))
        self.hint.setText(f"{ready}/{len(items)} 就绪")
        for r in items:
            self.rows.insertWidget(self.rows.count() - 1, self._row(r))
        self._ensure_watch()

    def _row(self, r: dict) -> QWidget:
        card = QFrame(objectName="Card")
        box = QVBoxLayout(card)
        box.setContentsMargins(12, 10, 12, 10)
        box.setSpacing(4)

        top = QHBoxLayout()
        ok = bool(r.get("ok"))
        install = str(r.get("install") or "")
        state = str(r.get("state") or "")
        title = QLabel(str(r.get("name") or r.get("id")), objectName="CardTitle")
        if ok:
            chip_text, chip_color = "✓ 已就绪", "#2f8a4c"
        elif install == "installer" and state == "ready":
            chip_text, chip_color = "待安装", "#b26a00"
        elif install == "installer" and state == "installing":
            chip_text, chip_color = "安装中…", "#b26a00"
        elif install == "installer" and state == "invalid":
            chip_text, chip_color = "签名不对", "#c2402f"
        else:
            chip_text, chip_color = "缺", "#c2402f"
        chip = QLabel(chip_text)
        chip.setStyleSheet(f"color: {chip_color}; font-weight: 600;")
        kind = QLabel(KIND_TEXT.get(str(r.get("kind")), str(r.get("kind"))), objectName="Muted")
        top.addWidget(title)
        top.addWidget(chip)
        top.addStretch(1)
        top.addWidget(kind)
        box.addLayout(top)

        src = str((r.get("source") or [""])[0])
        if install == "download":
            meta = f"下载地址：{src}"
        elif install == "guided":
            meta = f"官方页面：{src}"
        elif install == "installer":
            meta = "官方安装包 · 下载时显示大小"
        else:
            meta = f"来源：{src}"
        size = _mb(int(r.get("size") or 0))
        if size:
            meta += f"　·　约 {size}"
        if r.get("path"):
            meta += f"\n已登记：{r.get('path')}"
        if install == "installer" and r.get("installer_path"):
            meta += f"\n安装包：{r.get('installer_path')}"
        box.addWidget(QLabel(meta, objectName="Muted", wordWrap=True))

        bar = None
        mb = None
        if not ok and install in ("download", "installer"):
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(True)
            bar.setFormat("%p%")
            bar.setVisible(False)
            box.addWidget(bar)
            mb = QLabel("", objectName="Muted")
            mb.setVisible(False)
            box.addWidget(mb)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        if r.get("source"):
            if install == "installer":
                open_text = "打开官网"
            elif install == "download":
                open_text = "打开下载地址"
            else:
                open_text = "打开官方页面"
            b_open = QPushButton(open_text, objectName="Ghost")
            b_open.clicked.connect(lambda _=False, url=str(r["source"][0]):
                                   QDesktopServices.openUrl(QUrl(url)))
            btns.addWidget(b_open)
        if r.get("license_url"):
            b_lic = QPushButton("看许可", objectName="Ghost")
            b_lic.clicked.connect(lambda _=False, url=str(r["license_url"]):
                                  QDesktopServices.openUrl(QUrl(url)))
            btns.addWidget(b_lic)
        if install == "installer" and not ok and state != "installing":
            b_pick = QPushButton("选择已装路径…", objectName="Ghost")
            b_pick.clicked.connect(lambda _=False, item=r: self._pick(item))
            btns.addWidget(b_pick)
        dl_btn = None
        cancel_btn = None
        if install in ("download", "installer") and not ok and state != "installing":
            if install == "installer" and state in ("ready", "invalid"):
                dl_text = "重新下载"
            elif install == "installer":
                dl_text = "下载官方安装包"
            else:
                dl_text = "下载并校验"
            dl_btn = QPushButton(dl_text)
            dl_btn.clicked.connect(lambda _=False, item=r: self._download(item))
            btns.addWidget(dl_btn)
            cancel_btn = QPushButton("取消", objectName="Ghost")
            cancel_btn.setVisible(False)
            cancel_btn.clicked.connect(lambda _=False, key=str(r.get("id")): self._cancel(key))
            btns.addWidget(cancel_btn)
        if install == "installer" and state == "ready":
            b_install = QPushButton("安装")
            b_install.clicked.connect(lambda _=False, item=r: self._install(item))
            btns.addWidget(b_install)
            self._install_btns[str(r.get("id"))] = b_install
        if install == "installer" and state == "installing":
            b_retry = QPushButton("重新检测", objectName="Ghost")
            b_retry.clicked.connect(lambda _=False: self.reload())
            btns.addWidget(b_retry)
        btns.addStretch(1)
        box.addLayout(btns)
        if bar is not None and mb is not None and dl_btn is not None and cancel_btn is not None:
            rid = str(r.get("id"))
            self._rows[rid] = (bar, mb, cancel_btn, dl_btn)
            self._sync_row(rid)
        return card

    # ---------------------------------------------------------------- 动作

    def _download(self, r: dict) -> None:
        rid = str(r.get("id"))
        key = (self.mid, rid)
        if key in _ACTIVE:
            return
        install = str(r.get("install") or "")
        cancel = threading.Event()
        sig = _Sig(self)
        state = {"done": 0, "total": 0, "cancel": cancel, "sig": sig, "stage": ""}
        _ACTIVE[key] = state

        def push(done: int, total: int) -> None:
            state["done"] = int(done or 0)
            state["total"] = int(total or 0)
            try:
                sig.tick.emit(state["done"], state["total"])
            except RuntimeError:
                pass

        def stage(name: str) -> None:
            state["stage"] = str(name)
            try:
                sig.stage.emit(name)
            except RuntimeError:
                pass

        def ok(res: object) -> None:
            _ACTIVE.pop(key, None)
            self.changed = True
            path = (res or {}).get("path") if isinstance(res, dict) else ""
            try:
                self.reload()
                if install == "installer":
                    self.hint.setText("下载完成，签名校验通过；点「安装」运行官方安装程序")
                else:
                    self.hint.setText(f"好了：{path}" if path else "好了")
            except RuntimeError:
                pass

        def err(msg: str) -> None:
            _ACTIVE.pop(key, None)
            text = str(msg)
            if "取消" in text:
                text = "已取消下载"
            elif "403" in text:
                text = "下载源拒绝访问（403）。点「打开官网」手动下载，或稍后重试。"
            else:
                text = f"下载失败：{text}"
            try:
                self.reload()
                self.hint.setText(text)
            except RuntimeError:
                pass

        sig.tick.connect(lambda d, t, k=key: self._tick(k, d, t))
        sig.stage.connect(lambda name, k=key: self._stage(k, name))
        if install == "installer":
            self.hint.setText(f"正在解析「{r.get('name') or rid}」的官方下载地址…")
            work = lambda: pbab.download_installer(self.mid, rid, progress=push,
                                                   cancel=cancel.is_set, stage=stage)
        else:
            self.hint.setText(f"正在下载 {r.get('name') or rid}…（下载源，校验 sha256）")
            work = lambda: pbab.download_require(self.mid, rid, progress=push,
                                                 cancel=cancel.is_set, stage=stage)
        run_async(work, ok, err)
        self._sync_row(rid)

    def _tick(self, key: tuple[str, str], done: int, total: int) -> None:
        state = _ACTIVE.get(key)
        if state is None:
            return
        state["done"] = int(done or 0)
        state["total"] = int(total or 0)
        if key[0] == self.mid:
            self._sync_row(key[1])

    def _stage(self, key: tuple[str, str], name: str) -> None:
        state = _ACTIVE.get(key)
        if state is None or state["cancel"].is_set():
            return
        if key[0] != self.mid:
            return
        if name == "resolve":
            self.hint.setText("解析官方下载地址…")
        elif name == "verify":
            self.hint.setText("校验 sha256 中…")
        elif name == "signature":
            self.hint.setText("校验发布者签名…")
        elif name == "extract":
            self.hint.setText("解压中…")

    def _sync_row(self, rid: str) -> None:
        row = self._rows.get(rid)
        if row is None:
            return
        bar, mb, b_cancel, b_dl = row
        state = _ACTIVE.get((self.mid, rid))
        if state is None:
            bar.setVisible(False)
            mb.setVisible(False)
            b_cancel.setVisible(False)
            b_cancel.setText("取消")
            b_dl.setEnabled(True)
            return
        bar.setVisible(True)
        mb.setVisible(True)
        total = int(state.get("total") or 0)
        done = int(state.get("done") or 0)
        if total > 0:
            bar.setRange(0, 100)
            bar.setValue(max(0, min(100, int(done * 100 / total))))
            mb.setText(f"{_mb(done) or '0 KB'} / {_mb(total)}")
        else:
            bar.setRange(0, 0)
            mb.setText(f"已下载 {_mb(done) or '0 KB'}")
        b_cancel.setVisible(True)
        if state["cancel"].is_set():
            b_cancel.setText("取消中…")
            b_cancel.setEnabled(False)
        else:
            b_cancel.setText("取消")
            b_cancel.setEnabled(True)
        b_dl.setEnabled(False)

    def _cancel(self, rid: str) -> None:
        state = _ACTIVE.get((self.mid, rid))
        if state is None:
            return
        state["cancel"].set()
        self.hint.setText("正在取消…")
        self._sync_row(rid)

    def _poll(self) -> None:
        for rid in list(self._rows):
            self._sync_row(rid)

    def _install(self, r: dict) -> None:
        rid = str(r.get("id"))
        name = str(r.get("name") or rid)
        ans = QMessageBox.question(
            self, "安装官方程序",
            f"接下来会打开「{name}」的官方安装程序。安装由你完成，"
            "启动器不会替你点“下一步”、不会代勾协议，也不分发这个程序。是否继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans != QMessageBox.Yes:
            return
        try:
            res = pbab.start_installer(self.mid, rid)
        except Exception as exc:  # noqa: BLE001
            self.hint.setText(f"打开安装程序失败：{exc}")
            return
        if isinstance(res, dict) and res.get("cancelled"):
            self.hint.setText("已取消（没有打开安装程序）")
            return
        self.changed = True
        self._watch_started = time.time()
        self._watch.start()
        self.reload()
        self.hint.setText("安装程序已打开，等待安装完成…")

    def _ensure_watch(self) -> None:
        try:
            items = pbab.require_status(self.mid)
        except Exception:  # noqa: BLE001
            log.debug("读取模组依赖状态失败", exc_info=True)
            return
        installing = any(str(r.get("state")) == "installing" for r in items)
        if installing:
            if not self._watch.isActive():
                self._watch_started = time.time()
                self._watch.start()
        elif self._watch.isActive():
            self._watch.stop()

    def _check_installing(self) -> None:
        try:
            items = pbab.require_status(self.mid)
        except Exception:  # noqa: BLE001
            self._watch.stop()
            return
        installing = [r for r in items if str(r.get("state")) == "installing"]
        if not installing:
            self._watch.stop()
            return
        if time.time() - self._watch_started > 15 * 60:
            self._watch.stop()
            self.hint.setText("安装程序可能还没完成；装好后点「重新检测」或「选择已装路径…」")
            return
        done = False
        for r in installing:
            path = str(r.get("installed_path") or "")
            if not path:
                continue
            try:
                pbab.complete_install(self.mid, str(r.get("id")), path)
                done = True
            except Exception as exc:  # noqa: BLE001
                self.hint.setText(f"登记失败：{exc}")
        if done:
            self.changed = True
            self.reload()
            self.hint.setText("安装完成，已登记路径。")

    def _pick(self, r: dict) -> None:
        rid = str(r.get("id"))
        start = str(r.get("path") or "")
        chosen = QFileDialog.getExistingDirectory(self, f"选择「{r.get('name') or rid}」所在的目录",
                                                 start or str(Path.home()))
        if not chosen:
            return
        try:
            pbab.set_require_path(self.mid, rid, chosen)
        except Exception as exc:  # noqa: BLE001
            self.hint.setText(f"登记失败：{exc}")
            return
        self.changed = True
        self.reload()
