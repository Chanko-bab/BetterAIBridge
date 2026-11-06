# -*- coding: utf-8 -*-
"""自定义底子的 13 维参数：没有模型 Key 时也能落一套可用的初始值和变化强度。"""
from __future__ import annotations

import sys

from app.core import config


def apply(text: str) -> dict:
    """把一段自定义性格写进 custom_style.json / emotion_profile.json / llm.json。"""
    entity = config.entity_dir()
    root = entity.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from core import style_box  # 延迟导入：只有 onboarding 选自定义时才走这里

    doc = style_box.local(text)
    return style_box.apply(doc)
