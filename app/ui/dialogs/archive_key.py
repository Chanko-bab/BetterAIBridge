# -*- coding: utf-8 -*-
"""存档里 API Key 的两次询问：导出时问要不要带，导入时问缺的 Key 填不填。"""
from __future__ import annotations

from typing import Tuple

from PySide6.QtWidgets import QCheckBox, QInputDialog, QLineEdit, QMessageBox


def ask_include_key(parent) -> Tuple[bool, bool]:
    """导出前问一句。返回 (是否继续, 是否把 Key 打进存档)。"""
    box = QMessageBox(parent)
    box.setWindowTitle("存档")
    box.setText("存档里要不要带上 API Key？")
    box.setInformativeText(
        "不带：拿到存档的人打不开你的模型，换电脑要重填。\n"
        "带上：换电脑直接能用，但把存档发给别人，别人也能用你的额度。")
    box.setIcon(QMessageBox.Question)
    go = box.addButton("存档", QMessageBox.AcceptRole)
    box.addButton("取消", QMessageBox.RejectRole)
    chk = QCheckBox("带上 API Key（默认不带，更安全）")
    chk.setChecked(False)
    box.setCheckBox(chk)
    box.exec()
    return box.clickedButton() is go, bool(chk.isChecked())


def ask_missing_key(parent) -> Tuple[bool, str]:
    """导入前发现存档没带 Key。返回 (是否继续导入, 要补的 Key)。

    没有 Key 的智能体不能说话，所以这里只给两条路：现在填，或取消导入；
    不做「先导入、之后再说」——那等于让人领回一个不能回话的智能体。
    """
    box = QMessageBox(parent)
    box.setWindowTitle("这个存档没带 API Key")
    box.setText("存档里没有模型 Key，导入后智能体不能回话。现在填一个？")
    box.setInformativeText("没有 Key 的智能体是「哑」的；取消导入不会改动现有数据。")
    box.setIcon(QMessageBox.Question)
    fill = box.addButton("现在填", QMessageBox.AcceptRole)
    cancel = box.addButton("取消导入", QMessageBox.RejectRole)
    box.exec()
    hit = box.clickedButton()
    if hit is not fill:
        return False, ""
    key, ok = QInputDialog.getText(
        parent, "填 API Key", "模型服务的 API Key：", QLineEdit.Password)
    if not ok or not str(key).strip():
        return False, ""
    return True, str(key).strip()
