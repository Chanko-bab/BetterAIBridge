r"""配置：唯一真源 config/app.yaml；本程序只读 project_root 下的文件，只写 bundle_dir\plugins。

职责边界：
- 读：任意路径（只读）
- 写：本程序目录 + bundle_dir\plugins（装卸）
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import yaml

APP_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = APP_DIR / "config"
CONFIG_PATH = CONFIG_DIR / "app.yaml"
LOG_DIR = APP_DIR / "logs"
DATA_DIR = APP_DIR / "app" / "data"

def install_info() -> Dict[str, Any]:
    """安装身份（install.json）：install_id / 端口 / 用户数据目录。"""
    try:
        doc = json.loads((CONFIG_DIR / "install.json").read_text(encoding="utf-8-sig"))
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def data_root() -> Path | None:
    """0.4.19 起数据回安装目录；保留函数给旧调用，永远返回 None。"""
    return None


def entity_dir() -> Path:
    """人格/记忆/配置/模组所在目录：永远在程序目录的 WiseEntity/entity。"""
    return project_root() / "entity"


def _defaults() -> Dict[str, Any]:
    """默认值一律从程序所在目录推导，不写死盘符（换机器也能跑）。"""
    w = APP_DIR / "WiseEntity"
    return {
        "project_root": str(w),
        "bundle_dir": str(APP_DIR / "program_bundle"),
        "core_url": "http://127.0.0.1:40720",
        "start_all": str(w / "source_code" / "scripts" / "start-all.ps1"),
        "stop_all": str(w / "source_code" / "scripts" / "stop-all.ps1"),
        "start_core": str(w / "source_code" / "scripts" / "start-core.cmd"),
        "start_asr": str(w / "capability" / "voice" / "asr" / "start-asr.cmd"),
        "modules_dir": str(APP_DIR / "program_cache"),
        "logs_dir": str(w / "runtime" / "logs"),
    }


_PATH_KEYS = (
    "project_root",
    "bundle_dir",
    "modules_dir",
    "logs_dir",
    "start_all",
    "stop_all",
    "start_core",
    "start_asr",
)

DEFAULTS: Dict[str, Any] = {
    **_defaults(),
    "ports": {
        "core": 40720, "asr": 40715,
    },
    "ui": {
        "window_title": "BetterAIBridge",
        "start_page": "chat",
        "refresh_ports_ms": 3000,
        "refresh_state_ms": 5000,
        "window_size": [1180, 780],
        "font_family": "",
        "font_size": 13,
        "background": {
            "enabled": True,
            "effect": "blobs",
            "follower": "glow",
            "palette": "light",
            "click": True,
            "click_style": "ripple",
            "source": "image",
            "media": "",
            "speed": 1.0,
            "opacity": 1.0,
        },
    },
    "chat": {"session": "web:owner", "timeout_s": 90},
    "core": {"auto_restart": True},
    "update_url": "",
}

_cfg: Dict[str, Any] | None = None


def _merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _sanitize(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """路径不存在就回退到安装目录推导值（旧配置写着别的盘符时不留死路）。"""
    import logging

    log = logging.getLogger("xiaochen")
    for key in _PATH_KEYS:
        cur = cfg.get(key)
        if not isinstance(cur, str) or not cur.strip():
            cfg[key] = DEFAULTS[key]
            continue
        p = Path(cur)
        if key in ("logs_dir", "modules_dir"):
            # 这两个目录允许晚建：能就地建出来就算可用（新装的机器上很常见）
            try:
                p.mkdir(parents=True, exist_ok=True)
                continue
            except OSError:
                pass
        must_exist = key in ("project_root", "start_all", "stop_all", "start_core", "start_asr")
        ok = p.exists() if must_exist else p.parent.exists()
        if not ok:
            log.warning("配置项 %s 指向不存在的路径 %s，已回退到 %s", key, cur, DEFAULTS[key])
            cfg[key] = DEFAULTS[key]
    return cfg


def load(force: bool = False) -> Dict[str, Any]:
    global _cfg
    if _cfg is not None and not force:
        return _cfg
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw: Dict[str, Any] = {}
    if CONFIG_PATH.exists():
        try:
            raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            raw = {}
    _cfg = _sanitize(_merge(DEFAULTS, raw))
    if not CONFIG_PATH.exists():
        save(_cfg)
    return _cfg


def save(cfg: Dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def get(path: str, default: Any = None) -> Any:
    node: Any = load()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def set_value(path: str, value: Any) -> Any:
    """改一个配置项并立刻落盘（点一下勾选就生效，不用重启）。"""
    global _cfg

    cfg = load()
    parts = path.split(".")
    node = cfg
    for part in parts[:-1]:
        if not isinstance(node.get(part), dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value
    save(cfg)
    _cfg = None   # 下次 get 重新从磁盘读；别拿清空后的同一个 dict 覆盖回去
    return value


def project_root() -> Path:
    return Path(get("project_root", DEFAULTS["project_root"]))


def bundle_dir() -> Path:
    return Path(get("bundle_dir", DEFAULTS["bundle_dir"]))


def plugins_dir() -> Path:
    """控制台插件装卸地（唯一允许写的目录）。"""
    p = bundle_dir() / "plugins"
    p.mkdir(parents=True, exist_ok=True)
    return p


def is_relative_to_safe(target: str | os.PathLike) -> bool:
    """装卸路径必须落在 bundle_dir 内。"""
    try:
        t = Path(target).resolve()
        b = bundle_dir().resolve()
        return t == b or b in t.parents
    except Exception:
        return False
