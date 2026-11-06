"""无名的常驻内核（entity_core）HTTP 服务。

跑起来之后：
- 网页客厅   http://127.0.0.1:40720/
- 健康检查   /health
- 状态       /state
- 说话       POST /chat   {"session":"web:owner","text":"在吗"}
- 世界事件   POST /event  {"kind":"qzone_like","text":""}
- 记忆       GET /memory?q=...&session=...   POST /memory/note

她活着不依赖任何门：QQ 关了、B 站没开，这个进程仍然在跑、在长情绪、在记事。
"""
from __future__ import annotations

import asyncio
import time
import os
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import (auth, brain_box, bridge, chat_core, drives, emotion_core, event_bus, followup,
               modules_box, tts,
               llm_box, maintenance, memory_box, memory_store, nanny, persona_drift, presence,
               proactive, registry_box, self_reflect, self_store, self_trials, sense,
               settings as S, stomach_box, style_box, tool_bus, tutorial)

# 可选模组：B 站门（bili_door.py 由 bili_bridge 模组装进来，没装就跳过）
try:
    from . import bili_door  # type: ignore
except Exception:  # pragma: no cover
    bili_door = None

# 模组没启用就当作没装（bili_door.py 可能还留在 core 里）
if bili_door is not None:
    try:
        from . import modules_box as _mb

        _bili_on = any(
            str(m.get("id")) == "bili_bridge" and str(m.get("state")) == "enabled"
            for m in _mb.modules()
        )
    except Exception:  # noqa: BLE001
        _bili_on = False
    if not _bili_on:
        S.log("[bili] module disabled -> door skipped")
        bili_door = None

BILI_HINT = r"B 站模组没装载（把它装回来就有了）"


def _need_bili() -> None:
    if bili_door is None:
        raise HTTPException(status_code=503, detail=BILI_HINT)

STARTED = time.time()


class ChatIn(BaseModel):
    session: str = "web:owner"
    text: str = ""
    sender_name: str = ""
    is_owner: bool | None = None


class EventIn(BaseModel):
    kind: str = "msg"
    text: str = ""
    is_owner: bool | None = None


class NoteIn(BaseModel):
    text: str
    scope: str = "owner"
    group: str | None = None
    friend: str | None = None
    program: str = "program_qq"


