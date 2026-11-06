"""本地语音包：安装、启动、合成。

这里不把模型塞进安装包：用户选中「本地 MOSS」时才下载依赖包（独立 venv +
ONNX 权重），装在安装目录的 local_tts/ 里。卸载程序目录时一起删。

设计上的硬边界：
- 主程序不 import torch / onnxruntime；它们只活在 local_tts/venv 里。
- 本地服务挂了、没装好，都只影响 `/tts`，不影响聊天。
- 下载失败留下半成品，下次点「继续安装」可以接着来（已存在的文件不重下）。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import httpx

from . import config

log = logging.getLogger("xiaochen.local_tts")

PACK = config.APP_DIR / "local_tts"
VENV = PACK / "venv"
MOSS = PACK / "moss"
MODELS = PACK / "models"
READY = PACK / "ready.json"
PORT_FILE = PACK / "port.txt"
PID_FILE = PACK / "server.pid"
LOG = config.APP_DIR / "logs" / "local-tts.log"

PORT_START = 18084
HF_MIRROR = "https://hf-mirror.com"
HF_OFFICIAL = "https://huggingface.co"
MOSS_ZIP = "https://codeload.github.com/OpenMOSS/MOSS-TTS-Nano/zip/refs/heads/main"
MOSS_ZIP_PROXY = "https://ghproxy.net/https://github.com/OpenMOSS/MOSS-TTS-Nano/archive/refs/heads/main.zip"

TTS_REPO = "OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX"
CODEC_REPO = "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX"
TTS_FILES = (
    "browser_poc_manifest.json",
    "moss_tts_prefill.onnx",
    "moss_tts_decode_step.onnx",
    "moss_tts_local_decoder.onnx",
    "moss_tts_local_cached_step.onnx",
    "moss_tts_local_fixed_sampled_frame.onnx",
    "moss_tts_global_shared.data",
    "moss_tts_local_shared.data",
    "tokenizer.model",
    "tts_browser_onnx_meta.json",
)
CODEC_FILES = (
    "codec_browser_onnx_meta.json",
    "moss_audio_tokenizer_decode_full.onnx",
    "moss_audio_tokenizer_decode_shared.data",
    "moss_audio_tokenizer_decode_step.onnx",
    "moss_audio_tokenizer_encode.data",
    "moss_audio_tokenizer_encode.onnx",
)

_PROC: Optional[subprocess.Popen] = None
_PID: Optional[int] = None
_LOCK = threading.Lock()
_PORT: Optional[int] = None


class LocalTtsError(RuntimeError):
    pass


def _python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def _ready_doc() -> Dict[str, Any]:
    try:
        doc = json.loads(READY.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def is_ready() -> bool:
    doc = _ready_doc()
    if not doc or not _python().exists():
        return False
    return (MOSS / "onnx_tts_runtime.py").exists() and (MODELS / "MOSS-TTS-Nano-100M-ONNX").exists()


def status() -> Dict[str, Any]:
    doc = _ready_doc()
    port = _PORT or saved_port()
    health_doc = health(port) if is_ready() else None
    return {
        "ok": True,
        "ready": is_ready(),
        "running": bool(health_doc and health_doc.get("ok")),
        "pack": str(PACK),
        "port": int(port) if (health_doc and health_doc.get("ok")) else _PORT,
        "version": str(doc.get("version") or ""),
        "detail": "" if is_ready() else "本地语音包还没装好",
    }


def saved_port() -> int:
    """UI 读端口用；不探活，避免界面线程等网络。"""
    try:
        return int(PORT_FILE.read_text(encoding="utf-8").strip())
    except Exception:  # noqa: BLE001
        return PORT_START


def _free_port(start: int = PORT_START) -> int:
    for port in range(int(start), int(start) + 40):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.25)
        try:
            s.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
        finally:
            try:
                s.close()
            except Exception:  # noqa: BLE001
                log.debug("关闭探测 socket 失败", exc_info=True)
    raise LocalTtsError("找不到空闲端口")


def health(port: Optional[int] = None) -> Optional[Dict[str, Any]]:
    p = int(port or _PORT or PORT_START)
    try:
        with httpx.Client(timeout=2.0) as c:
            r = c.get(f"http://127.0.0.1:{p}/health")
            if r.status_code == 200:
                doc = r.json()
                if isinstance(doc, dict):
                    doc.setdefault("ok", True)
                    return doc
    except (httpx.HTTPError, OSError, ValueError):
        return None
    return None


def _pid_on_port(port: int) -> Optional[int]:
    """Windows: 找监听该端口的 pid；其他平台返回 None。"""
    if os.name != "nt":
        return None
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    needle = f":{int(port)}"
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        if not parts[1].endswith(needle) or parts[3].upper() != "LISTENING":
            continue
        try:
            pid = int(parts[4])
        except ValueError:
            continue
        if pid > 4 and pid != os.getpid():
            return pid
    return None


def _kill_pid(pid: int) -> None:
    """只杀一个明确 pid；Windows 用 taskkill 连子进程一起收。"""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                       capture_output=True, timeout=10)
    else:
        try:
            os.kill(int(pid), 15)
        except OSError:
            log.debug("POSIX 结束本地语音 pid=%s 失败", pid, exc_info=True)


def _remember_pid(pid: Optional[int]) -> None:
    global _PID
    _PID = int(pid) if pid and int(pid) > 4 else None
    try:
        if _PID:
            PID_FILE.write_text(str(_PID), encoding="utf-8")
        else:
            PID_FILE.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        log.debug("记录本地语音 pid 失败", exc_info=True)


def _read_pid() -> Optional[int]:
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        return pid if pid > 4 and pid != os.getpid() else None
    except (OSError, ValueError):
        return None


def _local_health(port: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """确认端口上跑的是我们的 MOSS sidecar，而不是别的程序。"""
    doc = health(port)
    if not doc or doc.get("engine") != "moss-tts-nano":
        return None
    return doc


def _run(cmd: List[str], cwd: Optional[Path] = None) -> str:
    p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=1800)
    if p.returncode != 0:
        tail = (p.stderr or p.stdout or "").strip()[-1200:]
        raise LocalTtsError(f"命令失败（{cmd[0]}）：{tail or p.returncode}")
    return (p.stdout or "").strip()


def _download(url: str, dest: Path, progress: Callable[[int, str], None],
              base: int, span: int) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    total = 0
    with httpx.stream("GET", url, timeout=httpx.Timeout(120.0, connect=20.0),
                      follow_redirects=True) as r:
        if r.status_code != 200:
            raise LocalTtsError(f"下载失败 HTTP {r.status_code}：{url}")
        total = int(r.headers.get("content-length") or 0)
        done = 0
        last_pct, last_t = -1, 0.0
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes(1024 * 256):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                pct = base + int(span * done / total) if total else base
                now = time.monotonic()
                # 别每 256KB 刷一次屏：进度变了 2% 或过了 1.2 秒才报
                if pct - last_pct >= 2 or now - last_t >= 1.2:
                    last_pct, last_t = pct, now
                    if total:
                        progress(pct, f"下载 {dest.name} {done // 1048576}/{total // 1048576} MB")
                    else:
                        progress(pct, f"下载 {dest.name} {done // 1048576} MB")
    if tmp.stat().st_size <= 0:
        tmp.unlink(missing_ok=True)
        raise LocalTtsError(f"下载为空：{url}")
    tmp.replace(dest)


def _download_hf(repo: str, name: str, dest: Path, progress, base, span) -> None:
    for host in (HF_MIRROR, HF_OFFICIAL):
        try:
            _download(f"{host}/{repo}/resolve/main/{name}?download=true", dest, progress, base, span)
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise LocalTtsError(f"模型文件下不下来：{name}（{last}）")


def _extract_moss(zip_path: Path, progress: Callable[[int, str], None]) -> None:
    if (MOSS / "onnx_tts_runtime.py").exists():
        return
    tmp = PACK / ".moss-extract"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        for member in z.infolist():
            name = member.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                continue
            z.extract(member, tmp)
    roots = [p for p in tmp.iterdir() if p.is_dir()]
    src = roots[0] if len(roots) == 1 else tmp
    MOSS.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = MOSS / item.name
        if target.exists():
            continue
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
    shutil.rmtree(tmp, ignore_errors=True)
    zip_path.unlink(missing_ok=True)


def install(progress: Optional[Callable[[int, str], None]] = None) -> Dict[str, Any]:
    """建 venv → 装依赖 → 下源码 → 下模型 → 写 ready.json。可重复调用。"""
    cb = progress or (lambda _p, _m: None)

    def stage(p: int, msg: str) -> None:
        cb(max(0, min(100, int(p))), msg)

    if is_ready():
        stage(100, "本地语音包已经装好")
        return status()

    PACK.mkdir(parents=True, exist_ok=True)
    (PACK / ".installing").write_text(str(time.time()), encoding="utf-8")

    if not _python().exists():
        stage(2, "创建独立运行环境（不污染主程序）…")
        _run([sys.executable, "-m", "venv", str(VENV)])

    stage(5, "检查 Python 依赖（torch / onnxruntime，第一次会比较久）…")
    pip = [str(_python()), "-m", "pip", "install", "--disable-pip-version-check",
           "--no-input", "torch", "torchaudio", "onnxruntime", "sentencepiece",
           "soundfile", "numpy", "huggingface_hub"]
    _run(pip, cwd=PACK)
    stage(35, "依赖装好了")

    src_zip = PACK / "moss.zip"
    if not (MOSS / "onnx_tts_runtime.py").exists():
        stage(38, "下载 MOSS-TTS-Nano 源码…")
        try:
            _download(MOSS_ZIP, src_zip, cb, 38, 4)
        except Exception:  # noqa: BLE001
            _download(MOSS_ZIP_PROXY, src_zip, cb, 38, 4)
        _extract_moss(src_zip, cb)

    tts_dir = MODELS / "MOSS-TTS-Nano-100M-ONNX"
    codec_dir = MODELS / "MOSS-Audio-Tokenizer-Nano-ONNX"
    tts_dir.mkdir(parents=True, exist_ok=True)
    codec_dir.mkdir(parents=True, exist_ok=True)
    stage(45, "下载中文语音模型（约 760MB，请别关窗口）…")
    total_files = len(TTS_FILES) + len(CODEC_FILES)
    idx = 0
    for name in TTS_FILES:
        idx += 1
        _download_hf(TTS_REPO, name, tts_dir / name, cb, 45 + int(35 * (idx - 1) / total_files),
                     35 // total_files)
    for name in CODEC_FILES:
        idx += 1
        _download_hf(CODEC_REPO, name, codec_dir / name, cb, 45 + int(35 * (idx - 1) / total_files),
                     35 // total_files)

    stage(84, "安装本地语音服务…")
    server_src = Path(__file__).resolve().parent.parent / "services" / "local_tts_server.py"
    if not server_src.exists():
        raise LocalTtsError(f"缺少本地语音服务文件：{server_src}")
    shutil.copy2(server_src, PACK / "server.py")

    doc = {
        "version": "moss-tts-nano-0.1b",
        "created": int(time.time()),
        "python": str(_python()),
        "tts_repo": TTS_REPO,
        "codec_repo": CODEC_REPO,
        "files": {d.name: d.stat().st_size for d in (tts_dir, codec_dir)},
    }
    READY.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    (PACK / ".installing").unlink(missing_ok=True)
    stage(100, "本地语音包装好了")
    return status()


def _tail_log(n: int = 12) -> str:
    try:
        lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception:  # noqa: BLE001
        return ""


def start(timeout: float = 180.0) -> Dict[str, Any]:
    """启动本地服务；已启动直接返回。"""
    global _PROC, _PORT
    with _LOCK:
        saved = saved_port()
        h = _local_health(saved)
        if h:
            _PORT = saved
            _remember_pid(h.get("pid") or _pid_on_port(saved))
            return {"ok": True, "port": _PORT, "detail": ""}
        h = _local_health()
        if h:
            _PORT = int(h.get("port") or _PORT or saved)
            _remember_pid(h.get("pid") or _pid_on_port(_PORT))
            return {"ok": True, "port": _PORT, "detail": ""}
        if not is_ready():
            raise LocalTtsError("本地语音包还没装好：先在「设置 → 声音」里下载依赖")
        _PORT = _PORT or _free_port()
        try:
            PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
            PORT_FILE.write_text(str(_PORT), encoding="utf-8")
        except Exception:  # noqa: BLE001
            log.warning("写本地语音端口文件失败，退出时可能找不到 sidecar", exc_info=True)
        LOG.parent.mkdir(parents=True, exist_ok=True)
        if _PROC is None or _PROC.poll() is not None:
            logf = LOG.open("a", encoding="utf-8", errors="replace")
            flags = 0x08000000 if os.name == "nt" else 0
            env = os.environ.copy()
            env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
            _PROC = subprocess.Popen(
                [str(_python()), str(PACK / "server.py"), "--port", str(_PORT)],
                cwd=str(PACK), env=env, stdin=subprocess.DEVNULL,
                stdout=logf, stderr=subprocess.STDOUT, creationflags=flags,
            )
            _remember_pid(_PROC.pid)
        deadline = time.time() + max(20.0, float(timeout))
        while time.time() < deadline:
            time.sleep(0.5)
            h = _local_health()
            if h:
                _remember_pid(h.get("pid") or (_PROC.pid if _PROC is not None else _PID))
                return {"ok": True, "port": _PORT, "detail": ""}
            if _PROC is not None and _PROC.poll() is not None:
                raise LocalTtsError("本地语音服务启动失败：\n" + _tail_log())
        raise LocalTtsError("本地语音服务 180 秒没起来：\n" + _tail_log())


def stop() -> None:
    """停掉本次启动的 sidecar；本次没启动过时，也清掉上次遗留的。"""
    global _PROC, _PID
    with _LOCK:
        proc, _PROC = _PROC, None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                try:
                    _kill_pid(proc.pid)
                except Exception:  # noqa: BLE001
                    log.warning("强杀本地语音进程 pid=%s 失败", getattr(proc, "pid", "?"), exc_info=True)
        port = _PORT or saved_port()
        h = _local_health(port)
        pid = int(h.get("pid")) if h and h.get("pid") else (_PID or _read_pid())
        if h and pid is None:
            pid = _pid_on_port(port)
        if h and pid and pid > 4 and pid != os.getpid():
            # 本次进程已经停掉时，pid 不同；只有健康检查确认是 MOSS 才杀
            if proc is None or proc.pid != pid:
                _kill_pid(pid)
        _PID = None
        _remember_pid(None)


def synth(text: str, voice: str = "", reference: str = "") -> bytes:
    start()
    payload = {"text": str(text or ""), "voice": str(voice or ""),
               "reference": str(reference or "")}
    with httpx.Client(timeout=httpx.Timeout(300.0, connect=5.0)) as c:
        r = c.post(f"http://127.0.0.1:{int(_PORT or saved_port())}/tts", json=payload)
    if r.status_code != 200:
        detail = (r.text or "").strip()[:300]
        raise LocalTtsError(f"本地语音合成失败 HTTP {r.status_code}：{detail}")
    if not r.content:
        raise LocalTtsError("本地语音合成没返回音频")
    return r.content


def uninstall() -> None:
    stop()
    if PACK.exists():
        shutil.rmtree(PACK, ignore_errors=True)
