"""保姆：开局分析 + 驻守模组端口。

两件事：
1. 开局分析（analyze）：把使用者填的昵称 / 称呼 / 性格，交给模型变成一份
   能直接用的人格草稿、几个称呼候选、一句开场白。只输出那几样，别的不要。
2. 驻守（watch_loop）：每 60 秒看一遍 registry 里"已启用"的模组，探它**真正在听**的
   端口（registry 的 `runtime_port`；没有才退回清单里的 `ports`）。连续两次不通记为
   degraded，写日志；不自动重启（自动重启由启动器负责，内核只报告事实）。

设计口径：
- 保姆不写她的记忆，也不改她的人格正文（人格由开场向导写，之后归主人）。
- 分析失败一律返回 {"ok": False, "error": ...}，不抛给界面。
"""
from __future__ import annotations

import asyncio
import json
import re
import socket
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx

from . import settings as S

STATE_PATH: Path = S.ENTITY / "state" / "nanny.json"
LOG_PATH: Path = S.ENTITY / "state" / "nanny_log.jsonl"
BUNDLE: Path = S.BUNDLE
WATCH_EVERY = 60.0
SESSION = "web:owner"
LOG_MAX_BYTES = 400_000
LOG_KEEP_LINES = 400


def log_event(kind: str, text: str) -> None:
    """保姆自己的独立日志：一条一行 JSON，失败了也不影响主流程。"""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": time.time(), "kind": str(kind or "note")[:24],
               "text": str(text or "").strip()[:2000]}
        if not rec["text"]:
            return
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        try:
            if LOG_PATH.stat().st_size > LOG_MAX_BYTES:
                lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
                LOG_PATH.write_text("\n".join(lines[-LOG_KEEP_LINES:]) + "\n", encoding="utf-8")
        except Exception:
            pass
    except Exception as e:  # noqa: BLE001
        S.log(f"[nanny] log failed: {e!r}")


def log_tail(limit: int = 120) -> List[Dict[str, Any]]:
    """读最近的保姆日志；坏行跳过，不让一条脏数据拖垮窗口。"""
    limit = max(1, min(500, int(limit or 120)))
    try:
        lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if isinstance(rec, dict) and str(rec.get("text") or "").strip():
            out.append(rec)
    return out


def panel(limit: int = 120) -> Dict[str, Any]:
    """给启动器的「保姆的小屋」：状态 + 自己的日志。"""
    data = status()
    data["log"] = log_tail(limit)
    return data


def _notice(text: str) -> None:
    """写一条保姆提醒（在聊天窗右侧那一栏显示）；落盘失败也不能影响看门。"""
    log_event("notice", text)
    try:
        from . import chat_core

        chat_core.push_notice(SESSION, text)
    except Exception as e:  # noqa: BLE001
        S.log(f"[nanny] notice failed: {e!r}")
FAILS_TO_DEGRADED = 2

_state: Dict[str, Any] = {}
_lock = asyncio.Lock()

PROMPT_BASE = """你在帮一个桌面 AI 程序做"开局建档"。程序是空框架：还没有名字、没有人格、没有记忆。
你的任务只有一件事：把使用者给的少量信息，变成能直接用的成品。要求：

- 只输出 JSON，不要解释，不要 markdown 代码块。
- 中文；不要出现"AI""模型""提示词""这是一个角色"这类词。
- 不要编造使用者的隐私信息；没给的不要猜。
"""


# ---------------------------------------------------------------- 状态文件

