"""语言盒：DeepSeek 调用 + 系统提示拼装。

系统提示顺序（越靠后越"近"）：
1. 人格正文（entity\\persona\\persona.md）
2. 脑子里的状态（情绪/处境）—— brain_box.prompt_fragment()
3. 记得的事 —— memory_box.fragment()
4. 这扇门的规矩（不同入口说话方式不一样）
"""
from __future__ import annotations

import asyncio
import json
import time

import httpx


class NotConfigured(RuntimeError):
    """框架还没配置（没有 key / 人格是占位符）。"""

from . import (avatar, brain_box, drives, emotion_core, memory_box, module_cfg,
               modules_box, persona_drift, presence, registry_box, self_model,
               self_store, sense, settings as S, status_box, stomach_box,
               style_box, tool_bus)

_client: httpx.AsyncClient | None = None
_persona_cache = {"text": "", "mtime": 0.0}


def _client_or_new() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=15.0))
    return _client


def persona() -> str:
    try:
        mtime = S.PERSONA_PATH.stat().st_mtime
    except OSError:
        return S.persona_text()
    if _persona_cache["mtime"] != mtime:
        _persona_cache["text"] = S.persona_text()
        _persona_cache["mtime"] = mtime
    return _persona_cache["text"]


EXPRESSION_RULES = """# 说话方式（硬性）
- 动作、神态、小动作只准写在全角方头括号里：〖抬了下眼皮〗。不是（），不是 *，不是 []，不是 **。
  （桌面外壳只认 〖 〗：里面的东西会被缩成灰色小字，而且永远不会被念出来。）
- 〖〗 里只写动作，别把要说的话塞进去——那部分她不会出声。
- 一条回复里动作最多一处、不超过 8 个字；多数时候干脆不写。
- 不要每句开头都摆一个动作；情绪靠用词本身，不靠括号。
- 一次只说一到两句，不要把一大段拆成一串动作加短句。"""


def door_rule(session: str) -> str:
    """这扇门的说话方式。关系词取她自己配置的 relation，不写死「主人」。"""
    rel = S.relation()
    rules = {
        "qq:owner": f"现在是 QQ 私聊，对方是我的{rel}。一条 1-10 字，最多两行；别写小作文。",
        "qq:friend": "现在是 QQ 私聊，对方是普通朋友。短、随口，别热情过头。",
        "qq:group": "现在是 QQ 群聊。只回被 @ 或被点名的那句，一到两行；别人没叫你就不插话。",
        "web:owner": f"现在是直接在这个对话窗口里和我的{rel}说话（可以稍微多说一句，但仍要像人）。",
        "bili:owner": f"现在是 B 站私信，对方是我的{rel}。一两行，别用括号动作，别提到 AI/模型/系统。",
        "bili:other": "现在是 B 站私信，对方是陌生人。客气但不热络，一两行，不透露个人隐私，不承认自己是机器人。",
    }
    if session in rules:
        return rules[session]
    for prefix in ("qq:group", "qq:friend", "qq:owner", "bili:other", "bili:owner", "web:owner"):
        if session.startswith(prefix):
            return rules[prefix]
    return "一两行，像人一样说话。"


BASE_TOOLS = """# 系统给我的工具（只说明有什么，不等于我会）
- 这个对话窗口（常驻内核 40720）：说话、记事、翻记忆。
- 我的眼睛、耳朵、头像，看下面的工具清单；清单里没有的，就是这会儿没有。
- 模组给的工具是真能调的（下面列了格式）；没列出来的就是没有。
- 对方问具体数字（温度、比分、价格、日期）时，先调工具查，别凭印象答；查不到就说查不到。
- 除了上面这些，我没有别的程序。清单里没有的名字（比如别的聊天工具、站子），就是这会儿没有，别凭印象编，也别用"没装"当借口。没装的东西，我连它的名字都不该知道——别人问起，就说这台机器上没有那个东西。

# 说人话
- 做不了的事直接说做不了，别装、别编，也别假装调用了什么工具。"""


SELF_RULE = """# 我说「我会」的时候
- 先看上面「我实际做过的（证据）」。
- 有成功证据：说「我做过，上次……」，不要只说「系统说我能」。
- 只有失败：说「我试过，没成」，不要把没成说成会。
- 没有证据：说「清单说我能，但我还没试过」。
- 清单里没有：说「我现在做不到」。
- 系统工具清单只说明有什么，不证明我会；不要把清单背给用户听。"""


def _module_line(mod: dict) -> str:
    mid = str(mod.get("id") or "")
    name = str(mod.get("name") or mid)
    try:
        conn = modules_box.connection(mid)
    except Exception:
        conn = {}
    provides = conn.get("provides") or {}
    tools = []
    for t in provides.get("tools") or []:
        if isinstance(t, dict):
            nm = str(t.get("name") or "").strip()
            desc = str(t.get("desc") or "").strip()
            if nm:
                tools.append(f"{nm}（{desc}）" if desc else nm)
        else:
            txt = str(t).strip()
            if txt:
                tools.append(txt)
    tail = ""
    if tools:
        tail = "；能调的工具：" + "、".join(tools[:14]) + ("…" if len(tools) > 14 else "")
    return f"- {name}：已装上、正开着{tail}"


