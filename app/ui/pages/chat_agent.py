"""聊天页在切换智能体后的清理：清空气泡、归零游标、按新人格刷新。"""
from __future__ import annotations

import time
from typing import Any


def reset_chat(page: Any) -> None:
    for row in list(getattr(page, "_bubble_rows", [])):
        try:
            page.msg_lay.removeItem(row)
            while row.count():
                item = row.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()
        except (RuntimeError, AttributeError, TypeError):
            page.log.debug("清旧气泡失败", exc_info=True)
    page._bubble_rows = []
    page._cursor = 0
    page._notice_cursor = time.time()
    page._last_me = ""
    page._pending_echo = 0
    page._pending = False
    page._attach = None
    from ...core import config, framework_setup

    page.session = str(config.get("chat.session", "web:owner"))
    try:
        page.typing.setText("")
        page.notice.setVisible(False)
        page.media_bar.hide()
    except (RuntimeError, AttributeError, TypeError):
        page.log.debug("清聊天状态失败", exc_info=True)
    page.apply_pronoun()
    if framework_setup.is_configured():
        page._maybe_tutorial()
