# -*- coding: utf-8 -*-
"""记忆库：按天一个 .txt，六段分桶，第一人称「我」。

设计（2026-10-31 与主人定稿）：

    entity/memory/
      internal/<门>/2026.10.31.txt              提炼过的记忆，给她自己读
      internal/.raw/<门>/2026.10.31.jsonl       原文，ingest 的原料
      internal/_index.jsonl                     检索索引
      external/<program>/<分类>/2026.10.31.txt  模组要求记的
      _summary/ _archive/ _legacy/

一天 00:00–23:59，六段：

    凌晨(00:00-06:00) 上午(06:00-11:00) 中午(11:00-13:00)
    下午(13:00-18:00) 傍晚(18:00-21:00) 夜晚(21:00-23:59)

每条一行：`HH:MM 我做了什么`——她来回忆时读到的就是"我"，不是"她"。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import time
from pathlib import Path
from typing import Iterable

from . import settings as S

# ---------------------------------------------------------------- 常量

BUCKETS: list[tuple[str, int, int, str]] = [
    ("凌晨", 0, 6, "凌晨(00:00-06:00)"),
    ("上午", 6, 11, "上午(06:00-11:00)"),
    ("中午", 11, 13, "中午(11:00-13:00)"),
    ("下午", 13, 18, "下午(13:00-18:00)"),
    ("傍晚", 18, 21, "傍晚(18:00-21:00)"),
    ("夜晚", 21, 24, "夜晚(21:00-23:59)"),
]
_HEADER_OF = {name: header for name, _, _, header in BUCKETS}

MEMORY_ROOT = Path(S.MEM_DIR)
INTERNAL = "internal"
EXTERNAL = "external"
INDEX_NAME = "_index.jsonl"

# 0.3.20：主人不管从哪个入口说话，记忆都记在同一扇门里。
# 旧版按入口分门（web_owner / qq_owner / bili_owner），读的时候还兼容它们。
OWNER_DOOR = "owner"
LEGACY_OWNER_DOORS = ("web_owner", "qq_owner", "bili_owner")

_DOOR_SAFE = re.compile(r"^[a-z0-9_\-]{1,40}$")
_CAT_SAFE = re.compile(r"^[\w\u4e00-\u9fff\-]{1,24}$")
_DAY_RE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})\.txt$")
_LINE_RE = re.compile(r"^(\d{1,2}):(\d{2})\s+(.*)$")


# ---------------------------------------------------------------- 工具

def memory_root() -> Path:
    return Path(S.MEM_DIR)


def _norm(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _parse_ts(ts=None) -> _dt.datetime:
    if ts is None or ts == "":
        return _dt.datetime.now()
    if isinstance(ts, (int, float)):
        return _dt.datetime.fromtimestamp(float(ts))
    s = str(ts).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return _dt.datetime.strptime(s[:len(fmt) + 6].strip(), fmt)
        except ValueError:
            continue
    try:
        return _dt.datetime.fromisoformat(s)
    except ValueError:
        return _dt.datetime.now()


def bucket_of(moment: _dt.datetime | None = None) -> str:
    hour = (moment or _dt.datetime.now()).hour
    for name, lo, hi, _ in BUCKETS:
        if lo <= hour < hi:
            return name
    return "夜晚"


def day_of(moment: _dt.datetime | None = None) -> str:
    return (moment or _dt.datetime.now()).strftime("%Y.%m.%d")


# ---------------------------------------------------------------- 门

def door_of(session: str) -> str:
    """会话 → 抽屉名。

    主人自己的入口（web:owner / qq:owner / bili:owner）统一是 `owner`——
    她在 QQ 上说过的事，BAB 聊天里也记得。群和别人的私聊仍然各是一扇门。
    """
    s = str(session or "")
    m = re.match(r"qq:group:(\w+)", s)
    if m:
        return _safe_door(f"qq_group_{m.group(1)}")
    m = re.match(r"qq:friend:(\w+)", s)
    if m:
        return _safe_door(f"qq_friend_{m.group(1)}")
    m = re.match(r"bili:other:(\w+)", s)
    if m:
        return _safe_door(f"bili_other_{m.group(1)}")
    return OWNER_DOOR


def _safe_door(door: str) -> str:
    door = str(door or "").strip().lower()
    if not _DOOR_SAFE.match(door):
        raise ValueError(f"非法的抽屉名：{door!r}")
    return door


def is_owner_door(door: str) -> bool:
    """主人自己的门：新的 `owner`，以及旧版的 `*_owner`。"""
    door = str(door or "")
    return door == OWNER_DOOR or door.endswith("_owner")


def _legacy_owner_doors() -> list[str]:
    """还留在盘上的旧门（迁移过就不用再看了）。"""
    base = memory_root() / INTERNAL
    raw = base / ".raw"
    out: list[str] = []
    for door in LEGACY_OWNER_DOORS:
        if (base / door).is_dir() or (raw / door).is_dir():
            out.append(door)
    return out


def owner_doors() -> list[str]:
    """读主人记忆时要看的所有门：新的 + 还没搬家的旧的。"""
    return [OWNER_DOOR] + _legacy_owner_doors()


def visible_doors(session: str) -> list[str]:
    """这扇门能看见哪些抽屉。

    群/好友：只有自己那一本，不串味。
    主人：`owner` 一本，外加还没搬家的旧门（web_owner / qq_owner / bili_owner）。
    """
    door = door_of(session)
    if not is_owner_door(door):
        return [door]
    return owner_doors()


def door_dir(door: str) -> Path:
    return memory_root() / INTERNAL / _safe_door(door)


def day_path(door: str, day: str) -> Path:
    return door_dir(door) / f"{day}.txt"


def raw_dir(door: str) -> Path:
    return memory_root() / INTERNAL / ".raw" / _safe_door(door)


def raw_path(door: str, day: str) -> Path:
    return raw_dir(door) / f"{day}.jsonl"


def external_dir(program: str, category: str) -> Path:
    return memory_root() / EXTERNAL / _safe_program(program) / _safe_category(category)


def _safe_program(program: str) -> str:
    p = str(program or "").strip().lower()
    if not re.match(r"^[a-z0-9_\-]{1,40}$", p):
        raise ValueError(f"非法的 program：{program!r}")
    return p


def _safe_category(category: str) -> str:
    c = str(category or "").strip()
    if not _CAT_SAFE.match(c) or c in (".", "..") or "/" in c or "\\" in c:
        raise ValueError(f"非法的分类名：{category!r}")
    return c


# ---------------------------------------------------------------- 写

def _skeleton(day: str) -> list[str]:
    out = [day]
    for _, _, _, header in BUCKETS:
        out.append(header)
    return out


def _ensure_file(path: Path, day: str) -> list[str]:
    if path.exists():
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            text = ""
        lines = [ln.rstrip("\r") for ln in text.splitlines()]
        if lines and lines[0].strip() == day:
            return lines
        # 文件存在但头不对：补一个日期头
        return [day] + lines
    return _skeleton(day)


def _insert_line(lines: list[str], bucket: str, entry: str) -> list[str]:
    header = _HEADER_OF[bucket]
    try:
        at = lines.index(header)
    except ValueError:
        lines.extend([header, entry])
        return lines
    # 找到下一段的头（或文件尾），插在它前面
    end = len(lines)
    for i in range(at + 1, len(lines)):
        if lines[i] in _HEADER_OF.values():
            end = i
            break
    # 跳过段尾空行
    while end > at + 1 and not lines[end - 1].strip():
        end -= 1
    lines.insert(end, entry)
    return lines


def append(door: str, text: str, ts=None, *, program: str = "", category: str = "",
           source: str = INTERNAL) -> dict:
    """往某一天某一段里追加一条记忆；顺带更新索引。"""
    body = str(text or "").strip()
    if not body:
        raise ValueError("empty memory")
    body = re.sub(r"\s+", " ", body)
    moment = _parse_ts(ts)
    day = day_of(moment)
    bucket = bucket_of(moment)
    stamp = moment.strftime("%H:%M")

    if source == EXTERNAL:
        path = external_dir(program, category) / f"{day}.txt"
    else:
        path = day_path(door, day)

    lines = _ensure_file(path, day)
    entry = f"{stamp} {body}"
    if entry in lines:
        return {"ok": True, "duplicate": True, "path": str(path), "date": day, "bucket": bucket}
    # 同一天里说过的话只记一次（换了个时间点也算重复）
    want = _norm(body)
    for ln in lines:
        m = _LINE_RE.match(ln)
        if m and _norm(m.group(3)) == want:
            return {"ok": True, "duplicate": True, "path": str(path), "date": day, "bucket": bucket}
    lines = _insert_line(lines, bucket, entry)
    _atomic_write(path, "\n".join(lines) + "\n")
    note = {
        "ts": moment.strftime("%Y-%m-%dT%H:%M:%S"),
        "date": moment.strftime("%Y-%m-%d"),
        "bucket": bucket,
        "time": stamp,
        "door": door if source == INTERNAL else "",
        "source": source,
        "program": program,
        "category": category,
        "text": body,
        "path": str(path),
    }
    _index_append(note)
    return {"ok": True, "duplicate": False, "path": str(path), "date": day, "bucket": bucket}


def _index_append(note: dict) -> None:
    path = memory_root() / INTERNAL / INDEX_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(note, ensure_ascii=False) + "\n")


def raw_append(session: str, text: str, role: str, ts=None, who: str = "") -> Path:
    """原文写进 .raw/<门>/<天>.jsonl（ingest 的原料，不再叫 transcript）。"""
    door = door_of(session)
    moment = _parse_ts(ts)
    path = raw_path(door, day_of(moment))
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": moment.strftime("%Y-%m-%dT%H:%M:%S+08:00"), "role": role,
           "text": str(text or ""), "who": who or ""}
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


# ---------------------------------------------------------------- 读

def read_day(door: str, day: str) -> list[dict]:
    path = day_path(door, day)
    return _parse_day_file(path, door)


def _parse_day_file(path: Path, door: str = "") -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return []
    out: list[dict] = []
    bucket = ""
    date = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if not date and re.match(r"^\d{4}\.\d{2}\.\d{2}$", line):
            date = line
            continue
        if line in _HEADER_OF.values():
            bucket = next(n for n, _, _, h in BUCKETS if h == line)
            continue
        m = _LINE_RE.match(line)
        if not m or not bucket:
            continue
        out.append({
            "date": date, "bucket": bucket, "time": f"{int(m.group(1)):02d}:{m.group(2)}",
            "text": m.group(3).strip(), "door": door, "path": str(path),
        })
    return out


def index_records() -> list[dict]:
    path = memory_root() / INTERNAL / INDEX_NAME
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8-sig") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if isinstance(rec, dict) and rec.get("text"):
                    out.append(rec)
    except OSError:
        pass
    return out


def entries(session: str, days: int = 0) -> list[dict]:
    """这扇门能看见的记忆（按时间倒序）。days>0 只看最近 N 天。"""
    doors = set(visible_doors(session))
    cutoff = ""
    if days > 0:
        cutoff = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    out = []
    for rec in index_records():
        if rec.get("source", INTERNAL) != INTERNAL:
            continue
        if rec.get("door") not in doors:
            continue
        if cutoff and str(rec.get("date") or "") < cutoff:
            continue
        out.append(rec)
    out.sort(key=lambda r: (str(r.get("date") or ""), str(r.get("time") or "")), reverse=True)
    return out


def external_entries(days: int = 0) -> list[dict]:
    """外部门（QQ/B站/模组）写回来的记忆。只给主人自己的门读。"""
    cutoff = ""
    if days > 0:
        cutoff = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    out = []
    for rec in index_records():
        if rec.get("source", INTERNAL) == INTERNAL:
            continue
        if cutoff and str(rec.get("date") or "") < cutoff:
            continue
        out.append(rec)
    out.sort(key=lambda r: (str(r.get("date") or ""), str(r.get("time") or "")), reverse=True)
    return out


def days_present(door: str = "") -> list[str]:
    """有哪些天有记忆（给了门就只看那扇门）。"""
    if door:
        roots = [door_dir(door)]
    else:
        base = memory_root() / INTERNAL
        roots = [p for p in base.iterdir()
                 if p.is_dir() and not p.name.startswith(("_", "."))] if base.exists() else []
    out: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for p in root.glob("*.txt"):
            m = _DAY_RE.match(p.name)
            if m:
                out.add(f"{m.group(1)}.{m.group(2)}.{m.group(3)}")
    return sorted(out)


def summary_lines(door: str, limit: int = 6) -> list[str]:
    """压过的那几天留下的几行（`_summary/<门>/YYYY-MM.md` 里最新的几条）。"""
    root = memory_root() / "_summary" / _safe_door(door)
    if not root.exists():
        return []
    files = sorted([p for p in root.glob("*.md")], reverse=True)
    out: list[str] = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        rows = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("- ")]
        out = rows[-limit:] + out
        if len(out) >= limit:
            break
    return out[-limit:]


# ---------------------------------------------------------------- 统计 / 配置

DEFAULT_CONFIG = {
    "max_gb": 2.0,
    "compress_gb": 0.5,
    "keep_days": 60,
    "allow_zip_archive": True,
}


def config_path() -> Path:
    return Path(S.ENTITY) / "config" / "memory.json"


def config() -> dict:
    data = dict(DEFAULT_CONFIG)
    try:
        raw = json.loads(config_path().read_text(encoding="utf-8-sig"))
        if isinstance(raw, dict):
            for k in DEFAULT_CONFIG:
                if k in raw:
                    data[k] = raw[k]
    except Exception:
        pass
    return data


def set_config(max_gb: float | None = None, compress_gb: float | None = None,
               keep_days: int | None = None, allow_zip_archive: bool | None = None) -> dict:
    data = config()
    if max_gb is not None:
        data["max_gb"] = float(max_gb)
    if compress_gb is not None:
        data["compress_gb"] = float(compress_gb)
    if keep_days is not None:
        data["keep_days"] = int(keep_days)
    if allow_zip_archive is not None:
        data["allow_zip_archive"] = bool(allow_zip_archive)
    if data["max_gb"] <= 0 or data["compress_gb"] <= 0:
        raise ValueError("上限和压缩阈值都要大于 0")
    if data["compress_gb"] > data["max_gb"]:
        raise ValueError("压缩阈值不能大于最大上限")
    if data["keep_days"] < 1:
        raise ValueError("保留天数至少 1 天")
    config_path().parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(config_path(), json.dumps(data, ensure_ascii=False, indent=2))
    return data


def stats() -> dict:
    root = memory_root()
    total = 0
    files = 0
    oldest = ""
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            p = Path(dirpath) / name
            try:
                total += p.stat().st_size
            except OSError:
                continue
            files += 1
            m = _DAY_RE.match(name)
            if m:
                d = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
                if not oldest or d < oldest:
                    oldest = d
    cfg = config()
    return {
        "used_bytes": total,
        "used_mb": round(total / 1048576, 2),
        "files": files,
        "oldest": oldest,
        "days": len(days_present()),
        "max_gb": cfg["max_gb"],
        "compress_gb": cfg["compress_gb"],
        "keep_days": cfg["keep_days"],
    }


# ---------------------------------------------------------------- 迁移

def _looks_broken(text: str) -> bool:
    s = str(text or "")
    if not s:
        return True
    return s.count("?") >= max(3, len(s) // 2)


def migrate(apply: bool = True) -> dict:
    """把旧 layout（notes.jsonl + transcript-*.jsonl）搬到新 layout。可重跑。"""
    root = memory_root()
    legacy = root / "_legacy"
    report = {"notes": 0, "raw": 0, "skipped": 0, "broken": 0, "applied": apply}
    seen = {_norm(r.get("text")) for r in index_records()}

    for notes in sorted(root.rglob("notes.jsonl")):
        if legacy in notes.parents:
            continue
        door = _legacy_door(notes, root)
        for rec in _read_jsonl(notes):
            text = str(rec.get("text") or "").strip()
            if not text:
                continue
            if _looks_broken(text):
                report["broken"] += 1
                continue
            if _norm(text) in seen:
                report["skipped"] += 1
                continue
            seen.add(_norm(text))
            if apply:
                append(door, text, ts=rec.get("ts") or rec.get("date"), source=INTERNAL)
            report["notes"] += 1

    for tpath in sorted(root.rglob("transcript-*.jsonl")):
        if legacy in tpath.parents:
            continue
        door = _legacy_door(tpath, root)
        for rec in _read_jsonl(tpath):
            text = str(rec.get("text") or "").strip()
            if not text:
                continue
            if apply:
                raw_append(f"{_door_prefix(door)}:owner", text, str(rec.get("role") or "user"),
                           ts=rec.get("ts"), who=str(rec.get("who") or ""))
            report["raw"] += 1

    if apply:
        for p in sorted(root.iterdir()):
            if p.name in (INTERNAL, EXTERNAL, INDEX_NAME) or p.name.startswith("_"):
                continue
            target = legacy / p.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                try:
                    p.rename(target)
                except OSError:
                    pass
    return report


def _door_prefix(door: str) -> str:
    if door.startswith("qq_"):
        return "qq"
    if door.startswith("bili_"):
        return "bili"
    return "web"


def _legacy_door(path: Path, root: Path) -> str:
    """旧路径 → 门：memory/program_web/owner → web_owner。"""
    try:
        rel = path.relative_to(root).parts
    except ValueError:
        return "web_owner"
    parts = [p for p in rel if p not in ("memory",)]
    program = parts[0] if parts else "program_web"
    prefix = {"program_web": "web", "program_qq": "qq", "program_bilibili": "bili"}.get(program, "web")
    if len(parts) >= 3 and parts[1] in ("groups", "people", "others"):
        kind = {"groups": "group", "people": "friend", "others": "other"}[parts[1]]
        return _safe_door(f"{prefix}_{kind}_{parts[2]}")
    return _safe_door(f"{prefix}_owner")


def _read_jsonl(path: Path) -> Iterable[dict]:
    try:
        with open(path, encoding="utf-8-sig") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if isinstance(rec, dict):
                    yield rec
    except OSError:
        return


if __name__ == "__main__":
    import sys as _sys
    if "--migrate" in _sys.argv:
        print(json.dumps(migrate(apply="--dry" not in _sys.argv), ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"stats": stats(), "config": config()}, ensure_ascii=False, indent=2))
