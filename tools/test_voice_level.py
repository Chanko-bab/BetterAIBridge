# -*- coding: utf-8 -*-
"""朗读口型/震动：包络算法、缓存、开始/批/结束三件事。"""
from __future__ import annotations

import math
import struct
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import voice_level  # noqa: E402


def tone(path: Path, seconds: float = 1.0, hz: float = 440.0) -> None:
    n = int(16000 * seconds)
    w = wave.open(str(path), "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(16000)
    w.writeframes(b"".join(
        struct.pack("<h", int(12000 * math.sin(2 * math.pi * hz * i / 16000))) for i in range(n)
    ))
    w.close()


def main() -> int:
    checks = 0

    def ok(cond, what):
        nonlocal checks
        checks += 1
        if not cond:
            raise AssertionError(what)

    # 1) 整数 RMS/峰值，不依赖 numpy
    frames = voice_level.frames_from_pcm([0] * 320)
    ok(len(frames) == 1 and frames[0][1] == 0 and frames[0][2] == 0, "静音应是 0")
    frames = voice_level.frames_from_pcm([32767] * 320)
    ok(frames[0][2] >= 999 and frames[0][1] >= 999, "满幅应到 1000")
    frames = voice_level.frames_from_pcm([1000] * 320)
    ok(0 < frames[0][1] < 100 and frames[0][1] == frames[0][2], "1000/32768 应约 31")
    frames = voice_level.frames_from_pcm(list(range(-100, 100)) * 2, hop_ms=20)
    ok(frames and all(0 <= x <= 1000 for f in frames for x in f[1:]), "范围 0..1000")

    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "tone.wav"
        tone(wav, 0.6)
        got = voice_level.envelope(wav)
        ok(got is not None and len(got) >= 25, f"0.6 秒应 >=25 帧，实际 {len(got or [])}")
        ok(got[0][1] > 100 and got[0][2] > got[0][1], "正弦应有音量且峰值更高")
        # 缓存命中：同一路径第二次应走缓存，值一样
        cache_before = voice_level.envelope(wav)
        cache_after = voice_level.envelope(wav)
        ok(cache_after == cache_before, "缓存应能复用")
        ok(any(voice_level._CACHE_DIR.glob("*.json")), "应落缓存文件")
        # 解不了的文件返回 None，不抛
        bad = Path(td) / "bad.mp3"
        bad.write_bytes(b"not audio")
        ok(voice_level.envelope(bad) is None, "坏文件应返回 None")

    # 2) 三件事：started / level / ended
    seen = []
    voice_level.set_hook(lambda phase, data: seen.append((phase, dict(data))))
    fake = [[0, 100, 200], [100, 300, 400], [200, 200, 250], [300, 50, 60]]
    orig = voice_level.envelope
    voice_level.envelope = lambda path, hop_ms=voice_level.HOP_MS: fake  # type: ignore
    try:
        voice_level.begin("p1", "x.wav", 400, time.monotonic(), lambda: True)
        deadline = time.time() + 2.0
        while time.time() < deadline and not any(p == "ended" for p, _ in seen):
            time.sleep(0.03)
    finally:
        voice_level.envelope = orig  # type: ignore
        voice_level.end("p1")
        voice_level.set_hook(None)
    phases = [p for p, _ in seen]
    ok("started" in phases and "ended" in phases, f"应有 started/ended，实际 {phases}")
    levels = [d for p, d in seen if p == "level"]
    ok(levels and all("frames" in d and len(d["frames"]) <= voice_level.BATCH for d in levels),
       "level 批应有 frames 且不超过 10 帧")
    ok(phases.index("started") == 0, "started 应最先")

    # 3) 中途 stop 也要收尾
    seen2 = []
    voice_level.set_hook(lambda phase, data: seen2.append(phase))
    voice_level.envelope = lambda path, hop_ms=voice_level.HOP_MS: [[i * 20, 10, 20] for i in range(500)]  # type: ignore
    try:
        voice_level.begin("p2", "y.wav", 5000, time.monotonic(), lambda: True)
        time.sleep(0.25)
        voice_level.end("p2")
        deadline = time.time() + 1.0
        while time.time() < deadline and "ended" not in seen2:
            time.sleep(0.02)
    finally:
        voice_level.envelope = orig  # type: ignore
        voice_level.set_hook(None)
    ok("started" in seen2 and "ended" in seen2, f"stop 后应结束，实际 {seen2}")

    print(f"voice_level: {checks} 项通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
