"""工具总线：把「已启用模组」在 connection.json 里声明的东西，变成她真能调的函数。

约定（和 pbab 对齐，不引入新配置）：
- `provides.tools` 支持两种写法（向后兼容）：
  1) 对象：`{"name","endpoint","desc","args":{...},"max_seconds"}` —— 推荐，描述和参数都明确；
  2) 字符串：名字末段要和某个 `endpoints[].name` 对上（`web_fetch` -> `fetch`）。
- 地址取模组的 `ports[0]`：`http://127.0.0.1:<port><endpoint.path>`。
- 只做 POST/GET 两种；参数必须是 dict；超时、结果截断、异常都变成 {ok:false,...} 还给她。

她"要调工具"时，回一行：
    [工具]{"name":"web_fetch","args":{"url":"https://example.com"}}
内核取这一行、真去调、把结果塞回上一轮，再让她用人话回。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Dict, List, Tuple

import httpx

from . import modules_box, settings as S

TIMEOUT_S = 45.0
MAX_RESULT_CHARS = 3500
CALL_TAG = "[工具]"

_cache: Dict[str, Any] = {"at": 0.0, "tools": {}}

# 一行 [工具]{...}；也容忍 ```tool 围栏
_LINE_RE = re.compile(r"\[工具\]\s*(\{.*\})\s*$", re.MULTILINE)
_FENCE_RE = re.compile(r"```(?:tool|json)?\s*(\{[^\n]*\"name\"[^\n]*\})\s*```", re.DOTALL)


def _base(port: Any) -> str:
    try:
        p = int(port)
    except Exception:
        return ""
    if not (1 <= p <= 65535):
        return ""
    return f"http://127.0.0.1:{p}"


def _build() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    try:
        mods = modules_box.enabled()
    except Exception as e:  # pragma: no cover
        S.log(f"[tool] 读模组失败：{e!r}")
        return out
    for mod in mods:
        mid = str(mod.get("id") or "")
        if not mid:
            continue
        ports = mod.get("ports") or []
        port = mod.get("runtime_port") or (ports[0] if ports else 0)
        base = _base(port)
        if not base:
            continue
        try:
            conn = modules_box.connection(mid)
        except Exception:
            continue
        prov = conn.get("provides") or {}
        eps = {}
        for ep in (prov.get("endpoints") or []):
            if isinstance(ep, dict) and ep.get("name"):
                eps[str(ep["name"]).lower()] = ep
        for t in (prov.get("tools") or []):
            if isinstance(t, str):
                name, hint, args, epic = t, "", {}, ""
            elif isinstance(t, dict) and t.get("name"):
                name = str(t["name"])
                hint = str(t.get("desc") or t.get("description") or "")
                args = t.get("args") if isinstance(t.get("args"), dict) else {}
                epic = str(t.get("endpoint") or "")
            else:
                continue
            ep = eps.get(epic.lower()) if epic else None
            if ep is None:
                ep = eps.get(name.rsplit("_", 1)[-1].lower())
            if not ep:
                # 声明了工具、却没有对应 endpoints[] 条目 —— 以前是静默丢掉，
                # 结果"她"永远不知道这个工具存在，也没人发现清单写漏了。
                S.log(f"[tool] {mid} 的工具 {name} 没有对应 endpoints[] 条目，已跳过")
                continue
            path = str(ep.get("path") or "")
            if not path.startswith("/"):
                continue
            try:
                secs = float(t.get("max_seconds")) if isinstance(t, dict) else 0.0
            except Exception:
                secs = 0.0
            out[name] = {
                "name": name,
                "module": mid,
                "module_name": str(mod.get("name") or mid),
                "url": base + path,
                "method": str(ep.get("method") or "POST").upper(),
                "hint": hint,
                "args": args,
                "sample": ep.get("body"),
                "returns": ep.get("returns"),
                "max_seconds": secs if secs > 0 else TIMEOUT_S,
            }
    return out


def _builtin_tools() -> Dict[str, Dict[str, Any]]:
    """内核自己给的工具（不依赖模组）：头像，以及她自己的眼睛和耳朵。"""
    from . import sense

    out: Dict[str, Dict[str, Any]] = {
        "avatar_see": {
            "name": "avatar_see",
            "module": "self",
            "module_name": "她自己",
            "hint": "看你自己的头像（主人可能换过），这样你才知道自己现在长什么样",
            "args": {},
            "method": "POST",
            "url": "",
            "builtin": "avatar_see",
            "max_seconds": 60.0,
        },
    }
    if sense.eyes():
        out["look_around"] = {
            "name": "look_around",
            "module": "self",
            "module_name": "她自己",
            "hint": "看一眼主人那边（摄像头优先，没选就看屏幕），回来告诉你看到了什么",
            "args": {"question": "可选：你想在画面里找什么"},
            "method": "POST",
            "url": "",
            "builtin": "look_around",
            "max_seconds": 130.0,
        }
    if sense.ears():
        out["listen_now"] = {
            "name": "listen_now",
            "module": "self",
            "module_name": "她自己",
            "hint": "听一下主人那边的声音，回来告诉你听到了什么（转好的文字）",
            "args": {"seconds": "可选：听几秒，1–20，默认 6"},
            "method": "POST",
            "url": "",
            "builtin": "listen_now",
            "max_seconds": 140.0,
        }
    return out


def tools() -> Dict[str, Dict[str, Any]]:
    now = time.time()
    if now - float(_cache["at"] or 0) < 5.0 and _cache["tools"]:
        return dict(_cache["tools"])
    data = _build()
    data.update(_builtin_tools())
    _cache["tools"] = data
    _cache["at"] = now
    return dict(data)


def has_tools() -> bool:
    return bool(tools())


_TYPE_NAMES = {
    "string": "文字", "str": "文字", "text": "文字",
    "integer": "整数", "int": "整数", "number": "数字", "float": "数字",
    "boolean": "开关", "bool": "开关", "array": "列表", "list": "列表",
    "object": "对象", "dict": "对象",
}
_ARG_ONE_MAX = 120
_ARG_ALL_MAX = 300


def _arg_clip(text: str, limit: int) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _arg_text(spec: Any) -> str:
    """把单个参数声明渲染成「类型，必填/可选，默认 X：说明」。"""
    if not isinstance(spec, dict):
        return _arg_clip(spec, _ARG_ONE_MAX)
    typ = str(spec.get("type") or "").strip()
    typ = _TYPE_NAMES.get(typ.lower(), typ)
    bits = [typ] if typ else []
    req = spec.get("required")
    if req is True:
        bits.append("必填")
    elif req is False:
        bits.append("可选")
    dv = spec.get("default")
    if dv is not None and dv != "":
        if isinstance(dv, (dict, list)):
            dv_text = json.dumps(dv, ensure_ascii=False)
        else:
            dv_text = str(dv)
        bits.append("默认 " + dv_text)
    desc = str(
        spec.get("description") or spec.get("desc") or spec.get("help") or spec.get("title") or ""
    ).strip()
    head = "，".join(bits)
    body = f"{head}：{desc}" if head and desc else (head or desc)
    return _arg_clip(body, _ARG_ONE_MAX)


def _arg_line(args: dict[str, Any]) -> str:
    """把结构化参数渲染成一行中文；逐参数 120 字、整段 300 字封顶。"""
    parts = []
    for key, spec in args.items():
        text = _arg_text(spec)
        if not text:
            parts.append(str(key))
        elif isinstance(spec, dict):
            meta, sep, desc = text.partition("：")
            parts.append(f"{key}（{meta}）：{desc}" if sep else f"{key}（{text}）")
        else:
            parts.append(f"{key}（{text}）")
    if not parts:
        return ""
    return _arg_clip("参数：" + "；".join(parts), _ARG_ALL_MAX)


def describe() -> str:
    """给提示词用的一段说明（只在真有工具时出现）。"""
    items = tools()
    if not items:
        return ""
    rows = []
    for name, t in items.items():
        hint = str(t.get("hint") or "").strip()
        args = t.get("args") or {}
        if isinstance(args, dict) and args:
            arg_s = _arg_line(args)
        else:
            sample = t.get("sample")
            arg_s = "参数示例 " + (json.dumps(sample, ensure_ascii=False) if isinstance(sample, dict) else "{}")
        line = f"- {name}（{t['module_name']}）"
        if hint:
            line += f"：{hint}"
        line += f"；{arg_s}" if arg_s else ""
        rows.append(line)
    return (
        "# 怎么调工具\n"
        "要查东西/读网页时，**单独回一行**，不要再带别的话：\n"
        '    [工具]{"name":"工具名","args":{...}}\n'
        "拿到结果后你再用自己的语气说一句。一次只调一个；没让你查就别查。\n"
        "能用的：" + "\n" + "\n".join(rows)
    )


def extract(text: str) -> Tuple[Dict[str, Any] | None, str]:
    """从她的回复里取出工具调用；返回 (调用, 去掉调用后的文本)。"""
    raw = text or ""
    m = _LINE_RE.search(raw) or _FENCE_RE.search(raw)
    if not m:
        return None, raw.strip()
    blob = m.group(1).strip()
    try:
        obj = json.loads(blob)
    except Exception:
        return None, raw.strip()
    if not isinstance(obj, dict):
        return None, raw.strip()
    name = str(obj.get("name") or obj.get("tool") or "").strip()
    args = obj.get("args") or obj.get("arguments") or {}
    if not name or not isinstance(args, dict):
        return None, raw.strip()
    cleaned = (raw[: m.start()] + raw[m.end():]).strip()
    return {"name": name, "args": args}, cleaned


def _short(data: Any) -> str:
    try:
        s = json.dumps(data, ensure_ascii=False)
    except Exception:
        s = str(data)
    if len(s) > MAX_RESULT_CHARS:
        s = s[:MAX_RESULT_CHARS] + "…（后面太长，截了）"
    return s


async def _call_impl(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    items = tools()
    spec = items.get(name)
    if not spec:
        return {"ok": False, "error": f"没有这个工具：{name}", "tools": list(items)}
    builtin = spec.get("builtin")
    if builtin in ("look_around", "listen_now"):
        started = time.time()
        try:
            from . import sense

            if builtin == "look_around":
                res = await asyncio.to_thread(
                    sense.look, str(args.get("question") or args.get("q") or ""))
            else:
                res = await asyncio.to_thread(
                    sense.listen, args.get("seconds") or 6)
            ms = int((time.time() - started) * 1000)
            S.log(f"[tool] {name} ok {ms}ms")
            return {"ok": True, "tool": name, "ms": ms, "result": res}
        except Exception as e:  # noqa: BLE001
            ms = int((time.time() - started) * 1000)
            S.log(f"[tool] {name} failed: {e!r}")
            return {"ok": False, "tool": name, "ms": ms,
                    "error": str(e).strip() or type(e).__name__}
    if builtin == "avatar_see":
        started = time.time()
        try:
            from . import avatar, llm_box

            one = avatar.info()
            text = await llm_box.describe_image(
                one["path"],
                "这是你自己的头像。用第一人称说说你现在长什么样（颜色、形状、风格），两三句就够。",
            )
            ms = int((time.time() - started) * 1000)
            S.log(f"[tool] avatar_see ok {ms}ms")
            return {"ok": True, "tool": name, "ms": ms,
                    "result": {"ok": True, "text": text, "path": one["path"]}}
        except Exception as e:  # noqa: BLE001
            ms = int((time.time() - started) * 1000)
            S.log(f"[tool] avatar_see failed: {e!r}")
            return {"ok": False, "error": f"{type(e).__name__}: {e}", "ms": ms}
    url = spec["url"]
    started = time.time()
    try:
        tmo = float(spec.get("max_seconds") or TIMEOUT_S)
        async with httpx.AsyncClient(timeout=httpx.Timeout(tmo, connect=8.0)) as cli:
            if spec["method"] == "GET":
                r = await cli.get(url, params=args)
            else:
                r = await cli.post(url, json=args)
            ms = int((time.time() - started) * 1000)
            if r.status_code != 200:
                return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:300]}", "ms": ms}
            data = r.json()
            if not isinstance(data, dict):
                data = {"ok": True, "data": data}
            if data.get("ok") is False:
                err = str(data.get("error") or "工具返回失败")
                S.log(f"[tool] {name} FAILED {ms}ms: {err[:140]} args={_short(args)[:100]}")
                return {"ok": False, "tool": name, "ms": ms, "error": err, "result": data}
            data.setdefault("ok", True)
            S.log(f"[tool] {name} ok {ms}ms args={_short(args)[:120]}")
            return {"ok": True, "tool": name, "ms": ms, "result": data}
    except Exception as e:  # pragma: no cover
        ms = int((time.time() - started) * 1000)
        S.log(f"[tool] {name} failed: {e!r}")
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "ms": ms}


async def call(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """所有工具调用都从这里过：先执行，再把真实结果写进她的能力证据。"""
    one = await _call_impl(name, args)
    try:
        from . import self_store
        self_store.record_tool(str(name), dict(args or {}), one)
    except Exception as e:  # pragma: no cover
        S.log(f"[self] record tool failed: {e!r}")
    return one


def feedback(one: Dict[str, Any]) -> str:
    """把工具结果变成给她看的一小段话。"""
    if not one.get("ok"):
        return f"（工具没成功：{one.get('error')}）照实说没查到，别编。"
    if one.get("ok") and isinstance(one.get("result"), dict) and one["result"].get("ok") is False:
        return "（工具返回失败：" + _short(one["result"]) + "）这就是真实结果，别当成做成了。"
    res = one.get("result")
    return "（工具返回：" + _short(res) + "）用这个结果回我一句，别把这些字段名念出来。"
