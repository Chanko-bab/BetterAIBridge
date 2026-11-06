"""服务页：只观测 + 调用既有脚本（不重写启动逻辑）。

0.4.3 起多了两件事：
- **端口占用**：谁占了核心/语音/端口池，按 PID 和进程名摊开；外面来的进程可以手动结束。
- **一键重启**：核心、语音各自「杀掉本服务进程 → 重新跑启动脚本」，不用先停全部。
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import QProcess, QTimer
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ...core import config, logger, registry
from ...core.events import bus
from ...services.worker import run_async

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None

SERVICES = [
    ("core", "内核 entity_core", 40720, "start_core"),
    ("asr", "语音 ASR", 40715, "start_asr"),
    ("tts", "朗读 TTS（edge-tts，在线）", "—", None),
]


def install_base() -> int:
    """本安装的端口池起点（config/install.json 的 base，缺省 40720）。"""
    try:
        doc = json.loads((config.APP_DIR / "config" / "install.json").read_text(encoding="utf-8-sig"))
        return int(doc.get("base") or 40720)
    except Exception:  # noqa: BLE001
        return 40720


def listening_map() -> dict[int, tuple[int, str]]:
    """一次扫描拿到「哪些端口在听、归谁」——别在循环里反复扫。"""
    out: dict[int, tuple[int, str]] = {}
    if psutil is not None:
        try:
            for c in psutil.net_connections(kind="inet"):
                try:
                    if c.status != psutil.CONN_LISTEN or not c.laddr:
                        continue
                    port = int(c.laddr.port)
                    pid = int(c.pid or 0)
                    name = ""
                    if pid:
                        try:
                            name = psutil.Process(pid).name()
                        except psutil.Error:
                            name = "?"
                    out[port] = (pid, name)
                except (ValueError, IndexError):
                    continue
            return out
        except (psutil.Error, OSError):
            pass
    try:
        res = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True,
                             text=True, timeout=5, errors="ignore")
        for line in (res.stdout or "").splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[3].upper() == "LISTENING" and ":" in parts[1]:
                try:
                    out[int(parts[1].rsplit(":", 1)[1])] = (int(parts[4]), "")
                except (ValueError, IndexError):
                    continue
    except (OSError, subprocess.SubprocessError):
        pass
    return out


def port_owner(port: int) -> tuple[int, str]:
    """谁在 LISTEN 这个端口：返回 (pid, 进程名)；没有就 (0, "")。"""
    if not port:
        return 0, ""
    return listening_map().get(int(port), (0, ""))


def kill_pid(pid: int, wait: float = 3.0) -> bool:
    """结束一个进程；当前程序自己绝不杀。"""
    if not pid or pid == os.getpid():
        return False
    if psutil is None:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=8)
            return True
        except Exception:  # noqa: BLE001
            return False
    try:
        p = psutil.Process(pid)
        p.terminate()
        try:
            p.wait(timeout=wait)
        except Exception:  # noqa: BLE001
            p.kill()
        return True
    except Exception:  # noqa: BLE001
        return False


class ServicesPage(QWidget):
    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        self.log = logger.get()
        self.procs: list[QProcess] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 16, 22, 16)
        outer.setSpacing(12)
        outer.addWidget(QLabel("服务", objectName="CardValue"))
        outer.addWidget(QLabel("现在只装内核与语音；模组在 program_cache 里，装了才有。",
                               objectName="Muted"))

        card = QFrame(objectName="Card")
        grid = QGridLayout(card)
        grid.setContentsMargins(16, 12, 16, 14)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        for col, h in enumerate(["服务", "端口", "状态", "启动 / 重启"]):
            grid.addWidget(QLabel(h, objectName="CardTitle"), 0, col)

        self.rows: dict[str, tuple[QLabel, QPushButton, QPushButton]] = {}
        for i, (key, name, port, cfg_key) in enumerate(SERVICES, start=1):
            grid.addWidget(QLabel(name), i, 0)
            grid.addWidget(QLabel(str(port), objectName="Muted"), i, 1)
            status = QLabel("—", objectName="Muted")
            grid.addWidget(status, i, 2)
            box = QHBoxLayout()
            box.setSpacing(8)
            btn = QPushButton("启动", objectName="Ghost")
            restart = QPushButton("重启", objectName="Ghost")
            if cfg_key is None:
                btn.setText("随内核")
                btn.setEnabled(False)
                restart.setEnabled(False)
            else:
                btn.clicked.connect(lambda _=False, k=cfg_key: self.launch(k))
                restart.clicked.connect(lambda _=False, k=key: self.restart_service(k))
            box.addWidget(btn)
            box.addWidget(restart)
            box.addStretch(1)
            holder = QWidget()
            holder.setLayout(box)
            grid.addWidget(holder, i, 3)
            self.rows[key] = (status, btn, restart)

        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(2, 1)
        outer.addWidget(card)

        # ---- 端口占用 ----
        pcard = QFrame(objectName="Card")
        pv = QVBoxLayout(pcard)
        pv.setContentsMargins(16, 12, 16, 14)
        pv.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(QLabel("端口占用", objectName="CardTitle"))
        head.addStretch(1)
        self.btn_refresh_ports = QPushButton("刷新", objectName="Ghost")
        self.btn_refresh_ports.clicked.connect(self.refresh_ports_table)
        head.addWidget(self.btn_refresh_ports)
        pv.addLayout(head)
        pv.addWidget(QLabel(
            "本程序自己的端口会标出来；端口池里被别的程序占着的，也可以在这里结束它（会先问你）。",
            objectName="Muted", wordWrap=True))
        self.port_box = QVBoxLayout()
        self.port_box.setSpacing(4)
        pv.addLayout(self.port_box)
        outer.addWidget(pcard)

        tools = QHBoxLayout()
        for text, slot in [
            ("启动全部（脚本）", self.start_all),
            ("停止全部（脚本）", self.stop_all),
            ("打开program_cache", self.open_modules),
            ("打开项目文件夹", self.open_root),
        ]:
            b = QPushButton(text, objectName="Primary" if "全部" in text else "Ghost")
            b.clicked.connect(slot)
            tools.addWidget(b)
        tools.addStretch(1)
        outer.addLayout(tools)

        self.hint = QLabel("", objectName="Muted")
        self.hint.setWordWrap(True)
        outer.addWidget(self.hint)
        outer.addStretch(1)

        bus.ports_changed.connect(self.on_ports)
        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self.refresh_ports_table)
        self.refresh_ports_table()

    # ---------------------------------------------------------------- 显隐

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        self._timer.start()
        self.refresh_ports_table()

    def hideEvent(self, ev) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(ev)

    # ---------------------------------------------------------------- 状态

    def on_ports(self, info: dict) -> None:
        ports = info.get("ports") or {}
        for key, (status, _btn, _restart) in self.rows.items():
            if key == "tts":
                up = bool(ports.get("core"))
                status.setText("可用" if up else "内核没起")
                status.setStyleSheet("color:#1a9d5b;" if up else "color:#c2402f;")
                continue
            up = bool(ports.get(key))
            status.setText("在线" if up else "离线")
            status.setStyleSheet("color:#1a9d5b;" if up else "color:#c2402f;")

    # ---------------------------------------------------------------- 端口表

    def _port_rows(self, owners: dict[int, tuple[int, str]]) -> list[tuple[int, str, str]]:
        """(端口, 归属, 类别)；类别：core / asr / module / pool。"""
        base = install_base()
        mods: dict[int, str] = {}
        try:
            for m in registry.modules():
                port = int(m.get("runtime_port") or 0)
                if port:
                    mods[port] = str(m.get("name") or m.get("id") or "模组")
        except (OSError, ValueError, TypeError):
            pass
        rows: list[tuple[int, str, str]] = []
        for key, _name, port, _cfg in SERVICES:
            if key == "tts":
                continue
            label = "本程序 · 核心" if key == "core" else "本程序 · 语音"
            rows.append((int(port), label, key))
        for p in range(base + 5, base + 20):
            if p in mods:
                rows.append((p, f"模组 · {mods[p]}", "module"))
            elif owners.get(p, (0, ""))[0]:
                rows.append((p, "端口池 · 未知占用", "pool"))
        for p, name in mods.items():
            if p not in [r[0] for r in rows]:
                rows.append((p, f"模组 · {name}", "module"))
        return rows

    def _clear_ports(self) -> None:
        while self.port_box.count():
            item = self.port_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def refresh_ports_table(self) -> None:
        self._clear_ports()
        try:
            owners = listening_map()
            rows = self._port_rows(owners)
        except Exception as exc:  # noqa: BLE001
            self.port_box.addWidget(QLabel(f"读不到端口：{exc}", objectName="Muted"))
            return
        if not rows:
            self.port_box.addWidget(QLabel("没有要看的端口。", objectName="Muted"))
            return
        for port, label, kind in rows:
            pid, name = owners.get(port, (0, ""))
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(10)
            lay.addWidget(QLabel(f"{port}", objectName="Muted"))
            lay.addWidget(QLabel(label), 1)
            if pid:
                who = f"{name or '未知进程'}（PID {pid}）"
                lay.addWidget(QLabel(who, objectName="Muted"))
                if kind == "pool":
                    b = QPushButton("结束…", objectName="Danger")
                    b.clicked.connect(lambda _=False, p=pid, pt=port: self.confirm_kill(p, pt))
                    lay.addWidget(b)
            else:
                lay.addWidget(QLabel("空闲", objectName="Muted"))
            self.port_box.addWidget(row)

    def confirm_kill(self, pid: int, port: int) -> None:
        yes = QMessageBox.question(
            self, "结束占用进程",
            f"端口 {port} 被 PID {pid} 占着。\n\n结束它？\n"
            "如果不是 BAB 自己的进程，可能影响别的程序。",
        )
        if yes != QMessageBox.Yes:
            return

        def work() -> bool:
            return kill_pid(pid)

        def ok(res) -> None:
            self.hint.setText("已结束" if res else "没结束成功（可能权限不够，或它已经退了）")
            self.refresh_ports_table()

        run_async(work, ok, lambda e: self.hint.setText(f"结束失败：{e}"))

    # ---------------------------------------------------------------- 启动 / 重启

    def _run(self, program: str, args: list[str], label: str) -> None:
        p = QProcess(self)
        p.setProgram(program)
        p.setArguments(args)
        p.readyReadStandardOutput.connect(lambda: self._drain(p, label))
        p.readyReadStandardError.connect(lambda: self._drain(p, label))
        p.finished.connect(lambda code, _s: self._done(label, code))
        p.start()
        self.procs.append(p)
        self.hint.setText(f"已执行：{label}")
        self.log.info("执行 %s（%s）", label, program)

    def _drain(self, p: QProcess, label: str) -> None:
        data = bytes(p.readAllStandardOutput()) + bytes(p.readAllStandardError())
        if data:
            text = data.decode("utf-8", "replace").strip()
            if text:
                self.log.info("[%s] %s", label, text[:400])

    def _done(self, label: str, code: int) -> None:
        self.hint.setText(f"{label} 结束（exit {code}）")
        self.refresh_ports_table()

    def launch(self, cfg_key: str) -> None:
        target = str(config.get(cfg_key, ""))
        if not target or not os.path.exists(target):
            self.hint.setText(f"路径不存在：{target}")
            return
        self._run("cmd.exe", ["/c", target], Path(target).name)
        QTimer.singleShot(1500, self.refresh_ports_table)

    def restart_service(self, key: str) -> None:
        """重启单个服务：先结束占着它端口的进程，再跑它自己的启动脚本。"""
        port = 0
        cfg_key = ""
        name = key
        for k, nm, p, ck in SERVICES:
            if k == key:
                port, cfg_key, name = int(p) if str(p).isdigit() else 0, str(ck or ""), nm
                break
        if not port or not cfg_key:
            return
        pid, _who = port_owner(port)
        yes = QMessageBox.question(
            self, "重启服务",
            f"重启「{name}」？\n\n会先结束占着 {port} 的进程（PID {pid or '无'}），再运行启动脚本。",
        )
        if yes != QMessageBox.Yes:
            return
        self.hint.setText(f"正在重启 {name} …")

        def work() -> bool:
            if pid:
                kill_pid(pid)
            for _ in range(20):
                if not port_owner(port)[0]:
                    break
                time.sleep(0.2)
            return True

        def ok(_res) -> None:
            self.launch(cfg_key)
            self.hint.setText(f"{name} 已重新启动，等它起来……")

        run_async(work, ok, lambda e: self.hint.setText(f"重启失败：{e}"))

    def start_all(self) -> None:
        self._run("powershell.exe",
                  ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                   str(config.get("start_all", ""))], "start-all")

    def stop_all(self) -> None:
        self._run("powershell.exe",
                  ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                   str(config.get("stop_all", ""))], "stop-all")

    def open_modules(self) -> None:
        subprocess.Popen(["explorer.exe", str(config.get("modules_dir"))])

    def open_root(self) -> None:
        subprocess.Popen(["explorer.exe", str(config.get("project_root"))])
