"""本地 MOSS-TTS-Nano 的 HTTP sidecar。

这个文件在安装目录的 local_tts/ 里运行（不是主程序 venv），只依赖
local_tts/venv 里的 torch / onnxruntime。主程序只通过 127.0.0.1 调它。

用法：
    local_tts/venv/Scripts/python.exe local_tts/server.py --port 18084

接口：
    GET  /health  -> {"ok": true, "voice": "Junhao"}
    POST /tts     -> WAV 字节；body={"text": "...", "voice": "Junhao",
                                     "reference": "可选参考音频路径"}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import traceback
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

PACK = Path(__file__).resolve().parent
MOSS = PACK / "moss"
MODELS = PACK / "models"
OUT = PACK / "out"
DEFAULT_VOICE = "Junhao"
MAX_TEXT = 800

sys.path.insert(0, str(MOSS))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

_RUNTIME = None
_LOAD_ERROR = ""
_LOCK = threading.Lock()


def log(*args: Any) -> None:
    print(*args, flush=True)


def load_runtime() -> None:
    global _RUNTIME, _LOAD_ERROR
    try:
        OUT.mkdir(parents=True, exist_ok=True)
        from onnx_tts_runtime import OnnxTtsRuntime  # noqa: WPS433
        log("loading MOSS-TTS-Nano ONNX runtime ...")
        _RUNTIME = OnnxTtsRuntime(
            model_dir=str(MODELS),
            thread_count=max(2, min(8, (os.cpu_count() or 4))),
            output_dir=str(OUT),
        )
        log("runtime ready; voices:", [v.get("voice") for v in _RUNTIME.list_builtin_voices()][:6])
    except Exception as exc:  # noqa: BLE001
        _LOAD_ERROR = f"{type(exc).__name__}: {exc}"
        log("LOAD FAILED:", _LOAD_ERROR)
        traceback.print_exc()


def _wav_info(path: Path) -> dict[str, Any]:
    with wave.open(str(path), "rb") as w:
        return {"rate": w.getframerate(), "channels": w.getnchannels(),
                "frames": w.getnframes(), "seconds": round(w.getnframes() / max(1, w.getframerate()), 3)}


class Handler(BaseHTTPRequestHandler):
    server_version = "BABLocalTTS/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D401
        log("%s - %s" % (self.address_string(), fmt % args))

    def _json(self, code: int, doc: dict[str, Any]) -> None:
        raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?")[0] != "/health":
            self._json(404, {"ok": False, "detail": "not found"})
            return
        if _RUNTIME is None:
            self._json(503, {"ok": False, "detail": _LOAD_ERROR or "模型还在加载"})
            return
        self._json(200, {"ok": True, "engine": "moss-tts-nano",
                         "voice": DEFAULT_VOICE, "pid": os.getpid(),
                         "port": int(self.server.server_address[1])})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?")[0] != "/tts":
            self._json(404, {"ok": False, "detail": "not found"})
            return
        if _RUNTIME is None:
            self._json(503, {"ok": False, "detail": _LOAD_ERROR or "模型还在加载"})
            return
        try:
            size = int(self.headers.get("Content-Length") or 0)
            if size <= 0 or size > 65536:
                self._json(400, {"ok": False, "detail": "请求体太大或为空"})
                return
            body = json.loads(self.rfile.read(size).decode("utf-8"))
            text = str(body.get("text") or "").strip()
            if not text:
                self._json(400, {"ok": False, "detail": "没有文字"})
                return
            if len(text) > MAX_TEXT:
                text = text[:MAX_TEXT]
            voice = str(body.get("voice") or DEFAULT_VOICE)
            ref = str(body.get("reference") or "").strip()
            ref_path = Path(ref).expanduser() if ref else None
            if ref_path is not None and not ref_path.is_file():
                self._json(400, {"ok": False, "detail": f"参考音频不存在：{ref}"})
                return

            OUT.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(prefix="say-", suffix=".wav", dir=str(OUT))
            os.close(fd)
            tmp = Path(tmp_name)
            try:
                with _LOCK:
                    result = _RUNTIME.synthesize(
                        text=text,
                        voice=voice,
                        prompt_audio_path=str(ref_path) if ref_path else None,
                        output_audio_path=str(tmp),
                        streaming=True,
                        enable_wetext=False,
                        enable_normalize_tts_text=True,
                    )
                audio_path = Path(str(result.get("audio_path") or tmp))
                raw = audio_path.read_bytes()
                if not raw.startswith(b"RIFF"):
                    raise RuntimeError("合成结果不是 WAV")
                info = _wav_info(audio_path)
                log(f"synth ok {len(text)} chars -> {info}")
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("X-Audio-Seconds", str(info["seconds"]))
                self.end_headers()
                self.wfile.write(raw)
            finally:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
        except Exception as exc:  # noqa: BLE001
            log("synth failed:", type(exc).__name__, exc)
            traceback.print_exc()
            self._json(500, {"ok": False, "detail": f"{type(exc).__name__}: {exc}"[:500]})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18084)
    args = ap.parse_args()
    load_runtime()
    if _RUNTIME is None:
        return 2
    pid_file = PACK / "server.pid"
    try:
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:  # noqa: BLE001
        print("写 pid 文件失败，退出时只能按端口清理", file=sys.stderr)
    srv = ThreadingHTTPServer(("127.0.0.1", int(args.port)), Handler)
    srv.daemon_threads = True
    log(f"listening on http://127.0.0.1:{int(args.port)}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            pid_file.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            print("删 pid 文件失败", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
