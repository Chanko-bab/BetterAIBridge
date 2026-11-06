#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""0.3.20 新东西的自检：记忆 A（owner 归一）+ 三个能力（tts/asr/vision）+ 语音服务骨架。

    python tools/test_caps.py

不联网、不下载模型：TTS 的合成、ASR 的转发、看图都打桩，只验接线和边界。
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import types
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "WiseEntity"))

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    if cond:
        PASS.append(name)
    else:
        FAIL.append(name + (f"  [{extra}]" if extra else ""))


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def memory_tests() -> None:
    from entity.core import settings as S

    tmp = Path(tempfile.mkdtemp(prefix="bab-caps-mem-"))
    S.MEM_DIR = tmp / "memory"
    from entity.core import memory_box as mb
    from entity.core import memory_store as ms

    check("memory:owner-door-web", ms.door_of("web:owner") == "owner", ms.door_of("web:owner"))
    check("memory:owner-door-qq", ms.door_of("qq:owner") == "owner")
    check("memory:owner-door-bili", ms.door_of("bili:owner") == "owner")
    check("memory:group-kept", ms.door_of("qq:group:1130026800") == "qq_group_1130026800")
    check("memory:friend-kept", ms.door_of("qq:friend:1602952702") == "qq_friend_1602952702")
    check("memory:bili-other-kept", ms.door_of("bili:other:12076317") == "bili_other_12076317")
    check("memory:is-owner-old", ms.is_owner_door("web_owner") and ms.is_owner_door("bili_owner"))
    check("memory:is-owner-new", ms.is_owner_door("owner"))
    check("memory:is-owner-group-false", not ms.is_owner_door("qq_group_1"))

    ms.append("owner", "我在网页上说的", ts="2026-11-01T10:00:00")
    ms.append("owner", "我在 QQ 上说的", ts="2026-11-01T11:00:00")
    ms.append("qq_group_1", "群里有人说的", ts="2026-11-01T12:00:00")

    owner = ms.entries("qq:owner")
    texts = [r["text"] for r in owner]
    check("memory:owner-sees-both", "我在网页上说的" in texts and "我在 QQ 上说的" in texts, str(texts))
    group = ms.entries("qq:group:1")
    check("memory:group-isolated", [r["text"] for r in group] == ["群里有人说的"])
    check("memory:visible-owner", ms.visible_doors("web:owner")[0] == "owner")
    check("memory:visible-group", ms.visible_doors("qq:group:1") == ["qq_group_1"])

    # 旧门还在盘上 → 也要读得到（迁移前的老记忆不能丢）
    ms.append("web_owner", "这是 0.3.19 之前记的", ts="2026-10-31T09:00:00")
    check("memory:legacy-door-listed", "web_owner" in ms.owner_doors(), str(ms.owner_doors()))
    old_texts = [r["text"] for r in ms.entries("web:owner")]
    check("memory:legacy-readable", "这是 0.3.19 之前记的" in old_texts, str(old_texts[:5]))

    # 压过的记忆：多扇门的 summary 都要能被她想起来
    for door, line in (("owner", "- 新近压过的一条"), ("web_owner", "- 旧门压过的一条")):
        d = S.MEM_DIR / "_summary" / door
        d.mkdir(parents=True, exist_ok=True)
        (d / "2026-10.md").write_text("# 压过的\n\n" + line + "\n", encoding="utf-8")
    frag = mb.fragment("最近怎么样", "qq:owner")
    check("memory:fragment-merges-summary",
          "新近压过的一条" in frag and "旧门压过的一条" in frag, frag[:200])


