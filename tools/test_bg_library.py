"""背景图片内部库：导入复制、sha 去重、索引、删除。"""
from __future__ import annotations

import base64
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import bg_library  # noqa: E402

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


def main():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        lib = base / "lib"
        old_root = bg_library.root
        bg_library.root = lambda: lib
        try:
            src = base / "我的 图.png"
            src.write_bytes(PNG)

            r1 = bg_library.import_file(src)
            check("import ok", Path(r1["path"]).is_file())
            check("import existing false", r1.get("existing") is False)
            check("import under lib", lib in Path(r1["path"]).parents)
            check("index one line", len((lib / "index.jsonl").read_text(encoding="utf-8").splitlines()) == 1)

            r2 = bg_library.import_file(src)
            check("dedupe same path", r2["path"] == r1["path"], (r1["path"], r2["path"]))
            check("dedupe existing true", r2.get("existing") is True)
            check("dedupe one item", len(bg_library.list_items()) == 1)

            check("find_by_path", (bg_library.find_by_path(r1["path"]) or {}).get("id") == r1["id"])
            check("stats", bg_library.stats()["count"] == 1)
            check("touch", bg_library.touch(r1["id"]) is not None)
            check("get", (bg_library.get(r1["id"]) or {}).get("name") == "我的 图.png")

            src2 = base / "second.jpg"
            src2.write_bytes(b"\xff\xd8\xff" + b"0" * 64)
            r3 = bg_library.import_file(src2)
            check("second import", r3["path"] != r1["path"])
            check("two items", len(bg_library.list_items()) == 2)

            bad = base / "not-image.png"
            bad.write_text("hello", encoding="utf-8")
            try:
                bg_library.import_file(bad)
                check("reject text", False)
            except ValueError:
                check("reject text", True)

            txt = base / "a.txt"
            txt.write_text("hello", encoding="utf-8")
            try:
                bg_library.import_file(txt)
                check("reject ext", False)
            except ValueError:
                check("reject ext", True)

            old_max = bg_library.MAX_BYTES
            bg_library.MAX_BYTES = 10
            try:
                bg_library.import_file(src)
                check("reject big", False)
            except ValueError:
                check("reject big", True)
            finally:
                bg_library.MAX_BYTES = old_max

            check("remove", bg_library.remove(r1["id"]) is True)
            check("removed file gone", not Path(r1["path"]).is_file())
            check("removed hidden", all(i["id"] != r1["id"] for i in bg_library.list_items()))
            check("remove again false", bg_library.remove(r1["id"]) is False)

            rows = [json.loads(x) for x in (lib / "index.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
            check("index still valid", len(rows) == 2, len(rows))
            check("deleted marked", any(r.get("deleted") and r["id"] == r1["id"] for r in rows))
            check("no tmp left", not (lib / "index.jsonl.tmp").exists())
        finally:
            bg_library.root = old_root

    print(f"\n{PASS} passed, {FAIL} failed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
