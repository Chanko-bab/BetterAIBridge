# -*- coding: utf-8 -*-
"""记忆盒：给内核各处用的门面，底下换成 memory_store 的「一天一个 .txt」。

对外还叫老名字（`select` / `fragment` / `add_note` / `counts` / `session_shard`），
但内容全部落在新格式里：

```
entity\\memory\\
  internal\\<门>\\2026.10.31.txt        提炼过的记忆（第一人称「我」）
  internal\\.raw\\<门>\\2026.10.31.jsonl 原文
  external\\<program>\\<分类>\\2026.10.31.txt  模组要求记的
```

门：`web_owner` / `qq_owner` / `qq_group_<号>` / `qq_friend_<号>` /
`bili_owner` / `bili_other_<mid>`。
隐私：每扇门只看自己那本；跨门检索只给主人（`search_all`）。
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import time
from pathlib import Path

from . import memory_store as store
from . import settings as S

_CJK = re.compile(r"[\u4e00-\u9fff]+")
_WORD = re.compile(r"[a-zA-Z0-9_]{2,}")
_cache: dict[str, tuple[float, list[dict]]] = {}

PROGRAMS = ("program_qq", "program_bilibili", "program_web")

_PREFIX = {"program_qq": "qq", "program_bilibili": "bili", "program_web": "web"}
_BACK = {"qq": "program_qq", "bili": "program_bilibili", "web": "program_web"}

_PROGRAM_RE = re.compile(r"[^a-z0-9_]+")


def program_key(program: str) -> str:
    """把任意 program 名洗成 `program_<小写字母数字下划线>`。

    以前这里是个白名单（只有 qq/bilibili/web），第三个以后装上的模组写记忆时会被
    悄悄塞进 `program_qq` 的抽屉——M 就是第一个受害者。现在改成"洗干净就用"，
    洗不出东西才回落到 program_qq。
    """
    raw = str(program or "").strip().lower()
    safe = _PROGRAM_RE.sub("_", raw)
    if safe.startswith("program_"):
        safe = safe[len("program_"):]
    safe = safe.strip("_")[:40]
    return "program_" + safe if safe else "program_qq"


# ---------------------------------------------------------------- 小工具

def _tokens(text: str) -> set[str]:
    out: set[str] = set()
    for run in _CJK.findall(text or ""):
        if len(run) == 1:
            out.add(run)
        for i in range(len(run) - 1):
            out.add(run[i:i + 2])
    for w in _WORD.findall(text or ""):
        out.add(w.lower())
    return out


def mem_root() -> Path:
    return store.memory_root()


def program_dir(program: str) -> Path:
    """老路径（只给还按 program 找东西的地方用）；新东西走 external/。"""
    return mem_root() / str(program or "program_web")


def self_path() -> Path:
    return mem_root() / "notes.jsonl"


def program_file(program: str, name: str) -> Path:
    return program_dir(program) / name


# ---------------------------------------------------------------- 门 → 会话

def door_for(program: str, scope: str = "owner", group: str | None = None,
             kind_key: str | None = None) -> str:
    prefix = _PREFIX.get(program) or program_key(program)[len("program_"):]
    scope = (scope or "owner").lower()
    if scope in ("group", "groups"):
        if not group:
            raise ValueError("group id required")
        return store._safe_door(f"{prefix}_group_{group}")
    if scope in ("friend", "other"):
        if not kind_key:
            raise ValueError("friend/other id required")
        return store._safe_door(f"{prefix}_{scope}_{kind_key}")
    return store._safe_door(f"{prefix}_owner")


def door_parts(door: str) -> tuple[str, str, str]:
    """门 → (program, kind, key)。"""
    for prefix, program in _BACK.items():
        if not door.startswith(prefix + "_"):
            continue
        rest = door[len(prefix) + 1:]
        if rest == "owner":
            return program, "owner", "owner"
        for kind in ("group", "friend", "other"):
            if rest.startswith(kind + "_"):
                return program, kind, rest[len(kind) + 1:]
    return "program_web", "owner", "owner"


def _kind_of(door: str) -> str:
    return door_parts(door)[1]


def session_shard(session: str) -> tuple[str, str, str, Path]:
    """会话 → (program, kind, key, 今天那份原文 .jsonl)。"""
    door = store.door_of(session)
    program, kind, key = door_parts(door)
    return program, kind, key, store.raw_path(door, store.day_of())


def _visible(session: str) -> list[tuple[str, str, str, Path]]:
    """这扇门能看见哪些抽屉（现在是"只有自己那一本"）。"""
    out = []
    for door in store.visible_doors(session):
        program, kind, key = door_parts(door)
        out.append((program, kind, key, store.door_dir(door)))
    return out


# ---------------------------------------------------------------- 读

def _read(path: Path) -> list[dict]:
    """读一份记忆：目录→所有 .txt；文件→.txt 或 .jsonl，都认。"""
    key = str(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    hit = _cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    rows: list[dict] = []
    try:
        if path.is_dir():
            for f in sorted(path.glob("*.txt")):
                rows.extend(store._parse_day_file(f, path.name))
        elif path.suffix.lower() == ".txt":
            rows.extend(store._parse_day_file(path, path.parent.name))
        else:
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
                        rows.append(rec)
    except OSError:
        return []
    _cache[key] = (mtime, rows)
    return rows


def note_date(rec: dict) -> str:
    d = str(rec.get("date") or "").strip()
    if d:
        return d
    ts = str(rec.get("ts") or "")
    return ts[:10] if len(ts) >= 10 else ""


def counts() -> dict:
    """老形状的计数（设置/详情页还在用）。"""
    res: dict = {"self": 0, "programs": {}}
    per_door: dict[str, int] = {}
    for rec in store.index_records():
        if str(rec.get("source") or "internal") != "internal":
            continue
        door = str(rec.get("door") or "")
        per_door[door] = per_door.get(door, 0) + 1
    for door, n in per_door.items():
        program, kind, key = door_parts(door)
        bucket = res["programs"].setdefault(
            program, {"owner": 0, "people": {}, "groups": {}, "others": {}})
        if kind == "owner":
            bucket["owner"] += n
            res["self"] += n if program == "program_web" else 0
        elif kind == "group":
            bucket["groups"][key] = bucket["groups"].get(key, 0) + n
        elif kind == "other":
            bucket["others"][key] = bucket["others"].get(key, 0) + n
        else:
            bucket["people"][key] = bucket["people"].get(key, 0) + n
    return res


def total_notes() -> int:
    c = counts()
    total = c["self"]
    for b in c["programs"].values():
        total += b["owner"] + sum(b["people"].values()) + sum(b["groups"].values()) + sum(b["others"].values())
    return total


# ---------------------------------------------------------------- 检索

def _weight(kind: str) -> float:
    return {"owner": 0.55, "group": 0.30, "friend": 0.25, "other": 0.25}.get(kind, 0.20)


def _age_days(rec: dict) -> float:
    ts = str(rec.get("ts") or rec.get("date") or "")
    for fmt, cut in (("%Y-%m-%dT%H:%M:%S%z", 25), ("%Y-%m-%dT%H:%M:%S", 19),
                     ("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d", 10)):
        try:
            t = time.mktime(_dt.datetime.strptime(ts[:cut], fmt).timetuple())
            return max(0.0, (time.time() - t) / 86400)
        except Exception:
            continue
    return 30.0


def _score(query_tokens: set[str], rec: dict) -> float:
    nt = _tokens(str(rec.get("text") or ""))
    if not nt:
        return 0.0
    overlap = len(query_tokens & nt) / (len(query_tokens) or 1)
    weight = _weight(_kind_of(str(rec.get("door") or "")))
    recency = max(0.0, 0.2 * (1 - _age_days(rec) / 20.0))
    return overlap + weight + recency


def select(query: str, session: str, limit: int = 12, max_chars: int = 900) -> list[dict]:
    q = _tokens(query)
    owner_view = store.is_owner_door(store.door_of(session))
    rows = store.entries(session)
    if owner_view:
        # 主人自己的门能看到 QQ/B站/模组写回来的记忆；群/好友门仍然只看自己那本。
        rows = rows + store.external_entries()
    scored: list[tuple[float, dict]] = []
    for rec in rows:
        external = rec.get("source", store.INTERNAL) != store.INTERNAL
        if q:
            s = _score(q, rec)
            if external:
                s = max(s, 0.55)
        else:
            s = _weight(_kind_of(str(rec.get("door") or "")))
            if external:
                s = max(s, 0.55)
        if q and s < 0.25:
            continue
        item = dict(rec)
        item["_where"] = str(rec.get("door") or rec.get("category") or "")
        item["_program"] = door_parts(str(rec.get("door") or ""))[0] or str(rec.get("program") or "")
        if external:
            item["_external"] = True
            item["_where"] = str(rec.get("category") or rec.get("program") or "别处")
        scored.append((s, item))
    scored.sort(key=lambda x: (x[0], str(x[1].get("date") or "")), reverse=True)
    picked: list[dict] = []
    used = 0
    seen: set[str] = set()
    for _, rec in scored:
        text = str(rec.get("text") or "").strip()
        if not text or text in seen:
            continue
        if used + len(text) > max_chars and picked:
            continue
        seen.add(text)
        picked.append(rec)
        used += len(text)
        if len(picked) >= limit:
            break
    return picked


def search_all(query: str, limit: int = 10) -> list[dict]:
    """跨门检索（只给主人看）。"""
    q = _tokens(query)
    scored: list[tuple[float, dict]] = []
    for rec in store.index_records():
        nt = _tokens(str(rec.get("text") or ""))
        if not nt:
            continue
        overlap = len(q & nt) / (len(q) or 1)
        item = dict(rec)
        item["_where"] = str(rec.get("door") or rec.get("category") or "外部")
        item["_program"] = str(rec.get("program") or "")
        scored.append((overlap, item))
    scored.sort(key=lambda x: (x[0], str(x[1].get("date") or "")), reverse=True)
    out: list[dict] = []
    seen: set[str] = set()
    for score, rec in scored:
        if q and score <= 0:
            continue
        text = str(rec.get("text") or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(rec)
        if len(out) >= limit:
            break
    return out


def fragment(query: str, session: str) -> str:
    """喂给提示词的记忆块：按「日期 + 时段」分组，第一人称原样保留。"""
    owner_view = store.is_owner_door(store.door_of(session))
    notes = select(query, session, limit=40 if owner_view else 12,
                   max_chars=4000 if owner_view else 900)
    if not notes:
        return ""
    groups: dict[tuple[str, str], list[str]] = {}
    order: list[tuple[str, str]] = []
    for n in notes:
        date = str(n.get("date") or "")
        bucket = str(n.get("bucket") or "")
        key = (date, bucket)
        if key not in groups:
            groups[key] = []
            order.append(key)
        stamp = str(n.get("time") or "")
        text = str(n.get("text") or "").strip()
        if n.get("_external"):
            where = str(n.get("_where") or "别处")
            text = f"【{where}】{text}"
        groups[key].append(f"- {stamp} {text}".strip() if stamp else f"- {text}")
    lines = ["# 你记得的事"]
    for key in order:
        date, bucket = key
        lines.append(f"## {date} {bucket}".strip())
        lines.extend(groups[key])
    try:
        early = []
        for door in store.visible_doors(session):
            for line in store.summary_lines(door, 4):
                if line not in early:
                    early.append(line)
        early = early[-4:]
    except Exception:
        early = []
    if early:
        lines.append("## 更早的事（压过的）")
        lines.extend(early)
    return "\n".join(lines)


def diary(days: int = 7, session: str = "qq:owner") -> list[dict]:
    rows = store.entries(session, days=max(1, days))
    buckets: dict[str, list[dict]] = {}
    for rec in rows:
        date = str(rec.get("date") or "")
        if not date:
            continue
        buckets.setdefault(date, []).append({
            "text": str(rec.get("text") or ""),
            "time": str(rec.get("time") or ""),
            "bucket": str(rec.get("bucket") or ""),
            "door": str(rec.get("door") or ""),
        })
    return [{"date": d, "items": buckets[d]} for d in sorted(buckets, reverse=True)]


# ---------------------------------------------------------------- 写

def add_note(text: str, scope: str = "owner", group: str | None = None,
             kind_key: str | None = None, program: str = "program_qq",
             category: str = "", target: str = "internal", ts=None) -> dict:
    """记一条。target=external 时落在 external/<program>/<分类>/。"""
    body = (text or "").strip()
    if not body:
        raise ValueError("empty note")
    program = program_key(program)
    if target == "external":
        res = store.append(store.OWNER_DOOR, body, ts=ts, program=program,
                           category=category or "笔记", source=store.EXTERNAL)
        return {"ok": True, **res, "where": f"external/{program}/{category or '笔记'}"}
    door = door_for(program, scope, group, kind_key)
    res = store.append(door, body, ts=ts)
    res["count"] = total_notes()
    res["door"] = door
    return {"ok": True, **res}


# ---------------------------------------------------------------- 老接口兜底

def append_jsonl(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def recent_jsonl(path: Path, n: int = 10) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-n:]:
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def shard_paths() -> list[tuple[str, str, str, Path]]:
    """还按老形状给出所有 internal 抽屉（设置页/诊断用）。"""
    out = []
    base = mem_root() / store.INTERNAL
    if not base.exists():
        return out
    for door_dir in sorted(base.iterdir()):
        if not door_dir.is_dir() or door_dir.name.startswith(".") or door_dir.name == "_legacy":
            continue
        program, kind, key = door_parts(door_dir.name)
        out.append((program, kind, key, door_dir))
    return out
