"""切换智能体时，只停正在跑的模组，不卸载、不改 enabled 状态。

放在 pbab 外面，是因为 pbab.py 已经到了体量上限；这里只借用它的模组
目录/端口清理函数，不复制生命周期。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from . import pbab, registry, winproc
from .pbab_process import _kill_module_procs, _kill_pid_files, _kill_port_owners

log = logging.getLogger(__name__)


def stop_running(keep_state: bool = True) -> List[Dict[str, Any]]:
    """停掉当前 registry 里 state=enabled 的模组进程，保留启用状态。

    切换智能体专用：旧智能体的 enabled 要留着，切回来才能自动恢复；不能走
    pbab.disable()，否则会把旧智能体写成 disabled。
    """
    rows = [m for m in registry.modules() if str(m.get("state") or "") == "enabled"]
    out: List[Dict[str, Any]] = []
    for mod in rows:
        mid = str(mod.get("id") or "")
        if not mid:
            continue
        pid = mod.get("pid")
        if pid:
            winproc.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        dirs = [Path(str(mod.get("dir") or pbab.module_dir(mid)))]
        try:
            pr = pbab.payload_root(mod)
            if pr and str(pr) != str(dirs[0]):
                dirs.append(pr)
        except (OSError, ValueError, TypeError):
            pass
        n = _kill_pid_files(dirs)
        n += _kill_module_procs(dirs)
        try:
            doc = pbab.manifest(mid) or {}
            ports = [int(x) for x in (doc.get("ports") or [])]
            if mod.get("runtime_port"):
                ports.append(int(mod["runtime_port"]))
            n += _kill_port_owners(ports, only_dir=str(dirs[0]))
        except (OSError, ValueError, TypeError, KeyError):
            log.warning("切换智能体时清理 %s 端口失败，继续", mid, exc_info=True)
        try:
            registry.patch(mid, pid=None)
        except (OSError, ValueError, KeyError):
            log.warning("切换智能体时清 %s pid 失败", mid, exc_info=True)
        out.append({"id": mid, "stopped": bool(pid), "cleaned": n, "keep_state": keep_state})
        log.info("切换智能体：停模组 %s（保留 enabled=%s）", mid, keep_state)
    return out
