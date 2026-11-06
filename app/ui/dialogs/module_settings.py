"""模组设置对话框：上面是介绍（introduce.md），下面是按 schema 生成的开关。"""
from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox, QTextBrowser,
    QVBoxLayout, QWidget,
)

from ...core import pbab, registry


class ModuleSettingsDialog(QDialog):
    def __init__(self, mid: str, parent=None) -> None:
        super().__init__(parent)
        mod = registry.get(mid) or {}
        self.mid = mid
        self.setWindowTitle(f"模组设置 · {mod.get('name') or mid}")
        self.resize(640, 620)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(10)

        head = QLabel(f"{mod.get('name') or mid}  v{mod.get('version') or '?'}", objectName="CardTitle")
        outer.addWidget(head)

        intro = QTextBrowser()
        intro.setOpenExternalLinks(True)
        intro.setMarkdown(pbab.read_introduce(mid))
        intro.setMinimumHeight(180)
        outer.addWidget(QLabel("介绍（给你看的；智能体在提示词里读的是 agent.md / persona.md）", objectName="Muted"))
        outer.addWidget(intro, 1)

        self.fields = pbab.settings_fields(mid)
        self.widgets: Dict[str, Any] = {}
        if self.fields:
            outer.addWidget(QLabel("模组设置", objectName="Muted"))
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            box = QWidget()
            form = QFormLayout(box)
            form.setLabelAlignment(Qt.AlignLeft)
            current = (mod.get("settings") or {})
            for f in self.fields:
                key = str(f.get("key"))
                raw_type = str(f.get("type") or "boolean").lower()
                # JSON-Schema 用 boolean/integer/number/enum，旧写法用 bool/int/choice；两种都认
                if raw_type in ("bool", "boolean"):
                    ftype = "bool"
                elif raw_type in ("int", "integer"):
                    ftype = "int"
                elif raw_type in ("number", "float"):
                    ftype = "float"
                elif raw_type in ("choice", "select", "enum") or f.get("enum") or f.get("options") or f.get("choices"):
                    ftype = "choice"
                elif raw_type in ("array", "object"):
                    continue
                else:
                    ftype = "text"
                label = str(f.get("label") or f.get("title") or key)
                default = f.get("default")
                val = current.get(key, default)
                if ftype == "bool":
                    w = QCheckBox()
                    w.setChecked(bool(val))
                    w.setFixedWidth(56)
                elif ftype == "choice":
                    w = QComboBox()
                    for opt in (f.get("options") or f.get("choices") or f.get("enum") or []):
                        if isinstance(opt, dict):
                            w.addItem(str(opt.get("label") or opt.get("value")), opt.get("value"))
                        else:
                            w.addItem(str(opt), opt)
                    idx = w.findData(val)
                    w.setCurrentIndex(max(0, idx))
                elif ftype == "int":
                    w = QSpinBox()
                    w.setFixedWidth(160)
                    lo = f.get("min", f.get("minimum", 0))
                    hi = f.get("max", f.get("maximum", 9999))
                    w.setRange(int(lo), int(hi))
                    w.setValue(int(val or 0))
                elif ftype == "float":
                    w = QDoubleSpinBox()
                    w.setFixedWidth(160)
                    lo = float(f.get("min", f.get("minimum", 0)) or 0)
                    hi = float(f.get("max", f.get("maximum", 9999)) or 9999)
                    w.setRange(lo, hi)
                    w.setDecimals(3 if hi <= 1 else 2)
                    w.setSingleStep(0.01 if hi <= 1 else 0.1)
                    try:
                        w.setValue(float(val or 0))
                    except (TypeError, ValueError):
                        w.setValue(0.0)
                else:
                    w = QLineEdit(str(val or ""))
                tip = str(f.get("help") or f.get("description") or "")
                if tip:
                    w.setToolTip(tip)
                self.widgets[key] = (ftype, w)
                form.addRow(label, w)
            scroll.setWidget(box)
            outer.addWidget(scroll, 1)
        else:
            outer.addWidget(QLabel("这个模组没有可调的设置项。", objectName="Muted"))

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("取消", objectName="Ghost")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存")
        save.clicked.connect(self._save)
        row.addWidget(cancel)
        row.addWidget(save)
        outer.addLayout(row)

    def _save(self) -> None:
        values: Dict[str, Any] = {}
        for key, (ftype, w) in self.widgets.items():
            if ftype == "bool":
                values[key] = bool(w.isChecked())
            elif ftype == "choice":
                values[key] = w.currentData()
            elif ftype == "int":
                values[key] = int(w.value())
            elif ftype == "float":
                values[key] = float(w.value())
            else:
                values[key] = w.text().strip()
        try:
            pbab.save_settings(self.mid, values)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "没保存", f"模组设置没保存：\n{exc}")
            return
        self.accept()
