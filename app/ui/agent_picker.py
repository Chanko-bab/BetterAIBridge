"""启动前的智能体选择窗口。

启动器每次打开先经过这里：选一个智能体，或者新建一个。选定后才进主窗口；
主窗口不再提供智能体管理页，只留“退出到选择界面”。
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from ..core import agent_paths, agents, framework_setup
from ..core.agents import AgentError
from .pages.agents import NewAgentDialog
from .widgets.see_through import see_through


def _when(raw: str) -> str:
    raw = str(raw or "").strip()
    if not raw:
        return "还没用过"
    try:
        return time.strftime(
            "%m-%d %H:%M", time.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return raw[:16]


class AgentPicker(QDialog):
    """类似账号选择：先选人，再进主界面。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.selected = ""
        self._rows: list[Dict[str, Any]] = []
        self._legacy = False
        self.setWindowTitle("选择智能体")
        self.setModal(True)
        self.setMinimumSize(560, 420)
        self.resize(680, 540)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        try:
            self._rows = agents.scan()
        except (OSError, ValueError) as exc:
            self._rows = []
            self.setToolTip(f"读取智能体列表失败：{exc}")
        legacy_dir = agent_paths.install_root() / "WiseEntity" / "entity"
        self._legacy = (
            not self._rows
            and not agent_paths.agent_id()
            and legacy_dir.is_dir()
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 18)
        outer.setSpacing(12)

        outer.addWidget(QLabel("选择智能体", objectName="PageTitle"))
        hint = QLabel(
            "每次打开都先从这里进入。Key、人格、记忆和仓库各自独立，"
            "模组同一时间只归一个智能体。",
            objectName="Muted")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        self.scroll = QScrollArea(objectName="SettingsScroll")
        see_through(self.scroll)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.body = QWidget()
        self.lay = QVBoxLayout(self.body)
        self.lay.setContentsMargins(0, 2, 8, 2)
        self.lay.setSpacing(10)
        self.scroll.setWidget(self.body)
        outer.addWidget(self.scroll, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.btn_new = QPushButton("新建智能体", objectName="Primary")
        self.btn_new.setCursor(Qt.PointingHandCursor)
        self.btn_new.clicked.connect(self._new)
        bottom.addWidget(self.btn_new)
        bottom.addStretch(1)
        self.btn_cancel = QPushButton("取消", objectName="Ghost")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(self.btn_cancel)
        outer.addLayout(bottom)

        self._fill()

    # ---------- 渲染 ----------
    def _fill(self) -> None:
        while self.lay.count():
            item = self.lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        active = agents.active_slug()
        for row in self._rows:
            self.lay.addWidget(self._card(row, active))
        if self._legacy:
            self.lay.addWidget(self._legacy_card())
        if not self._rows and not self._legacy:
            empty = QLabel("还没有智能体。点下面的“新建智能体”开始。", objectName="Muted")
            empty.setWordWrap(True)
            self.lay.addWidget(empty)
        self.lay.addStretch(1)

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
        text.addWidget(QLabel(
            f"id: {slug} · 最近使用 {_when(row.get('last_used'))}",
            objectName="Muted"))
        box.addLayout(text, 1)

        enter = QPushButton("进入", objectName="Primary")
        enter.setCursor(Qt.PointingHandCursor)
        enter.clicked.connect(lambda _=False, s=slug: self._pick(s))
        box.addWidget(enter)

        danger = QPushButton("删除", objectName="Ghost")
        danger.setCursor(Qt.PointingHandCursor)
        if slug == active:
            danger.setEnabled(False)
            danger.setToolTip("正在使用的智能体不能删；先进入别的再回来删。")
        else:
            danger.clicked.connect(lambda _=False, s=slug: self._trash(s))
        box.addWidget(danger)
        return card

    def _legacy_card(self) -> QWidget:
        raw_name = ""
        try:
            raw_name = str(framework_setup.display_name() or "").strip()
        except (OSError, ValueError):
            raw_name = ""
        name = raw_name or "旧数据"
        card = QFrame(objectName="Card")
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 14, 16, 14)
        box.setSpacing(6)
        box.addWidget(QLabel(f"{name}（旧单目录）", objectName="CardTitle"))
        copy = QLabel(
            "现在的 Key、人格、记忆仍在 WiseEntity\\entity 里。"
            "先进旧目录也可以；迁移后才会在这里出现多个智能体。",
            objectName="Muted")
        copy.setWordWrap(True)
        box.addWidget(copy)
        row = QHBoxLayout()
        enter = QPushButton("进入旧目录", objectName="Primary")
        enter.setCursor(Qt.PointingHandCursor)
        enter.clicked.connect(lambda: self._pick(""))
        row.addWidget(enter)
        help_btn = QPushButton("看看怎么迁移", objectName="Ghost")
        help_btn.setCursor(Qt.PointingHandCursor)
        help_btn.clicked.connect(self._migration_help)
        row.addWidget(help_btn)
        row.addStretch(1)
        box.addLayout(row)
        return card

    # ---------- 动作 ----------
    def _pick(self, slug: str) -> None:
        self.selected = slug
        self.accept()

    def _new(self) -> None:
        dlg = NewAgentDialog(self)
        if not dlg.exec() or not dlg.slug:
            return
        self.selected = dlg.slug
        self.accept()

    def _trash(self, slug: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        if slug == agents.active_slug():
            QMessageBox.information(
                self, "先切走", "这个智能体正在使用。先进入别的智能体，再回来删它。")
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
        self._rows = agents.scan()
        self._legacy = (
            not self._rows
            and not agent_paths.agent_id()
            and (agent_paths.install_root() / "WiseEntity" / "entity").is_dir()
        )
        self._fill()

    def _migration_help(self) -> None:
        from PySide6.QtWidgets import QMessageBox

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