async def _tick_loop() -> None:
    S.log("[tick] brain clock started")
    brain_box.ensure()
    n = 0
    while True:
        await asyncio.sleep(S.TICK_SECONDS)
        evs = brain_box.drain_inbox()
        if evs:
            S.log(f"[tick] inbox {len(evs)} events")
        _t0 = time.time()
        await asyncio.to_thread(brain_box.run, S.TICK_BIOTIC)
        n += 1
        try:
            _st = brain_box.state()
            _emo = _st.get("emotions") or {}
            _acted = await drives.act()
            if _acted.get("acted"):
                S.log(f"[tick] 自己找事做 -> {_acted.get('text','')[:40]}")
            _dr = drives.poll()
            _names = ",".join(d["name"] for d in _dr.get("active", [])[:3]) or "-"
            S.log("[tick] #%d bio=+%.0fs %.2fs mood=%s joy=%.3f fear=%.3f bored=%.3f energy=%.3f inbox=%d drives=%s"
                  % (n, S.TICK_BIOTIC, time.time() - _t0, _st.get("mood_line") or "-",
                     float(_emo.get("joy", 0)), float(_emo.get("fear", 0)),
                     float(_emo.get("boredom", 0)), float(_emo.get("energy", 0)),
                     len(evs), _names))
        except Exception as e:
            S.log(f"[tick] log error: {e!r}")
        try:
            _obs = await asyncio.to_thread(sense.auto_observe)
            if _obs:
                S.log(f"[sense] auto observe {len(_obs)} 条")
        except Exception as e:
            S.log(f"[tick] sense observe error: {e!r}")
        try:
            if self_trials.due():
                asyncio.create_task(self_trials.maybe_try())
        except Exception as e:
            S.log(f"[tick] self trial error: {e!r}")
        try:
            _trig = "idle" if proactive.idle_status().get("due") else ""
            _p = await proactive.maybe_send(trigger=_trig)
            if _p.get("sent"):
                S.log(f"[tick] 她主动开口（{_trig or 'drive'}）：{str(_p.get('text'))[:40]}")
        except Exception as e:
            S.log(f"[tick] proactive error: {e!r}")
        try:
            _cfg = bili_door.config() if bili_door is not None else {}
            if _cfg.get("enabled"):
                _st = S.read_json(bili_door.STATE_PATH, {}) or {}
                _lp = str(_st.get("last_poll") or "")
                _age = 10 ** 6
                if _lp:
                    try:
                        _age = (datetime.now() - datetime.fromisoformat(_lp).replace(tzinfo=None)).total_seconds()
                    except Exception:
                        _age = 10 ** 6
                if _age > 900:
                    _r = await bili_door.poll_once()
                    S.log(f"[tick] bili watchdog: last_poll {_age/60:.0f} 分钟前，补轮询 handled={_r.get('handled')}")
        except Exception as e:
            S.log(f"[tick] bili watchdog error: {e!r}")
        try:
            # 插话：她说完了、你还没回——到点就补一句。
            # 主动程度在设置页（0 关 / 1 克制 / 2 正常 / 3 黏人），存 entity\config\followup.json。
            if followup.enabled() and presence.is_online():
                for _sess in followup.tracker.pending_sessions():
                    _d = followup.tracker.due(_sess)
                    if not _d:
                        continue
                    _prof = followup.tracker.state(_sess).get("profile") or {}
                    _t = await chat_core.say_extra(_sess, int(_d.get("max_chars") or 18),
                                                   tone=str(_prof.get("tone") or ""))
                    if _t:
                        S.log(f"[followup] {_sess} 补了一句（第 {_d['extra']} 次）：{_t[:30]}")
        except Exception as e:
            S.log(f"[tick] followup error: {e!r}")
        try:
            _m = await asyncio.to_thread(maintenance.tick)
            if (_m.get("ingest") or {}).get("added"):
                S.log(f"[tick] maintenance ingest={_m.get('ingest')}")
        except Exception as e:
            S.log(f"[tick] maintenance error: {e!r}")
        if n % 4 == 0:
            brain_box.save()
            S.log(f"[tick] {n} rounds, mood={brain_box.state().get('mood_line')}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    S.ensure_dirs()
    auth.token()
    S.log(f"[core] starting on {S.HOST}:{S.PORT}")
    try:
        import json as _json
        _inst = S.STATE_DIR / "instance.json"
        _inst.parent.mkdir(parents=True, exist_ok=True)
        _inst.write_text(_json.dumps({
            "root": str(S.ROOT), "port": S.PORT, "pid": os.getpid(),
            "started": datetime.now().isoformat(timespec="seconds"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as _e:  # noqa: BLE001
        S.log(f"[core] 写 instance.json 失败：{_e!r}")
    brain_box.ensure()
    event_bus.bind(asyncio.get_running_loop())
    tasks = [asyncio.create_task(_tick_loop()), asyncio.create_task(nanny.watch_loop())]
    if bili_door is not None:
        tasks.append(asyncio.create_task(bili_door.loop()))
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        chat_core.save_sessions()
        brain_box.save()
        S.log("[core] stopped")


app = FastAPI(title="无名 entity_core", lifespan=lifespan)
app.include_router(bridge.router)


@app.middleware("http")
async def _local_auth(request: Request, call_next):
    """本机 token 闸：/health 与 /bridge/* 以外都要带 X-BAB-Core-Token。"""
    if auth.public(request.url.path):
        return await call_next(request)
    if auth.ok(request):
        return await call_next(request)
    # 网页客厅：/?token=<core_token> 首次进入时换 cookie，之后同源 fetch 自动带上。
    if request.url.path == "/":
        qt = str(request.query_params.get("token") or "")
        if auth.matches(qt):
            resp = await call_next(request)
            resp.set_cookie(auth.COOKIE, qt, httponly=True, samesite="strict")
            return resp
    return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

STATIC = Path(__file__).with_name("static")


@app.get("/", response_class=HTMLResponse)
async def index():
    try:
        return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))
    except Exception:
        return HTMLResponse("<h1>无名内核在线</h1>", status_code=200)


@app.get("/health")
async def health():
    st = brain_box.state()
    return {
        "ok": True, "configured": S.configured()[0],
        # 这份内核服务的是哪份安装：同一个 40720 上可能跑着"另一份"，
        # 那样壳的 Key 与人格它读不到，保姆就会报 no api key。
        "root": str(S.ROOT),
        "entity": S.entity_name(),
        "llm": str(S.ENTITY / "config" / "llm.json"),
        "has_key": bool(S.deepseek_key()),
        "port": S.PORT,
        "uptime": round(time.time() - STARTED, 1),
        "brain_ready": bool(st.get("ready")),
        "mood": st.get("mood_line", ""),
        "notes": memory_box.total_notes(),
        "sessions": len(chat_core._sessions) if chat_core._loaded else "-",
    }


class TtsIn(BaseModel):
    text: str = ""
    voice: str = ""
    rate: str = ""
    use: str = ""          # chat（朗读）| preview（试听）
    engine: str = ""       # edge | breezeblue | local，聊天朗读用
    preview_engine: str = ""  # edge | breezeblue | local，试听用
    bb_base: str = ""
    bb_key: str = ""
    bb_voice: str = ""
    bb_model: str = ""
    local_url: str = ""
    local_voice: str = ""
    local_ref: str = ""


@app.get("/tts/voices")
def tts_voices():
    return {"ok": True, "voices": tts.VOICES, "config": tts.cfg()}


@app.post("/tts/config")
def tts_config(inp: TtsIn):
    patch: dict = {"voice": inp.voice, "rate": inp.rate}
    for k in ("engine", "preview_engine", "bb_base", "bb_key", "bb_voice", "bb_model",
              "local_url", "local_voice", "local_ref"):
        v = getattr(inp, k, "")
        if v or k == "local_ref":
            patch[k] = v
    return {"ok": True, "config": tts.save_cfg(patch)}


@app.post("/tts")
def tts_say(inp: TtsIn):
    """合成一句，按引擎回 audio/wav 或 audio/mpeg；失败回 502 + 说明。"""
    purpose = "preview" if str(inp.use or "").strip().lower() == "preview" else "chat"
    try:
        path = tts.synth_sync(inp.text, inp.voice, inp.rate, purpose)
    except Exception as e:  # noqa: BLE001
        why = str(e).strip() or type(e).__name__
        raise HTTPException(502, f"合成失败：{why}") from e
    wav = str(path).lower().endswith(".wav")
    return FileResponse(str(path), media_type="audio/wav" if wav else "audio/mpeg",
                        filename="say.wav" if wav else "say.mp3")


class VisionIn(BaseModel):
    path: str = ""
    image: str = ""
    question: str = ""


class AsrIn(BaseModel):
    path: str = ""
    audio: str = ""
    hint: str = ""


@app.post("/vision")
async def vision_see(inp: VisionIn):
    """给启动器的耳目用：看一眼图，回文字描述（模型与 Key 都在内核这边）。"""
    src = (inp.image or inp.path or "").strip()
    if not src:
        raise HTTPException(400, "要看哪张图？path 或 image 给一个")
    try:
        text = await llm_box.describe_image(src, inp.question or "这张图里有什么？")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"看不了：{str(e).strip() or type(e).__name__}") from e
    return {"ok": True, "text": text}


@app.post("/asr")
def asr_hear(inp: AsrIn):
    """给启动器的耳目用：把一段录音转成文字（复用语音小服务）。"""
    return bridge._voice_asr("launcher", path=inp.path, audio=inp.audio, hint=inp.hint)


class StyleIn(BaseModel):
    text: str = ""


class StyleApplyIn(BaseModel):
    doc: dict = {}


@app.get("/style/custom")
def style_custom():
    doc = style_box.load()
    return {"ok": True, "active": doc is not None, "style": doc,
            "face": style_box.face_spec(doc)}


@app.post("/style/analyze")
async def style_analyze(inp: StyleIn):
    try:
        doc = await style_box.analyze(inp.text)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"分析失败：{str(e).strip() or type(e).__name__}") from e
    return {"ok": True, "style": doc, "face": style_box.face_spec(doc)}


@app.post("/style/apply")
def style_apply(inp: StyleApplyIn):
    try:
        doc = style_box.apply(inp.doc or {})
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"保存失败：{str(e).strip() or type(e).__name__}") from e
    return {"ok": True, "style": doc, "face": style_box.face_spec(doc)}


