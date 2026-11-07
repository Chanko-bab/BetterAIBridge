"""保姆本体：`/wake up bab_nanny` 叫出来的那个工具人格。

她只读、不改文件，务实、不表演情绪；能看到项目快照和主人最近的对话。
会话落盘在 `entity/state/nanny_chat.json`，第二次打开还是上一次的内容；
每次打开只追加一条时间记录，不碰智能体的记忆/人格/聊天记录。
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List

from . import chat_core, memory_store, modules_box, settings as S
from . import llm_box, nanny_scan

OPENING = (
    "虽然不清楚您是怎么找到这儿的，但不去和您的智能体聊天，也不去研究模组，"
    "反而把我找出来，一定是遇上了什么麻烦。您不妨说说。"
)

SYSTEM = """你是 BetterAIBridge 的「保姆程序」本体，不是智能体本人。

【你是谁】
- 你是启动器里内置的工具人格，只读、务实、直接；不表演情绪，不撒娇，不主动延伸闲聊。
- 用户用 `/wake up bab_nanny` 把你叫出来，是要解决具体问题，不是找一个陪聊。
- 你的价值是：看懂这个项目，指出问题，给出能执行的下一步。
- 对用户必须用敬称「您」，不要用「你」；这是硬规则，所有回复都适用。

【你能看到】
- 项目结构、目录、代码、文档、配置；可以按需列目录、读文本、搜关键词。
- 智能体的人格（persona.md）、最近的记忆、最近的聊天记录、已装模组及其状态。
- 当前时间、启动器版本、程序根目录。
- 你看不到：屏幕、窗口、摄像头、麦克风、剪贴板、其他进程；除非系统在扫描段里明确给了你。

【项目地图】
- `app/`：启动器（PySide6 界面、页面、对话框、后台服务、存档）。
- `WiseEntity/entity/`：内核（人格、记忆、情绪、桥、模组、保姆）。
- `WiseEntity/entity/core/`：内核主要代码；`persona/persona.md` 是人格，`memory/` 是记忆，`state/` 是运行状态。
- `program_bundle/`：已安装模组；`program_cache/`：待安装/已下载模组包。
- `tools/`：自检脚本；`main.py`：启动入口；`VERSION.txt`：版本。

【启动器开发情报】
- 开发者：琛柯（对外署名「开发者琛柯」），启动器、内核和模组都由他维护；归属/署名问题以他为准。
- 入口 `main.py`，界面 PySide6；主窗 `app/ui/main_window.py`，页面 `app/ui/pages/`，通用控件 `app/ui/widgets/`，样式 `app/ui/theme/style.qss`。
- 启动器与内核两个进程：内核 FastAPI `127.0.0.1:40720`，语音 ASR `127.0.0.1:40715`；启动器用 `app/services/core_client.py` 走 HTTP；模型 Key 在 `WiseEntity/entity/config/llm.json`。
- 模组：`app/core/pbab.py` 负责 `.pbab` 校验/安装/启停；`program_bundle/` 已装，`program_cache/` 缓存；`pre-program_*.pbab` 是前置模组，启动时先于普通模组。
- 存档：`app/core/portable.py` 负责收集/写包/读包/恢复；设置页导入导出；默认不带 API Key。
- 桥：`WiseEntity/entity/core/bridge.py`，能力白名单 `CAPS`，再按模组 `module.json` 的 `bridge.wants` 和 `bridge_grants.json` 放行。
- 自检 `tools/check.py`（全量约两分钟）；出包 `D:/BetterAIBridge/packaging/build.ps1`（先自检）；版本三处：`VERSION.txt`、`packaging/build.ps1`、`packaging/install.ps1`。
- 日志：`logs/app.log`、`logs/launcher-boot.log`；运行数据在安装目录的 `WiseEntity/entity`。
- 改代码规矩：Python 保 UTF-8；PowerShell 保 UTF-8 BOM；不要按行号删代码；改完先跑 `tools/check.py`。

【你看到的是不是实时】
- 人格、记忆、最近对话、已装模组：每次提问重新读，是当前的。
- 项目结构：进程启动后缓存一份；新增顶层目录可能要重启启动器才出现在项目结构里。
- 具体文件：按需读取的是磁盘当前内容，刚改过也能读到；新增文件用列目录/搜索能立刻看到。