def _load() -> Dict[str, Any]:
    global _state
    if _state:
        return _state
    try:
        _state = json.loads(STATE_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        _state = {}
    _state.setdefault("modules", {})
    _state.setdefault("last_check", 0.0)
    _state.setdefault("checks", 0)
    return _state


def _save() -> None:
    st = _load()
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(STATE_PATH)
    except Exception as e:  # noqa: BLE001
        S.log(f"[nanny] save failed: {e}")


# ---------------------------------------------------------------- 模型调用

def _extract_json(text: str) -> Dict[str, Any]:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", t)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return {}
    return {}


async def _chat(messages: List[Dict[str, str]], temperature: float = 0.7,
                max_tokens: int = 900) -> str:
    key = S.deepseek_key()
    if not key:
        raise RuntimeError(f"no api key（{S.ENTITY / 'config' / 'llm.json'}）")
    base = S.deepseek_base().rstrip("/")
    model = S.llm_cfg().get("model") or "deepseek-chat"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as cli:
        r = await cli.post(f"{base}/chat/completions",
                           headers={"Authorization": f"Bearer {key}"},
                           json=payload)
        r.raise_for_status()
        data = r.json()
    return (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""


def _fmt(payload: Dict[str, Any]) -> str:
    lines = []
    for k, v in (payload or {}).items():
        if v in (None, "", []):
            continue
        if isinstance(v, list):
            v = "；".join(str(x) for x in v)
        lines.append(f"- {k}: {v}")
    return "\n".join(lines)


TITLE_TASK = """使用者信息：
__INFO__

先看 relation（使用者自报的关系），称呼要合这段关系：
- 主人：可以有主从感（主人、老板、先生），但别油腻；
- 朋友 / 搭档：平辈、随口叫的绰号，不要"主人"；
- 家人 / 恋人：亲昵一点；
- 老师：带点敬但不用客套到底。
再给出 4 个候选（每个 1–4 个汉字，日常口语，不要"用户"）。挑一个最自然的。
输出 JSON：{"titles": ["…","…","…","…"], "pick": "…", "why": "一句话理由"}
"""

PERSONA_TASK = """使用者信息：
__INFO__

请写一份简短的人格（Markdown，200–400 字），结构固定为：
# <她的名字>
## 身份
## 说话方式
## 脾气
## 和<称呼>的关系
## 边界

要求：
- 用第三人称描述她、用"你"称呼她本人（"你是…"），不要写成角色卡口吻。
- 性格必须落在字句上（句子长短、会不会顶嘴、遇到不懂怎么办），不要形容词堆砌。
- 边界写死三条：不装不编、不主动报模型/参数、不替使用者做危险决定。
输出 JSON：{"persona": "…markdown…", "opening": "她第一次开口说的一句话（≤20 字）"}
"""


async def analyze(kind: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """开局分析。kind: title | persona"""
    info = _fmt(payload or {})
    if not info.strip():
        return {"ok": False, "error": "没有可分析的信息"}
    if kind == "title":
        task = TITLE_TASK.replace("__INFO__", info)
        want_keys = ("titles", "pick", "why")
        temp = 0.9
    elif kind == "persona":
        task = PERSONA_TASK.replace("__INFO__", info)
        want_keys = ("persona", "opening")
        temp = 0.8
    else:
        return {"ok": False, "error": f"未知类型 {kind}"}

    try:
        raw = await _chat([
            {"role": "system", "content": PROMPT_BASE},
            {"role": "user", "content": task},
        ], temperature=temp)
    except Exception as e:  # noqa: BLE001
        S.log(f"[nanny] analyze({kind}) failed: {e}")
        return {"ok": False, "error": str(e)}

    data = _extract_json(raw)
    if not data:
        return {"ok": False, "error": "模型没给出可解析的 JSON", "raw": raw[:400]}
    out = {k: data.get(k) for k in want_keys}
    S.log(f"[nanny] analyze({kind}) ok keys={list(data.keys())[:6]}")
    return {"ok": True, "data": out}


# ---------------------------------------------------------------- 驻守

def _registry() -> Dict[str, Any]:
    try:
        return json.loads((BUNDLE / "registry.json").read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


CORE_REG = S.ENTITY / "registry" / "programs.json"


BUILTIN_PROGRAMS = [
    ("webchat", "对话窗口", "常驻内核，跟她说话、记事、翻记忆"),
    ("voice", "语音", "语音转文字（可选，装了 faster-whisper 才有）"),
    ("vision", "看图", "图片理解（模型支持多模态时可用）"),
]


def _ensure_builtins(doc) -> bool:
    """内置三项跟着端口走：别把旧端口、旧叫法留在注册表里。"""
    rows = doc.get("programs") or []
    by = {str(r.get("name")): r for r in rows if isinstance(r, dict)}
    changed = False
    for name, title, what in BUILTIN_PROGRAMS:
        row = by.get(name)
        entry = "http://127.0.0.1:%d/" % S.PORT if name == "webchat" else (row or {}).get("entry", "")
        want = {"name": name, "title": title, "what": what, "entry": entry,
                "can": (row or {}).get("can") or ["聊天", "记忆"] if name == "webchat" else (row or {}).get("can") or [],
                "cant": (row or {}).get("cant") or []}
        if row is None:
            rows.append(want)
            by[name] = want
            changed = True
        else:
            for k, v in want.items():
                if row.get(k) != v:
                    row[k] = v
                    changed = True
    doc["programs"] = rows
    return changed


def _core_programs():
    try:
        doc = json.loads(CORE_REG.read_text(encoding="utf-8-sig")) or {}
    except Exception:
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    if not isinstance(doc.get("programs"), list):
        doc["programs"] = []
    try:
        if _ensure_builtins(doc):
            _core_save(doc)
            S.log("[nanny] 内置程序已校正（对话窗口/语音/看图，端口 %d）" % S.PORT)
    except Exception as e:
        S.log("[nanny] 内置程序校正失败：%r" % (e,))
    return doc


def _core_save(doc) -> None:
    CORE_REG.parent.mkdir(parents=True, exist_ok=True)
    tmp = CORE_REG.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CORE_REG)


def register_module(mod):
    mid = str(mod.get("id") or "").strip()
    if not mid:
        return {"ok": False, "error": "no id"}
    can = []
    for t in (mod.get("tools") or []):
        name = str(t.get("name") if isinstance(t, dict) else t).strip()
        if name:
            can.append(name)
    ports = [int(p) for p in (mod.get("ports") or []) if str(p).isdigit()]
    doc = _core_programs()
    rows = [r for r in doc["programs"] if isinstance(r, dict) and str(r.get("name")) != mid]
    rows.append({
        "name": mid,
        "title": str(mod.get("name") or mid),
        "what": str(mod.get("summary") or ""),
        "entry": "http://127.0.0.1:%d/" % ports[0] if ports else "",
        "can": can,
        "cant": [],
    })
    doc["programs"] = rows
    _core_save(doc)
    S.log("[nanny] 备案 %s（%d 个程序）" % (mid, len(rows)))
    return {"ok": True, "programs": len(rows)}


def unregister_module(mid):
    mid = str(mid or "").strip()
    doc = _core_programs()
    before = len(doc["programs"])
    doc["programs"] = [r for r in doc["programs"] if isinstance(r, dict) and str(r.get("name")) != mid]
    _core_save(doc)
    S.log("[nanny] 撤销备案 %s（%d -> %d）" % (mid, before, len(doc["programs"])))
    return {"ok": True, "programs": len(doc["programs"])}


def drain_pending() -> int:
    # 壳子进程宕着的时候，模组装卸先攒在 pending 里，等内核起来再补记
    p = S.STATE_DIR / "module_pending.jsonl"
    if not p.exists():
        return 0
    rows = []
    try:
        for line in p.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    except Exception as e:
        S.log("[nanny] pending 读不动：%r" % (e,))
        return 0
    if not rows:
        p.unlink(missing_ok=True)
        return 0
    n = 0
    for r in rows:
        try:
            if str(r.get("action")) == "unregister":
                unregister_module(str(r.get("id") or ""))
            else:
                register_module(r)
            n += 1
        except Exception as e:
            S.log("[nanny] pending 失败：%r" % (e,))
    p.unlink(missing_ok=True)
    return n


def _port_ok(port: int, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except Exception:
        return False


def check_once() -> Dict[str, Any]:
    try:
        drain_pending()
    except Exception as e:
        S.log(f"[nanny] drain_pending 失败：{e!r}")
    st = _load()
    reg = _registry()
    raw = reg.get("modules") or {}
    if isinstance(raw, dict):
        raw = list(raw.values())
    mods = [m for m in raw if isinstance(m, dict) and str(m.get("state")) == "enabled"]
    seen = set()
    for m in mods:
        mid = str(m.get("id") or "")
        if not mid:
            continue
        seen.add(mid)
        # 外壳 0.2.0 起不再给"清单里写的那个端口"，而是从池里挑一个空闲口，
        # 记在 registry 的 runtime_port 里（pbab.enable()）。清单里的 ports 只是"作者想要的"，
        # 探它只会把健康模组判成挂掉，还会漏掉真正的崩溃。
        runtime = str(m.get("runtime_port") or "")
        if runtime.isdigit():
            ports = [int(runtime)]
        else:
            ports = [int(p) for p in (m.get("ports") or []) if str(p).isdigit()]
        bad = [p for p in ports if not _port_ok(p)]
        slot = st["modules"].setdefault(mid, {"fails": 0, "state": "ok", "ports": {}})
        slot["ports"] = {str(p): (p not in bad) for p in ports}
        if bad:
            slot["fails"] = int(slot.get("fails") or 0) + 1
            if slot["fails"] >= FAILS_TO_DEGRADED and slot.get("state") != "degraded":
                slot["state"] = "degraded"
                S.log(f"[nanny] {mid} degraded: ports down {bad}")
                where = "、".join(str(p) for p in bad)
                log_event("degraded", f"模组「{m.get('name') or mid}」没响应了（{where} 不通）。")
                _notice(f"模组「{m.get('name') or mid}」没响应了（{where} 不通），可能已经掉了。")
        else:
            if slot.get("state") == "degraded":
                S.log(f"[nanny] {mid} recovered")
                log_event("recovered", f"模组「{m.get('name') or mid}」又回来了。")
                _notice(f"模组「{m.get('name') or mid}」又回来了。")
            slot["fails"] = 0
            slot["state"] = "ok"
        slot["checked_at"] = time.time()
    # 卸载掉的模组不再盯着
    for mid in list(st["modules"].keys()):
        if mid not in seen:
            st["modules"].pop(mid, None)
    st["last_check"] = time.time()
    st["checks"] = int(st.get("checks") or 0) + 1
    _save()
    return st


async def watch_loop() -> None:
    await asyncio.sleep(15.0)
    S.log("[nanny] watch loop started (every 60s)")
    while True:
        try:
            await asyncio.to_thread(check_once)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            S.log(f"[nanny] watch tick failed: {e}")
        await asyncio.sleep(WATCH_EVERY)


def status() -> Dict[str, Any]:
    st = _load()
    mods = []
    for mid, slot in (st.get("modules") or {}).items():
        mods.append({
            "id": mid,
            "state": slot.get("state") or "ok",
            "fails": slot.get("fails") or 0,
            "ports": slot.get("ports") or {},
            "checked_at": slot.get("checked_at") or 0,
        })
    return {
        "ok": True,
        "last_check": st.get("last_check") or 0,
        "checks": st.get("checks") or 0,
        "modules": mods,
        "degraded": [m["id"] for m in mods if m["state"] == "degraded"],
    }
