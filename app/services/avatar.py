"""智能体头像：一张方形图，存在 entity/config/avatar.png。

为什么要单独一个文件：壳上要用它（侧栏头像卡、资料弹窗、启动动画），
内核也要知道它（提示词里告诉她"这是你现在的样子"）。两边都按同一个约定读
entity/config/avatar.json，谁都不用去问对方。

* 默认头像是 assets/bab-256.png（内置灰发头像），不写进 config，删掉自定义图就回到它；
* 自定义图统一裁成 256×256 PNG，原图不动；
* avatar.json 记谁换的、什么时候换的、原图大小——提示词只念这几句。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap

SIZE = 256
MAX_SRC_BYTES = 12 * 1024 * 1024


def _assets() -> Path:
    return Path(__file__).resolve().parents[2] / "assets"


def default_path() -> Path:
    return _assets() / "bab-256.png"


def _cfg_dir() -> Path:
    from ..core import config

    d = config.entity_dir() / "config"
    d.mkdir(parents=True, exist_ok=True)
    return d


def custom_path() -> Path:
    return _cfg_dir() / "avatar.png"


def meta_path() -> Path:
    return _cfg_dir() / "avatar.json"


def is_custom() -> bool:
    return custom_path().is_file()


def current_path() -> Path:
    p = custom_path()
    return p if p.is_file() else default_path()


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
    """给界面和内核共用的一份说明。"""
    data = meta()
    return {
        "custom": is_custom(),
        "path": str(current_path()),
        "updated_at": str(data.get("updated_at") or ""),
        "updated_by": str(data.get("updated_by") or ""),
        "source": str(data.get("source") or ""),
    }


def pixmap(size: int = 96) -> QPixmap:
    """按方形取一张；读不出来就退默认图，再读不出返回空图。"""
    for p in (current_path(), default_path()):
        pm = QPixmap(str(p))
        if not pm.isNull():
            return pm.scaled(int(size), int(size), Qt.KeepAspectRatioByExpanding,
                             Qt.SmoothTransformation)
    return QPixmap()


def set_from_file(src: str | Path, by: str = "主人") -> Path:
    """把用户选的图裁方、缩到 256，写成 avatar.png；返回新路径。"""
    src = Path(src)
    if not src.is_file():
        raise ValueError("找不到这个图片文件。")
    if src.stat().st_size > MAX_SRC_BYTES:
        raise ValueError("图片太大了（超过 12 MB），换一张小一点的。")
    img = QImage(str(src))
    if img.isNull():
        raise ValueError("这张图读不出来，换 PNG/JPG 试试。")
    w, h = img.width(), img.height()
    if w <= 0 or h <= 0:
        raise ValueError("这张图是空的。")
    side = min(w, h)
    img = img.copy((w - side) // 2, (h - side) // 2, side, side)
    img = img.scaled(SIZE, SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    dst = custom_path()
    tmp = dst.with_suffix(".tmp.png")
    if not img.save(str(tmp), "PNG"):
        raise ValueError("保存头像失败。")
    tmp.replace(dst)
    meta_path().write_text(json.dumps({
        "updated_at": time.strftime("%Y-%m-%d %H:%M"),
        "updated_by": by,
        "source": src.name,
        "source_bytes": src.stat().st_size,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return dst


def reset() -> None:
    for p in (custom_path(), meta_path()):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
