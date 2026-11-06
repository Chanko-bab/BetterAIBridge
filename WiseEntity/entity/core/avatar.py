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
    """提示词里的那一小段；没有自定义头像时也说清楚"现在是默认的"。"""
    one = info()
    if not one["custom"]:
        return (
            "# 你的头像\n"
            f"我现在的头像还是默认的{DEFAULT_NAME}（灰发、像素风的小女孩头像），主人还没给我换过。\n"
            "想看看自己现在的样子，可以调 avatar_see。\n"
        )
    when = one.get("updated_at") or "最近"
    who = one.get("updated_by") or "主人"
    return (
        "# 你的头像\n"
        "主人给我换过头像了。现在的头像是一张方形图片，文件在：\n"
        f"{one['path']}\n"
        f"（{who} 在 {when} 换的。）\n"
        "想看自己现在的样子，可以调 avatar_see；别人问起时，照你看到的和这张图的来历说。\n"
    )
