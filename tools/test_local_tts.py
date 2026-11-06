"""本地语音包：不下载模型，只验接口、缓存格式和 WAV 落盘。

真模型/真 torch 的安装由界面「下载本地语音包」做；这里跑的是每次提交都能跑的部分。
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "WiseEntity" / "entity"))

from app.core import local_tts  # noqa: E402
from core import tts  # noqa: E402


def check(ok: bool, text: str) -> None:
    print(("ok   " if ok else "FAIL ") + text)
    if not ok:
        raise SystemExit(1)


def make_wav(seconds: float = 0.2) -> bytes:
    d = Path(tempfile.mkdtemp()) / "x.wav"
    with wave.open(str(d), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x00" * int(24000 * seconds))
    return d.read_bytes()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a) -> None:  # noqa: D401
        pass

    def do_POST(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        doc = json.loads(body or b"{}")
        if doc.get("text") != "你好":
            self.send_response(400)
            self.end_headers()
            return
        raw = make_wav()
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> int:
    check(local_tts.PORT_START == 18084, "本地语音默认端口是 18084")
    check(len(local_tts.TTS_FILES) == 10 and len(local_tts.CODEC_FILES) == 6,
          "模型文件清单是 10 + 6")
    check(local_tts.MOSS_ZIP.endswith("/main"), "源码 zip 用 main 分支")
    check(local_tts.saved_port() >= 18084, "没装时读端口也能回默认值")

    # 起一个假 sidecar，验证 core 的 local 分支和 .wav 缓存
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    tmp = Path(tempfile.mkdtemp())
    tts.CACHE = tmp
    tts.cfg = lambda: {  # type: ignore[assignment]
        "engine": "local", "preview_engine": "local",
        "voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%", "volume": "+0%",
        "bb_base": "", "bb_key": "", "bb_voice": "", "bb_model": "",
        "local_url": f"http://127.0.0.1:{port}", "local_voice": "Junhao", "local_ref": "",
    }
    path = asyncio.run(tts.synth("你好", purpose="preview"))
    check(path.suffix == ".wav", "本地引擎缓存后缀是 .wav")
    check(path.read_bytes()[:4] == b"RIFF", "本地引擎返回真的是 WAV")
    path2 = asyncio.run(tts.synth("你好", purpose="preview"))
    check(path2 == path, "第二次直接命中缓存")

    from app.services import audio

    p = audio.save_audio(b"RIFF" + b"\0" * 1000)
    check(p.suffix == ".wav", "save_audio 按 RIFF 头认 WAV")
    p2 = audio.save_audio(b"ID3" + b"\0" * 1000)
    check(p2.suffix == ".mp3", "save_audio 仍能认出 mp3")

    # 临时语音清理：只留最新 N 个，过期也删
    import os
    import time
    old_dir = audio.AUDIO_DIR
    with tempfile.TemporaryDirectory() as td:
        audio.AUDIO_DIR = Path(td)
        now = time.time()
        for i in range(5):
            f = audio.AUDIO_DIR / f"f{i}.wav"
            f.write_bytes(b"x")
            os.utime(f, (now - i * 100, now - i * 100))
        removed = audio.cleanup_audio(max_files=2, max_age=1000)
        left = sorted(x.name for x in audio.AUDIO_DIR.iterdir())
        check(removed == 3 and left == ["f0.wav", "f1.wav"], "临时语音按数量清理")
    audio.AUDIO_DIR = old_dir

    # 上次遗留的 sidecar：本次没 _PROC 也要按健康检查返回的 pid 杀掉
    old_port, old_pidfile, old_pid, old_health, old_kill = (
        local_tts.PORT_FILE, local_tts.PID_FILE, local_tts._PID,
        local_tts._local_health, local_tts._kill_pid)
    killed = []
    try:
        with tempfile.TemporaryDirectory() as td:
            local_tts.PORT_FILE = Path(td) / "port.txt"
            local_tts.PID_FILE = Path(td) / "server.pid"
            local_tts.PORT_FILE.write_text("18099", encoding="utf-8")
            local_tts._PORT = 18099
            local_tts._PID = None
            local_tts._local_health = lambda _p=None: {"ok": True, "engine": "moss-tts-nano", "pid": 12345}
            local_tts._kill_pid = lambda pid: killed.append(pid)
            local_tts.stop()
            check(killed == [12345], "残留 sidecar 按 pid 清理")
    finally:
        local_tts.PORT_FILE, local_tts.PID_FILE, local_tts._PID = old_port, old_pidfile, old_pid
        local_tts._local_health, local_tts._kill_pid = old_health, old_kill
        local_tts._PORT = None

    # 别把假音频留在公共临时目录里，别的测试会拿它当“真 mp3”样本
    p.unlink(missing_ok=True)
    p2.unlink(missing_ok=True)

    srv.shutdown()
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
