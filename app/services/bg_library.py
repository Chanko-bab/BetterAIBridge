"""背景图片内部库。

导入时把图片复制进 `entity/state/backgrounds/`，按 sha256 去重；外观页只认库里的
路径，用户不用再回头找原文件。这个库只服务启动器外观，不进智能体提示词，也不给
模组开放。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

from ..core import config

INDEX_NAME = "index.jsonl"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}
MAX_BYTES = 50 * 1024 * 1024
_LOCK = threading.Lock()


def root() -> Path:
    """库根目录；放在实体数据里，卸载备份能一起带走。"""
    return Path(config.entity_dir()) / "state" / "backgrounds"


def _ensure() -> Path:
    d = root()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path() -> Path:
    return _ensure() / INDEX_NAME


def _safe_stem(name: str) -> str:
    stem = Path(str(name or "image")).stem
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", stem).strip(" ._")
    return (stem or "image")[:40]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _looks_image(path: Path) -> bool:
    """不靠扩展名，先看文件头；挡掉改名成 .png 的随便什么文件。"""
    try:
        head = path.read_bytes()[:16]
    except OSError:
        return False
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if head.startswith(b"\xff\xd8\xff"):
        return True
    if head.startswith((b"GIF87a", b"GIF89a")):
        return True
    if head.startswith(b"BM"):
        return True
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return True
    return False


def _read_rows() -> List[Dict[str, Any]]:
    p = _index_path()
    if not p.is_file():
        return []
    out: List[Dict[str, Any]] = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("id"):
                out.append(row)
    except OSError:
        return []
    return out


def _write_rows(rows: List[Dict[str, Any]]) -> None:
    p = _ensure() / INDEX_NAME
    tmp = p.with_suffix(".jsonl.tmp")
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    tmp.write_text(body + ("\n" if body else ""), encoding="utf-8")
    os.replace(tmp, p)


def _abs(row: Dict[str, Any]) -> Path:
    rel = str(row.get("rel") or "")
    return _ensure() / rel if rel else _ensure()


def _public(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    out["path"] = str(_abs(row))
    out["exists"] = _abs(row).is_file()
    return out


def list_items() -> List[Dict[str, Any]]:
    """按最近使用排序；丢失的文件也返回（exists=False），让界面能提示。"""
    with _LOCK:
        rows = [r for r in _read_rows() if not r.get("deleted")]
    rows.sort(key=lambda r: float(r.get("last_used") or r.get("at") or 0), reverse=True)
    return [_public(r) for r in rows]


def get(item_id: str) -> Dict[str, Any] | None:
    with _LOCK:
        for row in _read_rows():
            if str(row.get("id")) == str(item_id) and not row.get("deleted"):
                return _public(row)
    return None


def find_by_path(path: str) -> Dict[str, Any] | None:
    try:
        target = Path(path).resolve()
    except OSError:
        return None
    with _LOCK:
        for row in _read_rows():
            if row.get("deleted"):
                continue
            if _abs(row).resolve() == target:
                return _public(row)
    return None


def import_file(src: str | Path) -> Dict[str, Any]:
    """复制一张图片进库；同一 sha256 直接复用，返回 existing=True。"""
    p = Path(str(src))
    if not p.is_file():
        raise ValueError("找不到这个文件")
    ext = p.suffix.lower()
    if ext not in IMAGE_EXTS:
        raise ValueError("只收图片：png / jpg / jpeg / bmp / webp / gif")
    size = p.stat().st_size
    if size > MAX_BYTES:
        raise ValueError(f"图片太大（上限 {MAX_BYTES // (1024 * 1024)} MB）")
    if not _looks_image(p):
        raise ValueError("这个文件看起来不是图片")
    sha = _sha256(p)
    with _LOCK:
        rows = _read_rows()
        for row in rows:
            if row.get("deleted") or row.get("sha256") != sha:
                continue
            if _abs(row).is_file():
                row["last_used"] = time.time()
                _write_rows(rows)
                out = _public(row)
                out["existing"] = True
                return out
        month = time.strftime("%Y.%m")
        folder = _ensure() / month
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{sha[:8]}_{_safe_stem(p.name)}{ext}"
        if not dest.is_file():
            shutil.copy2(p, dest)
        row = {
            "id": uuid.uuid4().hex[:10],
            "name": p.name,
            "ext": ext,
            "bytes": size,
            "sha256": sha,
            "rel": str(dest.relative_to(_ensure())).replace("\\", "/"),
            "at": time.time(),
            "last_used": time.time(),
            "deleted": False,
        }
        rows.append(row)
        _write_rows(rows)
        out = _public(row)
        out["existing"] = False
        return out


def touch(item_id: str) -> Dict[str, Any] | None:
    with _LOCK:
        rows = _read_rows()
        for row in rows:
            if str(row.get("id")) == str(item_id) and not row.get("deleted"):
                row["last_used"] = time.time()
                _write_rows(rows)
                return _public(row)
    return None


def remove(item_id: str) -> bool:
    """删库内文件并标记索引；当前背景若正用它，由界面负责回退。"""
    with _LOCK:
        rows = _read_rows()
        hit = None
        for row in rows:
            if str(row.get("id")) == str(item_id) and not row.get("deleted"):
                hit = row
                break
        if hit is None:
            return False
        try:
            _abs(hit).unlink(missing_ok=True)
        except OSError:
            pass
        hit["deleted"] = True
        _write_rows(rows)
        return True


def stats() -> Dict[str, int]:
    items = [r for r in list_items() if r.get("exists")]
    return {"count": len(items), "bytes": sum(int(r.get("bytes") or 0) for r in items)}
