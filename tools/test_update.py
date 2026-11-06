"""检查更新按钮：版本号、下载页地址、空地址不装死。"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import config  # noqa: E402
from app.services import update  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


# 1. 版本号读 VERSION.txt
ver = update.version()
check(bool(re.fullmatch(r"\d+\.\d+\.\d+", ver)), f"version() 读到版本号（实际 {ver!r}）")

# 2. 默认地址为空
check(isinstance(update.url(), str), "url() 返回字符串")
check(update.url() == "", f"没配置时地址为空（实际 {update.url()!r}）")

# 3. 空地址时提示、不打开
opened: list[str] = []
info: list[tuple] = []
orig_open = update.QDesktopServices.openUrl
orig_info = update.QMessageBox.information
update.QDesktopServices.openUrl = staticmethod(lambda u: opened.append(u.toString()) or True)
update.QMessageBox.information = staticmethod(lambda *a, **k: info.append(a))
try:
    ok = update.open_download(None)
    check(ok is False, "空地址时 open_download 返回 False")
    check(not opened, "空地址时没有打开任何网页")
    check(bool(info), "空地址时给了提示")
finally:
    update.QDesktopServices.openUrl = orig_open
    update.QMessageBox.information = orig_info

# 4. 配了地址就打开
orig_get = config.get
config.get = lambda key, default=None: "https://example.test/download" if key == "update_url" else orig_get(key, default)
update.config.get = config.get
opened.clear()
update.QDesktopServices.openUrl = staticmethod(lambda u: opened.append(u.toString()) or True)
try:
    ok = update.open_download(None)
    check(ok is True, "配了地址时 open_download 返回 True")
    check(opened == ["https://example.test/download"], f"打开的是配置的地址（实际 {opened}）")
finally:
    update.QDesktopServices.openUrl = orig_open
    config.get = orig_get
    update.config.get = orig_get

# 5. 读不到 VERSION.txt 时回空串
orig_dir = update.config.APP_DIR
with tempfile.TemporaryDirectory() as td:
    update.config.APP_DIR = Path(td)
    try:
        check(update.version() == "", "读不到 VERSION.txt 时返回空串")
    finally:
        update.config.APP_DIR = orig_dir

print(f"\n{'FAILED' if fails else 'ALL OK'} ({len(fails)} fail)")
sys.exit(1 if fails else 0)
