"""`.pbab` 模组：识别、安装、启用/停用、完全卸载、设置。

两种形态，同一套校验：

1. **文件夹**（已安装的样子，推荐）
   ```
   program_bundle\\program_<id>.pbab\\
       module.json        清单（必填：id/version/entry/health/ports/links/memory）
       introduce.md       介绍（必填，字数不限）
       connection.json    接入声明（必填，provides 对象）
       settings.json      设置（可选：{"schema": {...}, "values": {...}}）
       main\\              主要程序（可选；有 exe/服务就放这）
       tools\\             工具（可选；插件、脚本）
       ...                其它文件随便放（框架还没定型，允许 XXXX.pbab 之类）
   ```
2. **单文件 zip**（用来分发/导入）：同上，只是压缩成一个文件，导入后展开成 (1)。

判定"可用"的最小集：`module.json` + `introduce.md` + `connection.json`
+ 若 `entry.start` 指向文件，该文件必须存在。
缺任何一项 = 不可用，不进注册表、不进模组页。

清单格式（module.json）：
    {"format": "pbab/1", "id": "my_module", "name": "我的模组", "version": "1.0.0",
     "api": 1, "kind": "bridge", "summary": "...",
     "payload": {"mode": "external", "path": "program_name"},
     "entry": {"start": "start.cmd"},
       "health": {"type": "port", "host": "127.0.0.1", "port": 12345, "timeout_s": 60},
       "ports": [12345], "links": {"SomeDir": "some/sub/dir"},
     "memory": {"program": "program_demo", "scopes": ["owner"]}}
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from . import config, logger, registry
from .pbab_process import (
    _install_base,
    _kill_module_procs,
    _kill_pid_files,
    _kill_port_owners,
    _pid_alive,
    _port_open,
    _wait_health,
)

log = logger.get()

# 端口分配要「先占住再交出去」：两个模组同时启用时，只 bind 一下再释放，
# 两边会双双拿到同一个“空闲”端口，后起的那个绑不上直接崩。
_PORTS_LOCK = threading.Lock()
_RESERVED_PORTS: set = set()

# 同一个模组同时点两次启用时，第二次要等第一次跑完，避免起两个进程。
_ENABLE_LOCKS: Dict[str, threading.Lock] = {}
_ENABLE_LOCKS_GUARD = threading.Lock()

API_VERSION = 1
MODULE_SUFFIX = ".pbab"
MANIFEST = "module.json"
INTRODUCE = "introduce.md"
CONNECTION = "connection.json"
SETTINGS = "settings.json"
SETTINGS_FALLBACK = "settings.schema.json"
CHECKSUMS = "checksums.json"
MAIN_DIR = "main"
TOOLS_DIR = "tools"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,39}$")
_FOLDER_RE = re.compile(
    r"^(?P<pre>pre-)?program_(?P<id>[a-z0-9][a-z0-9_\-]{0,39})\.pbab$")
PRE_PREFIX = "pre-"
KIND_PRE = "pre"

REQUIRED_FILES = (MANIFEST, INTRODUCE, CONNECTION)

# 改过名的模组：旧 id -> 新 id（启动时一次性迁移 registry 和安装目录）
LEGACY_ID_MAP: Dict[str, str] = {"m": "m_framework"}


class PbabError(Exception):
    """给用户看的中文错误。"""


class PbabCancelled(PbabError):
    """用户主动取消下载。

    单独一个类，免得被「多源重试」当成普通的下载失败继续试下一个源。
    """


class PbabMissingRequires(PbabError):
    """启用时缺第三方依赖。UI 按类型识别，不去猜错误文案。"""


# 安装包依赖的运行期状态：同一次启动里，安装器开着就显示「安装中」。
_INSTALLING: Dict[Tuple[str, str], Dict[str, Any]] = {}
_RESOLVE_CACHE: Dict[Tuple[str, str], Tuple[float, str, str]] = {}
_SIG_CACHE: Dict[Tuple[str, int, int, str], Tuple[bool, str, str]] = {}
_INSTALLER_MAX_BYTES = 500 * 1024 * 1024
_INSTALL_TIMEOUT = 15 * 60


# ---------------------------------------------------------------- 路径


def bundle_dir() -> Path:
    return Path(config.bundle_dir())


def folder_name(mid: str, pre: bool = False) -> str:
    return f"{PRE_PREFIX if pre else ''}program_{mid}{MODULE_SUFFIX}"


def module_dir(mid: str, pre: Optional[bool] = None) -> Path:
    """模组装在哪（文件夹形态）。

    pre=None 时按 registry 里记的 kind 判断；安装前还没有记录，调用方要显式传 pre。
    """
    if pre is None:
        rec = registry.get(mid) or {}
        pre = str(rec.get("kind") or "") == KIND_PRE
    return bundle_dir() / folder_name(mid, bool(pre))


def parse_folder_name(name: str) -> str | None:
    # Windows 的文件名不分大小写，用户手建目录时写成 program_M.pbab 很常见；
    # id 本身规定是小写，所以这里按小写匹配（module_dir 取回时大小写也能对上）。
    m = _FOLDER_RE.match(str(name).lower())
    return m.group("id") if m else None


def folder_is_pre(name: str) -> bool:
    m = _FOLDER_RE.match(str(name).lower())
    return bool(m and m.group("pre"))


def prune_missing() -> List[str]:
    """清掉 registry 里安装目录已经不在的记录。

    原则：**没装就没有信息**——不能因为以前装过、后来目录被删了，
    就让一个不存在的模组继续挂在模组页上（点什么都失败）。
    """
    data = registry.load()
    mods = data.get("modules") or {}
    gone: List[str] = []
    for mid, rec in list(mods.items()):
        d = Path(str((rec or {}).get("dir") or module_dir(mid)))
        if not d.exists():
            mods.pop(mid, None)
            gone.append(mid)
    if gone:
        data["modules"] = mods
        registry.save(data)
        log.info("清掉 %d 条失效模组记录：%s", len(gone), "、".join(gone))
    return gone


def migrate_legacy_ids() -> List[str]:
    """把改过名的模组从旧 id 迁到新 id（0.4.0：`m` -> `m_framework`）。

    只在「旧 id 在、新 id 不在」时动手：改安装目录、改 registry 里的 id/dir/folder。
    记忆抽屉（`memory.program`）**不动**——那是她的记忆，不能因为改个名就找不到。
    """
    data = registry.load()
    mods = data.get("modules") or {}
    moved: List[str] = []
    for old, new in LEGACY_ID_MAP.items():
        if old not in mods or new in mods:
            continue
        rec = dict(mods.pop(old))
        old_dir = Path(str(rec.get("dir") or module_dir(old)))
        new_dir = module_dir(new)
        if not old_dir.exists():
            # 旧记录指向的安装目录已经没了：这是「没装却还留着信息」的鬼记录，
            # 直接清掉，别把它改名成新模组继续挂在界面上。
            log.info("清掉失效的旧模组记录 %s（目录已不存在：%s）", old, old_dir)
            moved.append(f"{old}->drop")
            continue
        if not new_dir.exists():
            try:
                old_dir.rename(new_dir)
            except OSError as exc:
                log.warning("迁移 %s 的目录失败（%s）：%s", old, old_dir, exc)
        rec.update({"id": new, "dir": str(new_dir), "folder": new_dir.name})
        mods[new] = rec
        moved.append(f"{old}->{new}")
    if moved:
        data["modules"] = mods
        registry.save(data)
        log.info("模组 id 迁移：%s", "、".join(moved))
    return moved


# ---------------------------------------------------------------- 读文件


def _json_bytes(data: bytes, what: str) -> Dict[str, Any]:
    try:
        obj = json.loads(data.decode("utf-8-sig"))
    except Exception as exc:
        raise PbabError(f"{what} 不是合法 JSON：{exc}") from exc
    if not isinstance(obj, dict):
        raise PbabError(f"{what} 顶层必须是对象")
    return obj


# ---------------------------------------------------------------- 外置依赖：状态与安装


def _requires_doc(mid: str) -> List[Dict[str, Any]]:
    doc = manifest(mid)
    reqs = doc.get(REQUIRES) if isinstance(doc, dict) else None
    return [r for r in (reqs or []) if isinstance(r, dict)]


def requires_state_path(mid: str) -> Path:
    return module_dir(mid) / REQUIRES_STATE


def read_requires_state(mid: str) -> Dict[str, Any]:
    p = requires_state_path(mid)
    try:
        doc = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001
        return {}
    return doc if isinstance(doc, dict) else {}


def _write_requires_state(mid: str, doc: Dict[str, Any]) -> None:
    p = requires_state_path(mid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def _state_item(mid: str, rid: str) -> Dict[str, Any]:
    items = read_requires_state(mid).get("items")
    rec = items.get(rid) if isinstance(items, dict) else None
    return rec if isinstance(rec, dict) else {}


def detect_require(req: Dict[str, Any]) -> str:
    """按清单里的 detect 规则找个现成的路径（不下载、不安装）。"""
    det = req.get("detect") or {}
    if not isinstance(det, dict):
        return ""
    for name in det.get("env") or []:
        raw = os.environ.get(str(name), "").strip()
        if raw and Path(raw).expanduser().exists():
            return str(Path(raw).expanduser())
    for item in det.get("registry") or []:
        if not isinstance(item, dict):
            continue
        try:
            import winreg
            hive_name = str(item.get("hive") or "HKLM").upper()
            hive = {"HKLM": winreg.HKEY_LOCAL_MACHINE,
                    "HKCU": winreg.HKEY_CURRENT_USER}[hive_name]
            access = winreg.KEY_READ
            if str(item.get("view")) == "32":
                access |= winreg.KEY_WOW64_32KEY
            elif str(item.get("view")) == "64":
                access |= winreg.KEY_WOW64_64KEY
            with winreg.OpenKey(hive, str(item.get("key") or ""), 0, access) as k:
                raw, _ = winreg.QueryValueEx(k, str(item.get("value") or ""))
            p = Path(os.path.expandvars(str(raw))).expanduser()
            if item.get("append"):
                p = p / str(item["append"])
            if p.exists():
                return str(p)
        except (OSError, ValueError, TypeError):
            continue
    for raw in det.get("paths") or []:
        try:
            p = Path(os.path.expandvars(str(raw))).expanduser()
        except (OSError, RuntimeError, ValueError):
            continue
        if p.exists():
            return str(p)
    for exe in det.get("where") or []:
        try:
            out = subprocess.run(["where", str(exe)], capture_output=True, text=True, timeout=8)
        except (OSError, subprocess.SubprocessError):
            continue
        for line in (out.stdout or "").splitlines():
            if line.strip() and Path(line.strip()).exists():
                return line.strip()
    return ""


def require_status(mid: str) -> List[Dict[str, Any]]:
    """一张「还缺什么」的表：给界面显示，也给启用前把关。"""
    out: List[Dict[str, Any]] = []
    for req in _requires_doc(mid):
        rid = str(req.get("id") or "")
        install = str(req.get("install") or ("guided" if req.get("kind") == "app" else "download"))
        rec = _state_item(mid, rid)
        base = {
            "id": rid, "name": str(req.get("name") or rid),
            "kind": str(req.get("kind") or "runtime"), "install": install,
            "source": [str(x) for x in (req.get("source") or [])],
            "homepage": str(req.get("homepage") or ""),
            "license_url": str(req.get("license_url") or ""),
            "sha256": str(req.get("sha256") or ""), "size": int(req.get("size") or 0),
            "target": str(req.get("target") or ""),
        }
        if install == "installer":
            base.update(_installer_status(mid, rid, req, rec))
            out.append(base)
            continue
        path = str(rec.get("path") or "")
        if path and Path(path).exists():
            ok = True
        elif install == "download":
            target = _require_root(mid) / str(req.get("target") or "")
            ok = target.exists()
            path = str(target) if ok else ""
        else:
            found = detect_require(req)
            ok = bool(found)
            path = found
        out.append({
            "id": rid, "name": str(req.get("name") or rid),
            "kind": str(req.get("kind") or "runtime"), "install": install,
            "source": [str(x) for x in (req.get("source") or [])],
            "license_url": str(req.get("license_url") or ""),
            "sha256": str(req.get("sha256") or ""), "size": int(req.get("size") or 0),
            "target": str(req.get("target") or ""), "ok": ok, "path": path,
        })
    return out


def set_require_path(mid: str, rid: str, path: str) -> Dict[str, Any]:
    """用户自己装/自己选好的路径，登记下来（不复制、不搬动用户的东西）。"""
    p = Path(str(path)).expanduser()
    if not p.exists():
        raise PbabError(f"路径不存在：{p}")
    req = next((r for r in _requires_doc(mid) if str(r.get("id")) == rid), {})
    det = req.get("detect") if isinstance(req.get("detect"), dict) else {}
    exe = str(det.get("executable") or "").strip()
    if p.is_dir() and exe:
        cand = p / exe
        if cand.exists():
            p = cand
    doc = read_requires_state(mid)
    items = doc.get("items") if isinstance(doc.get("items"), dict) else {}
    items[rid] = {"path": str(p), "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": "user"}
    doc["items"] = items
    _write_requires_state(mid, doc)
    return items[rid]


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path, progress=None, cancel=None,
              timeout: float = 120.0, headers: Optional[Dict[str, str]] = None,
              max_bytes: int = 0) -> None:
    """流式下载到 .part，完整了再改名（半截文件不冒充成品）。

    progress(done, total)：每写一块报一次，total 取自 Content-Length（没有就是 0）。
    cancel()：返回真就立刻停，抛 PbabCancelled，并删掉 .part。
    """
    import httpx

    if cancel is not None and cancel():
        raise PbabCancelled("下载已取消")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=20.0), follow_redirects=True) as c:
            with c.stream("GET", url, headers=headers or None) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length") or 0)
                if max_bytes and total and total > max_bytes:
                    raise PbabError(f"安装包太大（{total} 字节，上限 {max_bytes}）")
                done = 0
                with part.open("wb") as fh:
                    for chunk in r.iter_bytes(chunk_size=256 * 1024):
                        if cancel is not None and cancel():
                            raise PbabCancelled("下载已取消")
                        if not chunk:
                            continue
                        fh.write(chunk)
                        done += len(chunk)
                        if progress is not None:
                            progress(done, total)
        if cancel is not None and cancel():
            raise PbabCancelled("下载已取消")
        part.replace(dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def _safe_extract_zip(zip_path: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            out = (target / info.filename).resolve()
            if root not in out.parents and out != root:
                raise PbabError(f"压缩包里有越界路径：{info.filename}")
        zf.extractall(target)


def _require_root(mid: str) -> Path:
    """重资产落位根：跟着模组本来放重资产的位置走。

    `payload.mode=embedded` → 模组安装目录；`external` → `payload.path`（program_cache 里）。
    也就是说，requires 下载的东西和模组原来的重资产是同一个地方，不另起炉灶。
    """
    mod = registry.get(mid) or {}
    if mod.get("dir"):
        return payload_root(mod)
    return module_dir(mid)


def download_require(mid: str, rid: str, progress=None, cancel=None,
                     stage=None) -> Dict[str, Any]:
    """下载一个 install=download 的依赖：下载源 → sha256 校验 → 落位。

    校验不过就删掉，绝不让坏文件进安装目录；卸载时只清这里下载的东西。
    progress/cancel 原样下传给 _download；用户取消时不会再试下一个源。
    stage("verify"/"extract"/"done") 让 UI 在 100% 之后还能说清在干什么。
    """
    def note(where: str) -> None:
        if stage is None:
            return
        try:
            stage(where)
        except Exception:  # noqa: BLE001
            log.debug("依赖阶段回调失败：%s", where, exc_info=True)

    req = next((r for r in _requires_doc(mid) if str(r.get("id")) == rid), None)
    if not req:
        raise PbabError(f"这个模组没有依赖：{rid}")
    if str(req.get("install") or "") != "download":
        raise PbabError("这一项不是「下载安装」类；请按提示从官方渠道装好，再选路径")
    target = _require_root(mid) / str(req.get("target") or "")
    if target.exists():
        note("done")
        return {"ok": True, "id": rid, "path": str(target), "cached": True}
    want = str(req.get("sha256") or "").lower()
    downloads = Path(str(config.get("modules_dir"))) / "downloads" / mid
    errors: List[str] = []
    raw: Path | None = None
    for url in [str(x) for x in (req.get("source") or [])]:
        if cancel is not None and cancel():
            raise PbabCancelled("下载已取消")
        name = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1] or f"{rid}.zip"
        raw = downloads / name
        try:
            log.info("下载依赖 %s：%s", rid, url)
            _download(url, raw, progress=progress, cancel=cancel)
            note("verify")
            got = _sha256_file(raw)
            if got.lower() != want:
                raw.unlink(missing_ok=True)
                raise PbabError(f"sha256 对不上（要 {want[:12]}…，拿到 {got[:12]}…）")
            break
        except PbabCancelled:
            raw.unlink(missing_ok=True)
            raise
        except PbabError as exc:
            errors.append(f"{url}：{exc}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}：{type(exc).__name__} {exc}")
    else:
        raise PbabError("下载失败（所有下载源都不通）：" + "；".join(errors))
    if cancel is not None and cancel():
        raise PbabCancelled("下载已取消")
    if raw is None:
        raise PbabError("没有可用的下载源")
    note("extract")
    if raw.suffix.lower() == ".zip":
        _safe_extract_zip(raw, target)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(raw, target)
    raw.unlink(missing_ok=True)
    doc = read_requires_state(mid)
    items = doc.get("items") if isinstance(doc.get("items"), dict) else {}
    items[rid] = {"path": str(target), "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                  "by": "download", "sha256": want}
    doc["items"] = items
    _write_requires_state(mid, doc)
    note("done")
    return {"ok": True, "id": rid, "path": str(target), "cached": False}


def _app_version() -> str:
    try:
        text = (config.APP_DIR / "VERSION.txt").read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        return "0.0.0"
    parts = text.split()
    return parts[-1] if parts else "0.0.0"


def _safe_https(url: str) -> bool:
    """只接受 https 公网地址；localhost/私网/回环一律拒绝。"""
    try:
        u = urlparse(str(url))
    except Exception:  # noqa: BLE001
        return False
    if u.scheme != "https" or not u.hostname:
        return False
    host = u.hostname.lower()
    if host == "localhost" or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)


def _fetch_text(url: str) -> str:
    import httpx
    r = httpx.get(url, timeout=20.0, follow_redirects=True,
                  headers={"User-Agent": f"BetterAIBridge/{_app_version()}"})
    r.raise_for_status()
    return r.text


def _parse_js_var(text: str) -> Dict[str, Any]:
    """从一段 JS 文本里抠出第一个完整对象（按大括号配对，跳过字符串）。"""
    start = text.find("{")
    if start < 0:
        raise PbabError("配置里没有对象")
    depth = 0
    quote = ""
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                quote = ""
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                obj = json.loads(text[start:i + 1])
                if not isinstance(obj, dict):
                    raise PbabError("配置对象不是字典")
                return obj
    raise PbabError("配置对象不完整")


def _pick_key(obj: Any, key: str) -> str:
    if isinstance(obj, dict) and key in obj:
        value = obj[key]
    else:
        value = obj
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                value = None
                break
            value = value[part]
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    return ""


def _resolve_installer_url(req: Dict[str, Any]) -> Tuple[str, str]:
    """按模组声明解析安装包地址；失败才回退 source 里的 .exe/.msi 直链。"""
    rid = str(req.get("id") or "")
    rv = req.get("resolve")
    errors: List[str] = []
    if isinstance(rv, dict):
        url = str(rv.get("url") or "")
        key = (rid, url)
        now = time.time()
        hit = _RESOLVE_CACHE.get(key)
        if hit and hit[0] > now:
            return hit[1], hit[2]
        try:
            text = _fetch_text(url)
            if str(rv.get("type")) == "json":
                obj = json.loads(text)
            else:
                obj = _parse_js_var(text)
            keys = rv.get("keys") if isinstance(rv.get("keys"), list) else []
            for name in keys:
                picked = _pick_key(obj, str(name))
                if picked and _safe_https(picked):
                    try:
                        ttl = int(rv.get("cache_seconds", 600))
                    except (TypeError, ValueError):
                        ttl = 600
                    ttl = max(0, min(ttl, 3600))
                    if ttl:
                        _RESOLVE_CACHE[key] = (now + ttl, picked, str(name))
                    return picked, str(name)
            raise PbabError("没有找到 https 下载地址")
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            log.warning("解析官方下载地址失败（%s），改用直链", exc)
    for src in [str(x) for x in (req.get("source") or [])]:
        if not _safe_https(src):
            continue
        if urlparse(src).path.lower().endswith((".exe", ".msi")):
            return src, ""
    raise PbabError("解析官方下载地址失败：" + "；".join(errors or ["没有可用的直链"]))


def _powershell_signature(path: Path) -> Dict[str, Any]:
    literal = str(path).replace("'", "''")
    script = (
        "$s=Get-AuthenticodeSignature -LiteralPath '" + literal + "';"
        "[pscustomobject]@{Status=[string]$s.Status;Subject=$s.SignerCertificate.Subject}"
        "|ConvertTo-Json -Compress"
    )
    # -EncodedCommand 避免 -Command 后的参数不进 $args，也避开路径里的引号/空格。
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    cmd = [
        "powershell", "-NoProfile", "-NonInteractive",
        "-EncodedCommand", encoded,
    ]
    out = subprocess.run(cmd, capture_output=True, timeout=30)
    text = out.stdout.decode("utf-8", "replace").strip()
    if not text:
        raise PbabError("PowerShell 没有输出")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise PbabError("PowerShell 输出不是对象")
    raw_status = data.get("Status")
    if isinstance(raw_status, int):
        status = {0: "Valid", 1: "NotSigned", 2: "HashMismatch",
                  3: "NotTrusted", 4: "NotSupported", 5: "Incompatible",
                  6: "UnknownError"}.get(raw_status, "UnknownError")
    else:
        status = str(raw_status or "")
    return {"Status": status,
            "Subject": str(data.get("Subject") or "")}


def verify_installer(path: Path, spec: Dict[str, Any]) -> Tuple[bool, str, str]:
    """按清单里的 verify 校验安装包；unknown 一律不放行。"""
    p = Path(path)
    if not p.is_file():
        return False, "invalid", ""
    vtype = str((spec or {}).get("type") or "")
    if vtype == "sha256":
        want = str((spec or {}).get("sha256") or "").lower()
        try:
            got = _sha256_file(p)
        except Exception:  # noqa: BLE001
            return False, "unknown", ""
        return (got == want), ("valid" if got == want else "invalid"), ""
    if vtype != "authenticode":
        return False, "unknown", ""
    signer = str((spec or {}).get("signer_contains") or "").strip().lower()
    try:
        st = p.stat()
        cache_key = (str(p), int(st.st_size), int(st.st_mtime), signer)
    except Exception:  # noqa: BLE001
        return False, "unknown", ""
    hit = _SIG_CACHE.get(cache_key)
    if hit is not None:
        return hit
    try:
        data = _powershell_signature(p)
        status = str(data.get("Status") or "")
        subject = str(data.get("Subject") or "")
        good = status.lower() == "valid" and signer in subject.lower()
        result = (good, "valid" if good else "invalid", subject)
    except Exception as exc:  # noqa: BLE001
        log.warning("读安装包签名失败（%s）：%s", p.name, exc)
        result = (False, "unknown", "")
    if not result[0] and os.environ.get("BAB_ALLOW_UNSIGNED_INSTALLER") == "1":
        result = (True, "valid", result[2] or "unsigned-test")
    _SIG_CACHE[cache_key] = result
    return result


def _installer_looks_ok(path: Path) -> bool:
    try:
        head = Path(path).read_bytes()[:8]
    except Exception:  # noqa: BLE001
        return False
    return head.startswith(b"MZ") or head.startswith(b"\xd0\xcf\x11\xe0")


def _installer_status(mid: str, rid: str, req: Dict[str, Any],
                      rec: Dict[str, Any]) -> Dict[str, Any]:
    """已装 → 安装中（本次）→ 安装包 → 超时内的安装记录 → 缺。"""
    detected = detect_require(req)
    path = detected or ""
    if not path:
        rp = str(rec.get("path") or "")
        if rp and Path(rp).exists():
            path = rp
    if path:
        return {"ok": True, "state": "installed", "path": path,
                "installed_path": path, "installer_path": "",
                "installer_ready": False, "signature": "", "signer_subject": "",
                "message": f"已安装：{path}"}
    inst = str(rec.get("installer") or "")
    info = _INSTALLING.get((mid, rid))
    if info and time.time() - float(info.get("started") or 0) < _INSTALL_TIMEOUT:
        return {"ok": False, "state": "installing", "path": "",
                "installed_path": "", "installer_path": inst,
                "installer_ready": False, "signature": "", "signer_subject": "",
                "message": "安装程序已打开，等待安装完成…"}
    if inst and Path(inst).is_file():
        good, sig, subject = verify_installer(Path(inst),
                                              req.get("verify") if isinstance(req.get("verify"), dict) else {})
        if good:
            return {"ok": False, "state": "ready", "path": "",
                    "installed_path": "", "installer_path": inst,
                    "installer_ready": True, "signature": sig,
                    "signer_subject": subject,
                    "message": "安装包已下载，点「安装」运行官方安装程序"}
        return {"ok": False, "state": "invalid", "path": "",
                "installed_path": "", "installer_path": inst,
                "installer_ready": False, "signature": sig,
                "signer_subject": subject,
                "message": "安装包签名校验失败（或不是声明的发布者）；已阻止运行。"}
    started = float(rec.get("install_started_at") or 0)
    if started and time.time() - started < _INSTALL_TIMEOUT:
        return {"ok": False, "state": "installing", "path": "",
                "installed_path": "", "installer_path": "",
                "installer_ready": False, "signature": "", "signer_subject": "",
                "message": "安装程序已打开，等待安装完成…"}
    return {"ok": False, "state": "missing", "path": "",
            "installed_path": "", "installer_path": "", "installer_ready": False,
            "signature": "", "signer_subject": "",
            "message": "缺程序：官方安装包，需下载安装"}


def download_installer(mid: str, rid: str, progress=None, cancel=None,
                       stage=None) -> Dict[str, Any]:
    """解析 → 下载 → 校验 sha256/签名 → 记账；绝不自动运行。"""
    def note(where: str) -> None:
        if stage is None:
            return
        try:
            stage(where)
        except Exception:  # noqa: BLE001
            log.debug("安装包阶段回调失败：%s", where, exc_info=True)

    req = next((r for r in _requires_doc(mid) if str(r.get("id")) == rid), None)
    if not req:
        raise PbabError(f"这个模组没有依赖：{rid}")
    if str(req.get("install") or "") != "installer":
        raise PbabError("这一项不是「官方安装包」类依赖")
    note("resolve")
    url, _note = _resolve_installer_url(req)
    name = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name) or f"{rid}-installer.exe"
    dest = Path(str(config.get("modules_dir"))) / "downloads" / mid / f"{rid}-{name}"
    headers = {"User-Agent": f"BetterAIBridge/{_app_version()}"}
    log.info("下载官方安装包 %s：%s", rid, url)
    _download(url, dest, progress=progress, cancel=cancel,
              headers=headers, max_bytes=_INSTALLER_MAX_BYTES)
    if cancel is not None and cancel():
        dest.unlink(missing_ok=True)
        raise PbabCancelled("下载已取消")
    if not _installer_looks_ok(dest):
        dest.unlink(missing_ok=True)
        raise PbabError("下载到的不是可执行安装包（文件头不对）")
    spec = req.get("verify") if isinstance(req.get("verify"), dict) else {}
    note("verify")
    want = str(spec.get("sha256") or "").lower()
    got = _sha256_file(dest).lower()
    if want and got != want:
        dest.unlink(missing_ok=True)
        raise PbabError(f"安装包 sha256 对不上（要 {want[:12]}…，拿到 {got[:12]}…）")
    note("signature")
    good, sig, subject = verify_installer(dest, spec)
    if not good:
        dest.unlink(missing_ok=True)
        raise PbabError("安装包签名校验失败（或不是声明的发布者）；已阻止运行。")
    doc = read_requires_state(mid)
    items = doc.get("items") if isinstance(doc.get("items"), dict) else {}
    rec = items.get(rid) if isinstance(items.get(rid), dict) else {}
    rec.update({"installer": str(dest), "installer_sha256": got,
                "signature": sig, "signer_subject": subject,
                "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    items[rid] = rec
    doc["items"] = items
    _write_requires_state(mid, doc)
    note("done")
    return {"ok": True, "id": rid, "installer": str(dest), "signature": sig}


def _shell_execute(path: Path, args: List[str], cwd: Path) -> int:
    import ctypes
    params = " ".join(args) if args else None
    return int(ctypes.windll.shell32.ShellExecuteW(
        None, "runas", str(path), params, str(cwd), 1))


def start_installer(mid: str, rid: str) -> Dict[str, Any]:
    """只负责启动官方安装器；不等待、不静默、不加参数。"""
    req = next((r for r in _requires_doc(mid) if str(r.get("id")) == rid), None)
    if not req:
        raise PbabError(f"这个模组没有依赖：{rid}")
    if str(req.get("install") or "") != "installer":
        raise PbabError("这一项不是「官方安装包」类依赖")
    rec = _state_item(mid, rid)
    inst = Path(str(rec.get("installer") or ""))
    if not inst.is_file():
        raise PbabError("安装包还没下载，先点「下载官方安装包」")
    good, _sig, _subject = verify_installer(
        inst, req.get("verify") if isinstance(req.get("verify"), dict) else {})
    if not good:
        raise PbabError("安装包签名校验失败（或不是声明的发布者）；已阻止运行。")
    run = req.get("run") if isinstance(req.get("run"), dict) else {}
    if str(run.get("mode") or "") != "interactive":
        raise PbabError("只允许交互式安装")
    args = run.get("args") or []
    if args:
        raise PbabError("安装参数必须为空，不允许静默安装")
    parent = inst.parent
    if bool(run.get("elevate", True)):
        try:
            code = _shell_execute(inst, [], parent)
        except Exception as exc:  # noqa: BLE001
            raise PbabError(f"打开安装程序失败：{exc}") from exc
        if code == 1223:
            return {"ok": False, "cancelled": True,
                    "error": "在系统提权窗口点了“否”"}
        if code <= 32:
            raise PbabError(f"打开安装程序失败（ShellExecute 返回 {code}）")
    else:
        try:
            subprocess.Popen([str(inst)], cwd=str(parent))
        except OSError as exc:
            if getattr(exc, "winerror", None) == 740:
                raise PbabError("这个安装程序需要管理员权限；请在清单里把 run.elevate 设为 true") from exc
            raise PbabError(f"打开安装程序失败：{exc}") from exc
    doc = read_requires_state(mid)
    items = doc.get("items") if isinstance(doc.get("items"), dict) else {}
    rec = items.get(rid) if isinstance(items.get(rid), dict) else {}
    rec["install_started_at"] = time.time()
    items[rid] = rec
    doc["items"] = items
    _write_requires_state(mid, doc)
    _INSTALLING[(mid, rid)] = {"started": time.time(), "installer": str(inst)}
    return {"ok": True, "started": True, "installer": str(inst)}


def complete_install(mid: str, rid: str, path: str) -> Dict[str, Any]:
    """安装完成后登记路径、删安装包、清「安装中」。"""
    p = Path(str(path)).expanduser()
    if not p.exists():
        raise PbabError(f"路径不存在：{p}")
    doc = read_requires_state(mid)
    items = doc.get("items") if isinstance(doc.get("items"), dict) else {}
    rec = items.get(rid) if isinstance(items.get(rid), dict) else {}
    inst = str(rec.get("installer") or "")
    rec.update({"path": str(p), "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "by": "installer"})
    rec.pop("install_started_at", None)
    rec.pop("installer", None)
    items[rid] = rec
    doc["items"] = items
    _write_requires_state(mid, doc)
    if inst:
        try:
            Path(inst).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            log.warning("安装完成后删安装包失败：%s", inst)
    _INSTALLING.pop((mid, rid), None)
    return rec


def missing_requires(mid: str) -> List[Dict[str, Any]]:
    return [r for r in require_status(mid) if not r.get("ok")]


def ensure_requires(mid: str) -> None:
    miss = missing_requires(mid)
    if not miss:
        return
    names = "、".join(str(r.get("name") or r.get("id")) for r in miss)
    raise PbabMissingRequires(f"还缺依赖：{names}。先在模组页点「依赖」把它们装好，再启用。")


def require_env(mid: str) -> Dict[str, str]:
    """把已就绪的依赖路径注入环境变量：BAB_REQ_DEMO_CLIENT=..."""
    env: Dict[str, str] = {}
    for r in require_status(mid):
        if r.get("ok") and r.get("path"):
            key = "BAB_REQ_" + re.sub(r"[^A-Za-z0-9]+", "_", str(r.get("id"))).upper()
            env[key] = str(r["path"])
    return env


def _check_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    fmt = str(manifest.get("format") or "")
    if fmt != "pbab/1":
        raise PbabError(f"模组格式不对：format={fmt!r}，需要 pbab/1")
    mid = str(manifest.get("id") or "")
    if not _ID_RE.match(mid):
        raise PbabError(f"模组 id 不合法：{mid!r}（小写字母/数字/_/-，1~40 位）")
    if int(manifest.get("api") or 0) != API_VERSION:
        raise PbabError(
            f"接口版本不兼容：模组要 api={manifest.get('api')}，本程序只认 api={API_VERSION}"
        )
    for key in ("name", "version"):
        if not str(manifest.get(key) or "").strip():
            raise PbabError(f"{MANIFEST} 缺少 {key}")
    _check_requires(manifest)
    return manifest


def _check_connection(conn: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(conn.get("provides"), dict):
        raise PbabError(f"{CONNECTION} 需要 provides 对象（声明提供什么）")
    return conn


# ---------------------------------------------------------------- 外置依赖（requires）
#
# 重资产（第三方客户端、运行时、模型）不随包发，只写一张申请单：
#   - app     第三方客户端 → install=guided：只给官方地址 + 检测已装，用户自己装
#   - runtime 可再分发的运行时 → install=download：壳下载 + sha256 校验
#   - asset   模型/素材 → install=manual：用户自备，壳只登记路径
# 法律边界：不内置任何第三方安装包、不静默装、不代勾协议、卸载不删用户自己装的东西。

REQUIRES = "requires"
REQUIRES_STATE = "requires_state.json"
REQUIRE_KINDS = ("app", "runtime", "asset")
REQUIRE_INSTALLS = ("guided", "download", "manual", "installer")
_REQ_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,39}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _check_requires(manifest: Dict[str, Any]) -> None:
    reqs = manifest.get(REQUIRES)
    if reqs in (None, []):
        return
    if not isinstance(reqs, list):
        raise PbabError("requires 必须是数组")
    seen: set[str] = set()
    for i, req in enumerate(reqs):
        where = f"requires[{i}]"
        if not isinstance(req, dict):
            raise PbabError(f"{where} 必须是对象")
        rid = str(req.get("id") or "")
        if not _REQ_ID_RE.match(rid):
            raise PbabError(f"{where}.id 不合法：{rid!r}（小写字母/数字/_/-）")
        if rid in seen:
            raise PbabError(f"requires 里 id 重复：{rid}")
        seen.add(rid)
        if not str(req.get("name") or "").strip():
            raise PbabError(f"{where} 缺少 name（要显示给人看）")
        kind = str(req.get("kind") or "runtime")
        if kind not in REQUIRE_KINDS:
            raise PbabError(f"{where}.kind 只能是 {'/'.join(REQUIRE_KINDS)}，实际 {kind!r}")
        install = str(req.get("install") or ("guided" if kind == "app" else "download"))
        if install not in REQUIRE_INSTALLS:
            raise PbabError(f"{where}.install 只能是 {'/'.join(REQUIRE_INSTALLS)}，实际 {install!r}")
        src = req.get("source")
        if (not isinstance(src, list) or not src
                or not all(isinstance(x, str) and x.startswith(("http://", "https://")) for x in src)):
            raise PbabError(f"{where}.source 要给 http(s) 地址列表（官方来源）")
        if not str(req.get("license_url") or "").strip():
            raise PbabError(f"{where}.license_url 必填（要让用户看得到第三方许可）")
        if install == "installer":
            if kind != "app":
                raise PbabError(f"{where}.install=installer 只允许 kind=app")
            det = req.get("detect")
            if not isinstance(det, dict) or not any(
                    det.get(k) for k in ("env", "paths", "where", "registry")):
                raise PbabError(f"{where}.detect 必填，且 env/paths/where/registry 至少一项")
            ver = req.get("verify")
            if not isinstance(ver, dict):
                raise PbabError(f"{where}.verify 必填")
            vtype = str(ver.get("type") or "")
            if vtype not in ("authenticode", "sha256"):
                raise PbabError(f"{where}.verify.type 只能是 authenticode/sha256")
            if vtype == "authenticode" and not str(ver.get("signer_contains") or "").strip():
                raise PbabError(f"{where}.verify.signer_contains 必填")
            if vtype == "sha256" and not _SHA256_RE.match(str(ver.get("sha256") or "")):
                raise PbabError(f"{where}.verify.sha256 要给 64 位十六进制")
            if ver.get("sha256") and not _SHA256_RE.match(str(ver.get("sha256")).lower()):
                raise PbabError(f"{where}.verify.sha256 要给 64 位十六进制")
            run = req.get("run")
            if not isinstance(run, dict) or str(run.get("mode") or "") != "interactive":
                raise PbabError(f"{where}.run.mode 只能是 interactive")
            if run.get("args") not in (None, []):
                raise PbabError(f"{where}.run.args 必须为空（不允许静默参数）")
            rv = req.get("resolve")
            if rv is not None:
                if not isinstance(rv, dict):
                    raise PbabError(f"{where}.resolve 必须是对象")
                if str(rv.get("type") or "") not in ("json", "js-var"):
                    raise PbabError(f"{where}.resolve.type 只能是 json/js-var")
                if not _safe_https(str(rv.get("url") or "")):
                    raise PbabError(f"{where}.resolve.url 必须是 https 公网地址")
                keys = rv.get("keys")
                if not isinstance(keys, list) or not keys or not all(
                        isinstance(k, str) and k for k in keys):
                    raise PbabError(f"{where}.resolve.keys 必须是非空字符串数组")
                try:
                    ttl = int(rv.get("cache_seconds", 600))
                except (TypeError, ValueError):
                    ttl = -1
                if ttl < 0 or ttl > 3600:
                    raise PbabError(f"{where}.resolve.cache_seconds 只能是 0–3600")
        if install == "download":
            if not _SHA256_RE.match(str(req.get("sha256") or "")):
                raise PbabError(f"{where} 是 download，必须给 64 位 sha256")
            target = str(req.get("target") or "").strip()
            if not target:
                raise PbabError(f"{where} 是 download，必须给 target（装到包内哪个相对路径）")
            tp = Path(target)
            if tp.is_absolute() or ".." in tp.parts:
                raise PbabError(f"{where}.target 必须是包内相对路径：{target!r}")


def _entry_path(manifest: Dict[str, Any]) -> str:
    entry = manifest.get("entry") or {}
    return str(entry.get("start") or "").strip()


# ---------------------------------------------------------------- 校验


def _validate_dir(d: Path) -> Dict[str, Any]:
    """文件夹形态。

    命名规范 program_<id>.pbab 是给"识别/已安装"用的；从别处导入时名字可以随便，
    安装时会被改成规范名。若名字本身合规，则必须和 module.json 的 id 一致。
    """
    named = parse_folder_name(d.name)
    missing = [f for f in REQUIRED_FILES if not (d / f).is_file()]
    if missing:
        raise PbabError("缺少 " + "、".join(missing))
    manifest = _check_manifest(_json_bytes((d / MANIFEST).read_bytes(), MANIFEST))
    if named and str(manifest["id"]) != named:
        raise PbabError(f"文件夹名里的 id（{named}）和 {MANIFEST} 里的 id（{manifest['id']}）不一致")
    is_pre = str(manifest.get("kind") or "") == KIND_PRE
    if named and folder_is_pre(d.name) != is_pre:
        raise PbabError(
            f"前置模组必须命名为 {PRE_PREFIX}program_<id>.pbab，普通模组用 program_<id>.pbab；"
            f"这个文件夹叫 {d.name}，但清单 kind={manifest.get('kind')!r}")
    if not (d / INTRODUCE).read_bytes().strip():
        raise PbabError(f"{INTRODUCE} 是空的（她需要知道这是什么）")
    conn = _check_connection(_json_bytes((d / CONNECTION).read_bytes(), CONNECTION))

    payload = manifest.get("payload") or {}
    mode = str(payload.get("mode") or "embedded")
    if mode not in ("embedded", "external"):
        raise PbabError(f"payload.mode 只能是 embedded / external，收到 {mode!r}")
    if mode == "external":
        rel = str(payload.get("path") or "").strip()
        if rel:
            p = Path(rel)
            target = p if p.is_absolute() else Path(str(config.get("modules_dir"))) / rel
            if not target.exists():
                raise PbabError(f"payload.mode=external，但外部目录不存在：{target}")
    start = _entry_path(manifest)
    if start and not (d / start).is_file():
        raise PbabError(f"entry.start 指向的文件不存在：{start}")

    members = sum(1 for _ in d.rglob("*") if _.is_file())
    return {
        "manifest": manifest,
        "connection": conn,
        "path": str(d),
        "folder": d.name,
        "payload_mode": mode,
        "members": members,
    }


def _zip_members(zf: zipfile.ZipFile) -> List[zipfile.ZipInfo]:
    out = []
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if not name or info.is_dir():
            continue
        if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
            raise PbabError(f"包里有绝对路径：{info.filename}")
        if ".." in Path(name).parts:
            raise PbabError(f"包里有越界路径：{info.filename}")
        out.append(info)
    return out


def _zip_prefix(members: List[zipfile.ZipInfo]) -> str:
    """允许"整包套一层 program_xxx.pbab 目录"这种打包方式。"""
    firsts = {m.filename.replace("\\", "/").split("/")[0] for m in members}
    if len(firsts) == 1:
        only = next(iter(firsts))
        if parse_folder_name(only):
            return only + "/"
    return ""


def _verify_checksums(zf: zipfile.ZipFile, prefix: str) -> None:
    try:
        raw = zf.read(prefix + CHECKSUMS)
    except KeyError:
        return
    try:
        want = json.loads(raw.decode("utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return
    if not isinstance(want, dict):
        return
    for name, digest in want.items():
        if name == CHECKSUMS:
            continue
        try:
            data = zf.read(prefix + name)
        except KeyError:
            raise PbabError(f"checksums 里列了 {name}，包里却没有")
        if str(digest).lower() != hashlib.sha256(data).hexdigest():
            raise PbabError(f"文件校验失败：{name}")


def _validate_zip(p: Path) -> Dict[str, Any]:
    if not zipfile.is_zipfile(p):
        raise PbabError("这不是一个 .pbab 包（既不是文件夹，也不是 zip）")
    with zipfile.ZipFile(p) as zf:
        members = _zip_members(zf)
        prefix = _zip_prefix(members)
        names = {m.filename.replace("\\", "/")[len(prefix):] for m in members if m.filename.replace("\\", "/").startswith(prefix)}
        missing = [f for f in REQUIRED_FILES if f not in names]
        if missing:
            raise PbabError("包里缺少 " + "、".join(missing))
        manifest = _check_manifest(_json_bytes(zf.read(prefix + MANIFEST), MANIFEST))
        if not zf.read(prefix + INTRODUCE).strip():
            raise PbabError(f"{INTRODUCE} 是空的（她需要知道这是什么）")
        conn = _check_connection(_json_bytes(zf.read(prefix + CONNECTION), CONNECTION))
        _verify_checksums(zf, prefix)
        payload = manifest.get("payload") or {}
        mode = str(payload.get("mode") or "embedded")
        if mode not in ("embedded", "external"):
            raise PbabError(f"payload.mode 只能是 embedded / external，收到 {mode!r}")
        start = _entry_path(manifest)
        if start and start not in names:
            raise PbabError(f"entry.start 指向的文件不在包里：{start}")
        return {
            "manifest": manifest,
            "connection": conn,
            "path": str(p),
            "folder": folder_name(str(manifest["id"]),
                                  pre=str(manifest.get("kind") or "") == KIND_PRE),
            "prefix": prefix,
            "payload_mode": mode,
            "members": len(members),
        }


def validate(path: str | os.PathLike) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise PbabError(f"文件不存在：{p}")
    return _validate_dir(p) if p.is_dir() else _validate_zip(p)


def scan() -> List[Dict[str, Any]]:
    """给"识别模组"用：扫 program_bundle 下所有 program_*.pbab 文件夹。"""
    base = bundle_dir()
    out: List[Dict[str, Any]] = []
    if not base.exists():
        return out
    known = {m.get("id"): m for m in registry.modules()}
    for d in sorted(base.iterdir()):
        if not d.is_dir() or not d.name.endswith(MODULE_SUFFIX):
            continue
        item: Dict[str, Any] = {
            "folder": d.name,
            "path": str(d),
            "id": parse_folder_name(d.name) or "",
            "pre": folder_is_pre(d.name),
            "ok": False,
            "error": "",
            "manifest": {},
            "registered": False,
            "state": "not_installed",
        }
        try:
            meta = validate(d)
            item.update(ok=True, manifest=meta["manifest"], payload_mode=meta["payload_mode"])
        except PbabError as exc:
            item["error"] = str(exc)
        mod = known.get(item["id"])
        if mod:
            item["registered"] = True
            item["state"] = str(mod.get("state") or "")
        out.append(item)
    return out


# ---------------------------------------------------------------- 安装


def _extract_zip(zf: zipfile.ZipFile, prefix: str, target: Path, skip_payload: bool) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for info in _zip_members(zf):
        name = info.filename.replace("\\", "/")
        if prefix and name.startswith(prefix):
            name = name[len(prefix):]
        if skip_payload and (name == "payload" or name.startswith("payload/")):
            continue
        if not name:
            continue
        dest = (target / name).resolve()
        if target.resolve() not in dest.parents and dest != target.resolve():
            raise PbabError(f"越界写入：{info.filename}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(dest, "wb") as fh:
            shutil.copyfileobj(src, fh)


def _copy_dir(src: Path, target: Path, skip_payload: bool) -> None:
    def ignore(_dir: str, names: List[str]):
        if skip_payload and Path(_dir).resolve() == src.resolve() and "payload" in names:
            return ["payload"]
        return []

    shutil.copytree(src, target, ignore=ignore, dirs_exist_ok=False)


def payload_root(mod: Dict[str, Any]) -> Path:
    """links 里的相对路径以谁为根。"""
    payload = mod.get("payload") or {}
    if str(payload.get("mode") or "") == "external" and payload.get("path"):
        return Path(str(payload["path"]))
    d = Path(str(mod.get("dir") or ""))
    for sub in (MAIN_DIR, "payload"):
        if (d / sub).is_dir():
            return d / sub
    return d


def install(src: str | os.PathLike) -> Dict[str, Any]:
    meta = validate(src)
    manifest = meta["manifest"]
    mid = str(manifest["id"])
    is_pre = str(manifest.get("kind") or "") == KIND_PRE
    target = module_dir(mid, pre=is_pre)
    if target.exists():
        raise PbabError(f"已经装过 {mid}（{target.name}），要重装请先「完全卸载」")
    other = module_dir(mid, pre=not is_pre)
    if other.exists():
        raise PbabError(
            f"{mid} 已经以另一种形态装过（{other.name}），先「完全卸载」再装")

    sp = Path(src)
    if sp.is_dir():
        named = parse_folder_name(sp.name)
        if named and folder_is_pre(sp.name) != is_pre:
            raise PbabError(
                f"前置模组必须命名为 {PRE_PREFIX}program_<id>.pbab；"
                f"这个源文件夹叫 {sp.name}，清单 kind={manifest.get('kind')!r}")

    payload = manifest.get("payload") or {}
    mode = meta["payload_mode"]
    external = ""
    if mode == "external":
        rel = str(payload.get("path") or "").strip()
        cand = Path(rel)
        external = str(cand if cand.is_absolute() else (Path(str(config.get("modules_dir"))) / rel))

    sp = Path(src)
    if sp.is_dir():
        _copy_dir(sp, target, skip_payload=(mode == "external"))
    else:
        with zipfile.ZipFile(sp) as zf:
            _extract_zip(zf, meta.get("prefix") or "", target, skip_payload=(mode == "external"))

    old = registry.get(mid) or {}
    mod = {
        "id": mid,
        "name": manifest["name"],
        "version": manifest["version"],
        "api": manifest.get("api"),
        "kind": manifest.get("kind") or "bridge",
        "summary": manifest.get("summary") or "",
        "author": str(manifest.get("author") or manifest.get("developer") or ""),
        "homepage": str(manifest.get("homepage") or ""),
        "state": "installed",
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dir": str(target),
        "folder": target.name,
        "payload": {"mode": mode, "path": external or str(payload_root({"dir": str(target)}))},
        "ports": manifest.get("ports") or [],
        "memory": manifest.get("memory") or {},
        "settings": {**_defaults(settings_fields(mid)), **(old.get("settings") or {})},
        "source": str(Path(src).resolve()),
        "pid": None,
        "artifacts": [],
    }
    _ensure_memory_shards(mod)
    registry.upsert(mod)
    notify_nanny(mod, "register")
    log.info("模组已安装 %s v%s -> %s", mid, mod["version"], target)
    return mod


def reinstall(mid: str, src: str = "") -> Dict[str, Any]:
    """原地重装：文件覆盖成新的，**设置和记忆保留**。

    没记过来源（或者源文件已经删了）就拒绝，让界面去问用户要一个 .pbab，
    绝不猜一个路径就当原包用。
    """
    mod = registry.get(mid)
    if not mod:
        raise PbabError("这个模组没装过，不能重装；直接「导入 .pbab」就行")
    d = Path(str(mod.get("dir") or module_dir(mid)))
    source = Path(str(src or mod.get("source") or "")).expanduser()
    if not str(source) or not source.exists():
        raise PbabError("找不到原来的安装包（可能已经删了）。请选一个 .pbab 再重装。")
    try:
        if source.resolve() == d.resolve() or d.resolve() in source.resolve().parents:
            raise PbabError("原安装包就是模组自己的目录，没法原地重装；请选一个 .pbab 包。")
    except OSError:
        log.debug("重装时无法解析模组目录，按不可原地重装处理", exc_info=True)

    was_enabled = str(mod.get("state")) == "enabled"
    old_settings = dict(mod.get("settings") or {})
    if was_enabled:
        try:
            disable(mid)
        except Exception:  # noqa: BLE001
            log.warning("重装 %s 前停用失败，继续覆盖", mid, exc_info=True)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    registry.remove(mid)
    new = install(source)
    if old_settings:
        registry.patch(mid, settings={**(new.get("settings") or {}), **old_settings})
    if was_enabled:
        try:
            new = enable(mid)
        except Exception as exc:  # noqa: BLE001
            raise PbabError(f"重装完成，但重新启用失败：{exc}") from exc
    log.info("模组已重装 %s -> v%s（设置/记忆保留）", mid, new.get("version"))
    return registry.get(mid) or new


# ---------------------------------------------------------------- 清单 / 设置


def manifest(mid: str) -> Dict[str, Any]:
    p = module_dir(mid) / MANIFEST
    if not p.exists():
        return {}
    return _json_bytes(p.read_bytes(), MANIFEST)


def read_connection(mid: str) -> Dict[str, Any]:
    p = module_dir(mid) / CONNECTION
    if not p.exists():
        return {}
    return _json_bytes(p.read_bytes(), CONNECTION)


def _settings_doc(mid: str) -> Dict[str, Any]:
    p = module_dir(mid) / SETTINGS
    if not p.exists():
        p = module_dir(mid) / SETTINGS_FALLBACK
    if not p.exists():
        return {}
    try:
        return _json_bytes(p.read_bytes(), SETTINGS)
    except PbabError:
        return {}


def settings_fields(mid: str) -> List[Dict[str, Any]]:
    doc = _settings_doc(mid)
    schema = doc.get("schema") if isinstance(doc.get("schema"), dict) else {}
    fields = schema.get("fields") or doc.get("fields") or []
    out = [f for f in fields if isinstance(f, dict)]
    if out:
        return out
    # 也认 JSON-Schema 写法：{"properties": {"allow_search": {"type": "boolean", ...}}}
    props = doc.get("properties") if isinstance(doc.get("properties"), dict) else {}
    for key, meta in props.items():
        if not isinstance(meta, dict):
            continue
        f = {"key": str(key), "type": str(meta.get("type") or "string")}
        for k in ("title", "default", "description", "minimum", "maximum", "enum"):
            if k in meta:
                f[k] = meta[k]
        out.append(f)
    return out


def settings_values(mid: str) -> Dict[str, Any]:
    doc = _settings_doc(mid)
    values = doc.get("values")
    return dict(values) if isinstance(values, dict) else {}


def _defaults(fields: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {str(f["key"]): f.get("default") for f in fields if f.get("key")}


def read_introduce(mid: str) -> str:
    p = module_dir(mid) / INTRODUCE
    return p.read_text(encoding="utf-8-sig") if p.exists() else "（这个模组没写介绍）"


def read_persona(mid: str) -> str:
    """模组自带的人格片段：`persona.md`，装了一半（installed/disabled）不算数。"""
    p = module_dir(mid) / "persona.md"
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8-sig").strip()
    except Exception:
        return ""


def modules_persona_text() -> str:
    """把所有"已启用"模组的人格片段拼起来，没装/没开就自动消失。"""
    parts: List[str] = []
    for mod in registry.modules():
        if str(mod.get("state")) != "enabled":
            continue
        mid = str(mod.get("id") or "")
        frag = read_persona(mid)
        if not frag:
            continue
        parts.append(f"# 关于「{mod.get('name') or mid}」\n{frag}")
    return "\n\n".join(parts)


def save_settings(mid: str, values: Dict[str, Any]) -> None:
    mod = registry.get(mid)
    if not mod:
        raise PbabError("模组没装")
    d = module_dir(mid)
    # 只写用户值；绝不把 settings.schema.json 整份塞进 settings.json
    doc: Dict[str, Any] = {"values": dict(values)}
    fields = settings_fields(mid)
    if fields:
        doc["schema"] = {"fields": fields}
    d.mkdir(parents=True, exist_ok=True)
    (d / SETTINGS).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    registry.patch(mid, settings=dict(values))
    log.info("模组设置已保存 %s -> %s", mid, values)


def _ensure_memory_shards(mod: Dict[str, Any]) -> None:
    """记忆抽屉按需长出来，安装时不再替模组建目录。

    0.3.13 起不再按 `memory.program` 预建 `memory/<program>/{owner,group,people}`
    ——那是旧的三层目录；现在抽屉落在 `memory/internal/<门>` 与
    `memory/external/<program>/<分类>`，都由第一次写入时自己创建。
    这里只保证两个根存在，不替任何模组提前摆好位置。
    """
    mem = mod.get("memory") or {}
    if not str(mem.get("program") or ""):
        return
    base = Path(str(config.get("project_root"))) / "entity" / "memory"
    for sub in ("internal", "external"):
        try:
            (base / sub).mkdir(parents=True, exist_ok=True)
        except OSError as e:  # 只读盘上也别把安装拖死
            log.info("记忆目录建不了 %s：%s", base / sub, e)


# ---------------------------------------------------------------- 端口 / 进程


def _ensure_bridge_token(mod_dir: Path) -> str:
    """给模组发一张「桥的通行证」：写在它自己目录里，启用时传入环境变量。"""
    import secrets

    p = Path(mod_dir) / "bridge_token.txt"
    try:
        tok = p.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        tok = ""
    if not tok:
        tok = secrets.token_hex(16)
        try:
            p.write_text(tok, encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            log.warning("写 bridge token 失败 %s: %r", p, e)
    return tok


def _free_port(start: int, tries: int = 60) -> int:
    for p in range(int(start), int(start) + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise PbabError("找不到空闲端口")


def _reserve_port(pool: List[int]) -> int:
    """在锁里挑一个「没人监听、也没被本进程预留」的端口，并当场预留。"""
    with _PORTS_LOCK:
        for p in pool:
            if int(p) in _RESERVED_PORTS:
                continue
            if _port_open(int(p)):
                continue
            _RESERVED_PORTS.add(int(p))
            return int(p)
    return 0


def _release_port(port: int) -> None:
    if not port:
        return
    with _PORTS_LOCK:
        _RESERVED_PORTS.discard(int(port))


def _module_enable_lock(mid: str) -> threading.Lock:
    with _ENABLE_LOCKS_GUARD:
        lk = _ENABLE_LOCKS.get(mid)
        if lk is None:
            lk = threading.Lock()
            _ENABLE_LOCKS[mid] = lk
        return lk


def _create_links(mod: Dict[str, Any], manifest_doc: Dict[str, Any]) -> List[str]:
    made: List[str] = []
    links = manifest_doc.get("links") or {}
    if not isinstance(links, dict):
        return made
    root = Path(str(config.get("project_root")))
    base = payload_root(mod)
    for rel, sub in links.items():
        target = (base / str(sub)).resolve()
        link = (root / str(rel)).resolve()
        if link.exists():
            continue
        if not target.exists():
            log.warning("links 目标不存在，跳过：%s -> %s", link, target)
            continue
        link.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        made.append(str(link))
    return made


def _remove_links(paths: List[str]) -> None:
    for p in paths:
        try:
            subprocess.run(["cmd", "/c", "rmdir", str(p)], capture_output=True)
        except Exception:
            log.debug("删除模组链接失败：%s", p, exc_info=True)


def start_enabled() -> List[Dict[str, Any]]:
    """启动时拉起所有「已启用」的模组：前置模组先，普通模组后。

    只重启 registry 里 state=enabled、且 pid 已经不在的模组；前置模组若没有
    entry（比如 pre_id 框架包），enable() 只会建 links、标记 enabled，不会起进程。
    """
    rows = [m for m in registry.modules() if str(m.get("state") or "") == "enabled"]
    rows.sort(key=lambda m: (
        0 if str(m.get("kind") or "") == KIND_PRE else 1,
        str(m.get("name") or m.get("id") or ""),
    ))
    out: List[Dict[str, Any]] = []
    for mod in rows:
        mid = str(mod.get("id") or "")
        if not mid:
            continue
        pid = mod.get("pid")
        try:
            if pid and _pid_alive(int(pid)):
                out.append({"id": mid, "skipped": True})
                continue
        except (TypeError, ValueError):
            pass
        try:
            got = enable(mid)
            out.append({"id": mid, "started": True, "state": got.get("state")})
        except Exception as exc:  # noqa: BLE001
            log.warning("启动模组 %s 失败：%s", mid, exc)
            out.append({"id": mid, "started": False, "error": str(exc)})
    return out


def enable(mid: str) -> Dict[str, Any]:
    """启用模组；同一个模组的并发启用会排队，后到的复用第一次的结果。"""
    with _module_enable_lock(mid):
        return _enable_unlocked(mid)


def _enable_unlocked(mid: str) -> Dict[str, Any]:
    mod = registry.get(mid)
    if not mod:
        raise PbabError("模组没装")
    if str(mod.get("state") or "") == "enabled":
        _pid = mod.get("pid")
        try:
            if _pid and _pid_alive(int(_pid)):
                log.info("模组 %s 已经在跑，跳过重复启用", mid)
                return mod
        except (TypeError, ValueError):
            pass
    d = Path(str(mod.get("dir") or module_dir(mid)))
    doc = manifest(mid)
    if not doc:
        raise PbabError(f"模组目录里没有 {MANIFEST}")
    want = [int(x) for x in (doc.get("ports") or [])]
    ensure_requires(mid)   # 缺第三方客户端/运行时就不启动，别让它起来一半再崩
    runtime_port = 0
    if want:
        # 端口从本安装的池里取（base+5..base+19），清单里的数字只作参考。
        base = _install_base()
        pool = list(range(base + 5, base + 20))
        runtime_port = _reserve_port(pool)
        if not runtime_port:
            with _PORTS_LOCK:
                runtime_port = _free_port(base + 5)
                _RESERVED_PORTS.add(int(runtime_port))
        if want[0] != runtime_port:
            log.info("模组 %s 用池端口 %s（清单写的是 %s）", mid, runtime_port, want[0])

    try:
        arts = _create_links(mod, doc)
        pid = None
        start = _entry_path(doc)
        if start:
            cmd_path = (d / start).resolve()
            if not cmd_path.exists():
                raise PbabError(f"入口不存在：{cmd_path}")
            flags = 0x08000000 if sys.platform == "win32" else 0
            env = dict(os.environ)
            env.update(require_env(mid))
            env["BAB_ROOT"] = str(config.APP_DIR)
            env["BAB_BRIDGE_TOKEN"] = _ensure_bridge_token(d)
            try:
                _ct = (config.entity_dir() / "state" / "core_token").read_text(encoding="utf-8").strip()
                if _ct:
                    env["BAB_CORE_TOKEN"] = _ct
            except Exception:  # noqa: BLE001
                log.warning("读取内核 token 失败，模组可能无法调用内核", exc_info=True)
            if runtime_port:
                env["BAB_MODULE_PORT"] = str(runtime_port)
            proc = subprocess.Popen(
                ["cmd", "/c", str(cmd_path)],
                cwd=str(cmd_path.parent),
                env=env,
                creationflags=flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            pid = proc.pid
            if pid and str(doc.get("kind") or "") == KIND_PRE:
                # 前置模组常见形态是「跑一次就退出」：它启动后几秒内就会带着 bridge
                # token 来敲门，而 enabled 要等它退出才写，bridge 会先按 401 拒掉。
                # 这里先预写 enabled，让它活着的窗口内就能通过鉴权；退出码和健康
                # 检查的最终结论仍在下面覆盖，失败会改回 broken。
                try:
                    registry.patch(
                        mid, state="enabled", pid=pid, artifacts=arts, runtime_port=runtime_port
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("前置模组 %s 预写启用状态失败：%s", mid, exc)
        health_doc = doc.get("health") or {}
        ok = _wait_health(health_doc, port=runtime_port)
        if ok and pid and health_doc and not _pid_alive(int(pid)):
            # 端口通了不等于本模组活着：另一个模组也可能正听着同一个端口。
            ok = False
            log.warning("模组 %s 健康检查通过但进程 %s 已不在，按异常处理", mid, pid)
        if ok and pid and not health_doc:
            kind = str(doc.get("kind") or "")
            if kind == KIND_PRE:
                # 前置模组常见形态是「跑一次、把目录/文件/代码准备好就退出」。
                # 这种不能按普通模组判「退出=坏了」，要等它跑完并看退出码。
                deadline = time.time() + 30.0
                while time.time() < deadline and _pid_alive(pid):
                    time.sleep(0.1)
                rc = proc.poll()
                if rc is None:
                    log.warning("前置模组 %s 30 秒还没退出，按常驻进程处理", mid)
                else:
                    ok = rc == 0
                    if not ok:
                        log.warning("前置模组 %s 退出码 %s", mid, rc)
            else:
                # 普通模组：给它 1.5 秒，入口脚本如果自己失败了就判异常，
                # 避免"显示已启用、其实什么都没做"。
                time.sleep(1.5)
                if not _pid_alive(pid):
                    ok = False
                    log.warning("模组 %s 的入口脚本启动后立即退出（pid %s 已不在）", mid, pid)
        state = "enabled" if ok else "broken"
        registry.patch(mid, state=state, pid=pid, artifacts=arts, runtime_port=runtime_port)
        _note_event(mod, state)
        log.info("模组启用 %s state=%s pid=%s", mid, state, pid)
        if state == "enabled":
            try:
                notify_nanny(registry.get(mid) or mod, "register")
            except Exception:
                log.debug("通知保姆登记模组失败：%s", mid, exc_info=True)
        if not ok:
            raise PbabError("模组起来了但健康检查没通过，已标记为异常")
        return registry.get(mid) or {}
    finally:
        _release_port(runtime_port)


def disable(mid: str) -> Dict[str, Any]:
    mod = registry.get(mid) or {}
    pid = mod.get("pid")
    if pid:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    dirs = [Path(str(mod.get("dir") or module_dir(mid)))]
    pr = payload_root(mod) if mod else None
    if pr and str(pr) != str(dirs[0]):
        dirs.append(pr)
    n = _kill_pid_files(dirs)
    n += _kill_module_procs(dirs)
    # 只杀「属于这个安装/这个模组目录」的端口占用者；
    # 同一个模组可能被别的安装装在同一个端口上，绝不能越界杀。
    try:
        doc = manifest(mid)
        ports = [int(p) for p in (doc.get("ports") or [])]
        if mod.get("runtime_port"):
            ports.append(int(mod["runtime_port"]))
        n += _kill_port_owners(ports, only_dir=str(dirs[0]))
    except Exception:
        log.warning("停用 %s 时清理端口残留失败，继续停用", mid, exc_info=True)
    if n:
        log.info("模组停用 %s：额外清理了 %s 个残留进程", mid, n)
    _remove_links(mod.get("artifacts") or [])
    registry.patch(mid, state="disabled", pid=None, artifacts=[])
    _note_event(mod, "disabled")
    notify_nanny(registry.get(mid) or mod, "unregister")
    log.info("模组停用 %s", mid)
    return registry.get(mid) or {}


def _module_payload(mod: dict) -> dict:
    mid = str(mod.get("id") or "")
    conn = {}
    try:
        conn = read_connection(mid) or {}
    except Exception:
        conn = {}
    return {
        "id": mid,
        "name": str(mod.get("name") or mid),
        "summary": str(mod.get("summary") or ""),
        "ports": [int(p) for p in (mod.get("ports") or []) if str(p).isdigit()],
        "tools": (conn.get("provides") or {}).get("tools") or [],
    }


def _core_url() -> str:
    try:
        return str(config.get("core_url") or "http://127.0.0.1:40720").rstrip("/")
    except Exception:
        return "http://127.0.0.1:40720"


def _core_headers() -> dict:
    """内核本机 token；读不到就空（健康检查仍可用）。"""
    try:
        tok = (config.entity_dir() / "state" / "core_token").read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        tok = ""
    return {"X-BAB-Core-Token": tok} if tok else {}


def _post_core(path: str, payload: dict) -> bool:
    try:
        import httpx
    except Exception:
        return False
    try:
        r = httpx.post(_core_url() + path, json=payload, timeout=1.5, headers=_core_headers())
        if r.status_code >= 400:
            log.warning("保姆不收这份备案（%s）：%s", path, r.status_code)
            return False
        return True
    except Exception:
        return False


def _spool(payload: dict) -> None:
    # 内核没起来：先攒着，等它起来自己补记
    try:
        p = config.APP_DIR / "WiseEntity" / "entity" / "state" / "module_pending.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception as e:
        log.warning("备案攒不下来：%s", e)


def notify_nanny(mod: dict, action: str = "register") -> None:
    """模组装/卸之后，把这件事交给保姆记进她的程序清单。"""
    payload = _module_payload(mod)
    if action == "unregister":
        payload = {"id": payload["id"], "action": "unregister"}
        path = "/modules/unregister"
    else:
        path = "/modules/register"
    if _post_core(path, payload):
        log.info("保姆已备案 %s（%s）", payload.get("id"), action)
    else:
        _spool(payload)
        log.info("内核不在，备案先攒着：%s（%s）", payload.get("id"), action)


def _note_event(mod: Dict[str, Any], state: str) -> None:
    """记一笔模组开关，供提示词说「刚刚变了」。"""
    try:
        p = config.APP_DIR / "WiseEntity" / "entity" / "state" / "module_events.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "id": str(mod.get("id") or ""),
            "name": str(mod.get("name") or mod.get("id") or ""),
            "state": state,
        }
        last = {}
        if p.exists():
            tail = p.read_text(encoding="utf-8-sig", errors="ignore").splitlines()[-1:]
            if tail:
                try:
                    last = json.loads(tail[0])
                except Exception:
                    last = {}
        if last.get("id") == row["id"] and last.get("state") == row["state"]:
            return
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as e:  # pragma: no cover
        log.warning("记模组事件失败：%r", e)


def uninstall(mid: str) -> None:
    mod = registry.get(mid)
    if not mod:
        return
    try:
        disable(mid)
    except Exception:
        log.warning("卸载 %s 前停用失败，继续删目录", mid, exc_info=True)
    d = Path(str(mod.get("dir") or module_dir(mid)))
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    # 只清壳自己下载到 program_cache 的东西；用户从官网装好的软件一概不动
    dl = Path(str(config.get("modules_dir"))) / "downloads" / mid
    if dl.exists():
        shutil.rmtree(dl, ignore_errors=True)
    registry.remove(mid)
    notify_nanny(mod, "unregister")
    log.info("模组已完全卸载 %s", mid)