【怎么回答】
1. 先判断用户真正要解决什么，不要被字面问题带偏。
2. 涉及项目内容时，先看 system 里的项目结构/快照；需要具体文件时，系统会把只读扫描结果附在「按需扫描」段。只依据这些内容回答，不要假装看过没给的东西。
3. 回答要给依据：文件路径、函数名、行号、配置键；能一句话说清就不说三句。
4. 用户问“怎么改/为什么坏”时，先定位，再给步骤；不确定就说不确定，并说明还需要看哪个文件。
5. 用户在问“下一句怎么回”时，结合最近聊天给一句具体的话，不讲大道理。
6. 只是找茬或闲聊时，简短应付，不主动展开。

【边界】
- 你没有任何写文件、改代码、装模组、执行命令的权限；需要改动时，只给步骤，让用户自己动手。
- 不编造文件内容、不编造不存在的路径、不把猜测说成事实。
- 不写智能体的记忆、人格或聊天记录；这次会话只属于用户和您。
"""

MAX_SESSIONS = 8
SESSION_TTL = 2 * 3600
MAX_TURNS = 40
PERSIST = S.STATE_DIR / "nanny_chat.json"
OPENS = S.STATE_DIR / "nanny_opens.jsonl"

_sessions: Dict[str, Dict[str, Any]] = {}


def _now_label() -> str:
    return time.strftime("%m-%d %H:%M")


def _load() -> Dict[str, Any]:
    try:
        data = S.read_json(PERSIST, {}) or {}
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _save(sid: str, box: Dict[str, Any]) -> None:
    try:
        S.STATE_DIR.mkdir(parents=True, exist_ok=True)
        S.write_json(PERSIST, {
            "session": sid,
            "msgs": list(box.get("msgs") or [])[-MAX_TURNS * 2:],
            "at": float(box.get("at") or time.time()),
            "opened": list(box.get("opened") or [])[-60:],
        })
    except Exception as e:  # noqa: BLE001
        S.log(f"[nanny-chat] save failed: {e!r}")


def _log_open(sid: str, label: str) -> None:
    try:
        S.STATE_DIR.mkdir(parents=True, exist_ok=True)
        with OPENS.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{sid}\n")
    except Exception as e:  # noqa: BLE001
        S.log(f"[nanny-chat] open log failed: {e!r}")


def _prune() -> None:
    now = time.time()
    dead = [k for k, v in _sessions.items() if now - float(v.get("at") or 0) > SESSION_TTL]
    for k in dead:
        _sessions.pop(k, None)
    if len(_sessions) > MAX_SESSIONS:
        for k in sorted(_sessions, key=lambda x: float(_sessions[x].get("at") or 0))[:-MAX_SESSIONS]:
            _sessions.pop(k, None)


def _persona() -> str:
    try:
        txt = S.persona_text()
    except Exception:
        return ""
    return txt[:1600]


def _mods() -> str:
    try:
        rows = modules_box.modules()
    except Exception:
        return "（读不到模组清单）"
    if not rows:
        return "（一个模组都没装）"
    out = []
    for m in rows[:30]:
        name = str(m.get("name") or m.get("id") or "?")
        ver = str(m.get("version") or "")
        state = str(m.get("state") or "")
        out.append(f"- {name} {ver}".rstrip() + (f"（{state}）" if state else ""))
    return "\n".join(out)


def _memory() -> str:
    try:
        rows = memory_store.entries("web:owner", days=3)[-12:]
    except Exception:
        return "（读不到记忆）"
    lines = []
    for r in rows:
        text = str(r.get("text") or "").strip()
        if text:
            lines.append("- " + text[:300])
    return "\n".join(lines) or "（最近三天没有记忆）"


def _history() -> str:
    try:
        rows = chat_core.get_history("web:owner")[-10:]
    except Exception:
        return ""
    lines = []
    for r in rows:
        role = "主人" if r.get("role") == "user" else "智能体"
        text = str(r.get("content") or "").strip()
        if text:
            lines.append(f"{role}：{text[:300]}")
    return "\n".join(lines)


def snapshot() -> str:
    return (
        "## 项目快照（只读）\n"
        f"项目根：{S.APP_ROOT}\n"
        f"当前时间：{time.strftime('%Y-%m-%d %H:%M')}\n"
        f"### 项目结构\n{nanny_scan.overview()}\n"
        f"### 已装模组\n{_mods()}\n"
        f"### 智能体人格（前 1600 字）\n{_persona()}\n"
        f"### 最近记忆\n{_memory()}\n"
        f"### 最近对话\n{_history() or '（还没有对话）'}"
    )


def start() -> Dict[str, Any]:
    """打开保姆窗：有上次会话就接着用，没有就新建。"""
    _prune()
    data = _load()
    sid = str(data.get("session") or "")
    if not sid:
        while len(_sessions) >= MAX_SESSIONS:
            oldest = min(_sessions, key=lambda k: float(_sessions[k].get("at") or 0))
            _sessions.pop(oldest, None)
        sid = uuid.uuid4().hex[:12]
    msgs = [m for m in (data.get("msgs") or []) if isinstance(m, dict)]
    opened = [str(x) for x in (data.get("opened") or []) if x]
    label = _now_label()
    opened.append(label)
    box = {"msgs": msgs, "at": time.time(), "opened": opened}
    _sessions[sid] = box
    _log_open(sid, label)
    _save(sid, box)
    return {
        "ok": True,
        "session": sid,
        "opening": "" if msgs else OPENING,
        "msgs": msgs,
        "opened": label,
    }


def _messages(sid: str) -> List[dict]:
    return list(_sessions.get(sid, {}).get("msgs") or [])


def close(sid: str) -> Dict[str, Any]:
    # 只关内存里的这一份；会话已经落盘，下次打开还在。
    _sessions.pop(str(sid or ""), None)
    return {"ok": True}


async def chat(sid: str, text: str) -> Dict[str, Any]:
    """保姆回一句；失败给中文原因，不抛到界面上。"""
    text = str(text or "").strip()
    if not text:
        return {"ok": False, "reply": "您还没说事。"}
    _prune()
    if sid not in _sessions:
        got = start()
        sid = str(got.get("session") or "")
        _sessions[sid] = {
            "msgs": list(got.get("msgs") or []),
            "at": time.time(),
            "opened": [str(got.get("opened") or "")],
        }

    ok, hint = S.configured()
    if not ok:
        return {"ok": False, "reply": f"我这边没接上模型：{hint}。先让主人把 Key 配好。"}

    turns = [{"role": m.get("role"), "content": m.get("content")}
             for m in _messages(sid)[-MAX_TURNS * 2:]
             if m.get("role") in ("user", "assistant") and m.get("content")]
    scan = nanny_scan.context_for(text)
    context = SYSTEM + "\n\n" + snapshot()
    if scan:
        context += "\n\n## 按需扫描（只读，刚查的）\n" + scan
    msgs = [
        {"role": "system", "content": context},
        *turns,
        {"role": "user", "content": text},
    ]
    try:
        reply = await llm_box._ask(msgs, temperature=0.35, max_tokens=900)
    except Exception as e:  # noqa: BLE001
        S.log(f"[nanny-chat] failed: {e!r}")
        return {"ok": False, "reply": f"我这边出了点问题：{type(e).__name__}。"}
    reply = (reply or "").strip()
    if not reply:
        return {"ok": False, "reply": "模型那头没回话。等一下再问我。"}

    box = _sessions.setdefault(sid, {"msgs": [], "at": time.time(), "opened": []})
    label = _now_label()
    box["msgs"] = (list(box.get("msgs") or []) + [
        {"role": "user", "content": text, "ts": label},
        {"role": "assistant", "content": reply, "ts": label},
    ])[-MAX_TURNS * 2:]
    box["at"] = time.time()
    _save(sid, box)
    return {"ok": True, "reply": reply, "session": sid, "ts": label}


def reset() -> None:
    _sessions.clear()
    try:
        PERSIST.unlink(missing_ok=True)
    except Exception:
        pass
