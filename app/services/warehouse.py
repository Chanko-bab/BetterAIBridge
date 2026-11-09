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
IMAGE_EXTS = _w.IMAGE_EXTS
DOC_EXTS = _w.DOC_EXTS
TEXT_EXTS = _w.TEXT_EXTS
BLOCKED_EXTS = _w.BLOCKED_EXTS
MAX_IMAGE = _w.MAX_IMAGE
MAX_FILE = _w.MAX_FILE
MAX_TOTAL = _w.MAX_TOTAL


def root():
    return _w.root()


def kind_of(name: str) -> str:
    return _w.kind_of(name)


def import_file(src, source: str = "owner", name: str = ""):
    return _w.import_file(src, source=source, name=name)


def put_bytes(source: str, name: str, data: bytes, kind: str = ""):
    return _w.put_bytes(source, name, data, kind=kind)


def list_items(source=None, kind: str = "", query: str = "", with_path: bool = False):
    return _w.list_items(source=source, kind=kind, query=query, with_path=with_path)


def get(item_id: str, with_path: bool = True):
    return _w.get(item_id, with_path=with_path)


def resolve(ref: str, source=None):
    return _w.resolve(ref, source=source)


def find_by_path(path):
    return _w.find_by_path(path)


def is_inside(path) -> bool:
    return _w.is_inside(path)


def read_text(item_id: str, max_chars: int = 20000):
    return _w.read_text(item_id, max_chars=max_chars)


def remove(item_id: str) -> bool:
    return _w.remove(item_id)


def mkdir(source: str, name: str):
    return _w.mkdir(source, name)


def stats(source=None):
    return _w.stats(source=source)