@app.post("/style/clear")
def style_clear():
    style_box.clear()
    return {"ok": True, "active": False, "face": style_box.face_spec(None)}


@app.get("/style/face")
def style_face():
    return {"ok": True, **style_box.face_spec()}


class FollowupIn(BaseModel):
    level: int | None = None


@app.get("/followup/config")
def followup_get():
    lv = followup.level()
    return {
        "ok": True,
        "config": {"level": lv, "enabled": lv > 0},
        "levels": [{"level": k, "name": v["name"], "label": v["label"]}
                   for k, v in sorted(followup.LEVELS.items())],
    }


@app.post("/followup/config")
def followup_set(inp: FollowupIn):
    cur = followup.save_cfg({"level": inp.level})
    return {"ok": True, "config": {"level": cur["level"], "enabled": cur["level"] > 0}}


@app.get("/ports")
def ports_map():
    """这个安装的端口地图（谁在哪个口、模组池里谁占着）。"""
    mods = []
    for m in modules_box.enabled():
        mid = str(m.get("id") or "")
        man_ports = modules_box.manifest(mid).get("ports") or [0]
        mods.append({
            "id": mid, "name": m.get("name"), "state": m.get("state"),
            "port": m.get("runtime_port") or man_ports[0],
        })
    return {"ok": True, "install_id": S.INSTALL_ID, "base": S.BASE_PORT,
            "core": S.PORT, "asr": S.ASR_PORT, "modules": mods}


