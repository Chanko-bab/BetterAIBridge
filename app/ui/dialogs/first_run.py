"""首次启动：填名字 + API Key（没有 key 就不让聊）。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QPlainTextEdit,
    QVBoxLayout,
)

from ...core import framework_setup
from ...services.core_client import CoreClient
from ...services.worker import run_async


class FirstRunDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.saved = False
        self.setWindowTitle("先把自己配出来")
        self.setMinimumWidth(520)

        lay = QVBoxLayout(self)
        tip = QLabel("这是一份空框架：还没有名字、没有人格、没有记忆。\n"
                     "填完这两样，智能体才能开口说话。", objectName="Muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        cfg = framework_setup.read_llm()
        form = QFormLayout()
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("比如：阿岚")
        self.ed_key = QLineEdit(str(cfg.get("api_key") or ""))
        self.ed_key.setEchoMode(QLineEdit.Password)
        self.ed_key.setPlaceholderText("sk-...")
        self.ed_base = QLineEdit(str(cfg.get("api_base") or "https://api.deepseek.com/v1"))
        self.ed_model = QLineEdit(str(cfg.get("model") or "deepseek-chat"))
        form.addRow("名字", self.ed_name)
        form.addRow("API Key", self.ed_key)
        form.addRow("API 地址", self.ed_base)
        form.addRow("模型", self.ed_model)
        lay.addLayout(form)

        lay.addWidget(QLabel("人格（留空就用模板，之后可以改 entity/persona/persona.md）", objectName="Muted"))
        self.ed_persona = QPlainTextEdit()
        self.ed_persona.setPlaceholderText("留空 = 用模板；也可以直接写……")
        self.ed_persona.setMinimumHeight(120)
        lay.addWidget(self.ed_persona)

        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Save).setText("保存并开始")
        box.button(QDialogButtonBox.Cancel).setText("稍后")
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def _save(self) -> None:
        name = self.ed_name.text().strip()
        key = self.ed_key.text().strip()
        persona = self.ed_persona.toPlainText().strip()
        if not name and not persona:
            self.ed_name.setFocus()
            return
        framework_setup.save(
            api_key=key,
            api_base=self.ed_base.text().strip(),
            model=self.ed_model.text().strip(),
            entity_name=name,
            persona=persona,
        )
        self.saved = True
        # 内核在跑就顺手同步一份（内核读的是同一批文件，失败也无所谓）
        run_async(lambda: CoreClient().post("/setup", {
            "api_key": key, "api_base": self.ed_base.text().strip(),
            "model": self.ed_model.text().strip(),
            "entity_name": name, "persona": persona,
        }), on_ok=lambda _r: None, on_err=lambda _e: None)
        self.accept()