def caps_tests() -> None:
    from entity.core import bridge, llm_box, settings as S, tts

    for name in ("voice.tts", "voice.asr", "vision.describe"):
        check(f"caps:has-{name}", name in bridge.CAPS)
        check(f"caps:desc-{name}", bool((bridge.CAPS.get(name) or {}).get("desc")))

    # 没申请的模组不能调
    orig_cfg = bridge._bridge_cfg
    bridge._bridge_cfg = lambda mid: {"wants": ["chat.say"]}
    try:
        ok_tts, _ = bridge._allowed("m", "voice.tts")
        ok_say, _ = bridge._allowed("m", "chat.say")
    finally:
        bridge._bridge_cfg = orig_cfg
    check("caps:want-denied", not ok_tts and ok_say)

    # "*" = 框架类模组申请所有能力（含以后新加的），不用每加一条就改清单
    bridge._bridge_cfg = lambda mid: {"wants": ["*"]}
    try:
        ok_star, _ = bridge._allowed("m_framework", "vision.describe")
        ok_future, _ = bridge._allowed("m_framework", "future.cap")
    finally:
        bridge._bridge_cfg = orig_cfg
    check("caps:want-star", ok_star and ok_future)

    # --- TTS：合成打桩，只验接线、限流、长度
    tmp = Path(tempfile.mkdtemp(prefix="bab-caps-tts-"))
    fake = tmp / "a.mp3"
    fake.write_bytes(b"\xff\xfb" + b"\x00" * 24000)
    orig_synth = tts.synth_sync
    tts.synth_sync = lambda text, voice="", rate="": fake
    bridge._TTS_HITS.clear()
    try:
        one = bridge._voice_tts("m", text="你好呀", voice="x", rate="+0%")
        check("caps:tts-path", str(one.get("path")) == str(fake))
        check("caps:tts-chars", one.get("chars") == 3)
        check("caps:tts-duration", float(one.get("duration_s") or 0) > 0)
        try:
            bridge._voice_tts("m", text="")
            check("caps:tts-empty-400", False)
        except Exception as exc:  # noqa: BLE001
            check("caps:tts-empty-400", getattr(exc, "status_code", 0) == 400, repr(exc))
        bridge._TTS_HITS.clear()
        for _ in range(bridge._TTS_PER_MIN):
            bridge._voice_tts("m", text="再来一句")
        try:
            bridge._voice_tts("m", text="第七句")
            check("caps:tts-rate-429", False)
        except Exception as exc:  # noqa: BLE001
            check("caps:tts-rate-429", getattr(exc, "status_code", 0) == 429, repr(exc))
    finally:
        tts.synth_sync = orig_synth
        bridge._TTS_HITS.clear()

    # --- ASR：转发打桩
    wav = tmp / "a.wav"
    wav.write_bytes(b"RIFF....WAVE")
    orig_post = bridge.httpx.post

    class FakeResp:
        status_code = 200

        def json(self):
            return {"ok": True, "text": "她说了一句", "seconds": 1.1, "engine": "fake"}

    bridge.httpx.post = lambda *a, **kw: FakeResp()
    try:
        got = bridge._voice_asr("m", path=str(wav))
        check("caps:asr-text", got.get("text") == "她说了一句")
        check("caps:asr-chars", got.get("chars") == 5)
    finally:
        bridge.httpx.post = orig_post

    def boom(*a, **kw):
        raise RuntimeError("connection refused")

    bridge.httpx.post = boom
    try:
        bridge._voice_asr("m", path=str(wav))
        check("caps:asr-503", False)
    except Exception as exc:  # noqa: BLE001
        check("caps:asr-503", getattr(exc, "status_code", 0) == 503, repr(exc))
    finally:
        bridge.httpx.post = orig_post

    try:
        bridge._voice_asr("m", path=str(tmp / "nope.wav"))
        check("caps:asr-missing-400", False)
    except Exception as exc:  # noqa: BLE001
        check("caps:asr-missing-400", getattr(exc, "status_code", 0) == 400, repr(exc))

    # --- 看图：主模型打桩
    async def fake_describe(src, question="", max_tokens=0):
        return "一只白猫趴在窗台上"

    orig_desc = llm_box.describe_image
    llm_box.describe_image = fake_describe
    try:
        got = asyncio.run(bridge._vision_describe("m", image=str(wav)))
        check("caps:vision-text", got.get("text", "").startswith("一只白猫"))
        try:
            asyncio.run(bridge._vision_describe("m", image=""))
            check("caps:vision-empty-400", False)
        except Exception as exc:  # noqa: BLE001
            check("caps:vision-empty-400", getattr(exc, "status_code", 0) == 400, repr(exc))
    finally:
        llm_box.describe_image = orig_desc

    # data URL 原样透传、路径转 base64
    url = llm_box._image_part("data:image/png;base64,AAAA")
    check("caps:image-data-url", url.startswith("data:image/png;base64,"))
    p = tmp / "b.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    check("caps:image-file", llm_box._image_part(str(p)).startswith("data:image/png;base64,"))
    try:
        llm_box._image_part(str(tmp / "missing.png"))
        check("caps:image-b64-fallback", True)   # 当裸 base64 处理，不炸
    except Exception:  # noqa: BLE001
        check("caps:image-b64-fallback", False)


def asr_service_tests() -> None:
    """真起一次语音服务：没装引擎也要能说话、要认令牌。"""
    srv_py = ROOT / "WiseEntity" / "capability" / "voice" / "asr" / "server.py"
    check("asr:server-exists", srv_py.is_file(), str(srv_py))
    if not srv_py.is_file():
        return
    ent = Path(tempfile.mkdtemp(prefix="bab-caps-ent-"))
    (ent / "memory").mkdir(parents=True, exist_ok=True)
    (ent / "memory" / "bridge_token.json").write_text(json.dumps({"token": "t0k"}), encoding="utf-8")
    port = free_port()
    env = dict(os.environ)
    env.update({"BAB_ENTITY": str(ent), "BAB_ASR_PORT": str(port), "PYTHONUTF8": "1"})
    proc = subprocess.Popen([sys.executable, str(srv_py), "--port", str(port)],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        ok = False
        for _ in range(60):
            if proc.poll() is not None:
                break
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    ok = True
                    break
            except OSError:
                time.sleep(0.2)
        check("asr:starts", ok, (proc.stdout.read(400).decode("utf-8", "replace") if not ok else ""))

        def get(path):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
                return json.loads(r.read().decode("utf-8"))

        def post(path, body, token=""):
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json",
                         **({"x-bridge-token": token} if token else {})})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status, json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read().decode("utf-8") or "{}")

        health = get("/health")
        check("asr:health-ok", health.get("ok") is True and health.get("port") == port, str(health))
        check("asr:health-token-file", str(ent / "memory" / "bridge_token.json") == health.get("token_file"))
        code, body = post("/stt", {"path": "x.wav"}, token="bad")
        check("asr:bad-token-401", code == 401 and body.get("error") == "bad_token", f"{code} {body}")
        wav = ent / "probe.wav"
        wav.write_bytes(b"RIFF" + b"\x00" * 64 + b"WAVE")
        code, body = post("/stt", {"path": str(wav)}, token="t0k")
        has_engine = bool(health.get("engine"))
        if has_engine:
            check("asr:stt-reachable", code in (400, 500, 503), f"{code} {body}")
        else:
            check("asr:no-engine-503", code == 503 and body.get("error") == "no_engine", f"{code} {body}")
            check("asr:no-engine-hint", "faster-whisper" in str(body.get("install") or ""), str(body))
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            proc.kill()


def main() -> int:
    memory_tests()
    caps_tests()
    asr_service_tests()
    print("PASS %d" % len(PASS))
    if FAIL:
        print("FAIL %d" % len(FAIL))
        for f in FAIL:
            print("  - " + f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