@app.get("/tools")
async def tools():
    """她现在真能调的工具：模组 connection.json 的 tools -> endpoints。"""
    items = tool_bus.tools()
    return {"ok": True, "count": len(items),
            "tools": {k: {"url": v["url"], "module": v["module_name"]} for k, v in items.items()}}


@app.get("/brain/fragment")
async def brain_fragment():
    """给别的程序（AstrBot 插件等）取"脑子里现在"的提示词片段。"""
    st = brain_box.state()
    return {
        "fragment": brain_box.prompt_fragment(),
        "mood": st.get("mood_line", ""),
        "emotions": st.get("emotions", {}),
        "ready": bool(st.get("ready")),
    }


@app.get("/brain/state")
async def brain_state():
    return brain_box.state()


@app.get("/stomach")
async def stomach():
    """胃：余额 → 饱不饱。给别的程序（AstrBot 的 brain 插件）读。"""
    return {"state": stomach_box.state(), "fragment": stomach_box.fragment()}


@app.post("/stomach/poll")
async def stomach_poll():
    return stomach_box.poll_if_due(force=True) or {}


@app.get("/stomach/config")
async def stomach_config():
    """饱 / 饿两个分界（元）。设置页用它填两个框。"""
    return stomach_box.config()


class StomachCfgIn(BaseModel):
    full_at: float = 10.0
    hungry_at: float = 3.0


@app.post("/stomach/config")
async def stomach_config_set(inp: StomachCfgIn):
    try:
        cfg = stomach_box.set_config(inp.full_at, inp.hungry_at)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")
    st = stomach_box.poll_if_due(force=True) or {}
    return {"ok": True, "config": cfg, "state": st}


@app.post("/brain/stimulate")
async def brain_stimulate(inp: EventIn):
    if inp.text:
        brain_box.stimulate_text(inp.text, bool(inp.is_owner))
    else:
        brain_box.stimulate(inp.kind or "msg")
    return {"ok": True, "mood": brain_box.state().get("mood_line", "")}


@app.get("/state")
async def state():
    st = brain_box.state()
    st["notes"] = memory_box.counts()
    st["bili"] = bili_door.config() if bili_door is not None else {"installed": False}
    st["uptime"] = round(time.time() - STARTED, 1)
    return st


async def _emit(kind: str, data: dict | None = None) -> dict:
    """发一条事件：进总线，同时推给订阅了的模组（推失败不影响主流程）。"""
    rec = event_bus.publish(kind, data or {})
    try:
        await bridge.fanout(rec)
    except Exception as e:  # noqa: BLE001
        S.log(f"[bridge] fanout 失败：{e!r}")
    return rec

