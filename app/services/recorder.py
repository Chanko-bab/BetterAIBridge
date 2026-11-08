"""按住说话的录音器：winmm 流式录音，松手即停。

和「耳目」里的定长 record() 不一样：这里要能随时停，所以用回调把每 100ms
的缓冲攒起来；最长 90 秒由界面计时器兜底，录完写 16k 单声道 wav。
"""
from __future__ import annotations

import ctypes
import logging
import tempfile
import threading
import time
import uuid
import wave
from pathlib import Path
from typing import Any, Dict, List

from . import senses

log = logging.getLogger(__name__)

CALLBACK_FUNCTION = 0x00030000
WIM_DATA = 0x3C0
MIN_MS = 5000
MAX_MS = 90000
CHUNK_MS = 100

_winmm = senses.winmm
_WAVEINPROC = ctypes.WINFUNCTYPE(
    None, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t,
    ctypes.c_size_t, ctypes.c_size_t,
)

_winmm.waveInOpen.argtypes = [
    ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint,
    ctypes.POINTER(senses.WAVEFORMATEX), ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_uint,
]
_winmm.waveInOpen.restype = ctypes.c_uint


class RecorderError(Exception):
    """录音失败：message 直接给用户看。"""


def _mm_err(rc: int) -> str:
    try:
        buf = ctypes.create_unicode_buffer(256)
        _winmm.waveInGetErrorTextW(int(rc), buf, 256)
        return buf.value or f"错误码 {rc}"
    except Exception:  # noqa: BLE001
        return f"错误码 {rc}"


def write_wav(path: Path, raw: bytes, rate: int = senses.MIC_RATE) -> int:
    """把裸 PCM 写成 wav，返回毫秒。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(senses.MIC_CH)
        w.setsampwidth(senses.MIC_BITS // 8)
        w.setframerate(int(rate))
        w.writeframes(raw)
    return int(round(len(raw) / float(rate * senses.MIC_CH * (senses.MIC_BITS // 8)) * 1000))


class Recorder:
    """一次只录一条；start / stop / cancel 都在主线程调用。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._chunks: List[bytes] = []
        self._h: ctypes.c_void_p | None = None
        self._cb = None
        self._slots: List[tuple] = []
        self._stopping = False
        self._active = False
        self._t0 = 0.0
        self._rate = senses.MIC_RATE
        self._level = 0.0
        self.last_error = ""

    # ------------------------------------------------------------------ 状态
    @property
    def active(self) -> bool:
        return self._active

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000) if self._active else 0

    def level(self) -> float:
        return max(0.0, min(1.0, float(self._level)))

    # ------------------------------------------------------------------ 开始
    def start(self, device: int = senses.WAVE_MAPPER, rate: int = senses.MIC_RATE) -> None:
        if self._active:
            return
        self._chunks = []
        self._level = 0.0
        self._stopping = False
        self.last_error = ""
        self._rate = int(rate or senses.MIC_RATE)
        fmt = senses.WAVEFORMATEX(
            senses.WAVE_FORMAT_PCM, senses.MIC_CH, self._rate,
            self._rate * senses.MIC_CH * senses.MIC_BITS // 8,
            senses.MIC_CH * senses.MIC_BITS // 8, senses.MIC_BITS, 0,
        )
        h = ctypes.c_void_p()
        self._cb = _WAVEINPROC(self._on_data)
        rc = _winmm.waveInOpen(
            ctypes.byref(h), ctypes.c_uint(int(device)), ctypes.byref(fmt),
            ctypes.cast(self._cb, ctypes.c_void_p), 0, CALLBACK_FUNCTION,
        )
        if rc:
            self.last_error = _mm_err(rc)
            raise RecorderError(f"打不开麦克风：{self.last_error}")
        self._h = h
        nbytes = int(self._rate * CHUNK_MS / 1000.0) * senses.MIC_CH * senses.MIC_BITS // 8
        self._slots = []
        try:
            for _ in range(8):
                buf = ctypes.create_string_buffer(nbytes)
                hdr = senses.WAVEHDR()
                hdr.lpData = ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
                hdr.dwBufferLength = nbytes
                rc = _winmm.waveInPrepareHeader(h, ctypes.byref(hdr), ctypes.sizeof(hdr))
                if rc:
                    raise RecorderError(f"麦克风准备失败：{_mm_err(rc)}")
                rc = _winmm.waveInAddBuffer(h, ctypes.byref(hdr), ctypes.sizeof(hdr))
                if rc:
                    raise RecorderError(f"麦克风给不上缓冲：{_mm_err(rc)}")
                self._slots.append((buf, hdr))
            rc = _winmm.waveInStart(h)
            if rc:
                raise RecorderError(f"麦克风起不来：{_mm_err(rc)}")
        except Exception:
            self._close()
            raise
        self._active = True
        self._t0 = time.monotonic()

    # ------------------------------------------------------------------ 回调
    def _on_data(self, _hwi, msg, _inst, p1, _p2) -> None:
        if msg != WIM_DATA or not p1:
            return
        try:
            hdr = ctypes.cast(p1, ctypes.POINTER(senses.WAVEHDR)).contents
            n = int(hdr.dwBytesRecorded)
            if n > 0:
                raw = ctypes.string_at(hdr.lpData, n)
                with self._lock:
                    self._chunks.append(raw)
                    st = senses.audio_stats(raw)
                    self._level = min(1.0, float(st.get("rms") or 0) / 2500.0)
            if self._stopping:
                return
            # 只清 WHDR_DONE，必须保留 WHDR_PREPARED，否则 AddBuffer 会报
            # “The wave header was not prepared”，录到第 8 个缓冲（0.8 秒）就停。
            hdr.dwFlags &= ~0x00000001
            hdr.dwBytesRecorded = 0
            h = self._h
            if h:
                rc = _winmm.waveInAddBuffer(h, ctypes.byref(hdr), ctypes.sizeof(hdr))
                if rc:
                    self.last_error = _mm_err(rc)
                    log.warning("录音缓冲归还失败：%s", self.last_error)
        except Exception:  # noqa: BLE001
            log.debug("录音回调归还缓冲失败", exc_info=True)

    # ------------------------------------------------------------------ 停止
    def stop(self) -> Dict[str, Any]:
        ms = self.elapsed_ms()
        raw = self._finish()
        if not raw:
            raise RecorderError("麦克风开着，但一个字节都没录到")
        path = Path(tempfile.gettempdir()) / "bab-voice" / f"rec-{uuid.uuid4().hex[:10]}.wav"
        real_ms = write_wav(path, raw, self._rate) or ms
        return {"path": path, "ms": real_ms, "bytes": len(raw), "level": round(self.level(), 3)}

    def cancel(self) -> None:
        self._finish()
        self._level = 0.0

    def _finish(self) -> bytes:
        self._active = False
        with self._lock:
            self._stopping = True
        h = self._h
        if h:
            try:
                _winmm.waveInStop(h)
                _winmm.waveInReset(h)
            except Exception:  # noqa: BLE001
                log.debug("停止录音设备失败", exc_info=True)
            time.sleep(0.05)
            self._close()
        with self._lock:
            raw = b"".join(self._chunks)
            self._chunks = []
        return raw

    def _close(self) -> None:
        h = self._h
        self._h = None
        if not h:
            return
        for _buf, hdr in self._slots:
            try:
                _winmm.waveInUnprepareHeader(h, ctypes.byref(hdr), ctypes.sizeof(hdr))
            except Exception:  # noqa: BLE001
                log.debug("释放录音缓冲头失败", exc_info=True)
        try:
            _winmm.waveInClose(h)
        except Exception:  # noqa: BLE001
            log.debug("关闭录音设备失败", exc_info=True)
        self._slots = []
