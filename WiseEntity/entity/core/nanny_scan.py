"""保姆的按需只读扫描：列目录、读文本、按关键词找文件。

保姆仍然不能写、不能执行命令；这里只解决「她想看某个文件/某个目录时，
只能看启动快照」的问题。所有路径都被夹在 BAB 程序目录内。
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, List, Optional

from . import settings as S

MAX_ENTRIES = 80
MAX_READ = 6000
MAX_HITS = 16
MAX_FILES = 400
MAX_BYTES = 2 * 1024 * 1024

SKIP_DIRS = {".venv", "__pycache__", ".git", "node_modules", ".idea", ".mypy_cache"}
TEXT_EXT = {
    ".py", ".pyi", ".md", ".txt", ".json", ".jsonl", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".ps1", ".bat", ".cmd", ".qss", ".css",
    ".html", ".js", ".ts", ".tsx", ".jsx", ".csv", ".log", ".xml",
}

_PATH_RE = re.compile(
    r"""(?P<path>(?:[A-Za-z]:[\\/]|\.{1,2}[\\/]|[A-Za-z0-9_.-]+[\\/])"""
    r"""[A-Za-z0-9_./\\ -]*?\.(?:py|pyi|md|txt|json|jsonl|ya?ml|toml|ini|"""
    r"""cfg|ps1|bat|cmd|qss|css|html|js|ts|tsx|jsx|csv|log|xml))""",
    re.IGNORECASE,
)
_QUOTED_RE = re.compile(r"[`'\"]([^`'\"]{1,200})[`'\"]")


def _root() -> Path:
    return Path(S.APP_ROOT).resolve()


def _safe(raw: str) -> Path:
    text = str(raw or "").strip().replace("\\", "/")
    if not text:
        return _root()
    p = Path(text).expanduser()
    if not p.is_absolute():
        p = _root() / p
    p = p.resolve()
    root = _root()
    if p != root and root not in p.parents:
        raise ValueError(f"不能看程序目录外面：{raw}")
    return p


def _rel(p: Path) -> str:
    try:
        return p.relative_to(_root()).as_posix()
    except ValueError:
        return p.as_posix()


def list_dir(rel: str = "", depth: int = 1, limit: int = MAX_ENTRIES) -> str:
    try:
        p = _safe(rel)
    except ValueError as exc:
        return str(exc)
    if not p.is_dir():
        return f"（{_rel(p)} 不是目录）"
    lines: List[str] = []
    depth = max(1, min(int(depth or 1), 3))

    def walk(d: Path, left: int) -> None:
        if left >= limit:
            return
        try:
            children = sorted(d.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        except OSError as exc:
            lines.append(f"  （读不了 {_rel(d)}：{exc}）")
            return
        for child in children:
            if left >= limit:
                lines.append("  …（还有更多，先列到这里）")
                return
            if child.name in SKIP_DIRS:
                continue
            tag = "/" if child.is_dir() else ""
            lines.append("  " * (depth - 1) + f"- {child.name}{tag}")
            left += 1
            if child.is_dir() and depth > 1:
                walk(child, left)

    walk(p, 0)
    head = f"目录 {_rel(p) or '.'}：\n"
    return head + ("\n".join(lines) if lines else "（空目录）")


def read_file(rel: str, max_chars: int = MAX_READ) -> str:
    try:
        p = _safe(rel)
    except ValueError as exc:
        return str(exc)
    if not p.is_file():
        return f"（{_rel(p)} 不是文件）"
    if p.suffix.lower() not in TEXT_EXT:
        return f"（{_rel(p)} 不是文本文件，我不读二进制）"
    try:
        if p.stat().st_size > MAX_BYTES:
            return f"（{_rel(p)} 太大，超过 2MB，先不整份读）"
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"（读不了 {_rel(p)}：{exc}）"
    cut = text[:max_chars]
    return f"文件 {_rel(p)}（{len(text)} 字）：\n```\n{cut}\n```" + (
        "\n…（后面还有，先看这些）" if len(text) > max_chars else "")


def search(text: str, limit: int = MAX_HITS) -> str:
    needle = str(text or "").strip()
    if len(needle) < 2:
        return ""
    root = _root()
    hits: List[str] = []
    seen = 0
    for p in root.rglob("*"):
        if seen >= MAX_FILES or len(hits) >= limit:
            break
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if not p.is_file() or p.suffix.lower() not in TEXT_EXT:
            continue
        try:
            if p.stat().st_size > MAX_BYTES:
                continue
            seen += 1
            with p.open("r", encoding="utf-8", errors="replace") as fh:
                for no, line in enumerate(fh, 1):
                    if needle.lower() in line.lower():
                        hits.append(f"{_rel(p)}:{no}: {line.strip()[:180]}")
                        break
        except OSError:
            continue
    if not hits:
        return f"（在项目里没找到「{needle}」）"
    return "找到这些：\n" + "\n".join("- " + h for h in hits)


def _candidate_paths(text: str) -> List[str]:
    out: List[str] = []
    for m in _PATH_RE.finditer(text or ""):
        raw = m.group("path").strip().strip("`'\"")
        if raw and raw not in out:
            out.append(raw)
    if out:
        return out
    for raw in _QUOTED_RE.findall(text or ""):
        try:
            p = _safe(raw)
        except ValueError:
            continue
        if p.exists():
            return [raw]
    return []


def context_for(text: str) -> str:
    """按用户这句话，给保姆补一段只读扫描结果；没有明确指向就返回空。"""
    raw = str(text or "").strip()
    if not raw:
        return ""
    # 只在话里确实有“看/查/找”的意图时才翻项目；普通闲聊不扫。
    if not re.search(r"扫描|看看|看一下|看下|看一眼|查|找|读|打开|目录|文件|代码|在哪|位置|搜索|列一下", raw):
        return ""
    chunks: List[str] = []
    for cand in _candidate_paths(raw)[:3]:
        try:
            p = _safe(cand)
        except ValueError:
            chunks.append(f"{cand}：不能看程序目录外面。")
            continue
        if p.is_dir():
            chunks.append(list_dir(cand, depth=2))
        elif p.is_file():
            chunks.append(read_file(cand))
        else:
            chunks.append(f"{cand}：这个路径不存在。")
    if chunks:
        return "\n\n".join(chunks)
    # 没有路径时，才把整句话当关键词找；太短的词不扫，避免每句话都翻项目
    words = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9_]{2,}", raw)
    stop = {"扫描", "一下", "看看", "项目", "文件", "目录", "帮我", "查查", "检查"}
    keys = [w for w in words if not any(s in w for s in stop)]
    if not keys:
        return ""
    for key in keys[:2]:
        got = search(key)
        if "没找到" not in got:
            return got
    return search(keys[0])


def _count_files(p: Path, limit: int = 4000) -> int:
    n = 0
    try:
        for it in p.rglob("*"):
            if n >= limit:
                break
            if any(part in SKIP_DIRS for part in it.parts):
                continue
            if it.is_file():
                n += 1
    except OSError:
        return n
    return n


_OVERVIEW = ("", 0.0)
OVERVIEW_TTL = 20.0


def overview() -> str:
    """给保姆一张项目地图：顶层目录、关键文件、各块大致规模。"""
    global _OVERVIEW
    if _OVERVIEW[0] and time.time() - _OVERVIEW[1] < OVERVIEW_TTL:
        return _OVERVIEW[0]
    root = _root()
    rows: List[str] = [f"程序根：{root}"]
    for name, desc in (
        ("app", "启动器：界面、服务、存档、对话框"),
        ("WiseEntity/entity", "内核：人格、记忆、情绪、桥、模组、保姆"),
        ("WiseEntity/entity/core", "内核主要代码"),
        ("WiseEntity/entity/persona", "人格文件 persona.md"),
        ("WiseEntity/entity/memory", "智能体记忆"),
        ("WiseEntity/entity/state", "运行状态（会话、情绪、保姆日志）"),
        ("program_bundle", "已安装模组"),
        ("program_cache", "模组包缓存"),
        ("tools", "自检脚本"),
    ):
        p = root / name
        if p.exists():
            n = _count_files(p) if p.is_dir() else 1
            rows.append(f"- {name}/：{desc}（约 {n} 个文件）" if p.is_dir() else f"- {name}：{desc}")
    tops = []
    for p in sorted(root.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        if p.name in SKIP_DIRS or p.name in {"runtime", "logs", "dist", "build"}:
            continue
        tops.append(p.name + ("/" if p.is_dir() else ""))
    rows.append("顶层：" + "、".join(tops[:30]))
    text = "\n".join(rows)
    _OVERVIEW = (text, time.time())
    return text


def snapshot_line() -> str:
    return f"项目根：{_root()}"