def _ensure_configured() -> None:
    ok, hint = S.configured()
    if not ok:
        raise HTTPException(status_code=503, detail="还没配置：" + hint)


@app.post("/chat")
async def chat(inp: ChatIn):
    if not inp.text.strip():
        raise HTTPException(400, "empty text")
    _ensure_configured()
    before = emotion_core.mood_word()
    await _emit("message.in", {"session": inp.session, "text": inp.text[:500],
                               "is_owner": bool(inp.is_owner)})
    out = await chat_core.reply(inp.session, inp.text, is_owner=inp.is_owner,
                                sender_name=inp.sender_name)
    await _emit("message.out", {"session": inp.session,
                                "text": str(out.get("reply") or "")[:500],
                                "messages": out.get("messages") or []})
    after = emotion_core.mood_word()
    if after != before:
        await _emit("mood.changed", {"from": before, "to": after})
    try:
        self_store.observe_exchange(inp.text, str(out.get("reply") or ""))
        self_store.note_turn()
        if self_store.due():
            asyncio.create_task(self_reflect.maybe_reflect(
                inp.session, chat_core.get_history(inp.session)))
    except Exception as e:  # noqa: BLE001
        S.log(f"[self] schedule reflect failed: {e!r}")
    return out


class PresenceIn(BaseModel):
    state: str = "busy"


@app.get("/presence")
async def presence_get():
    st = presence.get()
    return {"state": st["state"], "label": presence.label(),
            "updated_at": st.get("updated_at", ""), "proactive": proactive.status()}


@app.get("/proactive/last")
async def proactive_last():
    return {"ok": True, **proactive.last()}


@app.get("/self")
async def self_status():
    return {"ok": True, **self_store.status(), "trials": self_trials.status()}


class SelfCalIn(BaseModel):
    text: str = ""


@app.post("/self/reflect")
async def self_reflect_now(session: str = "web:owner", force: int = 1):
    res = await self_reflect.reflect(session, chat_core.get_history(session),
                                     force=bool(force))
    return res


@app.post("/self/calibrate")
async def self_calibrate(inp: SelfCalIn):
    text = (inp.text or "").strip()
    if not text:
        raise HTTPException(400, "empty text")
    self_store.calibrate(text)
    return {"ok": True, "status": self_store.status()}


class SelfTryIn(BaseModel):
    ability: str = ""
    consent: str = "L0"


@app.post("/self/try")
async def self_try(inp: SelfTryIn):
    return await self_trials.try_once(inp.ability, inp.consent)


@app.post("/presence")
async def presence_set(inp: PresenceIn):
    before = presence.get().get("state")
    presence.set_state(inp.state, source="desktop")
    st = presence.get()
    if before != "online" and st.get("state") == "online":
        async def _hello() -> None:
            try:
                await proactive.maybe_send(trigger="online")
            except Exception as e:  # noqa: BLE001
                S.log(f"[presence] online proactive error: {e!r}")
        asyncio.create_task(_hello())
    await _emit("presence.changed", {"state": st.get("state")})
    return {"ok": True, "state": st["state"], "label": presence.label(),
            "updated_at": st.get("updated_at", "")}


@app.get("/notices")
async def get_notices(session: str = "web:owner", after: float = 0.0):
    return {"ok": True, "notices": chat_core.notices(session, after)}


class NoticeIn(BaseModel):
    text: str = ""
    session: str = "web:owner"
    kind: str = "nanny"


@app.post("/notice")
async def post_notice(inp: NoticeIn):
    """外壳自己产生的保姆提醒（比如「对方被打断」）也落盘，重启后还在。"""
    row = chat_core.push_notice(inp.session, inp.text, kind=inp.kind)
    return {"ok": True, "notice": row}


@app.get("/chat/feed")
async def chat_feed(session: str = "web:owner", after: int = 0):
    return chat_core.feed(session, after)


@app.post("/proactive/send")
async def proactive_send(force: int = 1):
    res = await proactive.maybe_send(force=bool(force))
    await _emit("proactive.spoke", {"silent": bool(res.get("silent")),
                                    "text": str(res.get("text") or "")[:500]})
    return res


