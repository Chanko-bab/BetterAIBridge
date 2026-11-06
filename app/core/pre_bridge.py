# -*- coding: utf-8 -*-
"""前置模组的改文件接口：预览、备份、落盘。

只给 kind=pre 的模组用。按用户要求完全放开：不再设路径黑名单、不再限
文件类型、不再限单次条数/大小，也可以写到 BAB 程序目录之外（任意绝对路
径，前提是 Windows 当前用户有权限）。落盘前会备份所有已存在的目标文件，
并写 pre_audit.jsonl；新建的文件/目录没有旧内容可备份。
"""
from __future__ import annotations

import json
import os
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List

from . import config


def _root() -> Path:
    return Path(config.APP_DIR).resolve()


def _resolve(raw: str) -> Path:
    text = str(raw or "").strip().replace("\\", "/")
    if not text:
        raise ValueError("path 不能为空")
    p = Path(text).expanduser()
    if not p.is_absolute():
        p = _root() / p
    return p.resolve()


def _label(p: Path) -> str:
    """审计/预览里的路径：程序目录内用相对路径，目录外用绝对路径。"""
    root = _root()
    try:
        return p.relative_to(root).as_posix()
    except ValueError:
        return p.as_posix()


def preview(ops: Any) -> Dict[str, Any]:
    """校验并描述这次要改什么；不落盘。"""
    if not isinstance(ops, list) or not ops:
        return {"ok": False, "error": "ops 必须是非空数组"}
    changes: List[Dict[str, Any]] = []
    for i, raw in enumerate(ops):
        if not isinstance(raw, dict):
            return {"ok": False, "error": f"ops[{i}] 必须是对象"}
        op = str(raw.get("op") or "").strip()
        try:
            p = _resolve(str(raw.get("path") or ""))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        rel = _label(p)
        if op == "mkdir":
            if p.exists() and not p.is_dir():
                return {"ok": False, "error": f"{rel} 已经被一个文件占用了"}
            changes.append({"op": op, "path": rel, "exists": p.exists()})
        elif op == "write":
            content = raw.get("content")
            if not isinstance(content, str):
                return {"ok": False, "error": f"{rel} 的 content 必须是字符串"}
            size = len(content.encode("utf-8"))
            old = ""
            if p.is_file():
                try:
                    old = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    old = ""
            changes.append({
                "op": op, "path": rel, "exists": p.is_file(), "bytes": size,
                "lines": content.count("\n") + 1,
                "preview": content[:1200],
                "old_preview": old[:400] if old else "",
            })
        elif op == "delete":
            if not p.is_file():
                return {"ok": False, "error": f"要删的文件不存在：{rel}（只允许删文件）"}
            changes.append({"op": op, "path": rel, "exists": True,
                            "bytes": p.stat().st_size})
        else:
            return {"ok": False, "error": f"不认识的 op：{op!r}（只支持 mkdir/write/delete）"}
    return {"ok": True, "changes": changes}


def _backup(paths: List[Path], mid: str) -> Path:
    base = Path(config.entity_dir()) / "state" / "pre_backups"
    base.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = base / f"{stamp}-{mid}.zip"
    n = 1
    while out.exists():
        out = base / f"{stamp}-{mid}-{n}.zip"
        n += 1
    root = _root()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            if not p.is_file():
                continue
            try:
                name = p.relative_to(root).as_posix()
            except ValueError:
                name = "abs/" + p.as_posix().lstrip("/").replace(":", "_")
            zf.write(p, name)
    return out


def apply(ops: List[Dict[str, Any]], mid: str, reason: str = "") -> Dict[str, Any]:
    """按已确认的 ops 落盘；先备份再写，失败时回报备份路径。"""
    pre = preview(ops)
    if not pre.get("ok"):
        return pre
    targets: List[Path] = []
    for raw in ops:
        p = _resolve(str(raw.get("path") or ""))
        if p not in targets:
            targets.append(p)
    backup = _backup(targets, mid)
    changed: List[str] = []
    try:
        for raw in ops:
            p = _resolve(str(raw.get("path") or ""))
            op = str(raw.get("op") or "")
            rel = _label(p)
            if op == "mkdir":
                p.mkdir(parents=True, exist_ok=True)
            elif op == "write":
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp = p.with_name(p.name + ".pre-tmp")
                tmp.write_text(str(raw.get("content") or ""), encoding="utf-8")
                os.replace(tmp, p)
            elif op == "delete":
                p.unlink(missing_ok=True)
            changed.append(f"{op} {rel}")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"改到一半失败：{exc}", "backup": str(backup),
                "changed": changed}
    _audit(mid, reason, changed, backup)
    return {"ok": True, "changed": changed, "backup": str(backup)}


def _audit(mid: str, reason: str, changed: List[str], backup: Path) -> None:
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "module": mid,
           "reason": str(reason or "")[:500], "changed": changed, "backup": str(backup)}
    path = Path(config.entity_dir()) / "state" / "pre_audit.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass
