"""日志：写 logs\\app.log（UTF-8，按天轮转），同时进 UI 的事件总线。"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from . import config

_ready = False


def setup(level: int = logging.INFO) -> logging.Logger:
    global _ready
    log = logging.getLogger("xiaochen")
    if _ready:
        return log
    cfg = config.load()
    log_dir = Path(config.APP_DIR) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log.setLevel(level)
    log.propagate = False

    fmt = logging.Formatter("%(asctime)s %(levelname)-5s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")

    fh = logging.handlers.TimedRotatingFileHandler(
        log_dir / "app.log", when="midnight", backupCount=14, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    log.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)
    try:  # Windows 控制台是 GBK，尽量别因为中文崩
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (OSError, AttributeError, ValueError):
        pass

    _ready = True
    log.info("日志就绪 | project_root=%s | core=%s", cfg.get("project_root"), cfg.get("core_url"))
    return log


def get() -> logging.Logger:
    return setup()
