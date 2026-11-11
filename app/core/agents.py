"""智能体档案：agents/<slug>/ 的创建、索引、回收站、导出与旧安装迁移。

P0 只做数据层。选择器 UI 在 P1 接这里；本模块不依赖 Qt，也不启动内核，
所以可以在启动器、测试和一次性迁移脚本里安全调用。

索引 ``agents.json`` 只是缓存：真正的真相是每个目录里的 ``agent.json``。
索引坏了可以 scan/rebuild，不会把智能体弄丢。
"""
from __future__ import annotations

import json
import shutil
import tempfile
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from . import agent_paths, bindings

INDEX_NAME = "agents.json"
AGENT_FILE = "agent.json"
TRASH_NAME = ".trash"
TRASH_DAYS = 7
_LOCK = threading.RLock()


class AgentError(RuntimeError):
    """智能体档案操作失败；调用方应把 message 原样给用户看。"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def index_path() -> Path:
    return agent_paths.install_root() / INDEX_NAME


def _agent_dir(slug: str) -> Path:
    return agent_paths.agents_root() / slug


def _entry(root: Path) -> Dict[str, Any] | None:
    doc = _read_json(root / AGENT_FILE, {})
    if not isinstance(doc, dict):
        return None
    slug = str(doc.get("slug") or root.name)
    return {
        "slug": slug,
        "name": str(doc.get("name") or slug),
        "avatar": str(doc.get("avatar") or ""),
        "created_at": str(doc.get("created_at") or ""),
        "last_used": str(doc.get("last_used") or ""),
        "path": str(root),
    }


def scan() -> List[Dict[str, Any]]:
    """扫 agents/ 下的真实目录；.trash 和临时目录自然被跳过。"""
    root = agent_paths.agents_root()
    out: List[Dict[str, Any]] = []
    try:
        children = list(root.iterdir())
    except OSError:
        return out
    for child in children:
        if not child.is_dir() or child.name.startswith("."):
            continue
        item = _entry(child)
        if item:
            out.append(item)
    out.sort(key=lambda x: (x.get("last_used") or "", x.get("name") or ""), reverse=True)
    return out


def load_index(rebuild: bool = True) -> Dict[str, Any]:
    doc = _read_json(index_path(), None)
    rows = doc.get("agents") if isinstance(doc, dict) else None
    if isinstance(rows, list) and rows:
        ok = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            slug = str(row.get("slug") or "")
            if slug and (_agent_dir(slug) / AGENT_FILE).exists():
                ok.append(row)
        if ok:
            return {"format": "bab-agents/1", "updated": str(doc.get("updated") or ""), "agents": ok}
    if not rebuild:
        return {"format": "bab-agents/1", "updated": "", "agents": []}
    rows = scan()
    doc = {"format": "bab-agents/1", "updated": _now(), "agents": rows}
    try:
        _write_json(index_path(), doc)
    except OSError:
        pass
    return doc


def save_index() -> Dict[str, Any]:
    doc = {"format": "bab-agents/1", "updated": _now(), "agents": scan()}
    _write_json(index_path(), doc)
    return doc


def _unique_slug(name: str) -> str:
    base = agent_paths.slugify(name)
    slug = base
    i = 2
    while _agent_dir(slug).exists():
        suffix = f"-{i}"
        slug = base[: 32 - len(suffix)].rstrip("-") + suffix
        i += 1
    return slug


def create_agent(name: str, api_key: str = "", avatar: str = "") -> Dict[str, Any]:
    """建一个最小智能体目录；人格/Key 的向导流程在 P1 接。"""
    name = (name or "").strip()
    if not name:
        raise AgentError("智能体名字不能为空")
    if len(name) > 40:
        raise AgentError("智能体名字最多 40 个字")
    with _LOCK:
        slug = _unique_slug(name)
        root = _agent_dir(slug)
        if root.exists():
            raise AgentError("智能体目录已经存在")
        tmp = agent_paths.agents_root() / f".tmp-{slug}-{int(time.time() * 1000)}"
        try:
            agent_paths.ensure_agent_dirs(tmp)
            doc = {
                "format": "bab-agent/1",
                "slug": slug,
                "name": name,
                "created_at": _now(),
                "last_used": "",
                "avatar": "",
            }
            _write_json(tmp / AGENT_FILE, doc)
            if avatar:
                src = Path(avatar)
                if src.is_file():
                    dst = tmp / "avatar.png"
                    shutil.copy2(src, dst)
                    doc["avatar"] = "avatar.png"
                    _write_json(tmp / AGENT_FILE, doc)
            if api_key.strip():
                _write_json(
                    tmp / "entity" / "config" / "llm.json",
                    {"api_key": api_key.strip()},
                )
            tmp.replace(root)
        except (OSError, ValueError) as exc:
            shutil.rmtree(tmp, ignore_errors=True)
            raise AgentError(f"建智能体失败：{exc}") from exc
        save_index()
        return _entry(root) or {}


def set_last_used(slug: str) -> None:
    root = _agent_dir(slug)
    doc = _read_json(root / AGENT_FILE, {})
    if not isinstance(doc, dict):
        return
    doc["last_used"] = _now()
    try:
        _write_json(root / AGENT_FILE, doc)
        save_index()
    except OSError:
        pass


def trash_agent(slug: str) -> Path:
    """删除不是立即抹掉：移到 agents/.trash，7 天后才清。"""
    with _LOCK:
        root = _agent_dir(slug)
        if not (root / AGENT_FILE).exists():
            raise AgentError("找不到这个智能体")
        trash_root = agent_paths.agents_root() / TRASH_NAME
        trash_root.mkdir(parents=True, exist_ok=True)
        dest = trash_root / f"{slug}-{time.strftime('%Y%m%d-%H%M%S')}"
        if dest.exists():
            dest = trash_root / f"{slug}-{int(time.time() * 1000)}"
        try:
            root.replace(dest)
        except OSError as exc:
            raise AgentError(f"删除失败（可能有进程占用）：{exc}") from exc
        _write_json(
            dest / "deleted.json",
            {
                "slug": slug,
                "deleted_at": _now(),
                "expires_at": datetime.fromtimestamp(time.time() + TRASH_DAYS * 86400)
                .strftime("%Y-%m-%dT%H:%M:%S"),
            },
        )
        save_index()
        return dest


def restore_agent(trash_dir: str | Path) -> Dict[str, Any]:
    with _LOCK:
        src = Path(trash_dir)
        meta = _read_json(src / "deleted.json", {})
        slug = str((meta or {}).get("slug") or src.name.split("-")[0])
        if not slug:
            raise AgentError("回收站条目坏了，找不到原 slug")
        dest = _agent_dir(slug)
        if dest.exists():
            raise AgentError(f"「{slug}」已经存在，不能恢复")
        try:
            src.replace(dest)
        except OSError as exc:
            raise AgentError(f"恢复失败：{exc}") from exc
        (dest / "deleted.json").unlink(missing_ok=True)
        save_index()
        return _entry(dest) or {}


def purge_trash(days: int = TRASH_DAYS) -> List[str]:
    """清掉过期回收站；返回清掉的目录名。启动器启动时调用一次即可。"""
    root = agent_paths.agents_root() / TRASH_NAME
    removed: List[str] = []
    if not root.exists():
        return removed
    deadline = time.time() - max(1, int(days)) * 86400
    for child in list(root.iterdir()):
        if not child.is_dir():
            continue
        meta = _read_json(child / "deleted.json", {})
        try:
            deleted = datetime.strptime(str((meta or {}).get("deleted_at")), "%Y-%m-%dT%H:%M:%S")
            ts = deleted.timestamp()
        except (TypeError, ValueError):
            ts = child.stat().st_mtime
        if ts < deadline:
            shutil.rmtree(child, ignore_errors=True)
            removed.append(child.name)
    return removed


def export_agent(slug: str, dest: str | Path, include_key: bool = False) -> Path:
    """导出 .babpak；默认不含 entity/config/llm.json。"""
    root = _agent_dir(slug)
    if not (root / AGENT_FILE).exists():
        raise AgentError("找不到这个智能体")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    manifest = {
        "format": "bab-agent-archive/1",
        "slug": slug,
        "exported_at": _now(),
        "include_key": bool(include_key),
    }
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                rel = path.relative_to(root).as_posix()
                if rel in {"deleted.json"} or rel.startswith("logs/") or rel.startswith("backups/"):
                    continue
                if rel == "entity/config/llm.json" and not include_key:
                    continue
                zf.write(path, f"agent/{rel}")
        tmp.replace(dest)
    except (OSError, zipfile.BadZipFile) as exc:
        tmp.unlink(missing_ok=True)
        raise AgentError(f"导出失败：{exc}") from exc
    return dest


def _enabled_modules(root: Path) -> List[str]:
    doc = _read_json(root / "program_bundle" / "registry.json", {})
    mods = doc.get("modules") if isinstance(doc, dict) else {}
    if not isinstance(mods, dict):
        return []
    return [
        str(mid)
        for mid, row in mods.items()
        if isinstance(row, dict) and str(row.get("state") or "") == "enabled"
    ]


def migrate_legacy(root: str | Path | None = None, dry_run: bool = False) -> Dict[str, Any] | None:
    """把旧安装的 WiseEntity/entity 迁成 agents/<slug>/entity。

    可回滚：任何一步失败都会把 entity 挪回原位。返回 None 表示不需要迁移。
    """
    install = Path(root) if root else agent_paths.install_root()
    legacy = install / "WiseEntity" / "entity"
    agents = install / "agents"
    if not legacy.exists():
        return None
    if agents.exists() and any(agents.iterdir()):
        return None
    persona = legacy / "persona" / "persona.md"
    name = "我的智能体"
    try:
        for line in persona.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
            text = line.strip()
            if text and not text.startswith("#"):
                name = text[:40]
                break
            if text.startswith("# ") and len(text) > 2:
                name = text[2:].strip()[:40]
                break
    except OSError:
        pass
    slug = agent_paths.slugify(name)
    plan = {
        "install_root": str(install),
        "legacy_entity": str(legacy),
        "agent_root": str(agents / slug),
        "slug": slug,
        "name": name,
        "modules": _enabled_modules(install),
    }
    if dry_run:
        return plan

    backup_dir = install / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"pre-agents-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    with zipfile.ZipFile(backup, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in legacy.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(install).as_posix())

    agents.mkdir(parents=True, exist_ok=True)
    tmp = agents / f".tmp-{slug}-{int(time.time() * 1000)}"
    moved = False
    reg_moved = False
    try:
        agent_paths.ensure_agent_dirs(tmp)
        # ensure_agent_dirs 会先建空 entity；rename 不能覆盖已存在目录，先摘掉。
        shutil.rmtree(tmp / "entity", ignore_errors=True)
        legacy.replace(tmp / "entity")
        moved = True
        reg = install / "program_bundle" / "registry.json"
        if reg.exists():
            (tmp / "program_bundle").mkdir(parents=True, exist_ok=True)
            reg.replace(tmp / "program_bundle" / "registry.json")
            reg_moved = True
        _write_json(
            tmp / AGENT_FILE,
            {
                "format": "bab-agent/1",
                "slug": slug,
                "name": name,
                "created_at": _now(),
                "last_used": _now(),
                "avatar": "",
            },
        )
        tmp.replace(agents / slug)
    except OSError as exc:
        if reg_moved and (tmp / "program_bundle" / "registry.json").exists():
            try:
                (tmp / "program_bundle" / "registry.json").replace(
                    install / "program_bundle" / "registry.json"
                )
            except OSError:
                pass
        if moved and (tmp / "entity").exists():
            try:
                (tmp / "entity").replace(legacy)
            except OSError:
                pass
        shutil.rmtree(tmp, ignore_errors=True)
        raise AgentError(f"迁移失败，已回滚：{exc}") from exc

    for mid in plan["modules"]:
        try:
            bindings.bind(mid, slug)
        except (RuntimeError, OSError):
            pass
    save_index()
    plan["backup"] = str(backup)
    return plan
