"""检查更新 + 下载/校验/应用更新包。

只信任 GitHub Release 里的 `update.json`：它写明版本、zip 文件名、sha256、大小。
真正的文件替换交给独立 Python helper，启动器退出后它才动手，避免锁文件。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, Optional

import httpx
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QWidget

from ..core import config

REPO = "Chanko-bab/BetterAIBridge"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
MARKET_PAGE = "https://chanko-bab.github.io/BetterAIBridge/modules.html"
UPDATE_MANIFEST = "update.json"
USER_AGENT = "BetterAIBridge-Updater/1"

# 更新包只允许碰这些位置；人格/记忆/配置/自我/状态/模组数据永远不进更新包。
ALLOWED = (
    "main.py",
    "launch.vbs",
    "BetterAIBridge.vbs",
    "start.cmd",
    "VERSION.txt",
    "app/",
    "assets/",
    "WiseEntity/entity/core/",
    "WiseEntity/entity/brain/",
    "WiseEntity/source_code/scripts/",
)
BLOCKED = (
    "WiseEntity/entity/config/",
    "WiseEntity/entity/memory/",
    "WiseEntity/entity/state/",
    "WiseEntity/entity/self/",
    "WiseEntity/entity/persona/",
    "WiseEntity/runtime/",
    "program_bundle/",
    "program_cache/",
    "local_tts/",
    "logs/",
    ".venv/",
)
BRAIN_ALLOWED_SUFFIX = (".py", ".md")


class UpdateError(RuntimeError):
    """更新流程里的可读错误。"""


@dataclass
class UpdateInfo:
    version: str
    notes: str
    update_url: str
    sha256: str
    size: int
    setup_url: str = ""
    manifest_url: str = ""


def url() -> str:
    """旧的下载页地址，保留兼容。"""
    try:
        return str(config.get("update_url") or "").strip()
    except (OSError, ValueError, TypeError, KeyError):
        return ""


def market_url() -> str:
    try:
        return str(config.get("market_url") or MARKET_PAGE).strip() or MARKET_PAGE
    except (OSError, ValueError, TypeError, KeyError):
        return MARKET_PAGE


def version() -> str:
    """返回当前安装目录里的 '0.6.0'；读不到就空串。"""
    try:
        p = Path(config.APP_DIR) / "VERSION.txt"
        text = p.read_text(encoding="utf-8-sig").strip()
        parts = text.split()
        return parts[-1] if parts else ""
    except (OSError, UnicodeError, IndexError):
        return ""


def parse_version(text: str) -> tuple[int, int, int]:
    nums = [int(x) for x in re.findall(r"\d+", str(text or ""))[:3]]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)  # type: ignore[return-value]


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def _ssl_context() -> ssl.SSLContext:
    """用系统证书库；certifi 在这台机器上不认企业代理根证书。"""
    return ssl.create_default_context()


def _fetch_json(url: str, timeout: float = 12.0) -> dict:
    try:
        r = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
            timeout=timeout,
            follow_redirects=True,
            verify=_ssl_context(),
        )
    except httpx.HTTPError as e:
        raise UpdateError(f"连不上 GitHub：{e}") from e
    if r.status_code == 404:
        raise UpdateError("GitHub 上还没有发布版本。")
    if r.status_code != 200:
        raise UpdateError(f"GitHub 返回 {r.status_code}，暂时查不了更新。")
    try:
        return r.json()
    except ValueError as e:
        raise UpdateError("GitHub 返回的不是有效 JSON。") from e


def _asset(payload: dict, name: str) -> Optional[dict]:
    for a in payload.get("assets") or []:
        if isinstance(a, dict) and a.get("name") == name:
            return a
    return None


def latest_release(fetch: Callable[[str], dict] = _fetch_json) -> dict:
    payload = fetch(API_LATEST)
    if not isinstance(payload, dict):
        raise UpdateError("GitHub 的 release 数据格式不对。")
    tag = str(payload.get("tag_name") or "").strip()
    if not tag:
        raise UpdateError("最新 release 没有版本号。")
    return {
        "version": tag.lstrip("v"),
        "notes": str(payload.get("body") or "").strip(),
        "payload": payload,
    }


def latest_info(fetch: Callable[[str], dict] = _fetch_json, release: Optional[dict] = None) -> UpdateInfo:
    rel = release or latest_release(fetch)
    payload = rel["payload"]
    man_asset = _asset(payload, UPDATE_MANIFEST)
    if not man_asset or not man_asset.get("browser_download_url"):
        raise UpdateError("这个版本没有自动更新包，请用下载页手动安装。")
    manifest = fetch(str(man_asset["browser_download_url"]))
    if not isinstance(manifest, dict):
        raise UpdateError("更新清单格式不对。")
    ver = str(manifest.get("version") or "").strip().lstrip("v")
    if not ver or parse_version(ver) != parse_version(rel["version"]):
        raise UpdateError("更新清单版本和 release 版本对不上。")
    fname = str(manifest.get("file") or "").strip()
    if not fname:
        raise UpdateError("更新清单没有文件名。")
    asset = _asset(payload, fname)
    if not asset or not asset.get("browser_download_url"):
        raise UpdateError("release 里找不到更新包文件。")
    sha = str(manifest.get("sha256") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise UpdateError("更新清单的 sha256 不对。")
    size = int(manifest.get("size") or 0)
    setup = _asset(payload, f"BetterAIBridge-Setup-{ver}.exe")
    return UpdateInfo(
        version=ver,
        notes=rel["notes"],
        update_url=str(asset["browser_download_url"]),
        sha256=sha,
        size=max(0, size),
        setup_url=str((setup or {}).get("browser_download_url") or ""),
        manifest_url=str(man_asset["browser_download_url"]),
    )


def check(current: Optional[str] = None, fetch: Callable[[str], dict] = _fetch_json) -> Optional[UpdateInfo]:
    """有新版返回 UpdateInfo；没有返回 None。"""
    rel = latest_release(fetch)
    cur = current if current is not None else version()
    if not is_newer(rel["version"], cur):
        return None
    return latest_info(fetch, rel)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _open_url(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=30, context=_ssl_context())


def download(
    url: str,
    dest: Path,
    sha256: str,
    size: int = 0,
    progress: Optional[Callable[[int, int], None]] = None,
) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    done = 0
    try:
        with _open_url(url) as resp, open(tmp, "wb") as f:
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, size)
        if size and done != size:
            raise UpdateError(f"更新包大小不对：收到 {done}，应为 {size}。")
        if h.hexdigest().lower() != sha256.lower():
            raise UpdateError("更新包校验失败，已丢弃下载文件。")
        os.replace(tmp, dest)
        return dest
    except UpdateError:
        tmp.unlink(missing_ok=True)
        raise
    except (OSError, ValueError, TypeError) as e:
        tmp.unlink(missing_ok=True)
        raise UpdateError(f"下载失败：{e}") from e


def _safe_name(name: str) -> str:
    name = name.replace("\\", "/")
    p = PurePosixPath(name)
    if p.is_absolute() or any(part in ("..", "") for part in p.parts):
        raise UpdateError("更新包里有不安全的路径。")
    norm = "/".join(p.parts)
    if norm.endswith("/"):
        norm = norm[:-1]
    if norm.startswith("BetterAIBridge-") and "/" in norm:
        # 允许整包套一层目录时自动剥掉（当前 build 不带，保留兼容）
        head, _, tail = norm.partition("/")
        if tail:
            return tail
    return norm


def _allowed(norm: str) -> bool:
    if norm in ("main.py", "launch.vbs", "BetterAIBridge.vbs", "start.cmd", "VERSION.txt"):
        return True
    if any(norm.startswith(p) for p in BLOCKED):
        return False
    if norm.startswith("WiseEntity/entity/brain/"):
        return norm.endswith(BRAIN_ALLOWED_SUFFIX)
    return any(norm.startswith(p) for p in ALLOWED)


def safe_extract(zip_path: Path, dest: Path) -> list[str]:
    """只解压白名单文件；宁可失败，也不碰用户数据。"""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    extracted: list[str] = []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            norm = _safe_name(info.filename)
            if not _allowed(norm):
                raise UpdateError(f"更新包含不允许的路径：{norm}")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise UpdateError(f"更新包含符号链接：{norm}")
            target = (dest / norm).resolve()
            if root not in target.parents and target != root:
                raise UpdateError(f"更新路径越界：{norm}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            extracted.append(norm)
    if "VERSION.txt" not in extracted:
        raise UpdateError("更新包缺少 VERSION.txt。")
    return extracted


def helper_source_path() -> Path:
    """独立 Python 更新助手在安装目录里的位置。"""
    return Path(config.APP_DIR).resolve() / "app" / "services" / "update_helper.py"


def _helper_log_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "BetterAIBridge" / "logs" / "update.log"


def helper_state_path() -> Path:
    return _helper_log_path().with_name("update_state.json")


def helper_state() -> str:
    try:
        data = json.loads(helper_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ""
    return str(data.get("state") or "")


def _helper_log(message: str) -> None:
    path = _helper_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{message}\n")
    except OSError:
        pass


def spawn_helper(install_dir: Path, zip_path: Path, version: str, parent_pid: int) -> int:
    """启动独立 Python 助手；返回 helper pid。

    Python 助手不经过 PowerShell 执行策略，也不依赖 .vbs 文件关联。
    """
    helper = helper_source_path()
    if not helper.exists():
        raise UpdateError("更新助手缺失：app/services/update_helper.py")

    python = Path(sys.executable)
    if python.name.lower() == "python.exe":
        pythonw = python.with_name("pythonw.exe")
        if pythonw.exists():
            python = pythonw
    try:
        helper_state_path().unlink(missing_ok=True)
    except OSError:
        pass
    _helper_log(f"spawn helper version={version} parent={parent_pid}")
    cmd = [
        str(python), "-I", str(helper),
        "--parent-pid", str(int(parent_pid)),
        "--zip", str(zip_path),
        "--dir", str(install_dir),
        "--version", str(version),
    ]
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    proc = None
    try:
        proc = subprocess.Popen(cmd, close_fds=True, creationflags=flags | 0x01000000)
    except OSError:
        proc = subprocess.Popen(cmd, close_fds=True, creationflags=flags)
    _helper_log(f"spawn helper pid={proc.pid}")
    return int(proc.pid)


def wait_helper_ready(timeout: float = 6.0) -> bool:
    """等 helper 写 ready；失败或超时返回 False。供单测/无 QTimer 调用。"""
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        state = helper_state()
        if state in ("ready", "done"):
            return True
        if state == "failed":
            return False
        time.sleep(0.1)
    return False


def installed() -> bool:
    try:
        return bool(config.install_info().get("install_id"))
    except (OSError, ValueError, TypeError, KeyError):
        return False


def open_market(parent: Optional[QWidget] = None) -> bool:
    return bool(QDesktopServices.openUrl(QUrl(market_url())))


def open_download(parent: Optional[QWidget] = None) -> bool:
    target = url()
    if not target:
        QMessageBox.information(
            parent, "检查更新",
            "下载页地址还没配置。\\n\\n可以在 config\\\\app.yaml 里填 update_url。",
        )
        return False
    return bool(QDesktopServices.openUrl(QUrl(target)))
