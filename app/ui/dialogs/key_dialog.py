"""只改模型 / Key / 地址的小窗口。

为什么单独做一个：向导会把人格整份重写一遍，改个 Key 却顺手把人格洗了，
这不是使用者要的。这里只写 llm.json 的三个字段，人格不动。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from ...core import framework_setup
from ...services.worker import run_async


class KeyDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("模型与 API Key")
        self.setMinimumWidth(470)
        self.saved = False

        cfg = framework_setup.read_llm()
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        tip = QLabel("只改模型连接，不动人格。Key 只存在本机的 entity\\config\\llm.json。")
        tip.setObjectName("Muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        form = QFormLayout()
        form.setSpacing(8)
        self.ed_key = QLineEdit(str(cfg.get("api_key") or ""))
        self.ed_key.setEchoMode(QLineEdit.Password)
        self.ed_key.setPlaceholderText("sk-…")
        self.ed_base = QLineEdit(str(cfg.get("api_base") or "https://api.deepseek.com/v1"))
        self.ed_model = QLineEdit(str(cfg.get("model") or "deepseek-chat"))
        form.addRow("API Key", self.ed_key)
        form.addRow("API 地址", self.ed_base)
        form.addRow("模型", self.ed_model)
        lay.addLayout(form)

        self.hint = QLabel("")
        self.hint.setObjectName("Muted")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save = QPushButton("验证并保存", objectName="Primary")
        self.btn_save.clicked.connect(self._save)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_save)
        lay.addLayout(row)

    # ------------------------------------------------------------------
    def _busy(self, busy: bool, msg: str = "") -> None:
        self.btn_save.setEnabled(not busy)
        self.btn_cancel.setEnabled(not busy)
        self.hint.setText(msg)

    def _save(self) -> None:
        key = self.ed_key.text().strip()
        base = self.ed_base.text().strip()
        model = self.ed_model.text().strip()
        if not key:
            self.hint.setText("Key 是空的。")
            return
        self._busy(True, "正在验证…")

        def ok(res) -> None:
            good, msg = res
            if not good:
                self._busy(False, f"验证没通过：{msg}")
                return
            try:
                framework_setup.save_llm(api_key=key, api_base=base, model=model)
            except Exception as e:  # noqa: BLE001
                self._busy(False, f"写入失败：{e}")
                return
            self.saved = True
            self.accept()

        def err(e) -> None:
            self._busy(False, f"验证没做完：{e}")

        run_async(lambda: framework_setup.probe_key(key, base, model),
                  on_ok=ok, on_err=err)
