"""内核 HTTP 鉴权集成：真实 FastAPI middleware（kernel venv）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "WiseEntity"))

from fastapi.testclient import TestClient  # noqa: E402

from entity.core.app import app  # noqa: E402
from entity.core import auth  # noqa: E402


def main() -> int:
    tok = auth.token()
    with TestClient(app) as c:
        check(c.get("/health").status_code == 200, "/health 要公开")
        check(c.get("/state").status_code == 401, "/state 没 token 要 401")
        r = c.get("/state", headers={"X-BAB-Core-Token": tok})
        check(r.status_code == 200, "/state 带 token 要 200")
        check(c.get("/").status_code == 401, "/ 没 token 要 401")
        check(c.get("/bridge/manifest").status_code == 401, "/bridge/* 由桥自己的 token 判 401")
    print("core http auth ok")
    return 0


def check(ok: bool, msg: str) -> None:
    if not ok:
        raise AssertionError(msg)


if __name__ == "__main__":
    raise SystemExit(main())
