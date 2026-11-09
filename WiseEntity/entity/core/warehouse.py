"""仓库：智能体自己的收藏 + 主人/模组的库。

不是聊天缓存。这里的每一条都要有“是什么、为什么留下”，收藏是智能体
看完之后主动留下的副本，和记忆互相引用。

目录：

- `warehouse/libraries/owner-main/`：主人发来的，默认库；
- `warehouse/libraries/agent-collection/`：智能体自己收着的副本；
- `warehouse/libraries/mod-<模组>-<库>/`：模组申请的库，默认 `main`。

索引在 `warehouse/index.jsonl`。旧版 `internal/owner`、`external/<模组>`
仍然可读（按 source 映射到默认库），新文件一律写进 `libraries/`。
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
LIBRARIES_NAME = "libraries.json"
OWNER_LIB = "owner-main"
AGENT_LIB = "agent-collection"
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
MAX_LIBRARIES = 8
MAX_LIB_QUOTA = 512 * 1024 * 1024
_LOCK = threading.Lock()
_MIGRATED = False

_DEFAULT_LIBS = {
    OWNER_LIB: {
        "id": OWNER_LIB, "owner_type": "owner", "owner_id": "owner",
        "title": "主人发来的", "purpose": "主人发来的图片、文档和文件",
        "quota_mb": 0, "default": True,
    },
    AGENT_LIB: {
        "id": AGENT_LIB, "owner_type": "agent", "owner_id": "agent",
        "title": "我收着的东西", "purpose": "智能体看完之后自己留下的副本",
        "quota_mb": 0, "default": True,
    },
}


def root() -> Path:
    return Path(ENTITY) / "warehouse"


def libraries_root() -> Path:
    return root() / "libraries"


def _ensure() -> Path:
    d = root()
    d.mkdir(parents=True, exist_ok=True)
    _ensure_defaults()
    return d


def _libs_path() -> Path:
    return root() / LIBRARIES_NAME


def _read_libs() -> Dict[str, Dict[str, Any]]:
    p = _libs_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, dict)}


def _write_libs(libs: Dict[str, Dict[str, Any]]) -> None:
    p = _libs_path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(libs, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _ensure_defaults() -> None:
    libs = _read_libs()
    changed = False
    for key, meta in _DEFAULT_LIBS.items():
        if key not in libs:
            libs[key] = {**meta, "created_at": time.time()}
            changed = True
    if changed or not _libs_path().is_file():
        _write_libs(libs)


def _safe_piece(text: str, fallback: str = "item") -> str:
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", str(text or "")).strip(" ._")
    return (s or fallback)[:60]


def _safe_lib(name: str) -> str:
    raw = str(name or "").strip().lower()
    s = re.sub(r"[^a-z0-9_-]+", "-", raw).strip("-_")
    if not s:
        raise ValueError("库名不能为空")
    return s[:40]


def _kind_of(name: str) -> str:
    ext = Path(str(name or "")).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in DOC_EXTS:
        return "document"
    return "file"


def kind_of(name: str) -> str:
    return _kind_of(name)


def _source_for_lib(lib: str, libs: Dict[str, Dict[str, Any]]) -> str:
    meta = libs.get(lib) or {}
    kind = str(meta.get("owner_type") or "")
    if kind == "owner":
        return "owner"
    if kind == "agent":
        return "agent"
    if kind == "module":
        return f"module:{meta.get('owner_id')}"
    return lib


def _lib_from_source(source: str) -> str:
    src = str(source or "owner").strip()
    if src == "agent":
        return AGENT_LIB
    if src.startswith("module:"):
        mid = _safe_piece(src.split(":", 1)[1], "module")
        return f"mod-{mid}-main"
    return OWNER_LIB


def _ensure_source_lib(source: str) -> str:
    src = str(source or "owner").strip()
    libs = _read_libs()
    if src == "agent":
        lib = AGENT_LIB
        if lib not in libs:
            ensure_library(lib, "agent", "agent", title="我收着的东西",
                           purpose="智能体看完之后自己留下的副本", default=True)
    elif src.startswith("module:"):
        mid = _safe_piece(src.split(":", 1)[1], "module")
        lib = f"mod-{mid}-main"
        if lib not in libs:
            ensure_library(lib, "module", mid, title="默认库",
                           purpose=f"{mid} 的默认仓库", default=True)
    else:
        lib = OWNER_LIB
        if lib not in libs:
            ensure_library(lib, "owner", "owner", title="主人发来的",
                           purpose="主人发来的图片、文档和文件", default=True)
    return lib


def _row_lib(row: Dict[str, Any]) -> str:
    lib = str(row.get("library") or "").strip()
    if lib:
        return lib
    return _lib_from_source(str(row.get("source") or "owner"))


def _lib_dir(lib: str) -> Path:
    return libraries_root() / _safe_lib(lib)


def _abs(row: Dict[str, Any]) -> Path:
    return _ensure() / str(row.get("rel") or "")


def _index_path() -> Path:
    return _ensure() / INDEX_NAME


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


def _public(row: Dict[str, Any], with_path: bool = False) -> Dict[str, Any]:
    out = {
        "id": row.get("id"),
        "name": row.get("name"),
        "title": row.get("title") or "",
        "kind": row.get("kind"),
        "bytes": int(row.get("bytes") or 0),
        "at": row.get("at"),
        "library": _row_lib(row),
        "source": row.get("source"),
        "ext": row.get("ext"),
        "sha256": row.get("sha256"),
        "desc": row.get("desc") or "",
        "tags": list(row.get("tags") or []),
        "why": row.get("why") or "",
        "preview": row.get("preview") or "",
        "readable": row.get("readable"),
        "inspected_at": row.get("inspected_at"),
        "kept": bool(row.get("kept")),
        "origin_id": row.get("origin_id") or "",
        "memory_id": row.get("memory_id") or "",
    }
    if with_path:
        out["path"] = str(_abs(row))
        out["exists"] = _abs(row).is_file()
    return out


def libraries() -> List[Dict[str, Any]]:
    libs = _read_libs()
    rows = [r for r in _read_rows() if not r.get("deleted")]
    out = []
    for key, meta in sorted(libs.items()):
        mine = [r for r in rows if _row_lib(r) == key]
        out.append({**meta, "count": len(mine),
                    "bytes": sum(int(r.get("bytes") or 0) for r in mine)})
    return out


def ensure_library(lib: str, owner_type: str, owner_id: str, title: str = "",
                   purpose: str = "", quota_mb: int = 0, default: bool = False) -> Dict[str, Any]:
    lib_id = _safe_lib(lib)
    libs = _read_libs()
    meta = libs.get(lib_id)
    if meta:
        return {**meta, "count": 0}
    meta = {
        "id": lib_id, "owner_type": str(owner_type), "owner_id": str(owner_id),
        "title": str(title or lib_id), "purpose": str(purpose or ""),
        "quota_mb": max(0, min(int(quota_mb or 0), MAX_LIB_QUOTA // (1024 * 1024))),
        "default": bool(default), "created_at": time.time(),
    }
    libs[lib_id] = meta
    _write_libs(libs)
    _lib_dir(lib_id).mkdir(parents=True, exist_ok=True)
    return meta


def _module_bundle(mid: str) -> Path | None:
    base = Path(ENTITY).parents[1] / "program_bundle"
    exact = base / f"program_{mid}.pbab" / "module.json"
    if exact.is_file():
        return exact
    for p in base.glob("program_*.pbab/module.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(data.get("id") or "") == str(mid):
            return p
    return None


def module_specs(mid: str) -> List[Dict[str, Any]]:
    """从 module.json 读 `warehouse.libraries`，最多 MAX_LIBRARIES 个。"""
    p = _module_bundle(mid)
    if not p:
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    wh = data.get("warehouse") if isinstance(data.get("warehouse"), dict) else {}
    specs = wh.get("libraries") if isinstance(wh.get("libraries"), list) else []
    out = []
    for item in specs[:MAX_LIBRARIES]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("id") or "").strip()
        if not name or name == "main":
            continue
        try:
            name = _safe_lib(name)
        except ValueError:
            continue
        out.append({
            "id": name,
            "title": str(item.get("title") or name),
            "purpose": str(item.get("purpose") or ""),
            "quota_mb": int(item.get("quota_mb") or 0),
        })
    return out


def module_libraries(mid: str) -> List[Dict[str, Any]]:
    """确保模组默认库 + 申请库存在，返回它的全部库。"""
    owner_id = _safe_piece(mid, "module")
    prefix = f"mod-{owner_id}-"
    ensure_library(f"{prefix}main", "module", mid, title="默认库",
                   purpose=f"{mid} 的默认仓库", default=True)
    for spec in module_specs(mid):
        ensure_library(f"{prefix}{spec['id']}", "module", mid,
                       title=spec["title"], purpose=spec["purpose"],
                       quota_mb=spec["quota_mb"])
    libs = _read_libs()
    return [dict(meta) for key, meta in sorted(libs.items()) if key.startswith(prefix)]


def module_library_id(mid: str, name: str = "main") -> str:
    owner_id = _safe_piece(mid, "module")
    want = _safe_lib(name or "main")
    allowed = {str(x.get("id")) for x in module_libraries(mid)}
    lib = f"mod-{owner_id}-{want}"
    if lib not in allowed:
        raise ValueError(f"这个模组没有申请过库：{want}")
    return lib


def _total_bytes(rows: List[Dict[str, Any]]) -> int:
    return sum(int(r.get("bytes") or 0) for r in rows if not r.get("deleted"))


def _library_bytes(lib: str, rows: List[Dict[str, Any]]) -> int:
    return sum(int(r.get("bytes") or 0) for r in rows
               if not r.get("deleted") and _row_lib(r) == lib)


def _check_quota(lib: str, rows: List[Dict[str, Any]], add: int) -> None:
    meta = _read_libs().get(lib) or {}
    quota = int(meta.get("quota_mb") or 0) * 1024 * 1024
    if quota and _library_bytes(lib, rows) + add > quota:
        raise ValueError("这个库满了，先删一些旧文件")
    if _total_bytes(rows) + add > MAX_TOTAL:
        raise ValueError("仓库满了（上限 2 GB），先删一些旧文件")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _insert(lib: str, name: str, data_path: Path | bytes, size: int, sha: str,
            kind: str, source: str, **extra: Any) -> Dict[str, Any]:
    with _LOCK:
        rows = _read_rows()
        for row in rows:
            if (row.get("deleted") or _row_lib(row) != lib
                    or row.get("sha256") != sha):
                continue
            if _abs(row).is_file():
                out = _public(row, with_path=True)
                out["existing"] = True
                return out
        _check_quota(lib, rows, size)
        month = time.strftime("%Y.%m")
        folder = _lib_dir(lib) / kind / month
        folder.mkdir(parents=True, exist_ok=True)
        ext = Path(name).suffix.lower()
        dest = folder / f"{sha[:8]}_{_safe_piece(Path(name).stem, 'file')}{ext}"
        if isinstance(data_path, Path):
            if not dest.is_file():
                shutil.copy2(data_path, dest)
        else:
            dest.write_bytes(data_path)
        row = {
            "id": uuid.uuid4().hex[:10],
            "name": Path(name).name,
            "title": str(extra.get("title") or ""),
            "ext": ext,
            "kind": kind,
            "bytes": int(size),
            "sha256": sha,
            "rel": str(dest.relative_to(_ensure())).replace("\\", "/"),
            "at": time.time(),
            "library": lib,
            "source": source,
            "desc": str(extra.get("desc") or ""),
            "tags": list(extra.get("tags") or []),
            "why": str(extra.get("why") or ""),
            "preview": str(extra.get("preview") or ""),
            "readable": extra.get("readable"),
            "inspected_at": extra.get("inspected_at"),
            "kept": bool(extra.get("kept")),
            "origin_id": str(extra.get("origin_id") or ""),
            "memory_id": str(extra.get("memory_id") or ""),
            "deleted": False,
        }
        rows.append(row)
        _write_rows(rows)
        out = _public(row, with_path=True)
        out["existing"] = False
        return out


def import_file(src: str | Path, source: str = "owner", name: str = "",
                library: str = "") -> Dict[str, Any]:
    _ensure()
    p = Path(str(src))
    if not p.is_file():
        raise ValueError("找不到这个文件")
    ext = p.suffix.lower()
    if ext in BLOCKED_EXTS:
        raise ValueError(f"不收这种文件：{ext}")
    display = name or p.name
    kind = _kind_of(display)
    size = p.stat().st_size
    limit = MAX_IMAGE if kind == "image" else MAX_FILE
    if size > limit:
        raise ValueError(f"文件太大（上限 {limit // (1024 * 1024)} MB）")
    lib = _safe_lib(library) if library else _ensure_source_lib(source)
    libs = _read_libs()
    if lib not in libs:
        raise ValueError("仓库里没有这个库")
    return _insert(lib, display, p, size, _sha256_file(p), kind,
                   _source_for_lib(lib, libs))


def put_bytes(source: str, name: str, data: bytes, kind: str = "",
              library: str = "") -> Dict[str, Any]:
    _ensure()
    if not data:
        raise ValueError("空文件")
    ext = Path(str(name or "")).suffix.lower()
    if ext in BLOCKED_EXTS:
        raise ValueError(f"不收这种文件：{ext}")
    k = kind if kind in ("image", "document", "file") else _kind_of(name)
    limit = MAX_IMAGE if k == "image" else MAX_FILE
    if len(data) > limit:
        raise ValueError(f"文件太大（上限 {limit // (1024 * 1024)} MB）")
    lib = _safe_lib(library) if library else _ensure_source_lib(source)
    libs = _read_libs()
    if lib not in libs:
        raise ValueError("仓库里没有这个库")
    return _insert(lib, name, data, len(data), _sha256_bytes(data), k,
                   _source_for_lib(lib, libs))


def list_items(source: str | None = None, kind: str = "", query: str = "",
               with_path: bool = False, library: str | None = None) -> List[Dict[str, Any]]:
    with _LOCK:
        rows = [r for r in _read_rows() if not r.get("deleted")]
    if library:
        rows = [r for r in rows if _row_lib(r) == _safe_lib(library)]
    if source:
        rows = [r for r in rows if r.get("source") == source]
    if kind:
        rows = [r for r in rows if r.get("kind") == kind]
    q = str(query or "").strip().lower()
    if q:
        def hay(r: Dict[str, Any]) -> str:
            return " ".join([
                str(r.get("name") or ""), str(r.get("title") or ""),
                str(r.get("desc") or ""), str(r.get("why") or ""),
                " ".join(str(t) for t in (r.get("tags") or [])),
            ]).lower()
        rows = [r for r in rows if q in hay(r)]
    rows.sort(key=lambda r: float(r.get("at") or 0), reverse=True)
    return [_public(r, with_path) for r in rows]


def search(query: str, library: str = "", kind: str = "") -> List[Dict[str, Any]]:
    return list_items(library=library or None, kind=kind, query=query)


def get(item_id: str, with_path: bool = True) -> Dict[str, Any] | None:
    ref = str(item_id or "")
    with _LOCK:
        for row in _read_rows():
            if row.get("deleted"):
                continue
            if str(row.get("id")) == ref:
                return _public(row, with_path)
    return None


def resolve(ref: str, source: str | None = None,
            library: str | None = None) -> Dict[str, Any] | None:
    ref = str(ref or "").strip()
    if not ref:
        return None
    hit = get(ref)
    if hit:
        if source and hit.get("source") != source:
            return None
        if library and hit.get("library") != _safe_lib(library):
            return None
        return hit
    with _LOCK:
        rows = [r for r in _read_rows() if not r.get("deleted")]
    if source:
        rows = [r for r in rows if r.get("source") == source]
    if library:
        rows = [r for r in rows if _row_lib(r) == _safe_lib(library)]
    rows = [r for r in rows
            if str(r.get("name") or "") == ref
            or str(r.get("title") or "") == ref
            or Path(str(r.get("name") or "")).stem == ref]
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


def update_meta(item_id: str, **fields: Any) -> Dict[str, Any]:
    allow = {"title", "desc", "why", "tags", "preview", "readable",
             "inspected_at", "memory_id", "kept"}
    with _LOCK:
        rows = _read_rows()
        hit = None
        for row in rows:
            if str(row.get("id")) == str(item_id) and not row.get("deleted"):
                hit = row
                break
        if hit is None:
            raise ValueError("仓库里没有这一条")
        for key, value in fields.items():
            if key in allow:
                hit[key] = value
        _write_rows(rows)
        return _public(hit, True)


def keep(item_id: str, title: str = "", desc: str = "", why: str = "",
         tags: list | None = None, memory_id: str = "") -> Dict[str, Any]:
    """把一条复制进 agent-collection；原条目留着。"""
    row = get(item_id)
    if not row:
        raise ValueError("仓库里没有这一条")
    if row.get("library") == AGENT_LIB:
        out = dict(row)
        out["existing"] = True
        return out
    src = Path(str(row.get("path") or ""))
    if not src.is_file():
        raise ValueError("原文件已经不见了")
    libs = _read_libs()
    out = _insert(AGENT_LIB, str(row.get("name") or "item"), src,
                  int(row.get("bytes") or 0), str(row.get("sha256") or ""),
                  str(row.get("kind") or "file"), _source_for_lib(AGENT_LIB, libs),
                  title=title or row.get("title") or Path(str(row.get("name"))).stem,
                  desc=desc or row.get("desc") or "",
                  why=why, tags=list(tags or []),
                  preview=row.get("preview") or "",
                  readable=row.get("readable"),
                  inspected_at=row.get("inspected_at") or time.time(),
                  kept=True, origin_id=row.get("id"), memory_id=memory_id)
    if out.get("library") != AGENT_LIB:
        # 已存在同 sha 的收藏：补上来源和说明
        out = update_meta(str(out.get("id")), title=title or row.get("title") or "",
                          desc=desc or row.get("desc") or "", why=why,
                          tags=list(tags or []), kept=True,
                          origin_id=row.get("id"), memory_id=memory_id)
    return out


def collection(query: str = "", limit: int = 20) -> List[Dict[str, Any]]:
    rows = list_items(library=AGENT_LIB, query=query)
    return rows[: max(1, int(limit))]


def related(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    q = str(query or "").strip().lower()
    rows = collection()
    if not q:
        return rows[:limit]
    tokens = [t for t in re.split(r"[\s,，。.!！?？]+", q)
              if len(t) >= 2 or ("\u4e00" <= t <= "\u9fff")]
    scored = []
    for row in rows:
        hay = " ".join([str(row.get("title") or ""), str(row.get("desc") or ""),
                        str(row.get("why") or ""),
                        " ".join(str(t) for t in (row.get("tags") or []))]).lower()
        score = sum(1 for t in tokens if t in hay)
        if score:
            scored.append((score, float(row.get("at") or 0), row))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [x[2] for x in scored[:limit]]


def fragment(query: str = "", limit: int = 4) -> str:
    """给提示词的一小块；没有收藏就返回空。"""
    rows = related(query, limit) if query else collection(limit=limit)
    if not rows:
        return ""
    lines = ["# 我收着的东西",
             "这些不是缓存，是我看完之后自己留下的副本；为什么留，写在每一条里。"]
    for row in rows[:limit]:
        title = row.get("title") or row.get("name") or "一件东西"
        desc = row.get("desc") or ""
        line = f"- 《{title}》（{row.get('kind')}，{row.get('id')}）"
        if desc:
            line += f"：{desc[:120]}"
        tags = [str(t) for t in (row.get("tags") or []) if str(t)]
        if tags:
            line += f"〔{'、'.join(tags[:4])}〕"
        lines.append(line)
    lines.append("想翻的时候用 warehouse_search；想给他看用 send_media；没看过的不要假装看过。")
    return "\n".join(lines)


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


def mkdir(source: str, name: str, library: str = "") -> Dict[str, Any]:
    piece = _safe_piece(name, "")
    if not piece:
        raise ValueError("目录名不能为空")
    lib = _safe_lib(library) if library else _lib_from_source(source)
    base = _lib_dir(lib).resolve()
    target = (base / piece).resolve()
    if base not in target.parents and target != base:
        raise ValueError("不能建到仓库外面")
    target.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "path": str(target),
            "rel": str(target.relative_to(_ensure())).replace("\\", "/"),
            "library": lib}


def stats(source: str | None = None, library: str | None = None) -> Dict[str, int]:
    rows = list_items(source=source, library=library)
    return {"count": len(rows),
            "bytes": sum(int(r.get("bytes") or 0) for r in rows)}
