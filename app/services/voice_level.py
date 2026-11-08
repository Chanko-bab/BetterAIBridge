"""朗读时把音量包络发给模组（口型 / 震动用）。

- 只做“旁听”：音频还是 `app/services/audio.py` 的 MCI 在放，这里不改播放。
- 启动器自己解码：GUI venv 里加了 miniaudio（纯 wheel，能解 mp3/wav），
  不需要 numpy，也不依赖 ASR 的 venv。
- 事件三件套：`voice.play.started` / `voice.level` / `voice.play.ended`。
  `voice.level` 每 100ms 一批，每批最多 10 帧（20ms 一格），帧是
  `[t_ms, rms, peak]`，音量归一到 0..1000。模组自己插值到 60fps。
- 没有订阅者时也照常算（很便宜）；不想算就把 hook 设成 None。
"""
from __future__ import annotations

import hashlib
import json
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..core import config

log = logging.getLogger(__name__)

HOP_MS = 20
BATCH = 10
TICK_S = 0.1
_CACHE_DIR = config.APP_DIR / "WiseEntity" / "entity" / "state" / "voice_level"

_hook: Optional[Callable[[str, Dict[str, Any]], None]] = None
_q: "queue.Queue" = queue.Queue(maxsize=400)
_worker: Optional[threading.Thread] = None
_guard = threading.Lock()
_current: Optional[Dict[str, Any]] = None


# ------------------------------------------------------------------ 解码/包络
def _decode(path: str, rate: int = 16000) -> Sequence[int]:
    import miniaudio  # 只有真要用时才 import，没装也能启动

    # 用内存解码，不用 decode_file：Windows 中文用户名路径会让 C 层打不开
    data = Path(path).read_bytes()
    got = miniaudio.decode(
        data,
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=1,
        sample_rate=rate,
    )
    return got.samples


def frames_from_pcm(pcm: Sequence[int], hop_ms: int = HOP_MS, rate: int = 16000) -> List[List[int]]:
    hop = max(1, int(rate * hop_ms / 1000))
    out: List[List[int]] = []
    n = len(pcm)
    for start in range(0, n, hop):
        piece = pcm[start:start + hop]
        if not piece:
            break
        # 16bit 满幅 32768；用整数算，避免依赖 numpy
        s = 0
        peak = 0
        for v in piece:
            x = int(v)
            s += x * x
            a = -x if x < 0 else x
            if a > peak:
                peak = a
        rms = int(round((s / len(piece)) ** 0.5 / 32768.0 * 1000.0))
        pk = int(round(peak / 32768.0 * 1000.0))
        out.append([len(out) * hop_ms, min(1000, rms), min(1000, pk)])
    return out


def _cache_key(path: Path, hop_ms: int) -> str:
    try:
        st = path.stat()
        raw = f"{path.resolve()}|{st.st_mtime_ns}|{st.st_size}|{hop_ms}"
    except OSError:
        raw = f"{path}|0|0|{hop_ms}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def envelope(path: str | Path, hop_ms: int = HOP_MS) -> Optional[List[List[int]]]:
    """返回 [[t_ms, rms, peak], …]；解不了返回 None（不抛给播放线程）。"""
    p = Path(path)
    key = _cache_key(p, hop_ms)
    cache = _CACHE_DIR / f"{key}.json"
    try:
        if cache.is_file():
            got = json.loads(cache.read_text(encoding="utf-8"))
            frames = got.get("frames")
            if isinstance(frames, list) and frames:
                return frames
    except (OSError, ValueError):
        pass
    try:
        import miniaudio
    except ImportError:
        return None
    try:
        pcm = _decode(str(p))
        frames = frames_from_pcm(pcm, hop_ms)
    except (miniaudio.MiniaudioError, OSError, ValueError) as exc:
        log.debug("音量包络算不出来（%s）：%r", p, exc)
        return None
    if not frames:
        return None
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps({"frames": frames}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(cache)
    except OSError:
        pass
    return frames


# ------------------------------------------------------------------ 发事件
def set_hook(fn: Optional[Callable[[str, Dict[str, Any]], None]]) -> None:
    """由 main_window 注入：把 (phase, data) 送到内核。None = 关闭。"""
    global _hook, _worker
    with _guard:
        _hook = fn
        if fn is not None and (_worker is None or not _worker.is_alive()):
            _worker = threading.Thread(target=_loop, name="bab-voice-level", daemon=True)
            _worker.start()


def _loop() -> None:
    while True:
        try:
            phase, data = _q.get(timeout=0.5)
        except queue.Empty:
            continue
        fn = _hook
        if fn is None:
            continue
        try:
            fn(phase, data)
        except Exception as exc:  # noqa: BLE001 - 内核没起来/网络抖动，丢帧即可
            log.debug("音量事件没送到（%s）：%r", phase, exc)


def _emit(phase: str, data: Dict[str, Any]) -> None:
    if _hook is None:
        return
    try:
        _q.put_nowait((phase, data))
    except queue.Full:
        pass


def begin(play_id: str, path: str | Path, length_ms: int, t0: float,
          alive: Callable[[], bool]) -> None:
    """播放开始时叫一下；自己起线程算包络并按播放位置发批。"""
    global _current
    if _hook is None:
        return
    stop = threading.Event()
    with _guard:
        if _current is not None:
            _current["stop"].set()
        _current = {"id": play_id, "stop": stop}
    _emit("started", {"id": play_id, "path": str(path), "ms": max(0, int(length_ms))})
    threading.Thread(
        target=_run, args=(play_id, str(path), int(length_ms), float(t0), alive, stop),
        name="bab-voice-level-play", daemon=True,
    ).start()


def end(play_id: str) -> None:
    global _current
    with _guard:
        if _current and _current.get("id") == play_id:
            _current["stop"].set()
            _current = None


def _run(play_id: str, path: str, length_ms: int, t0: float,
         alive: Callable[[], bool], stop: threading.Event) -> None:
    frames = envelope(path)
    if not frames:
        _emit("ended", {"id": play_id, "ms": 0, "ok": False})
        return
    sent = 0
    total = len(frames)
    while not stop.is_set() and alive():
        pos = (time.monotonic() - t0) * 1000.0
        ready = [f for f in frames[sent:] if f[0] <= pos + 120]
        if ready:
            batch = ready[:BATCH]
            _emit("level", {"id": play_id, "t_ms": int(pos), "frames": batch})
            sent += len(batch)
        if sent >= total or pos > length_ms + 250:
            break
        stop.wait(TICK_S)
    _emit("ended", {"id": play_id, "ms": int(length_ms)})
