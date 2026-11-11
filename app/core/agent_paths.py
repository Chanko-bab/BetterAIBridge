"""多智能体路径契约：程序根与智能体数据根分离。

为什么要单独一个模块：
    P0 之前，整个程序默认“一次安装 = 一个智能体”，大量代码直接把
    ``BAB_ROOT/WiseEntity/entity`` 当成唯一的数据目录。多智能体不能靠改
    几个字符串蒙混过去——模组还要用 ``BAB_ROOT/.venv`` 找 Python，所以
    ``BAB_ROOT`` 必须继续指向安装根，智能体数据另用 ``BAB_AGENT_ROOT``。

约定：
    BAB_ROOT          安装/程序根（不变）
    BAB_AGENTS_ROOT   智能体目录集合，默认 <安装根>/agents
    BAB_AGENT_ROOT    当前智能体根，如 <安装根>/agents/xiaoyue
    BAB_ENTITY        当前智能体 entity，默认 <BAB_AGENT_ROOT>/entity
    BAB_BUNDLE        共享模组包根，默认 <安装根>/program_bundle
    BAB_AGENT_ID      当前智能体 slug

没有设置任何智能体变量时，所有函数回退到旧的单智能体路径，保证旧安装、
旧测试和旧模组仍能启动。
"""
from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from pathlib import Path

RESERVED_SLUGS = frozenset(
    {
        "app",
        "wiseentity",
        "assets",
        "agents",
        "logs",
        "config",
        "program_bundle",
        "program_cache",
        "packaging",
        "tools",
        "templates",
        "data",
        "backups",
        "con",
        "prn",
        "aux",
        "nul",
    }
)


def install_root() -> Path:
    """安装/程序根。BAB_ROOT 始终是它，不是智能体目录。"""
    raw = (os.environ.get("BAB_ROOT") or "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[2]


def agents_root() -> Path:
    raw = (os.environ.get("BAB_AGENTS_ROOT") or "").strip()
    if raw:
        return Path(raw)
    return install_root() / "agents"


def agent_root(slug: str | None = None) -> Path | None:
    """当前智能体根；没设置且没给 slug 时返回 None（旧单智能体模式）。"""
    raw = (os.environ.get("BAB_AGENT_ROOT") or "").strip()
    if raw:
        return Path(raw)
    if slug:
        return agents_root() / slug
    return None


def entity_root(slug: str | None = None) -> Path:
    """人格/记忆/情绪/仓库所在目录。

    优先级：BAB_ENTITY > BAB_AGENT_ROOT/entity > 旧安装根/WiseEntity/entity。
    """
    raw = (os.environ.get("BAB_ENTITY") or "").strip()
    if raw:
        return Path(raw)
    root = agent_root(slug)
    if root is not None:
        return root / "entity"
    return install_root() / "WiseEntity" / "entity"


def bundle_root() -> Path:
    raw = (os.environ.get("BAB_BUNDLE") or "").strip()
    if raw:
        return Path(raw)
    return install_root() / "program_bundle"


def agent_id() -> str:
    return (os.environ.get("BAB_AGENT_ID") or "").strip()


def has_agent() -> bool:
    return agent_root() is not None


def module_env() -> dict[str, str]:
    """给模组进程补的多智能体环境变量；旧单智能体模式下返回空 dict。"""
    root = agent_root()
    if root is None:
        return {}
    return {
        "BAB_AGENT_ROOT": str(root),
        "BAB_AGENT_ID": agent_id(),
        "BAB_ENTITY": str(entity_root()),
        "BAB_BUNDLE": str(bundle_root()),
    }


def slugify(name: str) -> str:
    """把显示名压成安全的目录名。

    中文没有内置拼音，不能可靠转写，所以非 ASCII 名字退化为
    ``agent-<sha1 前 8 位>``；ASCII 名字保留可读性。这样改名只改
    agent.json 的 name，目录永远稳定。
    """
    text = unicodedata.normalize("NFKD", name or "")
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    text = re.sub(r"-{2,}", "-", text)[:32].strip("-")
    if not text:
        digest = hashlib.sha1((name or "agent").encode("utf-8")).hexdigest()[:8]
        text = f"agent-{digest}"
    if text in RESERVED_SLUGS:
        text = f"agent-{text}"
    return text[:32].strip("-") or "agent"


def valid_slug(slug: str) -> bool:
    if not isinstance(slug, str):
        return False
    if slug != slug.strip().lower():
        return False
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", slug):
        return False
    return slug not in RESERVED_SLUGS


def ensure_agent_dirs(root: Path) -> None:
    """给一个智能体建最小骨架；不写人格/Key，留给创建向导。"""
    root = Path(root)
    for rel in (
        "entity/persona",
        "entity/memory",
        "entity/emotion",
        "entity/state",
        "entity/config",
        "entity/warehouse",
        "logs",
        "backups",
    ):
        (root / rel).mkdir(parents=True, exist_ok=True)