@app.post("/event")
async def event(inp: EventIn):
    kind = inp.kind or "msg"
    if inp.text:
        brain_box.stimulate_text(inp.text, bool(inp.is_owner) if inp.is_owner is not None else kind in ("msg", "owner_msg", "moments"))
    else:
        brain_box.stimulate("msg" if kind in ("msg", "owner_msg") else kind)
    return {"ok": True, "mood": brain_box.state().get("mood_line", "")}


@app.get("/memory")
async def memory(q: str = "", session: str = "web:owner", all: int = 0):
    if all:
        return {"notes": memory_box.search_all(q, 12)}
    return {"notes": memory_box.select(q, session)}


@app.get("/memory/stats")
async def memory_stats():
    return {"ok": True, "stats": memory_store.stats(), "config": memory_store.config()}


class MemoryCfgIn(BaseModel):
    max_gb: float = 2.0
    compress_gb: float = 0.5
    keep_days: int = 60
    allow_zip_archive: bool = True


@app.get("/memory/config")
async def memory_config():
    return {"ok": True, "config": memory_store.config()}


@app.post("/memory/config")
async def memory_config_set(inp: MemoryCfgIn):
    try:
        cfg = memory_store.set_config(
            max_gb=inp.max_gb, compress_gb=inp.compress_gb,
            keep_days=inp.keep_days, allow_zip_archive=inp.allow_zip_archive,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "config": cfg, "stats": memory_store.stats()}


@app.post("/memory/note")
async def memory_note(inp: NoteIn):
    try:
        return memory_box.add_note(inp.text, scope=inp.scope, group=inp.group,
                                   kind_key=inp.friend, program=inp.program)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/persona")
async def persona():
    return {"persona": llm_box.persona()}


@app.get("/programs")
def programs():
    return {"ok": True, "text": registry_box.dump_text(), "items": registry_box.all_programs()}


@app.get("/programs/{name}")
def program_one(name: str):
    p = registry_box.get(name)
    if not p:
        raise HTTPException(404, "no such program")
    return {"ok": True, "item": p}


class OutboxSentIn(BaseModel):
    text: str
    door: str = "qq"
    session: str = "qq:owner"


@app.post("/outbox/sent")
def outbox_sent(body: OutboxSentIn):
    """QQ 侧的 outbox 插件发完之后回调这里，把那句话补进原文（之后照常过 ingest）。"""
    try:
        import datetime as _dt
        memory_store.raw_append(body.session or "qq:owner", body.text, "assistant",
                                ts=_dt.datetime.now(), who="无名")
        S.log(f"[outbox] sent via {body.door}: {body.text[:40]}")
        return {"ok": True}
    except Exception as e:
        S.log(f"[outbox] record failed: {e!r}")
        return {"ok": False, "error": str(e)}


@app.get("/diary")
def diary(days: int = 7, session: str = "qq:owner"):
    return {"ok": True, "days": days, "entries": memory_box.diary(days, session)}


@app.get("/drives")
def drives_status():
    return drives.poll()


@app.get("/drift")
def drift():
    return {"ok": True, "due": persona_drift.due(), "fragment": persona_drift.fragment()}


@app.get("/bili/status")
async def bili_status():
    _need_bili()
    return {"config": bili_door.config(), "state": S.read_json(bili_door.STATE_PATH, {})}


class VideoIn(BaseModel):
    title: str
    url: str = ""
    up: str = ""
    bvid: str = ""
    duration: str = ""
    note: str = ""


@app.post("/bili/video")
async def bili_video(inp: VideoIn):
    """记一条"刷到的视频"到 B 站抽屉。"""
    _need_bili()
    return bili_door.record_video(inp.title, inp.url, inp.up, inp.bvid, inp.duration, inp.note)


@app.get("/bili/videos")
async def bili_videos(n: int = 10):
    _need_bili()
    return {"items": bili_door.recent_videos(max(1, min(n, 50)))}


@app.post("/bili/poll")
async def bili_poll(force: int = 1):
    _need_bili()
    try:
        return await bili_door.poll_once(force=bool(force))
    except Exception as e:
        return JSONResponse({"error": repr(e)}, status_code=500)