def _module_events(limit: int = 2, hours: float = 24.0) -> str:
    """最近开关过的模组：让她知道「刚刚变了」。"""
    p = S.STATE_DIR / "module_events.jsonl"
    if not p.exists():
        return ""
    rows = []
    try:
        for line in p.read_text(encoding="utf-8-sig", errors="ignore").splitlines()[-20:]:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            rows.append(row)
    except Exception:
        return ""
    cutoff = time.time() - hours * 3600
    keep = []
    for row in rows:
        try:
            ts = time.mktime(time.strptime(str(row.get("ts")), "%Y-%m-%dT%H:%M:%S"))
        except Exception:
            continue
        if ts >= cutoff:
            keep.append((ts, row))
    if not keep:
        return ""
    # 只保留"现在这台机器上还装着"的模组的事件：卸掉的模组，连名字都不该再出现
    try:
        alive = {str(m.get("id") or "") for m in modules_box.modules()}
    except Exception:  # noqa: BLE001
        alive = set()
    keep = [(ts, row) for ts, row in keep if str(row.get("id") or "") in alive]
    keep.sort(key=lambda x: x[0])
    out = []
    for ts, row in keep[-limit:]:
        name = str(row.get("name") or row.get("id") or "")
        state = str(row.get("state") or "")
        when = time.strftime("%m-%d %H:%M", time.localtime(ts))
        if state == "enabled":
            out.append(f"- {when} 他把「{name}」打开了，现在能用。")
        elif state == "disabled":
            out.append(f"- {when} 他把「{name}」关了，现在用不了。")
        elif state == "broken":
            out.append(f"- {when}「{name}」启动失败，现在用不了。")
    if not out:
        return ""
    return "# 最近的变化\n" + "\n".join(out)


def tools_text() -> str:
    lines = [BASE_TOOLS]
    try:
        mods = modules_box.modules()
    except Exception:
        mods = []
    on = [m for m in mods if str(m.get("state")) == "enabled"]
    off = [m for m in mods if str(m.get("state")) in ("installed", "disabled")]
    if on:
        lines.append("# 已经装上的模组（能用）\n" + "\n".join(_module_line(m) for m in on))
    if off:
        names = "、".join(str(m.get("name") or m.get("id") or "") for m in off)
        lines.append(f"# 装了但没开\n- {names}：现在用不了，他问就照实说没开。")
    lines.append(
        "# 以这份清单为准\n"
        "- 上面是此刻的状态。清单上没有的东西，就是这会儿用不了；\n"
        "- 你之前说过「能」，而现在没列出来，那就是刚被关了，照实改口一句就行，别嘴硬。"
    )
    ev = _module_events()
    if ev:
        lines.append(ev)
    # 开关提示：被她记着，但不用背数字
    hints = []
    for m in on:
        mid = str(m.get("id") or "")
        vals = module_cfg.values(mid)
        if not vals:
            continue
        offs = [k for k, v in vals.items() if v is False]
        if offs:
            hints.append(f"- {str(m.get('name') or mid)}：" + "、".join(offs) + " 是关着的。")
    if hints:
        lines.append("# 被关掉的小功能（别去做）\n" + "\n".join(hints))
    try:
        how = tool_bus.describe()
        if how:
            lines.append(how)
    except Exception as e:  # pragma: no cover
        S.log(f"[tool] describe failed: {e!r}")
    return "\n\n".join(lines)



# 提示词的"身份框架"：标签用第二人称指路，内容用第一人称自述。
# 这样模型知道自己读的是"关于我自己的资料"，不会把"我是…"当成用户说的话。
FRAME_PERSONA = (
    "# 你的个人信息\n"
    "下面写的是「我」自己的事——不是别人对我说的话，是我本来就知道的。\n\n"
)
FRAME_ABILITY = (
    "# 你的能力\n"
    "下面写的是「我」能做的事——第一人称，是我自己的本事清单。\n\n"
)


