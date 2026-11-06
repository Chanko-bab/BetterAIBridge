"""内核本机鉴权：token 文件、header、公开路径、CoreClient 带头。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "WiseEntity"))

from entity.core import auth  # noqa: E402
from app.services import core_client  # noqa: E402


class Req:
    def __init__(self, headers=None, cookies=None):
        self.headers = dict(headers or {})
        self.cookies = cookies or {}


n = 0


def main() -> int:
    old_path = auth.TOKEN_PATH
    old_cache = dict(core_client._TOKEN_CACHE)
    with tempfile.TemporaryDirectory() as td:
        auth.TOKEN_PATH = Path(td) / "state" / "core_token"
        tok = auth.token()
        check(bool(tok) and len(tok) >= 20, "token 要够长")
        check(auth.token() == tok, "token 要稳定，不能每次重生成")
        check(auth.TOKEN_PATH.is_file(), "token 文件要落盘")
        check(auth.ok(Req({"x-bab-core-token": tok})), "正确 header 要放行")
        check(not auth.ok(Req({"x-bab-core-token": tok + "x"})), "错误 header 要拒绝")
        check(not auth.ok(Req()), "没 header 要拒绝")
        check(auth.ok(Req(cookies={"bab_core_token": tok})), "同源 cookie 要放行")
        check(auth.ok(Req({"authorization": "Bearer " + tok})), "Bearer 要放行")
        check(auth.matches(tok), "token 比对要正确")
        check(not auth.matches(tok + "x"), "错误 token 比对要拒绝")
        check(auth.public("/health"), "/health 要公开")
        check(auth.public("/bridge/call"), "/bridge/* 由桥自己的 token 管")
        check(not auth.public("/state"), "/state 不能公开")

        # 启动器读同一个文件，给每个请求带 header
        core_client._TOKEN_CACHE.update({"path": "", "mtime": 0.0, "token": ""})
        old_entity = core_client.config.entity_dir
        core_client.config.entity_dir = lambda: Path(td)  # type: ignore[assignment]
        try:
            h = core_client._local_headers()
            check(h.get("X-BAB-Core-Token") == tok, "CoreClient 要带内核 token")
        finally:
            core_client.config.entity_dir = old_entity  # type: ignore[assignment]

    auth.TOKEN_PATH = old_path
    core_client._TOKEN_CACHE.update(old_cache)
    print(f"core auth: {n} checks ok")
    return 0


def check(ok: bool, msg: str) -> None:
    global n
    n += 1
    if not ok:
        raise AssertionError(msg)


if __name__ == "__main__":
    raise SystemExit(main())
