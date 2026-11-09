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
from pathlib import Path
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
    """内核自己给的工具（不依赖模组）：头像、眼睛、仓库。"""
    from . import sense

    out: Dict[str, Dict[str, Any]] = {
        "module_status": {
            "name": "module_status",
            "module": "self",
            "module_name": "自己",
            "hint": "看看模组现在都什么状况：谁开着、谁掉线了、为什么",
            "args": {},
            "method": "POST",
            "url": "",
            "builtin": "module_status",
            "max_seconds": 5.0,
        },
        "warehouse_list": {
            "name": "warehouse_list",
            "module": "self",
            "module_name": "自己",
            "hint": "看仓库里有什么：对方发来的、你自己收着的、模组给的，都能列",
            "args": {"kind": "image|document|file?", "query": "按文件名找?",
                     "library": "库 id?（不填就列全部）"},
            "method": "POST",
            "url": "",
            "builtin": "warehouse_list",
            "max_seconds": 5.0,
        },
        "warehouse_search": {
            "name": "warehouse_search",
            "module": "self",
            "module_name": "自己",
            "hint": "翻仓库：按标题/描述/标签/为什么留着找，尤其适合找自己收过的东西",
            "args": {"query": "要找的词", "kind": "image|document|file?",
                     "library": "库 id?"},
            "method": "POST",
            "url": "",
            "builtin": "warehouse_search",
            "max_seconds": 5.0,
        },
        "warehouse_inspect": {
            "name": "warehouse_inspect",
            "module": "self",
            "module_name": "自己",
            "hint": "先看懂一条：图片说出内容、文本给摘要、文档给基本信息；收下/发出前先做",
            "args": {"id": "仓库条目的 id 或文件名"},
            "method": "POST",
            "url": "",
            "builtin": "warehouse_inspect",
            "max_seconds": 130.0,
        },
        "warehouse_keep": {
            "name": "warehouse_keep",
            "module": "self",
            "module_name": "自己",
            "hint": "看完觉得值得留，就复制进自己的收藏，并记一笔“为什么留”",
            "args": {"id": "仓库条目的 id 或文件名", "title": "你给它起的名字?",
                     "desc": "它是什么?", "why": "为什么留?", "tags": "标签数组?"},
            "method": "POST",
            "url": "",
            "builtin": "warehouse_keep",
            "max_seconds": 15.0,
        },
        "warehouse_read": {
            "name": "warehouse_read",
            "module": "self",
            "module_name": "自己",
            "hint": "读仓库里一个文本文件（txt/md/csv/json 等）；PDF/DOCX 只存不读",
            "args": {"id": "仓库条目的 id 或文件名"},
            "method": "POST",
            "url": "",
            "builtin": "warehouse_read",
            "max_seconds": 20.0,
        },
        "warehouse_forget": {
            "name": "warehouse_forget",
            "module": "self",
            "module_name": "自己",
            "hint": "把收藏里的某一条删掉（只删收藏，不删记忆）",
            "args": {"id": "仓库条目的 id 或文件名"},
            "method": "POST",
            "url": "",
            "builtin": "warehouse_forget",
            "max_seconds": 10.0,
        },
        "see_image": {
            "name": "see_image",
            "module": "self",
            "module_name": "自己",
            "hint": "看仓库里的一张图，并说出你看到了什么（可以用它回答对方）",
            "args": {"id": "仓库条目的 id 或文件名", "question": "可选：你想在画面里找什么"},
            "method": "POST",
            "url": "",
            "builtin": "see_image",
            "max_seconds": 130.0,
        },
        "send_media": {
            "name": "send_media",
            "module": "self",
            "module_name": "自己",
            "hint": "从收藏里挑一张图或一个文件发到聊天；必须先 warehouse_inspect 看过",
            "args": {"id": "仓库条目的 id 或文件名", "caption": "可选：附一句话"},
            "method": "POST",
            "url": "",
            "builtin": "send_media",
            "max_seconds": 10.0,
        },
        "avatar_see": {
            "name": "avatar_see",
            "module": "self",
            "module_name": "自己",
            "hint": "看你自己的头像（对方可能换过），这样你才知道自己现在长什么样",
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
            "module_name": "自己",
            "hint": "看一眼对方那边（摄像头优先，没选就看屏幕），回来告诉你看到了什么",
            "args": {"question": "可选：你想在画面里找什么"},
            "method": "POST",
            "url": "",
            "builtin": "look_around",
            "max_seconds": 130.0,
        }
    return out

_MEDIA: Dict[str, list] = {}


def queue_media(session: str, item: Dict[str, Any]) -> None:
    """记录她这一轮要发到聊天里的仓库文件，reply() 收尾时落成 assistant 轮。"""
    key = str(session or "web:owner")
    bucket = _MEDIA.setdefault(key, [])
    if len(bucket) < 4:
        bucket.append(dict(item))


def take_media(session: str) -> list:
    return _MEDIA.pop(str(session or "web:owner"), [])


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


async def _call_impl(name: str, args: Dict[str, Any], session: str = "") -> Dict[str, Any]:
    items = tools()
    spec = items.get(name)
    if not spec:
        return {"ok": False, "error": f"没有这个工具：{name}", "tools": list(items)}
    builtin = spec.get("builtin")
    if builtin == "look_around":
        started = time.time()
        try:
            from . import sense

            res = await asyncio.to_thread(
                sense.look, str(args.get("question") or args.get("q") or ""))
            ms = int((time.time() - started) * 1000)
            S.log(f"[tool] {name} ok {ms}ms")
            return {"ok": True, "tool": name, "ms": ms, "result": res}
        except Exception as e:  # noqa: BLE001
            ms = int((time.time() - started) * 1000)
            S.log(f"[tool] {name} failed: {e!r}")
            return {"ok": False, "tool": name, "ms": ms,
                    "error": str(e).strip() or type(e).__name__}
    if builtin == "module_status":
        rows = []
        for m in modules_box.modules():
            mid = str(m.get("id") or "")
            rows.append({
                "id": mid,
                "name": str(m.get("name") or mid),
                "state": str(m.get("state") or ""),
                "health": str(m.get("last_health") or ""),
                "last_ok": str(m.get("last_ok") or ""),
                "last_error": str(m.get("last_error") or "")[:300],
                "port": m.get("runtime_port") or ((m.get("ports") or [0])[0] if m.get("ports") else 0),
                "pid": m.get("pid") or 0,
            })
        return {"ok": True, "tool": name,
                "result": {"ok": True, "count": len(rows), "modules": rows}}
    if builtin in ("warehouse_list", "warehouse_search"):
        from . import warehouse

        lib = str(args.get("library") or "").strip() or None
        try:
            rows = warehouse.list_items(kind=str(args.get("kind") or ""),
                                        query=str(args.get("query") or args.get("q") or ""),
                                        library=lib)
        except (OSError, ValueError) as e:
            return {"ok": False, "tool": name, "error": f"{type(e).__name__}: {e}"}
        return {"ok": True, "tool": name,
                "result": {"ok": True, "count": len(rows), "items": rows[:60]}}
    if builtin == "warehouse_inspect":
        from . import warehouse

        ref = str(args.get("id") or args.get("name") or args.get("ref") or "")
        row = warehouse.resolve(ref)
        if not row or not row.get("path"):
            return {"ok": False, "tool": name, "error": "仓库里没有这一条"}
        if not warehouse.is_inside(row["path"]):
            return {"ok": False, "tool": name, "error": "这个文件不在仓库里"}
        ext = str(row.get("ext") or "").lower()
        desc, preview, readable = "", "", False
        try:
            if str(row.get("kind")) == "image":
                from . import llm_box

                desc = await llm_box.describe_image(
                    str(row["path"]),
                    "描述这张图：画面里有什么、气氛/风格、有没有文字；两三句，具体一点。")
                preview, readable = desc[:300], True
            elif ext in warehouse.TEXT_EXTS:
                data = warehouse.read_text(str(row["id"]))
                text = str(data.get("text") or "")
                desc = text.strip().splitlines()[0][:160] if text.strip() else "空文本"
                preview, readable = text[:400], True
            else:
                desc = f"{row.get('kind')} {ext}，{int(row.get('bytes') or 0) // 1024} KB；这一类只存不读正文"
        except (OSError, ValueError, TypeError, RuntimeError) as e:
            return {"ok": False, "tool": name, "error": f"{type(e).__name__}: {e}"}
        try:
            meta = warehouse.update_meta(str(row["id"]), desc=desc, preview=preview,
                                         readable=readable, inspected_at=time.time())
        except ValueError as e:
            return {"ok": False, "tool": name, "error": str(e)}
        return {"ok": True, "tool": name,
                "result": {"ok": True, **meta}}
    if builtin == "warehouse_keep":
        from . import memory_box, warehouse

        ref = str(args.get("id") or args.get("name") or args.get("ref") or "")
        row = warehouse.resolve(ref)
        if not row:
            return {"ok": False, "tool": name, "error": "仓库里没有这一条"}
        if not row.get("inspected_at"):
            return {"ok": False, "tool": name,
                    "error": "先用 warehouse_inspect 看过，再决定留不留"}
        title = str(args.get("title") or "").strip()[:80]
        desc = str(args.get("desc") or "").strip()[:400]
        why = str(args.get("why") or "").strip()[:300]
        raw_tags = args.get("tags") or []
        tags = [str(t).strip()[:24] for t in raw_tags if str(t).strip()][:8] \
            if isinstance(raw_tags, list) else []
        try:
            kept = warehouse.keep(str(row["id"]), title=title, desc=desc, why=why, tags=tags)
        except ValueError as e:
            return {"ok": False, "tool": name, "error": str(e)}
        text = (f"我收下了一件东西《{kept.get('title') or kept.get('name')}》："
                f"{kept.get('desc') or '（还没写是什么）'}。"
                f"为什么留着：{why or '（还没写）'}。（收藏 {kept.get('id')}）")
        try:
            note = memory_box.add_note(text, scope="owner", program="program_web")
            warehouse.update_meta(str(kept["id"]), memory_id=str(note.get("id") or ""))
        except (OSError, ValueError) as e:
            S.log(f"[warehouse] keep memory failed: {e!r}")
        return {"ok": True, "tool": name,
                "result": {"ok": True, "kept": kept, "memory": text}}
    if builtin == "warehouse_forget":
        from . import warehouse

        ref = str(args.get("id") or args.get("name") or args.get("ref") or "")
        row = warehouse.resolve(ref)
        if not row:
            return {"ok": False, "tool": name, "error": "仓库里没有这一条"}
        if row.get("library") != warehouse.AGENT_LIB:
            return {"ok": False, "tool": name, "error": "只能删自己收着的东西"}
        return {"ok": True, "tool": name,
                "result": {"ok": warehouse.remove(str(row["id"])), "id": row["id"]}}
    if builtin in ("warehouse_read", "see_image", "send_media"):
        from . import warehouse

        ref = str(args.get("id") or args.get("name") or args.get("ref") or "")
        row = warehouse.resolve(ref)
        if not row or not row.get("path"):
            return {"ok": False, "tool": name, "error": "仓库里没有这一条"}
        if not warehouse.is_inside(row["path"]):
            return {"ok": False, "tool": name, "error": "这个文件不在仓库里"}
        if builtin == "warehouse_read":
            try:
                data = warehouse.read_text(str(row["id"]))
            except ValueError as e:
                return {"ok": False, "tool": name, "error": str(e)}
            return {"ok": True, "tool": name, "result": data}
        if not Path(str(row["path"])).is_file():
            return {"ok": False, "tool": name, "error": "文件已经不在仓库里了"}
        if builtin == "see_image":
            if str(row.get("kind") or "") != "image":
                return {"ok": False, "tool": name, "error": "这一条不是图片"}
            try:
                from . import llm_box

                text = await llm_box.describe_image(
                    str(row["path"]),
                    str(args.get("question") or args.get("q") or "描述这张图，先说看到什么，再回答对方可能关心的点。"),
                )
            except (OSError, ValueError, TypeError, RuntimeError) as e:
                return {"ok": False, "tool": name, "error": f"{type(e).__name__}: {e}"}
            try:
                warehouse.update_meta(str(row["id"]), desc=text[:400], preview=text[:300],
                                      readable=True, inspected_at=time.time())
            except ValueError:
                pass
            return {"ok": True, "tool": name,
                    "result": {"ok": True, "id": row["id"], "name": row["name"], "text": text}}
        if not row.get("inspected_at"):
            return {"ok": False, "tool": name,
                    "error": "先 warehouse_inspect 看过，确认它是什么再发"}
        caption = str(args.get("caption") or "").strip()[:200]
        queue_media(session, {**row, "caption": caption})
        return {"ok": True, "tool": name,
                "result": {"ok": True, "queued": True, "id": row["id"], "name": row["name"],
                           "kind": row.get("kind"), "caption": caption,
                           "desc": row.get("desc") or ""}}
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


async def call(name: str, args: Dict[str, Any], session: str = "") -> Dict[str, Any]:
    """所有工具调用都从这里过：先执行，再把真实结果写进她的能力证据。"""
    one = await _call_impl(name, args, session=session)
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