def build_system(session: str, query: str) -> str:
    blocks: list[str] = []
    try:
        names = list(tool_bus.tools().keys())
    except Exception:
        names = []
    try:
        owned = self_store.prompt_block(names)
        if owned:
            blocks.append(owned)
    except Exception as e:  # pragma: no cover
        S.log(f"[self] prompt failed: {e!r}")
    blocks.append(FRAME_PERSONA + persona())
    try:
        av = avatar.fragment()
        if av:
            blocks.append(av)
    except Exception:
        pass
    try:
        sn = sense.fragment()
        if sn:
            blocks.append(sn)
    except Exception:
        pass
    try:
        st = style_box.fragment()
        if st:
            blocks.append(st)
    except Exception:
        pass
    try:
        mod_persona = modules_box.persona_text()
        if mod_persona:
            blocks.append(FRAME_ABILITY + mod_persona)
    except Exception:
        pass
    # 7 维 flybrain 只做"体内状态"，不再往提示词里写第二套情绪；
    # 对外只认 emotion_core（有 5 档话术、能驱动 gates）。
    try:
        blocks.append(presence.fragment())
    except Exception:
        pass
    mem = memory_box.fragment(query, session)
    if mem:
        blocks.append(mem)
    try:
        drift = persona_drift.fragment()
        if drift:
            blocks.append(drift)
    except Exception:
        pass
    try:
        urge = drives.fragment()
        if urge:
            blocks.append(urge)
    except Exception:
        pass
    try:
        blocks.append(emotion_core.prompt_block(session))
    except Exception as e:
        S.log(f"[emotion] prompt failed: {e!r}")
    try:
        blocks.append(self_model.fragment())
    except Exception as e:  # pragma: no cover
        S.log(f"[self] portrait failed: {e!r}")
    blocks.append(tools_text())
    try:
        blocks.append(registry_box.pointer())
    except Exception:
        pass
    try:
        blocks.append(status_box.fragment())
    except Exception:
        pass
    try:
        tummy = stomach_box.fragment()
        if tummy:
            blocks.append("# 你的肚子\n" + tummy)
    except Exception:
        pass
    blocks.append(EXPRESSION_RULES)
    blocks.append(SELF_RULE)
    blocks.append("# 现在这扇门\n" + door_rule(session))
    return "\n\n".join(b for b in blocks if b)


async def _ask(msgs: list[dict], temperature: float, max_tokens: int) -> str:
    key = S.deepseek_key()
    payload = {
        "model": "deepseek-chat",
        "messages": msgs,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "presence_penalty": 0.3,
        "frequency_penalty": 0.2,
        "stream": False,
    }
    url = S.deepseek_base() + "/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    last_err = ""
    for attempt in range(3):
        try:
            r = await _client_or_new().post(url, json=payload, headers=headers)
            if r.status_code == 200:
                data = r.json()
                return (data["choices"][0]["message"]["content"] or "").strip()
            last_err = f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:  # pragma: no cover
            last_err = repr(e)
        await asyncio.sleep(1.5 * (attempt + 1))
    S.log(f"[llm] failed: {last_err}")
    return ""


def _image_part(src: str, max_bytes: int = 6 * 1024 * 1024) -> str:
    """把「路径 / data URL / 裸 base64」统一成 image_url 能吃的 data URL。"""
    import base64
    import mimetypes
    from pathlib import Path

    raw = str(src or "").strip()
    if not raw:
        raise ValueError("没有给图")
    if raw.startswith("data:"):
        return raw
    p = Path(raw).expanduser()
    if p.is_file():
        data = p.read_bytes()
        if len(data) > max_bytes:
            raise ValueError(f"这张图 {len(data) // 1024 // 1024} MB，太大了，先缩一下")
        mime = mimetypes.guess_type(p.name)[0] or "image/png"
        return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
    # 不是路径就当裸 base64
    if len(raw) > max_bytes:
        raise ValueError("这张图太大了，先缩一下")
    return "data:image/png;base64," + raw


async def describe_image(src: str, question: str = "这张图里有什么？", max_tokens: int = 400) -> str:
    """把一张图交给主模型看（已实测 deepseek-chat 收 image_url）。

    src：文件路径 / data URL / 裸 base64。返回值是她看完之后的一句描述。
    """
    ok, hint = S.configured()
    if not ok:
        raise NotConfigured(hint)
    url = _image_part(src)
    q = (question or "").strip() or "这张图里有什么？"
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": q + "\n\n（用中文回答，先说你看到的东西，再回答上面的问题；不确定就说不确定。）"},
        {"type": "image_url", "image_url": {"url": url}},
    ]}]
    return await _ask(msgs, 0.2, max_tokens)


async def chat(session: str, query: str, history: list[dict] | None = None,
               temperature: float = 0.9, max_tokens: int = 420,
               max_tool_rounds: int = 3) -> str:
    ok, hint = S.configured()
    if not ok:
        raise NotConfigured(hint)
    system = await asyncio.to_thread(build_system, session, query)
    msgs = [{"role": "system", "content": system}]
    for turn in (history or [])[-16:]:
        role = turn.get("role")
        content = str(turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": query})

    rounds = 0
    while True:
        content = await _ask(msgs, temperature, max_tokens)
        if not content:
            return ""
        call, cleaned = tool_bus.extract(content)
        if not call:
            return cleaned
        if rounds >= max_tool_rounds:
            # 轮数用完了，她还想再调一个。以前这里会 `return cleaned or content`，
            # 于是把 "[工具]{...}" 这行协议原文当成答案丢给使用者（0.3.6 实测踩过）。
            # 协议行绝不能进对话：剥干净，剥完是空的就给一句人话。
            S.log(f"[tool] 放弃多余的调用 rounds={rounds} name={call.get('name')}")
            return cleaned or "（我这边工具还没回话，稍等一下我再试。）"
        rounds += 1
        S.log(f"[tool] 调用 {call['name']} args={str(call['args'])[:160]}")
        one = await tool_bus.call(str(call["name"]), dict(call["args"]))
        msgs.append({"role": "assistant", "content": content})
        msgs.append({"role": "user", "content": tool_bus.feedback(one)})
