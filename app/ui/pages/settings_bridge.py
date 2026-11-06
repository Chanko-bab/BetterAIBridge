"""设置页的「桥权限」卡：列模组、按能力勾选、失败回滚。"""
from __future__ import annotations

import threading

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel


class BridgeActionsMixin:
    def refresh_bridge(self) -> None:
        from ...services.core_client import CoreClient

        while self.bridge_box.count():
            item = self.bridge_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        def work():  # noqa: ANN202
            try:
                self.bridge_ready.emit(CoreClient().bridge_modules())
            except Exception as e:  # noqa: BLE001
                self.bridge_ready.emit({"ok": False, "error": str(e)})

        # 先清空，再放一句“读取中”，不阻塞界面
        self.bridge_box.addWidget(QLabel("读取中…", objectName="Muted"))
        self._spawn(work)

    def _apply_bridge(self, d: dict) -> None:
        while self.bridge_box.count():
            item = self.bridge_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not d.get("ok"):
            self.bridge_box.addWidget(QLabel(f"（内核没连上：{d.get('error')}）"))
            return
        mods = d.get("modules") or []
        if not mods:
            self.bridge_box.addWidget(QLabel("还没有启用的模组。", objectName="Muted"))
            return
        for m in mods:
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{m.get('name')}（{m.get('id')}）"))
            caps = m.get("caps") or {}
            if not caps:
                row.addWidget(QLabel("没申请任何能力", objectName="Muted"))
            for cap, on in caps.items():
                cb = QCheckBox(str(cap))
                cb.setChecked(bool(on))
                cb.toggled.connect(lambda v, mid=str(m.get("id")), c=str(cap), box=cb:
                                   self._grant(mid, c, v, box))
                row.addWidget(cb)
            row.addStretch(1)
            self.bridge_box.addLayout(row)

    def _grant(self, mid: str, cap: str, allow: bool, box=None) -> None:
        from ...services.core_client import CoreClient

        key = f"grant:{mid}:{cap}"
        seq = int(self._grant_seq.get(key) or 0) + 1
        self._grant_seq[key] = seq
        lock = self._grant_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            self._grant_locks[key] = lock

        def work():
            # 同一个能力的多次快速点击串行执行；排队期间已被更新点击覆盖的旧请求直接跳过。
            with lock:
                if int(self._grant_seq.get(key) or 0) != seq:
                    return None
                return CoreClient(timeout=4).set_grant(mid, cap, allow)

        def failed(e):
            if int(self._grant_seq.get(key) or 0) != seq:
                return
            self.lbl_ports.setToolTip(f"改权限失败：{e}")
            if box is not None:
                try:
                    box.blockSignals(True)
                    box.setChecked(not allow)
                    box.blockSignals(False)
                except Exception:  # noqa: BLE001
                    self.log.debug("回滚桥权限复选框失败", exc_info=True)

        self._spawn(work, on_err=failed, key=key, dedupe=False)
