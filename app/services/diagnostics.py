"""导出诊断包：一个 zip，内含版本、系统信息、日志，供使用者发给开发者排错。

只读：不修改任何配置、不重启任何进程。
脱敏：所有文本里的 API key（sk-…）和桥令牌会被替换成 ***。
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

log = logging.getLogger("xiaochen.diagnostics")

ROOT = Path(__file__).resolve().parents[2]          # D:\BetterAIBridge
ENTITY = ROOT / "WiseEntity" / "entity"
RUNTIME_LOGS = ROOT / "WiseEntity" / "runtime" / "logs"
LOGS = ROOT / "logs"
BUNDLE = ROOT / "program_bundle"

MAX_LOG_BYTES = 512 * 1024          # 每个日志最多带 512 KB（尾部）
_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|brz_[A-Za-z0-9_\-]{8,}|\b[0-9a-f]{32}\b)", re.I)
_HEADER_RE = re.compile(
    r"(?i)((?:authorization\s*:\s*bearer|(?:x-bridge-token|x-sense-token|xi-api-key)\s*:)\s*)\S+")
_QUERY_RE = re.compile(r"(?i)([?&](?:token|key|api_key)=)[^&\s]+")
LOG_NAMES = ("app.log", "startup-error.log", "core-boot.log", "asr-boot.log", "launcher-boot.log")



def _tail(path: Path, limit: int = MAX_LOG_BYTES) -> str:
    """读文件尾部（大日志只带最后一段），失败返回空串。"""
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > limit:
                fh.seek(-limit, os.SEEK_END)
                data = fh.read()
                text = data.decode("utf-8", "replace")
                return "…（前面省略 " + f"{size - limit:,}" + " 字节）\n" + text
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _scrub(text: str) -> str:
    text = _SECRET_RE.sub("***", text)
    text = _HEADER_RE.sub(lambda m: m.group(1) + "***", text)
    return _QUERY_RE.sub(lambda m: m.group(1) + "***", text)


def _version() -> str:
    try:
        return (ROOT / "VERSION.txt").read_text(encoding="utf-8-sig").strip()
    except OSError:
        return "unknown"


def _registry_summary() -> str:
    try:
        data = json.loads((BUNDLE / "registry.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return "（没有 registry.json）"
    lines = []
    for mid, info in (data.get("modules") or {}).items():
        lines.append(
            "{id} {ver} state={state} runtime_port={port} pid={pid}".format(
                id=mid,
                ver=info.get("version", "?"),
                state=info.get("state", "?"),
                port=info.get("runtime_port", 0),
                pid=info.get("pid", 0),
            )
        )
    return "\n".join(lines) or "（没有装模组）"


def _sysinfo() -> str:
    try:
        import psutil

        mem = f"{psutil.virtual_memory().total / 1024 ** 3:.1f} GB"
        cpu = f"{psutil.cpu_count(logical=True)} 线程"
    except Exception:
        mem, cpu = "?", "?"
    try:
        import PySide6

        qt = PySide6.__version__
    except Exception:
        qt = "?"
    return "\n".join(
        [
            f"BAB 版本: {_version()}",
            f"系统: {platform.platform()}",
            f"Python: {sys.version.split()[0]}（{sys.executable}）",
            f"PySide6: {qt}",
            f"CPU: {cpu}",
            f"内存: {mem}",
            f"程序目录: {ROOT}",
            f"导出时间: {datetime.now():%Y-%m-%d %H:%M:%S}",
        ]
    )


def _collect(files: dict[str, str]) -> None:
    files["系统信息.txt"] = _scrub(_sysinfo())
    files["模组状态.txt"] = _scrub(_registry_summary())
    try:
        from ..core import perf
        rows = perf.snapshot()
        if rows:
            files["启动耗时.json"] = json.dumps(rows, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        log.debug("诊断包收集启动耗时才失败", exc_info=True)

    for name in LOG_NAMES:
        text = _tail(LOGS / name)
        if text:
            files[f"日志/{name}"] = _scrub(text)

    text = _tail(RUNTIME_LOGS / "entity_core.log")
    if text:
        files["日志/entity_core.log"] = _scrub(text)

    if BUNDLE.is_dir():
        for mod_dir in sorted(BUNDLE.iterdir()):
            log_dir = mod_dir / "logs"
            if not log_dir.is_dir():
                continue
            for log in sorted(log_dir.glob("*.log")):
                text = _tail(log)
                if text:
                    files[f"模组日志/{mod_dir.name}/{log.name}"] = _scrub(text)


def _unique(path: Path) -> Path:
    """同一秒里导出两次也不覆盖：名字重了就加 -2、-3。"""
    if not path.exists():
        return path
    for i in range(2, 1000):
        cand = path.with_name(f"{path.stem}-{i}{path.suffix}")
        if not cand.exists():
            return cand
    return path.with_name(f"{path.stem}-{os.getpid()}{path.suffix}")


def export_zip(target_dir: Path | None = None) -> Path:
    """打包诊断信息，返回 zip 路径。target_dir 默认桌面，失败则用临时目录。"""
    files: dict[str, str] = {}
    _collect(files)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"BAB诊断-{stamp}.zip"
    candidates = [target_dir] if target_dir else []
    desktop = Path.home() / "Desktop"
    if desktop.is_dir():
        candidates.append(desktop)
    candidates += [Path.home() / "Documents", Path(tempfile.gettempdir())]

    last_err: Exception | None = None
    for folder in candidates:
        if folder is None:
            continue
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = _unique(folder / name)
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                for arc, text in files.items():
                    zf.writestr(arc, text.encode("utf-8"))
            return path
        except OSError as exc:          # 桌面被 OneDrive 重定向等
            last_err = exc
            continue
    raise OSError(f"无法写入诊断包：{last_err}")


if __name__ == "__main__":
    print(export_zip())
