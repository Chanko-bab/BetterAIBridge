"""内核侧的头像信息：只读 entity/config/avatar.json，不碰界面。

壳（启动器）负责换头像、写文件；内核负责让她"知道"——提示词一段、桥一个能力、
工具一个 avatar_see。三处都从这一个文件读，避免各说各话。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from . import settings as S

DEFAULT_NAME = "灰发头像"


def config_dir() -> Path:
    return S.ENTITY / "config"


def custom_path() -> Path:
    return config_dir() / "avatar.png"


def meta_path() -> Path:
    return config_dir() / "avatar.json"


def meta() -> Dict[str, Any]:
    p = meta_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def info() -> Dict[str, Any]:
    data = meta()
    custom = custom_path().is_file()
    return {
        "custom": custom,
        "default": DEFAULT_NAME,
        "path": str(custom_path() if custom else (S.APP_ROOT / "assets" / "bab-256.png")),
        "updated_at": str(data.get("updated_at") or ""),
        "updated_by": str(data.get("updated_by") or ""),
        "source": str(data.get("source") or ""),
    }


def fragment() -> str:
    """提示词里的那一小段；默认头像不描述长相，也不给看它的口子。"""
    one = info()
    if not one["custom"]:
        return (
            "# 你的头像\n"
            "我还没换过自己的头像。现在用的是程序默认的占位图，"
            "那张图不是我，我也看不到它；\n"
            "不要拿它来描述自己，也不要把它当成自己的样子。\n"
            "等对方给我换过头像，我才能看。\n"
        )
    when = one.get("updated_at") or "最近"
    who = one.get("updated_by") or "对方"
    return (
        "# 你的头像\n"
        "对方给我换过头像了。现在的头像是一张方形图片，文件在：\n"
        f"{one['path']}\n"
        f"（{who} 在 {when} 换的。）\n"
        "想看自己现在的样子，可以调 avatar_see；别人问起时，照你看到的和这张图的来历说。\n"
    )
