"""启动器侧访问内核仓库（`WiseEntity/entity/core/warehouse.py`）。

显式转出函数，避免 `from ... import warehouse` 时只拿到一个局部名字。
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from WiseEntity.entity.core import warehouse as _w  # noqa: E402

INDEX_NAME = _w.INDEX_NAME
LIBRARIES_NAME = _w.LIBRARIES_NAME
OWNER_LIB = _w.OWNER_LIB
AGENT_LIB = _w.AGENT_LIB
IMAGE_EXTS = _w.IMAGE_EXTS
DOC_EXTS = _w.DOC_EXTS
TEXT_EXTS = _w.TEXT_EXTS
BLOCKED_EXTS = _w.BLOCKED_EXTS
MAX_IMAGE = _w.MAX_IMAGE
MAX_FILE = _w.MAX_FILE
MAX_TOTAL = _w.MAX_TOTAL
MAX_LIBRARIES = _w.MAX_LIBRARIES
MAX_LIB_QUOTA = _w.MAX_LIB_QUOTA


def root():
    return _w.root()


def libraries_root():
    return _w.libraries_root()


def kind_of(name: str) -> str:
    return _w.kind_of(name)


def libraries():
    return _w.libraries()


def ensure_library(lib, owner_type, owner_id, title="", purpose="",
                   quota_mb=0, default=False):
    return _w.ensure_library(lib, owner_type, owner_id, title=title,
                             purpose=purpose, quota_mb=quota_mb, default=default)


def module_specs(mid):
    return _w.module_specs(mid)


def module_libraries(mid):
    return _w.module_libraries(mid)


def module_library_id(mid, name="main"):
    return _w.module_library_id(mid, name)


def import_file(src, source: str = "owner", name: str = "", library: str = ""):
    return _w.import_file(src, source=source, name=name, library=library)


def put_bytes(source: str, name: str, data: bytes, kind: str = "", library: str = ""):
    return _w.put_bytes(source, name, data, kind=kind, library=library)


def list_items(source=None, kind: str = "", query: str = "",
               with_path: bool = False, library=None):
    return _w.list_items(source=source, kind=kind, query=query,
                         with_path=with_path, library=library)


def search(query: str, library: str = "", kind: str = ""):
    return _w.search(query, library=library, kind=kind)


def get(item_id: str, with_path: bool = True):
    return _w.get(item_id, with_path=with_path)


def resolve(ref: str, source=None, library=None):
    return _w.resolve(ref, source=source, library=library)


def find_by_path(path):
    return _w.find_by_path(path)


def is_inside(path) -> bool:
    return _w.is_inside(path)


def read_text(item_id: str, max_chars: int = 20000):
    return _w.read_text(item_id, max_chars=max_chars)


def update_meta(item_id: str, **fields):
    return _w.update_meta(item_id, **fields)


def keep(item_id: str, title="", desc="", why="", tags=None, memory_id=""):
    return _w.keep(item_id, title=title, desc=desc, why=why, tags=tags,
                   memory_id=memory_id)


def collection(query="", limit=20):
    return _w.collection(query=query, limit=limit)


def related(query: str, limit: int = 5):
    return _w.related(query, limit=limit)


def fragment(query: str = "", limit: int = 4):
    return _w.fragment(query, limit=limit)


def remove(item_id: str) -> bool:
    return _w.remove(item_id)


def mkdir(source: str, name: str, library: str = ""):
    return _w.mkdir(source, name, library=library)


def stats(source=None, library=None):
    return _w.stats(source=source, library=library)
