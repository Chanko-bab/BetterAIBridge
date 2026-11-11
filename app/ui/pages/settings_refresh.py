"""设置页首屏刷新：先把页面画出来，再逐张卡去读状态。"""
from __future__ import annotations

import os

from PySide6.QtCore import QTimer


class RefreshActionsMixin:
    def schedule_settings_refresh(self) -> None:
        if os.environ.get("BAB_NO_ANIM"):
            self.refresh_settings_cards()
        else:
            QTimer.singleShot(0, self.refresh_settings_cards)

    def refresh_settings_cards(self) -> None:
        for fn in (self.refresh_model, self.refresh_ports, self.refresh_bridge,
                   self.refresh_stomach, self.refresh_memory, self.refresh_voice,
                   self.refresh_followup, self.refresh_startup, self.refresh_asr,
                   self.refresh_sense, self.refresh_warehouse):
            fn()
