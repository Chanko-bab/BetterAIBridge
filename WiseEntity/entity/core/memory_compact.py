# -*- coding: utf-8 -*-
"""记忆压缩：太旧的那几天压成几行，原文打包收起来。

规则（与主人在 m02499 / m02508 定下的）：

- 触发：整个记忆库超过 `compress_gb`（默认 0.5 G）才开始动手；
- 动手对象：日期比 `keep_days`（默认 60 天）更旧的 `.txt`；
- 一天一压：读那天的 `.txt` → 模型压成 2–4 行「我……」→ 追加到
  `_summary/<门>/YYYY-MM.md` → 原文塞进 `_archive/<门>/YYYY-MM.zip` → 删掉原 `.txt`；
- 幂等：`_summary/<门>/.done.json` 记已经压过哪些天，重跑不会重复压；
- 压完还超过 `max_gb`（默认 2 G），在保姆栏喊一次，别让它悄悄涨。
"""
from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

import httpx

from . import memory_store as store
from . import settings as S

def _prompt() -> str:
    """压缩提示词（关系词跟着配置走）。"""
    return f"""你在替一个叫「无名」的角色整理她自己的记忆。
下面是她某一天记下的事，每条都是「HH:MM 我做了什么」。
请把这一天压成 2–4 行，要求：
- 第一人称，主语还是「我」；提到对方写「{S.user_title()}」；
- 每行不超过 30 个字，不带时间、不带编号、不带引号；
- 只留以后还会想起的事（人和人的关系、做过的事、答应过的事），琐碎的一次性别留；
- 只输出 JSON：{{"lines": ["...", "..."]}}
"""

_last_notice_day = ""


def summary_dir(door: str) -> Path:
    return store.memory_root() / "_summary" / store._safe_door(door)


def archive_dir(door: str) -> Path:
    return store.memory_root() / "_archive" / store._safe_door(door)


def _done_path(door: str) -> Path:
    return summary_dir(door) / ".done.json"


def _done(door: str) -> dict:
    try:
        data = json.loads(_done_path(door).read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _mark_done(door: str, day: str) -> None:
    data = _done(door)
    data[day] = time.strftime("%Y-%m-%dT%H:%M:%S")
    p = _done_path(door)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _days(door: str) -> list[str]:
    return store.days_present(door)


def _older_than(day: str, cutoff: str) -> bool:
    return day < cutoff


def candidates(cfg: dict | None = None) -> list[tuple[str, str]]:
    """(门, 天) 里该压的那些，按时间从旧到新。"""
    cfg = cfg or store.config()
    days = max(1, int(cfg.get("keep_days") or 60))
    cutoff = time.strftime("%Y.%m.%d", time.localtime(time.time() - days * 86400))
    out: list[tuple[str, str]] = []
    base = store.memory_root() / store.INTERNAL
    if not base.exists():
        return out
    for door_dir in sorted(base.iterdir()):
        if not door_dir.is_dir() or door_dir.name.startswith((".", "_")):
            continue
        door = door_dir.name
        done = _done(door)
        for day in _days(door):
            if day >= cutoff or day in done:
                continue
            out.append((door, day))
    out.sort(key=lambda x: x[1])
    return out


def _summarise(lines: list[str]) -> list[str]:
    key = S.deepseek_key()
    if not key or not lines:
        return []
    body = "\n".join(lines[-120:])
    payload = {"model": "deepseek-chat",
               "messages": [{"role": "user", "content": f"{_prompt()}\n记忆：\n{body}"}],
               "temperature": 0.3, "max_tokens": 400, "stream": False}
    try:
        r = httpx.post(S.deepseek_base() + "/chat/completions",
                       headers={"Authorization": f"Bearer {key}",
                                "Content-Type": "application/json"},
                       json=payload, timeout=90.0)
        if r.status_code != 200:
            S.log(f"[compact] llm HTTP {r.status_code}: {r.text[:160]}")
            return []
        text = (r.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:  # noqa: BLE001
        S.log(f"[compact] llm failed: {e!r}")
        return []
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except Exception:
        return []
    rows = data.get("lines") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        s = str(row or "").strip().strip('"“”')
        s = s.lstrip("-·• ").strip()
        if 2 <= len(s) <= 60:
            out.append(s)
    return out[:4]


def _archive(door: str, day: str, path: Path, allow_zip: bool) -> bool:
    target = archive_dir(door) / f"{day[:7].replace('.', '-')}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        if allow_zip:
            with zipfile.ZipFile(target, "a", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(f"{door}/{day}.txt", path.read_text(encoding="utf-8"))
        else:
            gz = path.with_suffix(".txt.gz")
            import gzip
            gz.write_bytes(gzip.compress(path.read_bytes()))
    except Exception as e:  # noqa: BLE001
        S.log(f"[compact] archive failed {door}/{day}: {e!r}")
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


def _append_summary(door: str, day: str, lines: list[str]) -> None:
    month = day[:7].replace(".", "-")
    p = summary_dir(door) / f"{month}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    chunk = [f"## {day.replace('.', '-')}"]
    chunk.extend(f"- {ln}" for ln in lines)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write("\n".join(chunk) + "\n")


def _notice(text: str) -> None:
    global _last_notice_day
    today = time.strftime("%Y-%m-%d")
    if _last_notice_day == today:
        return
    _last_notice_day = today
    try:
        from . import chat_core
        chat_core.push_notice("web:owner", text)
    except Exception as e:  # noqa: BLE001
        S.log(f"[compact] notice failed: {e!r}")


def run(force: bool = False, limit: int = 40) -> dict:
    """压一批旧记忆。force=True 时忽略容量阈值（测试/手动用）。"""
    cfg = store.config()
    stats = store.stats()
    compress_bytes = float(cfg.get("compress_gb") or 0.5) * 1024 ** 3
    max_bytes = float(cfg.get("max_gb") or 2.0) * 1024 ** 3
    if not force and stats["used_bytes"] < compress_bytes:
        return {"skipped": "under threshold", "used_mb": stats["used_mb"],
                "compress_gb": cfg.get("compress_gb")}
    todo = candidates(cfg)[:max(1, limit)]
    if not todo:
        if stats["used_bytes"] > max_bytes:
            _notice("记忆库已经超过上限了，旧的那些天都压完了，"
                    "要不要把「保留天数」调小一点，或者把上限调大？")
            return {"skipped": "nothing old", "used_mb": stats["used_mb"]}
        return {"skipped": "nothing old", "used_mb": stats["used_mb"]}

    allow_zip = bool(cfg.get("allow_zip_archive", True))
    done_days = 0
    failed = 0
    for door, day in todo:
        path = store.day_path(door, day)
        rows = store.read_day(door, day)
        if not rows:
            _mark_done(door, day)
            continue
        compressed = _summarise([r["text"] for r in rows])
        if not compressed:
            failed += 1
            continue
        _append_summary(door, day, compressed)
        if not _archive(door, day, path, allow_zip):
            failed += 1
            continue
        _mark_done(door, day)
        done_days += 1

    after = store.stats()
    S.log(f"[compact] 压了 {done_days} 天，失败 {failed}，现在 {after['used_mb']} MB")
    if after["used_bytes"] > max_bytes:
        _notice(f"记忆库到 {after['used_mb']:.0f} MB 了，比上限还大；"
                "旧的那几天已经压过，要不要把保留天数再调小一点？")
    return {"compressed_days": done_days, "failed": failed,
            "used_mb": after["used_mb"], "candidates": len(todo)}
