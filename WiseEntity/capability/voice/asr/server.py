# -*- coding: utf-8 -*-
"""语音转写小服务（本机 127.0.0.1，只给内核和模组用）。

- `GET  /health` → 引擎在不在、模型下没下
- `POST /stt`    → {"path": "a.wav"} 或 {"audio": "<base64>"}，回 {"text": ...}

它不属于任何一个模组：内核用自己的全局令牌 `entity/memory/bridge_token.json`
来敲它，模组通过内核能力 `voice.asr` 转手，不直接连这里。

引擎是 faster-whisper（CPU、int8、small）。没装的话 /health 会如实说，
/stt 回 503 并给出一次性安装命令——不偷偷下载模型。
"""
from __future__ import annotations

import base64
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "0.1.0"
HERE = Path(__file__).resolve().parent


def _find_entity() -> Path:
    """从本文件往上找 `entity/core/settings.py`——不写死盘符，整目录搬家也能跑。"""
    env = (os.environ.get("BAB_ENTITY") or "").strip()
    if env:
        return Path(env)
    for p in [HERE] + list(HERE.parents):
        cand = p / "entity"
        if (cand / "core" / "settings.py").is_file():
            return cand
        if (p / "core" / "settings.py").is_file():   # 传进来的就是 entity 本身
            return p
    return HERE.parents[3] / "entity"


ENTITY = _find_entity()
TOKEN_FILE = ENTITY / "memory" / "bridge_token.json"
MODELS = Path(os.environ.get("BAB_ASR_MODELS") or (HERE / "models"))
MODEL_NAME = os.environ.get("BAB_ASR_MODEL") or "small"
PORT = int(os.environ.get("BAB_ASR_PORT") or 40715)
LOGS = HERE / "logs"
LOGS.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()
_model = None
_load_error = ""
_loaded_at = 0.0


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    try:
        with (LOGS / "asr.log").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def token() -> str:
    env = (os.environ.get("BAB_ASR_TOKEN") or "").strip()
    if env:
        return env
    try:
        doc = json.loads(TOKEN_FILE.read_text(encoding="utf-8-sig"))
        return str(doc.get("token") or "").strip()
    except Exception:
        return ""


def engine_ready() -> tuple[bool, str]:
    try:
        import faster_whisper  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, f"没装 faster-whisper（{exc.__class__.__name__}）"
    return True, ""


def model_cached() -> bool:
    """faster-whisper 把模型缓存在 HF 目录下；本地 models/ 也认。"""
    if MODELS.is_dir() and any(MODELS.glob("*")):
        return True
    hf = Path(os.environ.get("HF_HOME") or (Path.home() / ".cache" / "huggingface"))
    return (hf / "hub").is_dir() and any((hf / "hub").glob("*faster-whisper*"))


def load_model():
    global _model, _load_error, _loaded_at
    with _lock:
        if _model is not None:
            return _model
        ok, why = engine_ready()
        if not ok:
            _load_error = why
            raise RuntimeError(why)
        from faster_whisper import WhisperModel  # type: ignore

        log(f"加载模型 {MODEL_NAME} …")
        t0 = time.time()
        _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8",
                              download_root=str(MODELS))
        _loaded_at = time.time()
        log(f"模型就绪，用了 {_loaded_at - t0:.1f}s")
        return _model


def transcribe(path: Path) -> dict:
    model = load_model()
    t0 = time.time()
    segs, info = model.transcribe(str(path), language="zh", vad_filter=True,
                                  beam_size=5)
    text = "".join(s.text for s in segs).strip()
    secs = round(time.time() - t0, 2)
    log(f"转写 {path.name}：{len(text)} 字，{secs}s")
    return {"text": text, "seconds": secs,
            "engine": f"faster-whisper/{MODEL_NAME}",
            "audio_s": round(float(getattr(info, "duration", 0.0) or 0.0), 2)}


class Handler(BaseHTTPRequestHandler):
    server_version = "BABASR/" + VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: A003
        log("%s " % self.address_string() + fmt % args)

    def _send(self, code: int, doc: dict) -> None:
        raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except Exception:
            pass

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except Exception:
            n = 0
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8")) or {}
        except Exception:
            return {}

    def do_GET(self):  # noqa: N802
        if self.path.split("?")[0] != "/health":
            return self._send(404, {"ok": False, "error": "no_route"})
        ok, why = engine_ready()
        return self._send(200, {
            "ok": True, "version": VERSION, "port": PORT,
            "engine": ok, "engine_why": why,
            "model": MODEL_NAME, "model_cached": model_cached(),
            "loaded": _model is not None, "load_error": _load_error,
            "token_file": str(TOKEN_FILE),
        })

    def do_POST(self):  # noqa: N802
        route = self.path.split("?")[0]
        if route != "/stt":
            return self._send(404, {"ok": False, "error": "no_route"})
        want = token()
        got = (self.headers.get("x-bridge-token") or "").strip()
        if want and got != want:
            return self._send(401, {"ok": False, "error": "bad_token"})
        body = self._body()
        path = str(body.get("path") or "").strip()
        if not path and body.get("audio"):
            tmp = Path(os.environ.get("TEMP") or ".") / f"bab-asr-{int(time.time() * 1000)}.wav"
            try:
                tmp.write_bytes(base64.b64decode(str(body["audio"])))
            except Exception as exc:  # noqa: BLE001
                return self._send(400, {"ok": False, "error": f"base64: {exc}"})
            path = str(tmp)
        src = Path(path).expanduser()
        if not src.is_file():
            return self._send(400, {"ok": False, "error": "file_not_found", "path": str(src)})
        try:
            return self._send(200, {"ok": True, **transcribe(src)})
        except Exception as exc:  # noqa: BLE001
            ok, why = engine_ready()
            if not ok:
                return self._send(503, {"ok": False, "error": "no_engine", "hint": why,
                                        "install": "pip install faster-whisper"})
            log(f"转写失败：{exc!r}")
            return self._send(500, {"ok": False, "error": str(exc)[:300]})


class QuietServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        self.socket.setsockopt(__import__("socket").SOL_SOCKET, __import__("socket").SO_REUSEADDR, 0)
        super().server_bind()


def main(argv: list[str] | None = None) -> int:
    global PORT
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--port" in argv:
        try:
            PORT = int(argv[argv.index("--port") + 1])
        except Exception:
            pass
    ok, why = engine_ready()
    log(f"启动 v{VERSION} port={PORT} engine={'ok' if ok else why} model={MODEL_NAME}")
    srv = QuietServer(("127.0.0.1", PORT), Handler)
    print(f"bab-asr {VERSION} listening on http://127.0.0.1:{PORT}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
