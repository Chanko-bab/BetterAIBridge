"""本机内核鉴权。

为什么要这层：
  内核只监听 127.0.0.1，但本机任何进程都能访问 127.0.0.1。
  没有这层 token，别的程序可以直接 GET /memory、POST /chat，用掉用户的 Key。

边界：
  - 只防“本机其他进程顺手调用”，不是防同用户恶意软件（它仍可读 token 文件）。
  - /health 保持公开，供启动器探活。
  - /bridge/* 由模组自己的 X-BAB-Token 鉴权，不再套这一层。
  - 网页客厅 / 需要 token，暂不做浏览器登录；启动器是主入口。
"""
from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path
from typing import Any

from . import settings as S

HEADER = "x-bab-core-token"
COOKIE = "bab_core_token"
PUBLIC_EXACT = {"/health"}
PUBLIC_PREFIX = ("/bridge/",)
TOKEN_PATH: Path = S.STATE_DIR / "core_token"


def _read() -> str:
    try:
        return TOKEN_PATH.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        return ""


def token(force: bool = False) -> str:
    """读或创建 token；并发启动时只有一个进程能写，其他读赢家。"""
    if not force:
        got = _read()
        if len(got) >= 20:
            return got
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    val = secrets.token_urlsafe(32)
    try:
        fd = os.open(str(TOKEN_PATH), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(val)
        return val
    except FileExistsError:
        got = _read()
        if len(got) >= 20:
            return got
        # 文件在但空/坏：覆盖为新的（极小概率）
        TOKEN_PATH.write_text(val + "\n", encoding="utf-8")
        return val


def public(path: str) -> bool:
    p = str(path or "")
    if p in PUBLIC_EXACT:
        return True
    return any(p.startswith(x) for x in PUBLIC_PREFIX)


def _header(request: Any, name: str) -> str:
    try:
        return str(request.headers.get(name) or "")
    except Exception:  # noqa: BLE001
        return ""


def matches(value: str) -> bool:
    want = _read()
    return len(want) >= 20 and bool(value) and hmac.compare_digest(str(value), want)


def ok(request: Any) -> bool:
    """接受 header 或同源 cookie；失败一律 False。"""
    got = _header(request, HEADER)
    if not got:
        auth = _header(request, "authorization")
        if auth.lower().startswith("bearer "):
            got = auth[7:].strip()
    if not got:
        try:
            got = str(request.cookies.get(COOKIE) or "")
        except Exception:  # noqa: BLE001
            got = ""
    return matches(got)
