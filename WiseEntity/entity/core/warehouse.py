"""仓库：和记忆同级的文件抽屉。

`entity/warehouse/` 下分两块：

- `internal/owner/{image,document,file}/YYYY.MM/`：主人拖进来/收进来的；
- `external/<模组 id>/...`：模组自己的，只准碰自己那一格。

索引在 `warehouse/index.jsonl`，按 sha256 去重。这里只管“存、列、读、发”，
不做 PDF/DOCX 正文提取；图片可以由智能体用 `see_image` 看。
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

from .settings import ENTITY

INDEX_NAME = "index.jsonl"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}
DOC_EXTS = {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt",
            ".xls", ".xlsx", ".csv", ".ppt", ".pptx"}
TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".log", ".py", ".yaml", ".yml"}
BLOCKED_EXTS = {".exe", ".bat", ".cmd", ".ps1", ".js", ".vbs", ".msi",
                ".dll", ".scr", ".com", ".jar", ".sh", ".lnk"}
MAX_IMAGE = 30 * 1024 * 1024
MAX_FILE = 200 * 1024 * 1024
MAX_TOTAL = 2 * 1024 * 1024 * 1024
MAX_TEXT = 20000
_LOCK = threading.Lock()


def root() -> Path:
    return Path(ENTITY) / "warehouse"


def _ensure() -> Path:
    d = root()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path() -> Path:
    return _ensure() / INDEX_NAME


def kind_of(name: str) -> str:
    ext = Path(str(name or "")).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in DOC_EXTS:
        return "document"
    return "file"


def _safe_piece(text: str, fallback: str = "item") -> str:
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", str(text or "")).strip(" ._")
    return (s or fallback)[:60]


def _source_key(source: str) -> str:
    """owner / module:<id> → internal/owner 或 external/<id>。"""
    src = str(source or "owner").strip()
    if src == "owner":
        return "internal/owner"
    if src.startswith("module:"):
        mid = _safe_piece(src.split(":", 1)[1], "module")
        return f"external/{mid}"
    raise ValueError("不认识的仓库来源")


def _read_rows() -> List[Dict[str, Any]]:
    p = _index_path()
    if not p.is_file():
        return []
    out = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
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
    return _ensure() / str(row.get("rel") or "")


def _public(row: Dict[str, Any], with_path: bool = False) -> Dict[str, Any]:
    out = {
        "id": row.get("id"),
        "name": row.get("name"),
        "kind": row.get("kind"),
        "bytes": int(row.get("bytes") or 0),
        "at": row.get("at"),
        "source": row.get("source"),
        "ext": row.get("ext"),
        "sha256": row.get("sha256"),
    }
    if with_path:
        out["path"] = str(_abs(row))
        out["exists"] = _abs(row).is_file()
    return out


def _total_bytes(rows: List[Dict[str, Any]]) -> int:
    return sum(int(r.get("bytes") or 0) for r in rows if not r.get("deleted"))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def import_file(src: str | Path, source: str = "owner", name: str = "") -> Dict[str, Any]:
    p = Path(str(src))
    if not p.is_file():
        raise ValueError("找不到这个文件")
    ext = p.suffix.lower()
    if ext in BLOCKED_EXTS:
        raise ValueError(f"不收这种文件：{ext}")
    kind = kind_of(name or p.name)
    size = p.stat().st_size
    limit = MAX_IMAGE if kind == "image" else MAX_FILE
    if size > limit:
        raise ValueError(f"文件太大（上限 {limit // (1024 * 1024)} MB）")
    sha = _sha256_file(p)
    disp = _safe_piece(name or p.name, "file")
    if not Path(disp).suffix:
        disp += ext
    with _LOCK:
        rows = _read_rows()
        for row in rows:
            if row.get("deleted") or row.get("source") != source or row.get("sha256") != sha:
                continue
            if _abs(row).is_file():
                out = _public(row, with_path=True)
                out["existing"] = True
                return out
        if _total_bytes(rows) + size > MAX_TOTAL:
            raise ValueError("仓库满了（上限 2 GB），先删一些旧文件")
        month = time.strftime("%Y.%m")
        folder = _ensure() / _source_key(source) / kind / month
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{sha[:8]}_{Path(disp).stem}{ext}"
        if not dest.is_file():
            shutil.copy2(p, dest)
        row = {
            "id": uuid.uuid4().hex[:10],
            "name": Path(name or p.name).name,
            "ext": ext,
            "kind": kind,
            "bytes": size,
            "sha256": sha,
            "rel": str(dest.relative_to(_ensure())).replace("\\", "/"),
            "at": time.time(),
            "source": source,
            "deleted": False,
        }
        rows.append(row)
        _write_rows(rows)
        out = _public(row, with_path=True)
        out["existing"] = False
        return out


def put_bytes(source: str, name: str, data: bytes, kind: str = "") -> Dict[str, Any]:
    if not data:
        raise ValueError("空文件")
    ext = Path(str(name or "")).suffix.lower()
    if ext in BLOCKED_EXTS:
        raise ValueError(f"不收这种文件：{ext}")
    k = kind if kind in ("image", "document", "file") else kind_of(name)
    limit = MAX_IMAGE if k == "image" else MAX_FILE
    if len(data) > limit:
        raise ValueError(f"文件太大（上限 {limit // (1024 * 1024)} MB）")
    sha = _sha256_bytes(data)
    disp = _safe_piece(name, "file")
    if not Path(disp).suffix and ext:
        disp += ext
    with _LOCK:
        rows = _read_rows()
        for row in rows:
            if row.get("deleted") or row.get("source") != source or row.get("sha256") != sha:
                continue
            if _abs(row).is_file():
                out = _public(row, with_path=True)
                out["existing"] = True
                return out
        if _total_bytes(rows) + len(data) > MAX_TOTAL:
            raise ValueError("仓库满了（上限 2 GB），先删一些旧文件")
        month = time.strftime("%Y.%m")
        folder = _ensure() / _source_key(source) / k / month
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{sha[:8]}_{Path(disp).stem}{ext}"
        dest.write_bytes(data)
        row = {
            "id": uuid.uuid4().hex[:10],
            "name": Path(name or disp).name,
            "ext": ext,
            "kind": k,
            "bytes": len(data),
            "sha256": sha,
            "rel": str(dest.relative_to(_ensure())).replace("\\", "/"),
            "at": time.time(),
            "source": source,
            "deleted": False,
        }
        rows.append(row)
        _write_rows(rows)
        out = _public(row, with_path=True)
        out["existing"] = False
        return out


def list_items(source: str | None = None, kind: str = "", query: str = "",
               with_path: bool = False) -> List[Dict[str, Any]]:
    with _LOCK:
        rows = [r for r in _read_rows() if not r.get("deleted")]
    if source:
        rows = [r for r in rows if r.get("source") == source]
    if kind:
        rows = [r for r in rows if r.get("kind") == kind]
    q = str(query or "").strip().lower()
    if q:
        rows = [r for r in rows if q in str(r.get("name") or "").lower()]
    rows.sort(key=lambda r: float(r.get("at") or 0), reverse=True)
    return [_public(r, with_path) for r in rows]


def get(item_id: str, with_path: bool = True) -> Dict[str, Any] | None:
    ref = str(item_id or "")
    with _LOCK:
        for row in _read_rows():
            if row.get("deleted"):
                continue
            if str(row.get("id")) == ref:
                return _public(row, with_path)
    return None


def resolve(ref: str, source: str | None = None) -> Dict[str, Any] | None:
    """按 id 或文件名找一条；同名取最新。"""
    ref = str(ref or "").strip()
    if not ref:
        return None
    hit = get(ref)
    if hit:
        if source and hit.get("source") != source:
            return None
        return hit
    with _LOCK:
        rows = [r for r in _read_rows() if not r.get("deleted")]
    if source:
        rows = [r for r in rows if r.get("source") == source]
    rows = [r for r in rows if str(r.get("name") or "") == ref or Path(str(r.get("name") or "")).stem == ref]
    rows.sort(key=lambda r: float(r.get("at") or 0), reverse=True)
    return _public(rows[0], True) if rows else None


def find_by_path(path: str | Path) -> Dict[str, Any] | None:
    try:
        target = Path(str(path)).resolve()
    except OSError:
        return None
    with _LOCK:
        for row in _read_rows():
            if row.get("deleted"):
                continue
            try:
                if _abs(row).resolve() == target:
                    return _public(row, True)
            except OSError:
                continue
    return None


def is_inside(path: str | Path) -> bool:
    try:
        target = Path(str(path)).resolve()
        base = root().resolve()
        return target == base or base in target.parents
    except OSError:
        return False


def read_text(item_id: str, max_chars: int = MAX_TEXT) -> Dict[str, Any]:
    row = get(item_id)
    if not row:
        raise ValueError("仓库里没有这一条")
    path = Path(str(row.get("path") or ""))
    if not path.is_file():
        raise ValueError("文件已经不在仓库里了")
    ext = str(row.get("ext") or "").lower()
    if ext not in TEXT_EXTS:
        raise ValueError("这类文件只存不读正文；可以发出去，或让主人打开看")
    data = path.read_bytes()[: max(200, int(max_chars)) * 4]
    text = data.decode("utf-8", errors="replace")
    clipped = text[: max(200, int(max_chars))]
    return {"ok": True, "id": row.get("id"), "name": row.get("name"),
            "text": clipped, "chars": len(clipped), "truncated": len(text) > len(clipped)}


def remove(item_id: str) -> bool:
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


def mkdir(source: str, name: str) -> Dict[str, Any]:
    piece = _safe_piece(name, "")
    if not piece:
        raise ValueError("目录名不能为空")
    d = _ensure() / _source_key(source) / piece
    base = (_ensure() / _source_key(source)).resolve()
    target = d.resolve()
    if base not in target.parents and target != base:
        raise ValueError("不能建到仓库外面")
    d.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "path": str(d), "rel": str(d.relative_to(_ensure())).replace("\\", "/")}


def stats(source: str | None = None) -> Dict[str, int]:
    rows = list_items(source=source)
    return {"count": len(rows), "bytes": sum(int(r.get("bytes") or 0) for r in rows)}
