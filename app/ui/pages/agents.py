"""智能体：列出、创建、切换、删除（先放回收站）。

切换本身不在这里做：页面只把 slug 交给主窗口，由主窗口统一停内核/模组、
换 env、再拉起来；否则两个地方各停各的，很容易把旧进程漏掉。
"""
from __future__ import annotations

import time
from typing import Any, Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ...core import agent_paths, agents
from ...core.agents import AgentError
from ..widgets.see_through import see_through


def _when(raw: str) -> str:
    raw = str(raw or "").strip()
    if not raw:
        return "还没用过"
    try:
        return time.strftime("%m-%d %H:%M", time.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return raw[:16]


class NewAgentDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("新建智能体")
        self.setMinimumWidth(440)
        self.slug = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        lay.addWidget(QLabel("给新智能体起个名字", objectName="CardTitle"))
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("例如：小林")
        lay.addWidget(self.ed_name)
        lay.addWidget(QLabel("API Key（可以先不填，进去之后再建档）", objectName="Muted"))
        self.ed_key = QLineEdit()
        self.ed_key.setEchoMode(QLineEdit.Password)
        self.ed_key.setPlaceholderText("sk-…（可留空）")
        lay.addWidget(self.ed_key)
        lay.addWidget(QLabel(
            "每个智能体的 Key、人格、记忆、仓库都是分开的；"
            "模组同一时间只归一个智能体。", objectName="Muted"))
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._create)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.ed_name.setFocus()

    def _create(self) -> None:
        name = self.ed_name.text().strip()
        if not name:
            QMessageBox.information(self, "还差一步", "名字不能空着。")
            self.ed_name.setFocus()
            return
        try:
            entry = agents.create_agent(name, api_key=self.ed_key.text().strip())
        except AgentError as exc:
            QMessageBox.warning(self, "没建成", str(exc))
            return
        self.slug = str(entry.get("slug") or "")
        self.accept()


class AgentsPage(QWidget):
    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        self.setObjectName("AgentsPage")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        shell = QVBoxLayout(self)
        shell.setContentsMargins(18, 10, 18, 14)
        shell.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(QLabel("智能体", objectName="PageTitle"))
        head.addStretch(1)
        self.btn_new = QPushButton("新建智能体", objectName="Primary")
        self.btn_new.setCursor(Qt.PointingHandCursor)
        self.btn_new.clicked.connect(self._new_agent)
        head.addWidget(self.btn_new)
        shell.addLayout(head)

        self.hint = QLabel("", objectName="Muted")
        self.hint.setWordWrap(True)
        shell.addWidget(self.hint)

        self.scroll = QScrollArea(objectName="SettingsScroll")
        see_through(self.scroll)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.body = QWidget()
        self.lay = QVBoxLayout(self.body)
        self.lay.setContentsMargins(0, 0, 8, 8)
        self.lay.setSpacing(10)
        self.scroll.setWidget(self.body)
        shell.addWidget(self.scroll, 1)

        self.refresh()

    # ---------- 渲染 ----------
    def refresh(self) -> None:
        while self.lay.count():
            item = self.lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        active = agents.active_slug()
        rows = agents.scan()
        legacy = not agent_paths.agent_id()

        if legacy:
            card = QFrame(objectName="Card")
            box = QVBoxLayout(card)
            box.setContentsMargins(16, 14, 16, 14)
            box.setSpacing(6)
            box.addWidget(QLabel("现在还是旧的单目录模式", objectName="CardTitle"))
            box.addWidget(QLabel(
                "当前仍从 WiseEntity\\entity 读写。迁移会把旧数据备份，再搬到 agents/ 下；"
                "为了不在你聊天时搬文件，迁移要退出启动器后单独跑。", objectName="Muted"))
            btn = QPushButton("看看怎么迁移", objectName="Ghost")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(self._show_migrate_help)
            box.addWidget(btn)
            self.lay.addWidget(card)

        for row in rows:
            self.lay.addWidget(self._card(row, active))
        if not rows and not legacy:
            self.lay.addWidget(QLabel("还没有智能体。点右上角新建一个。", objectName="Muted"))
        self.lay.addStretch(1)
        self.hint.setText(
            "切换会重启内核和模组；正在聊天的那一边会先停掉。"
            "删除只是移到回收站，7 天内还能恢复。")

    def _card(self, row: Dict[str, Any], active: str) -> QWidget:
        slug = str(row.get("slug") or "")
        name = str(row.get("name") or slug)
        card = QFrame(objectName="Card")
        box = QHBoxLayout(card)
        box.setContentsMargins(16, 12, 14, 12)
        box.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(3)
        title = QHBoxLayout()
        title.setSpacing(8)
        title.addWidget(QLabel(name, objectName="CardTitle"))
        if slug == active:
            badge = QLabel("当前", objectName="Muted")
            badge.setStyleSheet("color:#3f7ce8;font-weight:600;")
            title.addWidget(badge)
        if not agents.is_configured(slug):
            title.addWidget(QLabel("未建档", objectName="Muted"))
        title.addStretch(1)
        text.addLayout(title)
        who = f"id: {slug} · 最近使用 {_when(row.get('last_used'))}"
        text.addWidget(QLabel(who, objectName="Muted"))
        box.addLayout(text, 1)

        if slug != active:
            btn = QPushButton("切换", objectName="Primary")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, s=slug: self._switch(s))
            box.addWidget(btn)
        else:
            btn = QPushButton("正在使用", objectName="Ghost")
            btn.setEnabled(False)
            box.addWidget(btn)
        danger = QPushButton("删除", objectName="Ghost")
        danger.setCursor(Qt.PointingHandCursor)
        danger.clicked.connect(lambda _=False, s=slug: self._trash(s))
        box.addWidget(danger)
        return card

    # ---------- 动作 ----------
    def _new_agent(self) -> None:
        dlg = NewAgentDialog(self)
        if not dlg.exec() or not dlg.slug:
            return
        self.refresh()
        self._switch(dlg.slug)

    def _switch(self, slug: str) -> None:
        if not self.win.switch_agent(slug):
            return
        self.refresh()

    def _trash(self, slug: str) -> None:
        if slug == agents.active_slug():
            QMessageBox.information(
                self, "先切走", "这个智能体正在使用。先切到别的智能体，再删它。")
            return
        if QMessageBox.question(
                self, "删除智能体",
                "会把这个智能体移到回收站，7 天内还能恢复。\n"
                "聊天记录、人格和仓库都在里面；API Key 不会导出。\n\n确定删除？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            agents.trash_agent(slug)
        except AgentError as exc:
            QMessageBox.warning(self, "删不掉", str(exc))
            return
        self.refresh()

    def _show_migrate_help(self) -> None:
        import subprocess
        import sys
        from pathlib import Path

        root = agent_paths.install_root()
        py = root / ".venv" / "Scripts" / "python.exe"
        if not py.exists():
            py = Path(sys.executable)
        script = root / "tools" / "migrate_agents.py"
        command = subprocess.list2cmdline(
            [str(py), "-X", "utf8", str(script), "--dry-run"])
        QMessageBox.information(
            self, "迁移旧目录",
            "先在启动器里退出，再运行：\n\n"
            f"{command}\n\n"
            "确认输出后去掉 --dry-run。脚本会先备份 WiseEntity\\entity，"
            "失败会回滚。")

    def on_show(self) -> None:
        self.refresh()
