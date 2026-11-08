"""启动器侧的语音库入口：真正的实现与内核共用一份（纯标准库）。

注意：这里必须显式再导出函数/常量。只写
``from WiseEntity.entity.core import voice_store`` 只会把内核模块绑在
本模块的局部名字上，``app.services.voice_store.save`` 仍然是找不到的。
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from WiseEntity.entity.core.voice_store import (  # noqa: E402,F401
    INDEX_NAME,
    MAX_BYTES,
    clear_all,
    duration_ms,
    get,
    janitor,
    purge_temp,
    rows,
    save,
    temp_dir,
    total_bytes,
    update,
    voice_dir,
)
