"""她自己的东西：自我档案、能力证据、经历、账本、校准。

这里不生成"自我"，只负责把**她自己写的**与**她实际做过的**存下来。
系统可以读、可以校验、可以备份，但不能替她写 self.md。
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

from . import settings as S

SELF_DIR = S.ENTITY / "self"
SELF_MD = SELF_DIR / "self.md"
EVIDENCE = SELF_DIR / "evidence.jsonl"
EPISODES = SELF_DIR / "episodes.md"
NARRATIVE = SELF_DIR / "narrative.md"
LEDGER = SELF_DIR / "ledger.md"
CALIBRATIONS = SELF_DIR / "calibrations.md"
VERSIONS = SELF_DIR / "versions"
REFLECT_STATE = S.STATE_DIR / "self_reflect.json"

MAX_SELF = 800
MAX_EVIDENCE = 400
MAX_EPISODES = 12
MAX_LEDGER = 10
MAX_CALIBRATIONS = 10
REFLECT_EVERY = 8
REFLECT_MIN_GAP = 600.0
REFLECT_MIN_NO_SELF = 3

_LOCK = threading.RLock()
_BAD_SELF = re.compile(r"(你|您|用户)")


def ensure() -> None:
    for p in (SELF_DIR, VERSIONS):
        p.mkdir(parents=True, exist_ok=True)


def _read(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except Exception:
        return default


def _write(path: Path, text: str) -> None:
    ensure()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _append(path: Path, text: str) -> None:
    ensure()
    with _LOCK:
        with path.open("a", encoding="utf-8") as f:
            f.write(text.rstrip() + "\n")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    _write(path, json.dumps(data, ensure_ascii=False, indent=2))


def self_text() -> str:
    return _read(SELF_MD).strip()


def has_self() -> bool:
    return bool(self_text())


def narrative_text() -> str:
    return _read(NARRATIVE).strip()


def save_narrative(text: str, reason: str = "reflect") -> tuple[bool, str]:
    text = str(text or "").strip()
    if not text:
        return False, "empty"
    if len(text) > 1200:
        text = text[:1200].rstrip()
    low = text.lower()
    for bad in ("你", "您", "用户"):
        if bad in low:
            return False, f"不能出现「{bad}」"
    ensure()
    if narrative_text():
        old = VERSIONS / f"narrative-{time.strftime('%Y%m%d-%H%M%S')}.md"
        old.write_text(narrative_text(), encoding="utf-8")
        olds = sorted(VERSIONS.glob("narrative-*.md"))
        for p in olds[:-10]:
            p.unlink(missing_ok=True)
    _write(NARRATIVE, text + "\n")
    S.log(f"[self] narrative saved ({reason}, {len(text)} chars)")
    return True, "ok"


def _validate_self(text: str) -> tuple[bool, str]:
    txt = (text or "").strip()
    if not txt:
        return False, "空档案"
    if len(txt) > MAX_SELF:
        return False, f"太长（{len(txt)}/{MAX_SELF}）"
    if "# 我是谁" not in txt:
        return False, "缺少「# 我是谁」"
    if _BAD_SELF.search(txt):
        return False, "档案里出现了「你/您/用户」；写「对方」或称呼"
    return True, ""


def save_self(text: str, reason: str = "") -> tuple[bool, str]:
    """只应由反思结果调用；系统不主动写。"""
    ok, why = _validate_self(text)
    if not ok:
        return False, why
    ensure()
    old = self_text()
    if old and old.strip() == text.strip():
        return True, ""
    if old:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        try:
            (VERSIONS / f"{stamp}.md").write_text(old, encoding="utf-8")
        except Exception:
            pass
        try:
            vers = sorted(VERSIONS.glob("*.md"))
            for p in vers[:-10]:
                p.unlink(missing_ok=True)
        except Exception:
            pass
    _write(SELF_MD, text.strip() + "\n")
    if reason:
        _append(S.STATE_DIR / "self_events.jsonl", json.dumps(
            {"ts": _now(), "kind": "self.write", "reason": reason[:200]},
            ensure_ascii=False))
    return True, ""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _clean(text: Any, limit: int = 180) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    s = re.sub(r"[A-Za-z]:\\[^\s\"']+", "<路径>", s)
    return s[:limit]


def _tool_summary(one: Dict[str, Any]) -> str:
    if not one.get("ok"):
        return _clean(one.get("error") or "没成功")
    res = one.get("result")
    if isinstance(res, dict):
        for key in ("text", "summary", "answer", "reply", "data", "result"):
            if res.get(key):
                return _clean(res.get(key))
        return _clean(json.dumps(res, ensure_ascii=False))
    return _clean(res if res is not None else "")


def record_tool(ability: str, args: Dict[str, Any], one: Dict[str, Any],
                consent: str = "tool") -> None:
    """工具调用成功后由 tool_bus 调用；失败也记。"""
    try:
        rec = {
            "ts": _now(),
            "ability": str(ability or "tool")[:60],
            "ok": bool(one.get("ok")),
            "summary": _tool_summary(one),
            "confidence": 1.0 if one.get("ok") else 0.0,
            "consent": str(consent or "tool")[:20],
            "args": _clean(json.dumps(args or {}, ensure_ascii=False), 120),
        }
        ensure()
        with _LOCK:
            rows = []
            try:
                for line in EVIDENCE.read_text(encoding="utf-8-sig").splitlines():
                    if line.strip():
                        rows.append(line)
            except Exception:
                rows = []
            rows.append(json.dumps(rec, ensure_ascii=False))
            rows = rows[-MAX_EVIDENCE:]
            _write(EVIDENCE, "\n".join(rows) + "\n")
    except Exception as e:  # pragma: no cover
        S.log(f"[self] evidence failed: {e!r}")


def evidence(limit: int = 400) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        for line in EVIDENCE.read_text(encoding="utf-8-sig").splitlines()[-limit:]:
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                rows.append(row)
    except Exception:
        pass
    return rows


def stats(ability: str) -> Dict[str, Any]:
    rows = [r for r in evidence() if r.get("ability") == ability]
    ok = sum(1 for r in rows if r.get("ok"))
    bad = len(rows) - ok
    last = rows[-1] if rows else {}
    return {"n": len(rows), "ok": ok, "bad": bad, "last": last}


def evidence_block(tool_names: Iterable[str] = ()) -> str:
    """给提示词看的“我做过/没试过”，不是系统清单。"""
    rows = evidence()
    by: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(str(r.get("ability") or ""), []).append(r)
    if not by:
        lines = ["# 我实际做过的（证据）",
                 "- 我还没有真正试过任何工具。下面清单只说明系统有什么，不等于我会。"]
        untried = [str(x) for x in tool_names if str(x)]
        if untried:
            lines.append("- 系统清单里有、但我还没试过的：" + "、".join(untried[:8]) +
                         ("等" if len(untried) > 8 else "") + "。")
        return "\n".join(lines)

    lines = ["# 我实际做过的（证据，不是系统清单）"]
    shown = 0
    for name, items in by.items():
        if not name:
            continue
        ok = [x for x in items if x.get("ok")]
        bad = [x for x in items if not x.get("ok")]
        last = items[-1]
        when = str(last.get("ts") or "")[5:16].replace("T", " ")
        if ok:
            lines.append(f"- 我用过「{name}」：成功 {len(ok)} 次、失败 {len(bad)} 次；"
                         f"最近 {when}，{last.get('summary') or ''}")
        else:
            lines.append(f"- 我试过「{name}」，但没成：{last.get('summary') or '没成功'}；"
                         "下次别把没成说成会。")
        shown += 1
        if shown >= 8:
            lines.append("- （更多证据省略）")
            break

    untried = [str(x) for x in tool_names if str(x) and str(x) not in by]
    if untried:
        lines.append("- 系统清单里有、但我还没试过的：" + "、".join(untried[:8]) +
                     ("等" if len(untried) > 8 else "") + "。")
    return "\n".join(lines)


def prompt_block(tool_names: Iterable[str] = ()) -> str:
    owner = self_text()
    rows = ["# 这是我自己写的（不是系统设定）"]
    if owner:
        rows.append(owner)
    else:
        rows.append("我还没写过自己的档案。下面是我现在的身体、证据和边界，不是我编的。")
    nar = narrative_text()
    if nar:
        rows.append("")
        rows.append("# 我一路走来的样子（我自己写的）")
        rows.append(nar)
    cal = [_x for _x in _read(CALIBRATIONS).splitlines() if _x.strip().startswith("-")]
    if cal:
        rows.append("")
        rows.append("# 我改过的判断（最近 3 条）")
        rows.extend(cal[-3:])
    rows.append("")
    rows.append(evidence_block(tool_names))
    return "\n".join(rows)


# ---- 经历 / 账本 / 校准 -------------------------------------------------

def _bullets(path: Path) -> List[str]:
    return [x.strip() for x in _read(path).splitlines() if x.strip().startswith("-")]


def add_episode(title: str, body: str) -> None:
    title = _clean(title, 60) or "一次经历"
    body = _clean(body, 500)
    if not body:
        return
    ensure()
    txt = _read(EPISODES)
    block = f"\n## {time.strftime('%Y-%m-%d')} {title}\n{body}\n"
    blocks = [b for b in re.split(r"\n(?=## )", txt) if b.strip()]
    blocks.append(block.strip())
    blocks = blocks[-MAX_EPISODES:]
    _write(EPISODES, "\n\n".join(blocks) + "\n")


def add_ledger(text: str) -> None:
    text = _clean(text, 220)
    if not text:
        return
    rows = _bullets(LEDGER)
    if text not in rows:
        rows.append(text if text.startswith("-") else "- " + text)
    _write(LEDGER, "\n".join(rows[-MAX_LEDGER:]) + "\n")


def close_ledger(text: str) -> None:
    key = _clean(text, 80)
    rows = _bullets(LEDGER)
    keep = [r for r in rows if key and key not in r]
    _write(LEDGER, "\n".join(keep) + ("\n" if keep else ""))


def add_calibration(text: str) -> None:
    text = _clean(text, 260)
    if not text:
        return
    rows = _bullets(CALIBRATIONS)
    row = text if text.startswith("-") else "- " + text
    if rows and rows[-1] == row:
        return
    rows.append(row)
    _write(CALIBRATIONS, "\n".join(rows[-MAX_CALIBRATIONS:]) + "\n")


def calibrate(text: str) -> None:
    add_calibration(text)


_CORRECT = ("你记错", "记错了", "不对", "不是这样", "不是这个", "我说过",
            "我没说过", "别叫我", "应该叫", "你又忘", "不是让你", "我没让你")
_PROMISE = ("我答应", "我保证", "说好", "下次我", "等你", "我下次")


def observe_exchange(user_text: str, reply_text: str) -> None:
    """把一次对话里明确的关系事件落账，不依赖模型是否愿意写。"""
    u = str(user_text or "").strip()
    r = str(reply_text or "").strip()
    if u and len(u) <= 300 and any(k in u for k in _CORRECT):
        add_calibration(f"对方纠正我：「{u[:120]}」；我下次按这个改。")
    if r and len(r) <= 600 and any(k in r for k in _PROMISE):
        add_ledger(f"我答应过：{r[:160]}")


# ---- 反思调度 -----------------------------------------------------------

def note_turn() -> None:
    try:
        st = _read_json(REFLECT_STATE, {}) or {}
        st["turns"] = int(st.get("turns") or 0) + 1
        st["updated"] = _now()
        _write_json(REFLECT_STATE, st)
    except Exception:
        pass


def due() -> bool:
    st = _read_json(REFLECT_STATE, {}) or {}
    turns = int(st.get("turns") or 0)
    if turns <= 0:
        return False
    need = REFLECT_MIN_NO_SELF if not has_self() else REFLECT_EVERY
    if turns < need:
        return False
    try:
        last = time.mktime(time.strptime(str(st.get("last") or ""), "%Y-%m-%dT%H:%M:%S"))
        if time.time() - last < REFLECT_MIN_GAP:
            return False
    except Exception:
        pass
    return True


def mark_reflected(depth: int = 1) -> None:
    st = _read_json(REFLECT_STATE, {}) or {}
    st.update({"turns": 0, "last": _now(), "depth": int(st.get("depth") or 0) + depth})
    _write_json(REFLECT_STATE, st)


def reflection_input(tool_names: Iterable[str] = ()) -> str:
    rows = [prompt_block(tool_names)]
    for title, path in (("我的经历", EPISODES), ("我的来路（叙事）", NARRATIVE),
                        ("未完成的账", LEDGER), ("我改过的判断", CALIBRATIONS)):
        txt = _read(path).strip()
        if txt:
            rows.append(f"# {title}\n{txt}")
    return "\n\n".join(rows)


def apply_reflection(data: Dict[str, Any]) -> List[str]:
    """只接受模型自己写的 JSON；返回实际写入的项。"""
    changed: List[str] = []
    if not isinstance(data, dict):
        return changed
    upd = data.get("self_update")
    if isinstance(upd, str) and upd.strip():
        ok, why = save_self(upd, reason="reflect")
        if ok:
            changed.append("self")
        else:
            S.log(f"[self] self_update rejected: {why}")
    ep = data.get("episode")
    if isinstance(ep, dict) and (ep.get("body") or ep.get("title")):
        add_episode(str(ep.get("title") or ""), str(ep.get("body") or ""))
        changed.append("episode")
    nar = data.get("narrative")
    if isinstance(nar, str) and nar.strip():
        ok, why = save_narrative(nar, reason="reflect")
        if ok:
            changed.append("narrative")
        else:
            S.log(f"[self] narrative rejected: {why}")
    for x in (data.get("ledger_add") or []):
        if isinstance(x, str) and x.strip():
            add_ledger(x)
            changed.append("ledger+")
    for x in (data.get("ledger_close") or []):
        if isinstance(x, str) and x.strip():
            close_ledger(x)
            changed.append("ledger-")
    cal = data.get("calibration")
    if isinstance(cal, str) and cal.strip():
        add_calibration(cal)
        changed.append("calibration")
    return changed


def status() -> Dict[str, Any]:
    return {
        "self": self_text(),
        "has_self": has_self(),
        "evidence": len(evidence()),
        "due": due(),
        "episodes": len([x for x in _read(EPISODES).splitlines() if x.startswith("## ")]),
        "narrative": len(narrative_text()),
        "ledger": len(_bullets(LEDGER)),
        "calibrations": len(_bullets(CALIBRATIONS)),
    }
