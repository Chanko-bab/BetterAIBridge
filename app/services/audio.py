"""放声音：用 Windows 自带的 MCI 播 mp3（PySide6-Essentials 里没有 QtMultimedia）。

- 只做一件事：把 mp3 文件播出来，不阻塞界面。
- 播的时候用独立线程；重复调用会先把上一条停掉（免得叠着响）。
- 放不出来要**说出来**：返回 False + 写日志，不许假装成功（0.3.4 之前这里全静默）。
"""
from __future__ import annotations

import ctypes
import logging
import os
import queue
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

_winmm = ctypes.WinDLL("winmm") if os.name == "nt" else None
log = logging.getLogger(__name__)

AUDIO_DIR = Path(tempfile.gettempdir()) / "bab-tts"
MAX_AUDIO_FILES = 120
MAX_AUDIO_AGE = 7 * 24 * 3600


def cleanup_audio(max_files: int = MAX_AUDIO_FILES, max_age: int = MAX_AUDIO_AGE) -> int:
    """清掉旧的临时语音；只动 AUDIO_DIR，返回删掉的数量。"""
    if not AUDIO_DIR.exists():
        return 0
    removed = 0
    try:
        files = sorted((p for p in AUDIO_DIR.iterdir() if p.is_file()),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return 0
    now = time.time()
    for i, p in enumerate(files):
        try:
            too_old = now - p.stat().st_mtime > max_age
            too_many = i >= max(1, int(max_files))
            if too_old or too_many:
                p.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue
    return removed


def _mci_ex(cmd: str) -> tuple[int, str]:
    """发一条 MCI 命令，返回 (返回码, 文本)。返回码 0 才算成功。"""
    if _winmm is None:
        return 0, ""
    buf = ctypes.create_unicode_buffer(512)
    try:
        rc = _winmm.mciSendStringW(cmd, buf, 511, None)
    except Exception as exc:  # noqa: BLE001
        return -1, str(exc)
    return rc, buf.value


def _mci(cmd: str) -> str:
    return _mci_ex(cmd)[1]


def _mci_error(rc: int) -> str:
    """把 MCI 数字返回码翻成人话。"""
    if not rc:
        return ""
    if _winmm is None:
        return f"MCI 返回码 {rc}"
    buf = ctypes.create_unicode_buffer(512)
    try:
        _winmm.mciGetErrorStringW(rc, buf, 511)
    except Exception:  # noqa: BLE001
        return f"MCI 返回码 {rc}"
    return buf.value or f"MCI 返回码 {rc}"


class _Player:
    """所有 MCI 调用都跑在同一个专属线程里。

    为什么非这样不可：MCI 的别名是**线程亲和**的。在 A 线程 open、在 B 线程 play，
    返回 263「指定的设备未打开，或不被 MCI 所识别」；status/close 跨线程同样失败
    （实测见 tools/ 里的探针记录）。0.3.0–0.3.4 就是 open 在主线程、play 丢进子线程，
    于是每一次播放都在 263 上静默失败，而界面写着「试听放出来了」。
    """

    def __init__(self) -> None:
        self._q: "queue.Queue" = queue.Queue()
        self._guard = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._alias: Optional[str] = None
        self._deadline = 0.0
        self.last_error = ""

    # ------------------------------------------------------------------ 对外
    def play(self, path: Path | str) -> bool:
        """放一段 mp3；返回「真的开始播了没有」。放不出来返回 False 并记 last_error。"""
        p = str(path)
        if not os.path.exists(p):
            self.last_error = f"文件不在：{p}"
            log.warning("放不出声：%s", self.last_error)
            return False
        box: list[bool] = []
        done = threading.Event()
        self._post(("play", p, box, done))
        if not done.wait(3.0):
            self.last_error = "MCI 3 秒没有回应"
            log.warning("放不出声：%s（%s）", self.last_error, p)
            return False
        return bool(box and box[0])

    def stop(self) -> None:
        """停掉当前这条（异步，不挡界面）。"""
        self._post(("stop", None, None, None))

    def play_wait(self, path: Path | str) -> bool:
        """播完再返回（测试/诊断用）。整段都在调用线程里，天然同线程。"""
        p = str(path)
        alias = "bab" + uuid.uuid4().hex[:8]
        kind = "waveaudio" if p.lower().endswith(".wav") else "mpegvideo"
        rc, _ = _mci_ex(f'open "{p}" type {kind} alias {alias}')
        if rc:
            self.last_error = f"打不开：{_mci_error(rc)}"
            log.warning("放不出声（play_wait）：%s", self.last_error)
            return False
        try:
            _mci_ex(f"play {alias} wait")
        finally:
            _mci_ex(f"close {alias}")
        return True

    # ---------------------------------------------------------------- 内部实现
    def _post(self, item) -> None:
        with self._guard:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="bab-audio", daemon=True)
                self._thread.start()
        self._q.put(item)

    def _loop(self) -> None:
        while True:
            try:
                item = self._q.get(timeout=0.2)
            except queue.Empty:
                self._reap()
                continue
            kind, p, box, done = item
            try:
                if kind == "play":
                    ok = self._play_now(p)
                    if box is not None:
                        box.append(ok)
                elif kind == "stop":
                    self._stop_now()
            except Exception as exc:  # noqa: BLE001
                log.warning("音频线程出错：%s", exc)
                if box is not None:
                    box.append(False)
            finally:
                if done is not None:
                    done.set()
            self._reap()

    def _play_now(self, p: str) -> bool:
        self._stop_now()
        alias = "bab" + uuid.uuid4().hex[:8]
        kind = "waveaudio" if p.lower().endswith(".wav") else "mpegvideo"
        rc, _ = _mci_ex(f'open "{p}" type {kind} alias {alias}')
        if rc:
            self.last_error = f"打不开：{_mci_error(rc)}"
            log.warning("放不出声：%s（%s）", self.last_error, p)
            return False
        rc, length = _mci_ex(f"status {alias} length")
        if rc or not length.strip().isdigit():
            self.last_error = f"读不到时长：{_mci_error(rc) or length.strip()[:60]}"
            log.warning("放不出声：%s（%s）", self.last_error, p)
            _mci_ex(f"close {alias}")
            return False
        rc, _ = _mci_ex(f"play {alias}")  # 不带 wait：立刻返回，播完自己停
        if rc:
            self.last_error = f"播不动：{_mci_error(rc)}"
            log.warning("放不出声：%s（%s）", self.last_error, p)
            _mci_ex(f"close {alias}")
            return False
        self._alias = alias
        self._deadline = time.monotonic() + int(length) / 1000.0 + 0.4
        self.last_error = ""
        return True

    def _stop_now(self) -> None:
        if not self._alias:
            return
        _mci_ex(f"stop {self._alias}")
        _mci_ex(f"close {self._alias}")
        self._alias = None

    def _reap(self) -> None:
        """播完了就把别名关掉，别攒句柄。"""
        if self._alias and time.monotonic() >= self._deadline:
            _mci_ex(f"close {self._alias}")
            self._alias = None


player = _Player()


def save_audio(data: bytes, suffix: str = "") -> Path:
    """把合成出来的字节落到临时文件，返回路径。

    没给后缀时按头部认：RIFF 是 WAV，其余当 mp3。MCI 播 WAV 要用 waveaudio。
    """
    if not suffix:
        suffix = ".wav" if data[:4] == b"RIFF" else ".mp3"
    d = AUDIO_DIR
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{uuid.uuid4().hex}{suffix}"
    p.write_bytes(data)
    cleanup_audio()
    return p
