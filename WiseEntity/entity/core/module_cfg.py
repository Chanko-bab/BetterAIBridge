"""模组设置：读 `program_bundle\\program_<id>.pbab\\settings.json` 的 values。

插件侧用法（需要 sys.path 里有程序根目录）：

    from app.core import module_cfg
    if not module_cfg.enabled("qq_bridge", "moments.enabled", True):
        return

设计：只读、带 mtime 缓存；读不到就返回默认值，绝不让配置问题拦住聊天。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

def _bundle_dir() -> Path:
    """优先读 install.json 的 data_dir（0.4.16+），旧安装仍用程序目录。"""
    app = Path(__file__).resolve().parents[3]
    try:
        doc = json.loads((app / "config" / "install.json").read_text(encoding="utf-8-sig"))
        data = str(doc.get("data_dir") or "").strip()
        if data:
            p = Path(data) / "program_bundle"
            if p.is_dir():
                return p
    except Exception:  # noqa: BLE001
        pass
    return app / "program_bundle"


BUNDLE = _bundle_dir()
_cache: Dict[str, tuple] = {}   # path -> (mtime, values)
_TTL = 60.0


def _settings_path(mid: str) -> Path:
    return BUNDLE / f"program_{mid}.pbab" / "settings.json"


def values(mid: str) -> Dict[str, Any]:
    p = _settings_path(mid)
    try:
        st = p.stat()
    except OSError:
        return {}
    hit = _cache.get(str(p))
    if hit and hit[0] == st.st_mtime and (time.time() - hit[2]) < _TTL:
        return hit[1]
    try:
        doc = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    vals = doc.get("values") if isinstance(doc, dict) else None
    vals = dict(vals) if isinstance(vals, dict) else {}
    _cache[str(p)] = (st.st_mtime, vals, time.time())
    return vals


def value(mid: str, key: str, default: Any = None) -> Any:
    return values(mid).get(key, default)


def enabled(mid: str, key: str, default: bool = True) -> bool:
    v = value(mid, key, default)
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(default)
