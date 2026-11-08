"""语音消息的落盘与索引（启动器与内核共用，纯标准库）。

目录：
- 持久：<安装根>/WiseEntity/entity/state/voice/YYYY-MM/<id>.wav
- 临时：%TEMP%/bab-voice/<id>.wav（本次运行可听，退出即清）

索引：state/voice/index.jsonl，一行一条；删除只把行标 deleted，转写保留。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
import uuid
import wave
from pathlib import Path
from typing import Any, Dict, List

_LOCK = threading.RLock()
INDEX_NAME = "index.jsonl"
MAX_BYTES = 40 * 1024 * 1024


def voice_dir(root: str | Path) -> Path:
    return Path(root) / "WiseEntity" / "entity" / "state" / "voice"


def temp_dir() -> Path:
    return Path(tempfile.gettempdir()) / "bab-voice"


def _index_path(root: str | Path) -> Path:
    return voice_dir(root) / INDEX_NAME


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def duration_ms(path: str | Path) -> int:
    """wav 的真实时长；其它格式返回 0（让调用方给）。"""
    try:
        with wave.open(str(path), "rb") as w:
            rate = int(w.getframerate() or 0)
            if rate <= 0:
                return 0
            return int(round(w.getnframes() * 1000.0 / rate))
    except Exception:
        return 0


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 256), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_rows(root: str | Path) -> List[Dict[str, Any]]:
    p = _index_path(root)
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    try:
        for line in p.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict) and row.get("id"):
                out.append(row)
    except Exception:
        return []
    return out


def _write_rows(root: str | Path, rows: List[Dict[str, Any]]) -> None:
    p = _index_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, p)


def rows(root: str | Path, include_deleted: bool = False) -> List[Dict[str, Any]]:
    with _LOCK:
        data = _read_rows(root)
    if include_deleted:
        return data
    return [r for r in data if not r.get("deleted")]


def get(root: str | Path, vid: str) -> Dict[str, Any] | None:
    for row in rows(root, include_deleted=True):
        if str(row.get("id")) == str(vid):
            return row
    return None


def _copy_in(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dest)


def save(root: str | Path, src: str | Path | bytes, *,
         ms: int = 0, source: str = "owner", kept: bool = True,
         transcript: str = "", into_temp: bool = False, suffix: str = ".wav") -> Dict[str, Any]:
    """把一段音频收进语音库，返回索引行。

    src 为 bytes 时按 suffix 落盘；为路径时复制原文件。
    kept=False 只放临时目录，索引仍记一条（kept=False），退出时由 purge_temp 清。
    """
    vid = uuid.uuid4().hex[:16]
    if into_temp:
        dest = temp_dir() / f"{vid}{suffix}"
    else:
        dest = voice_dir(root) / time.strftime("%Y-%m") / f"{vid}{suffix}"
    if isinstance(src, (bytes, bytearray)):
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(bytes(src))
    else:
        sp = Path(src)
        if not sp.is_file():
            raise FileNotFoundError(str(sp))
        if sp.stat().st_size > MAX_BYTES:
            raise ValueError("音频太大")
        _copy_in(sp, dest)
    size = dest.stat().st_size
    dur = int(ms or 0)
    if not dur and dest.suffix.lower() == ".wav":
        dur = duration_ms(dest)
    row = {
        "id": vid,
        "at": _now_iso(),
        "ts": round(time.time(), 3),
        "path": str(dest),
        "rel": "" if into_temp else str(dest.relative_to(Path(root))),
        "bytes": size,
        "sha256": _sha256(dest),
        "dur_ms": int(dur or 0),
        "source": source,
        "kept": bool(kept),
        "transcript": (transcript or "").strip(),
        "deleted": False,
    }
    with _LOCK:
        data = _read_rows(root)
        data.append(row)
        _write_rows(root, data)
    return row


def update(root: str | Path, vid: str, **fields: Any) -> Dict[str, Any] | None:
    with _LOCK:
        data = _read_rows(root)
        hit = None
        for row in data:
            if str(row.get("id")) == str(vid):
                row.update(fields)
                hit = row
                break
        if hit is not None:
            _write_rows(root, data)
    return hit


def total_bytes(root: str | Path) -> int:
    n = 0
    for row in rows(root):
        try:
            n += int(row.get("bytes") or 0)
        except Exception:
            pass
    return n


def clear_all(root: str | Path) -> Dict[str, int]:
    """删除所有持久与临时音频；索引行标记 deleted，转写保留。"""
    files = 0
    size = 0
    roots = [voice_dir(root), temp_dir()]
    with _LOCK:
        for base in roots:
            if not base.exists():
                continue
            for p in base.rglob("*"):
                if p.is_file() and p.name != INDEX_NAME:
                    try:
                        size += p.stat().st_size
                        p.unlink()
                        files += 1
                    except Exception:
                        pass
        data = _read_rows(root)
        changed = 0
        for row in data:
            if not row.get("deleted"):
                row["deleted"] = True
                row["path"] = ""
                changed += 1
        if changed:
            _write_rows(root, data)
    return {"files": files, "bytes": size, "rows": changed}


def purge_temp() -> int:
    """退出时清临时语音；返回删了几个文件。"""
    base = temp_dir()
    n = 0
    if not base.exists():
        return 0
    for p in base.glob("*"):
        if p.is_file():
            try:
                p.unlink()
                n += 1
            except Exception:
                pass
    return n


def janitor(root: str | Path, days: int = 30) -> int:
    """持久语音满 days 天自动清（默认 30）；已删/临时行顺手收拾。"""
    cutoff = time.time() - max(1, int(days)) * 86400
    removed = 0
    with _LOCK:
        data = _read_rows(root)
        for row in data:
            if row.get("deleted"):
                continue
            path = Path(str(row.get("path") or ""))
            try:
                old = float(row.get("ts") or 0) < cutoff
            except Exception:
                old = False
            temp_row = not bool(row.get("kept"))
            if (old or (temp_row and not path.exists())) and path.is_file():
                try:
                    path.unlink()
                except Exception:
                    pass
            if old or (temp_row and not path.exists()):
                row["deleted"] = True
                row["path"] = ""
                removed += 1
        if removed:
            _write_rows(root, data)
    return removed