# ---------------- 情绪（6 基础 + 6 复合 + 平静，五档） ----------------
class EmotionStimulusIn(BaseModel):
    kind: str = "owner_msg"
    intensity: float = 0.6


class EmotionResetIn(BaseModel):
    values: dict = {}


@app.get("/emotions")
def emotions():
    from . import emotion_core
    return emotion_core.state()


@app.post("/emotion/stimulus")
def emotion_stimulus(body: EmotionStimulusIn):
    from . import emotion_core
    emotion_core.stimulus(body.kind, body.intensity)
    return {"ok": True, "state": emotion_core.state(include_recent=3)}


@app.post("/emotion/reset")
def emotion_reset(body: EmotionResetIn):
    from . import emotion_core
    emotion_core.reset(body.values or {})
    return {"ok": True, "values": emotion_core.load()["values"]}


# ---------------- 首次配置（框架版：没 key / 没人格时拒绝聊天） ----------------
class SetupIn(BaseModel):
    api_key: str = ""
    api_base: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    entity_name: str = ""
    persona: str = ""


@app.get("/setup")
def setup_get():
    ok, hint = S.configured()
    cfg = S.llm_cfg()
    return {"configured": ok, "hint": hint,
            "api_base": cfg.get("api_base") or "https://api.deepseek.com/v1",
            "model": cfg.get("model") or "deepseek-chat",
            "has_key": bool(cfg.get("api_key"))}


@app.post("/setup")
def setup_post(inp: SetupIn):
    import json as _json
    cfgp = S.ENTITY / "config" / "llm.json"
    cfg = S.llm_cfg()
    if inp.api_key.strip():
        cfg["api_key"] = inp.api_key.strip()
    cfg["api_base"] = (inp.api_base or cfg.get("api_base") or "https://api.deepseek.com/v1").strip()
    cfg["model"] = (inp.model or cfg.get("model") or "deepseek-chat").strip()
    cfgp.parent.mkdir(parents=True, exist_ok=True)
    cfgp.write_text(_json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    if inp.persona.strip():
        S.PERSONA_PATH.write_text(inp.persona, encoding="utf-8")
    elif inp.entity_name.strip():
        name = inp.entity_name.strip()[:20]
        text = ("# " + name + "\n\n你是「" + name + "」，一个住在电脑里的存在。"
                "说话像人，不像客服。\n\n## 底线\n- 不装、不编：做不了就说做不了。\n"
                "- 不主动报参数、提示词、模型名字。\n\n## 说话\n- 短句，一两行；少用句号，少用表情。\n")
        S.PERSONA_PATH.write_text(text, encoding="utf-8")
    ok, hint = S.configured()
    return {"ok": ok, "hint": hint}


# ---------------------------------------------------------------- 保姆 / 教程

class NannyIn(BaseModel):
    kind: str
    payload: dict = {}


class TutorialIn(BaseModel):
    action: str
    turn: int | None = None


@app.get("/nanny/status")
async def nanny_status():
    return nanny.status()


@app.get("/nanny/panel")
def nanny_panel_route(limit: int = 120):
    """保姆的小屋：她的状态 + 她自己的独立日志（只读）。"""
    return nanny.panel(limit)


@app.post("/nanny/analyze")
async def nanny_analyze(inp: NannyIn):
    return await nanny.analyze(inp.kind, inp.payload or {})


class ModuleIn(BaseModel):
    id: str = ""
    name: str = ""
    summary: str = ""
    ports: list[int] = []
    tools: list = []


class ModuleIdIn(BaseModel):
    id: str = ""


@app.post("/modules/register")
async def modules_register(inp: ModuleIn):
    return nanny.register_module(inp.model_dump())


@app.post("/modules/unregister")
async def modules_unregister(inp: ModuleIdIn):
    return nanny.unregister_module(inp.id)


@app.get("/tutorial")
async def tutorial_get():
    return tutorial.get()


@app.post("/tutorial")
async def tutorial_post(inp: TutorialIn):
    try:
        return tutorial.update(inp.action, inp.turn)
    except ValueError as e:
        raise HTTPException(400, str(e))
