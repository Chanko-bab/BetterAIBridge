"""耳目的感官层：把「画面」和「声音」变成字。

只依赖标准库，另加三样 Windows 自带的东西：

* GDI（`user32` / `gdi32`）截图，PNG 自己用 `zlib` 编，不装 Pillow；
* `winmm` 的 `waveIn` 录音，不装 pyaudio；
* 系统自带的 PowerShell（OCR 用它的 WinRT 接口，`tools/ocr.ps1`）。

摄像头走老式的 VFW（`avicap32`），但**一定另起进程**去试——有的机器上
`capCreateCaptureWindowW` 会卡住几十秒，卡住也只是杀掉那个子进程。

写文件一律落在 `data/` 下面，`pack_pbab.py` 打包时会跳过 data/。
"""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import wave
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "BetterAIBridge" / "senses"
SHOTS = DATA / "shots"
CLIPS = DATA / "clips"
OCR_PS1 = HERE / "ocr.ps1"
CAMGRAB = HERE / "camgrab.py"

KEEP_FILES = 60          # 每类最多留几个
KEEP_BYTES = 400 * 1024 * 1024

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class SenseError(Exception):
    """感官失败：message 给模型看，hint 告诉她接下来能做什么。"""

    def __init__(self, message: str, hint: str = "", code: str = "sense"):
        super().__init__(message)
        self.hint = hint
        self.code = code


# ------------------------------------------------------------------ PNG

def _chunk(tag: bytes, data: bytes) -> bytes:
    return (len(data).to_bytes(4, "big") + tag + data
            + (zlib.crc32(tag + data) & 0xFFFFFFFF).to_bytes(4, "big"))


def encode_png(width: int, height: int, rows: List[bytes], level: int = 3) -> bytes:
    """把若干行 RGBA 编成 PNG。行数必须等于 height。"""
    raw = b"".join(b"\x00" + r for r in rows)
    return b"".join([
        b"\x89PNG\r\n\x1a\n",
        _chunk(b"IHDR", width.to_bytes(4, "big") + height.to_bytes(4, "big")
               + bytes((8, 6, 0, 0, 0))),
        _chunk(b"IDAT", zlib.compress(raw, level)),
        _chunk(b"IEND", b""),
    ])


# ------------------------------------------------------------------ 截图

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
SM_CXSCREEN, SM_CYSCREEN = 0, 1
SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
DIB_RGB_COLORS = 0
BI_RGB = 0
HALFTONE = 4
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


_DPI_READY = False


def _dpi_aware() -> None:
    """让截图拿到物理像素——不设的话 125% 缩放会截出一张被拉伸的糊图。"""
    global _DPI_READY
    if _DPI_READY:
        return
    _DPI_READY = True
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.WinDLL("shcore").SetProcessDpiAwareness(1)
        except (OSError, AttributeError):
            pass


def grab_rect(x: int, y: int, w: int, h: int, out_w: int = 0, out_h: int = 0) -> Tuple[int, int, List[bytes]]:
    """截一块屏幕，返回 (宽, 高, RGBA 行列表)。给 out_w/out_h 就在 GDI 里缩好再取。"""
    _dpi_aware()
    if w <= 0 or h <= 0:
        raise SenseError("这块屏幕没有面积，截不了。", "换一块屏或者用 scope=screen 试试。")
    out_w = int(out_w or w)
    out_h = int(out_h or h)
    hdc = user32.GetDC(0)
    if not hdc:
        raise SenseError("拿不到屏幕的设备上下文（GDI 失败）。", "可能是远程桌面或会话被锁了。")
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, out_w, out_h)
    old = gdi32.SelectObject(mem, bmp)
    try:
        if (out_w, out_h) != (w, h):
            gdi32.SetStretchBltMode(mem, HALFTONE)
            gdi32.SetBrushOrgEx(mem, 0, 0, None)
            ok = gdi32.StretchBlt(mem, 0, 0, out_w, out_h, hdc, x, y, w, h, SRCCOPY)
        else:
            ok = gdi32.BitBlt(mem, 0, 0, w, h, hdc, x, y, SRCCOPY | CAPTUREBLT)
        if not ok:
            raise SenseError("截屏失败：GDI 没画上去。", "锁屏或者会话断开时截不到，先解锁再试。")
        bi = BITMAPINFO()
        bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.bmiHeader.biWidth = out_w
        bi.bmiHeader.biHeight = -out_h
        bi.bmiHeader.biPlanes = 1
        bi.bmiHeader.biBitCount = 32
        bi.bmiHeader.biCompression = BI_RGB
        buf = ctypes.create_string_buffer(out_w * out_h * 4)
        got = gdi32.GetDIBits(mem, bmp, 0, out_h, buf, ctypes.byref(bi), DIB_RGB_COLORS)
        if not got:
            raise SenseError("截屏失败：读不出像素。", "重试一次；还不行就报给使用者。")
    finally:
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(0, hdc)
    raw = buf.raw
    stride = out_w * 4
    rows: List[bytes] = []
    for i in range(out_h):
        row = bytearray(raw[i * stride:(i + 1) * stride])
        row[0::4], row[2::4] = row[2::4], row[0::4]   # BGRA -> RGBA
        row[3::4] = b"\xff" * out_w                   # 有些驱动给 alpha=0
        rows.append(bytes(row))
    return out_w, out_h, rows


class RECT(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG), ("right", wt.LONG), ("bottom", wt.LONG)]


def _proc_name(pid: int) -> str:
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return ""
        try:
            size = wt.DWORD(1024)
            buf = ctypes.create_unicode_buffer(1024)
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return Path(buf.value).name
        finally:
            k32.CloseHandle(h)
    except (OSError, AttributeError, ctypes.ArgumentError):
        pass
    return ""


def focus_window() -> Dict[str, Any]:
    """前台窗口：标题、进程、外框。拿不到就给空字典。"""
    info: Dict[str, Any] = {}
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return info
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        info["title"] = buf.value.strip()
        pid = wt.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        info["process"] = _proc_name(pid.value)
        rect = RECT()
        ok = False
        try:
            dwm = ctypes.WinDLL("dwmapi")
            if dwm.DwmGetWindowAttribute(wt.HWND(hwnd), 9, ctypes.byref(rect), ctypes.sizeof(rect)) == 0:
                ok = True
        except Exception:
            ok = False
        if not ok:
            ok = bool(user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(rect)))
        if ok:
            info["rect"] = [int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)]
        info["hwnd"] = int(hwnd)
    except (OSError, AttributeError, ctypes.ArgumentError):
        pass
    return info


def screen_bounds(monitor_index: int = 0) -> Tuple[int, int, int, int]:
    """第 N 块屏的 (x, y, w, h)；N 越界或问不到就给整块虚拟屏。"""
    _dpi_aware()
    try:
        if monitor_index > 0:
            MONITORENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC, ctypes.POINTER(RECT), wt.LPARAM)
            found: List[Tuple[int, int, int, int]] = []

            def _cb(hmon, hdc, lprc, data):
                r = lprc.contents
                found.append((int(r.left), int(r.top), int(r.right - r.left), int(r.bottom - r.top)))
                return True

            user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_cb), 0)
            if len(found) > monitor_index:
                return found[monitor_index]
    except (OSError, AttributeError, ctypes.ArgumentError):
        pass
    x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    w = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN) or user32.GetSystemMetrics(SM_CXSCREEN)
    h = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN) or user32.GetSystemMetrics(SM_CYSCREEN)
    return int(x), int(y), int(w), int(h)


def monitor_count() -> int:
    try:
        return max(1, int(user32.GetSystemMetrics(80)))  # SM_CMONITORS
    except Exception:
        return 1


# ------------------------------------------------------------------ 落盘

def ensure_dirs() -> None:
    for d in (SHOTS, CLIPS):
        d.mkdir(parents=True, exist_ok=True)


def stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def new_shot_path(tag: str = "shot") -> Path:
    ensure_dirs()
    p = SHOTS / f"{stamp()}-{tag}.png"
    n = 1
    while p.exists():
        p = SHOTS / f"{stamp()}-{tag}-{n}.png"
        n += 1
    return p


def new_clip_path(tag: str = "clip") -> Path:
    ensure_dirs()
    p = CLIPS / f"{stamp()}-{tag}.wav"
    n = 1
    while p.exists():
        p = CLIPS / f"{stamp()}-{tag}-{n}.wav"
        n += 1
    return p


def prune(folder: Path, keep_files: int = KEEP_FILES, keep_bytes: int = KEEP_BYTES) -> None:
    """留最新的若干份；两类上限任一超了就删老的。截屏常常一两兆，不能无限堆。"""
    try:
        files = sorted((p for p in folder.iterdir() if p.is_file()),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    total = 0
    for i, p in enumerate(files):
        try:
            total += p.stat().st_size
        except OSError:
            continue
        if i >= keep_files or total > keep_bytes:
            try:
                p.unlink()
            except OSError:
                pass


def rel(p: Path) -> str:
    """给人看的相对路径（模块目录下），别把 C:\\Users\\... 抖出去。"""
    try:
        return str(Path(p).resolve().relative_to(HERE)).replace("\\", "/")
    except Exception:
        return str(p)


def latest(kind: str) -> Optional[Path]:
    folder = SHOTS if kind in ("shot", "photo") else CLIPS
    try:
        files = [p for p in folder.iterdir() if p.is_file()]
        return max(files, key=lambda p: p.stat().st_mtime) if files else None
    except OSError:
        return None


# ------------------------------------------------------------------ OCR（调系统自带 PowerShell + WinRT）

def _drop(path: Path) -> None:
    """删临时文件，删不掉也不吵。"""
    try:
        Path(path).unlink()
    except OSError:
        pass


def _decode(b: bytes) -> str:
    for enc in ("utf-8", "gbk", "utf-16"):
        try:
            return b.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return b.decode("utf-8", "replace")


def ocr_available() -> Tuple[bool, str]:
    if os.name != "nt":
        return False, "只有 Windows 才有系统 OCR"
    if not OCR_PS1.is_file():
        return False, f"少了 {rel(OCR_PS1)}"
    exe = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not exe.is_file():
        return False, "找不到 powershell.exe（系统 OCR 靠它）"
    return True, ""


def ocr_png(png_path: Path, lang: str = "", timeout: float = 25.0) -> str:
    """用 Windows 自带的 OCR 认字，返回按行拼好的文字（可能为空串）。"""
    ok, why = ocr_available()
    if not ok:
        raise SenseError(f"认字这步用不了：{why}", "把设置里的「认字」关掉，或者用看图描述。", code="no_ocr")
    out_txt = Path(tempfile.gettempdir()) / f"bab-sense-ocr-{os.getpid()}-{int(time.time()*1000)}.txt"
    exe = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    cmd = [str(exe), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
           "-File", str(OCR_PS1), "-Path", str(png_path), "-Out", str(out_txt)]
    if lang:
        cmd += ["-Lang", lang]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout,
                              creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise SenseError(f"认字超时（{int(timeout)} 秒没回来）。",
                         "画面可能太花，换 scope=window 只看一个窗口再试。", code="ocr_timeout")
    except Exception as e:
        raise SenseError(f"认字起不来：{type(e).__name__}: {e}",
                         "这台机器可能没有 Windows 自带的 OCR 组件。", code="no_ocr")
    text = ""
    if out_txt.is_file():
        try:
            text = out_txt.read_text(encoding="utf-8", errors="replace")
        finally:
            try:
                out_txt.unlink()
            except OSError:
                pass
    if proc.returncode != 0 and not text.strip():
        err = _decode(proc.stderr or b"").strip().splitlines()
        tail = err[-1] if err else f"退出码 {proc.returncode}"
        raise SenseError(f"认字失败：{tail[:200]}",
                         "缺中文语言包时装不上，先在设置里换成 en-US 试试。", code="no_ocr")
    return clean_ocr(text)


_CJK = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"


def clean_ocr(text: str) -> str:
    """OCR 爱在中文字之间插空格，也爱把同一行认两遍。收拾一下再给人看。"""
    import re
    lines: List[str] = []
    for raw in text.replace("\r", "\n").split("\n"):
        s = raw.strip()
        if not s:
            continue
        s = re.sub(rf"(?<=[{_CJK}])\s+(?=[{_CJK}])", "", s)      # 中 文 之 间 的 空 格
        s = re.sub(rf"(?<=[{_CJK}])\s+(?=[0-9A-Za-z])", "", s)
        s = re.sub(rf"(?<=[0-9A-Za-z])\s+(?=[{_CJK}])", "", s)
        s = re.sub(r"[ \t]{2,}", " ", s)
        if lines and lines[-1] == s:
            continue                                               # 相邻重复行
        lines.append(s)
    out = "\n".join(lines)
    return out


# ------------------------------------------------------------------ 录音（winmm）

winmm = ctypes.WinDLL("winmm", use_last_error=True)
WAVE_FORMAT_PCM = 1
WAVE_MAPPER = ctypes.c_uint(-1).value
CALLBACK_NULL = 0
WHDR_DONE = 0x00000001
MIC_RATE = 16000
MIC_CH = 1
MIC_BITS = 16


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", wt.WORD), ("nChannels", wt.WORD), ("nSamplesPerSec", wt.DWORD),
        ("nAvgBytesPerSec", wt.DWORD), ("nBlockAlign", wt.WORD), ("wBitsPerSample", wt.WORD),
        ("cbSize", wt.WORD),
    ]


class WAVEHDR(ctypes.Structure):
    _fields_ = [
        ("lpData", ctypes.POINTER(ctypes.c_char)), ("dwBufferLength", wt.DWORD),
        ("dwBytesRecorded", wt.DWORD), ("dwUser", ctypes.c_size_t),
        ("dwFlags", wt.DWORD), ("dwLoops", wt.DWORD),
        ("lpNext", ctypes.c_void_p), ("reserved", ctypes.c_size_t),
    ]


class WAVEINCAPS(ctypes.Structure):
    _fields_ = [
        ("wMid", wt.WORD), ("wPid", wt.WORD), ("vDriverID", wt.DWORD),
        ("szPname", wt.WCHAR * 32),
        ("dwFormats", wt.DWORD), ("wChannels", wt.WORD), ("wReserved1", wt.WORD),
    ]


def _mm_err(rc: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    try:
        winmm.waveInGetErrorTextW(int(rc), buf, 256)
        return buf.value or f"错误码 {rc}"
    except Exception:
        return f"错误码 {rc}"


def list_mics() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        n = int(winmm.waveInGetNumDevs())
    except Exception:
        return out
    for i in range(n):
        caps = WAVEINCAPS()
        rc = winmm.waveInGetDevCapsW(ctypes.c_uint(i), ctypes.byref(caps), ctypes.sizeof(caps))
        if rc == 0:
            out.append({"index": i, "name": caps.szPname.strip(), "channels": int(caps.wChannels)})
        else:
            out.append({"index": i, "name": f"(第 {i} 个，问不出名字：{_mm_err(rc)})", "channels": 0})
    return out


def pick_mic(want: str) -> int:
    """settings 里写的麦克风：空 = 系统默认；数字 = 第几台；其它 = 名字里含这几个字。"""
    want = (want or "").strip()
    if not want:
        return WAVE_MAPPER
    mics = list_mics()
    if want.isdigit():
        idx = int(want)
        return idx if 0 <= idx < len(mics) else WAVE_MAPPER
    for m in mics:
        if want.lower() in str(m["name"]).lower():
            return int(m["index"])
    return WAVE_MAPPER


def record(seconds: float, device: int = WAVE_MAPPER, rate: int = MIC_RATE) -> Dict[str, Any]:
    """录一段 wav。返回路径与响度统计；没麦克风/被占用都会抛 SenseError。"""
    seconds = max(0.3, min(float(seconds), 60.0))
    fmt = WAVEFORMATEX(WAVE_FORMAT_PCM, MIC_CH, rate, rate * MIC_CH * MIC_BITS // 8,
                       MIC_CH * MIC_BITS // 8, MIC_BITS, 0)
    h = ctypes.c_void_p()
    rc = winmm.waveInOpen(ctypes.byref(h), ctypes.c_uint(device), ctypes.byref(fmt), 0, 0, CALLBACK_NULL)
    if rc:
        hint = ("设置里把「麦克风」写成序号或名字来换一台；"
                "也可能被别的程序独占了。")
        raise SenseError(f"打不开麦克风：{_mm_err(rc)}", hint, code="no_mic")
    nbytes = int(rate * seconds) * MIC_CH * MIC_BITS // 8
    buf = ctypes.create_string_buffer(nbytes)
    hdr = WAVEHDR()
    hdr.lpData = ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
    hdr.dwBufferLength = nbytes
    ok = False
    try:
        if winmm.waveInPrepareHeader(h, ctypes.byref(hdr), ctypes.sizeof(hdr)):
            raise SenseError("麦克风准备失败（waveInPrepareHeader）。", "换一台麦克风试试。", code="no_mic")
        if winmm.waveInAddBuffer(h, ctypes.byref(hdr), ctypes.sizeof(hdr)):
            raise SenseError("麦克风给不上缓冲（waveInAddBuffer）。", "换一台麦克风试试。", code="no_mic")
        if winmm.waveInStart(h):
            raise SenseError("麦克风起不来（waveInStart）。", "可能被别的程序占着。", code="no_mic")
        ok = True
        deadline = time.time() + seconds + 2.0
        while time.time() < deadline:
            if hdr.dwFlags & WHDR_DONE:
                break
            time.sleep(0.03)
    finally:
        try:
            winmm.waveInStop(h)
            winmm.waveInReset(h)
            winmm.waveInUnprepareHeader(h, ctypes.byref(hdr), ctypes.sizeof(hdr))
        except (OSError, AttributeError, ctypes.ArgumentError):
            pass
        winmm.waveInClose(h)
    if not ok:
        raise SenseError("录音没跑起来。", "再试一次；还不行就是设备问题。", code="no_mic")
    got = int(hdr.dwBytesRecorded)
    if got <= 0:
        raise SenseError("麦克风开着，但一个字节都没录到。",
                         "多半是系统里的「允许应用访问麦克风」被关了。", code="no_mic")
    raw = buf.raw[:got]
    stats = audio_stats(raw)
    path = new_clip_path("mic")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(MIC_CH)
        w.setsampwidth(MIC_BITS // 8)
        w.setframerate(rate)
        w.writeframes(raw)
    prune(CLIPS)
    stats.update({"path": path, "seconds": round(got / (rate * MIC_CH * (MIC_BITS // 8)), 2)})
    return stats


def audio_stats(raw: bytes) -> Dict[str, Any]:
    """大概有多响。不判断"是不是人说话"——那得靠 ASR，别在这儿编。"""
    import struct
    n = len(raw) // 2
    if n <= 0:
        return {"peak": 0, "rms": 0.0, "loud_ratio": 0.0, "quiet": True}
    step = max(1, n // 40000)          # 60 秒也只有几万个采样点，够估响度
    samples = struct.unpack(f"<{n}h", raw)[::step]
    peak = max(abs(s) for s in samples)
    rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
    loud = sum(1 for s in samples if abs(s) > 800)
    return {"peak": int(peak), "rms": round(rms, 1),
            "loud_ratio": round(loud / len(samples), 3), "quiet": rms < 40}


def describe_loudness(stats: Dict[str, Any]) -> str:
    rms = float(stats.get("rms") or 0)
    if rms < 40:
        return "很安静，几乎没声音"
    if rms < 300:
        return "有点底噪/很轻的声音"
    if rms < 2000:
        return "能听清的正常音量"
    return "挺大声的"


# ------------------------------------------------------------------ 转文字（本地 BAB 的 ASR / 远程 OpenAI 兼容接口）

def _no_proxy_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


_OPENER = _no_proxy_opener()


def _json_post(url: str, payload: Dict[str, Any], headers: Dict[str, str], timeout: float) -> Dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8", **headers})
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        body = e.read()[:400].decode("utf-8", "replace")
        raise SenseError(f"{url} 回 {e.code}：{body[:200]}", "检查接口地址、模型名和密钥。", code="asr_http")
    except Exception as e:
        raise SenseError(f"连不上 {url}：{type(e).__name__}: {e}", "确认服务开着、地址端口对。", code="asr_net")


def _read_token(bab_root: Optional[Path]) -> str:
    cands = ([bab_root / "WiseEntity" / "entity" / "memory" / "bridge_token.json",
              bab_root / "memory" / "bridge_token.json"] if bab_root else [])
    for p in cands:
        try:
            return str(json.loads(p.read_text(encoding="utf-8-sig")).get("token") or "")
        except (OSError, ValueError, TypeError):
            continue
    return ""


def trim_silence(wav_path: Path, threshold: float = 0.010, pad: float = 0.15) -> float:
    """把首尾的静音剪掉（16k/单声道/16bit）。返回剪完的秒数；出错就原样不动。"""
    try:
        import wave
        with wave.open(str(wav_path), "rb") as wf:
            rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
        import array
        pcm = array.array("h")
        pcm.frombytes(frames)
        if not pcm:
            return 0.0
        step = max(1, int(rate * 0.03))
        loud = []
        for i in range(0, len(pcm), step):
            chunk = pcm[i:i + step]
            peak = max(abs(min(chunk)), abs(max(chunk))) / 32768.0
            loud.append(peak >= threshold)
        if not any(loud):
            return len(pcm) / float(rate)
        first = next(i for i, v in enumerate(loud) if v)
        last = len(loud) - 1 - next(i for i, v in enumerate(reversed(loud)) if v)
        start = max(0, first * step - int(rate * pad))
        end = min(len(pcm), (last + 1) * step + int(rate * pad))
        if end - start < int(rate * 0.3):
            return len(pcm) / float(rate)
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(pcm[start:end].tobytes())
        return (end - start) / float(rate)
    except Exception:
        return 0.0


def local_asr_health(base: str, bab_root: Optional[Path], timeout: float = 2.0) -> Dict[str, Any]:
    """问 BAB 自带的语音服务：在不在、模型装了没有。"""
    url = base.rstrip("/") + "/health"
    try:
        with _OPENER.open(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def local_asr(wav_path: Path, base: str, bab_root: Optional[Path], timeout: float = 90.0) -> str:
    tok = _read_token(bab_root)
    headers = {"x-bridge-token": tok} if tok else {}
    got = _json_post(base.rstrip("/") + "/stt", {"path": str(wav_path)}, headers, timeout)
    if not got.get("ok"):
        raise SenseError(str(got.get("error") or "本机语音服务没转出来")[:200],
                         "模型没装就去 capability/voice/asr 跑 fetch-small.ps1。", code="asr_local")
    return str(got.get("text") or "").strip()


def remote_asr(wav_path: Path, base: str, model: str, key: str, timeout: float = 120.0) -> str:
    """OpenAI 兼容的 /audio/transcriptions，手搓 multipart——标准库没有现成的。"""
    boundary = "----bab-sense" + str(int(time.time() * 1000))
    parts: List[bytes] = []
    for name, value in (("model", model), ("response_format", "json")):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8"))
    body = wav_path.read_bytes()
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{wav_path.name}\"\r\n"
        f"Content-Type: audio/wav\r\n\r\n".encode("utf-8") + body + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    data = b"".join(parts)
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(base.rstrip("/") + "/audio/transcriptions", data=data, method="POST", headers=headers)
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            got = json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        body_txt = e.read()[:300].decode("utf-8", "replace")
        raise SenseError(f"远程转写回 {e.code}：{body_txt[:160]}", "检查密钥、模型名和地址。", code="asr_http")
    except Exception as e:
        raise SenseError(f"远程转写连不上：{type(e).__name__}: {e}", "确认网络和地址。", code="asr_net")
    text = got.get("text") if isinstance(got, dict) else ""
    return str(text or "").strip()


# ------------------------------------------------------------------ 看图（多模态模型，可选）

def vision_ready(base: str, model: str, key: str) -> Tuple[bool, str]:
    if not base:
        return False, "没填「看图模型」的接口地址"
    if not model:
        return False, "没填「看图模型」的模型名"
    return True, ""


def vision_describe(png_path: Path, question: str, base: str, model: str, key: str,
                    timeout: float = 90.0) -> str:
    raw = png_path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    prompt = (question or "").strip() or (
        "这是使用者此刻屏幕上的画面。用中文说清楚：这是什么程序/什么场景、"
        "上面有什么值得注意的内容或数字，150 字以内。看不到就说看不到，不要编。")
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }],
        "max_tokens": 600,
        "temperature": 0.3,
    }
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    got = _json_post(base.rstrip("/") + "/chat/completions", payload, headers, timeout)
    try:
        return str(got["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        raise SenseError(f"看图模型回的东西看不懂：{json.dumps(got, ensure_ascii=False)[:200]}",
                         "确认地址是 OpenAI 兼容的 /chat/completions。", code="vision")


# ------------------------------------------------------------------ 摄像头（VFW，另起进程）

_CAM_ERR: Dict[str, Any] = {"at": 0.0, "msg": ""}
_CAM_LIST: Dict[str, Any] = {"at": 0.0, "names": []}
CAM_LIST_TTL = 120.0


def pnp_cameras(timeout: float = 6.0) -> List[str]:
    """问 Windows 要「这台机器上装了哪些摄像头」的友好名字（VFW 只会给通用名）。"""
    cmd = ("Get-CimInstance Win32_PnPEntity -Filter \"PNPClass='Camera' or PNPClass='Image'\" "
           "| Select-Object -ExpandProperty Name")
    try:
        proc = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                               "-Command", cmd],
                              capture_output=True, timeout=timeout,
                              creationflags=CREATE_NO_WINDOW)
        text = _decode(proc.stdout or b"")
        return [ln.strip() for ln in text.splitlines() if ln.strip()]
    except Exception:
        return []


def camera_list(timeout: float = 8.0) -> List[str]:
    """枚举摄像头。枚举也可能卡几秒，所以结果缓存两分钟——没有摄像头的机器尤其需要。

    VFW 在 USB 摄像头上经常只回一个「Microsoft WDM Image Capture (Win32)」的通用桥，
    以前把它滤掉，结果有摄像头也报「没有」。现在：通用项照样算一台，名字换成 PnP 里的
    「Integrated Camera」这种能看懂的；序号仍然对得上（通用项就是第 0 台）。
    """
    now = time.time()
    if now - float(_CAM_LIST["at"]) < CAM_LIST_TTL:
        return list(_CAM_LIST["names"])
    if not CAMGRAB.is_file():
        return []
    raw: List[str] = []
    try:
        proc = subprocess.run([sys.executable, str(CAMGRAB), "--list"],
                              capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)
        got = json.loads(_decode(proc.stdout or b"{}").strip() or "{}")
        raw = [str(x) for x in (got.get("cameras") or [])]
    except Exception:
        raw = []
    generic = [n for n in raw if "WDM Image Capture" in n]
    real = [n for n in raw if "WDM Image Capture" not in n]
    pnp = pnp_cameras()
    if real:
        names = real
    elif generic:
        names = pnp if pnp else ["摄像头 0"]
    elif pnp:
        # VFW 一个都没枚举到，但系统里确实有摄像头：仍然报出去，抓帧时试 0 号
        names = pnp
    else:
        names = []
    _CAM_LIST.update({"at": now, "names": names})
    return names


CAMSHOT = HERE / "camshot.ps1"


def png_size(path: Path) -> Tuple[int, int]:
    """从 PNG 头里读宽高（IHDR）。"""
    try:
        raw = path.read_bytes()[:33]
        if raw[:8] != b"\x89PNG\r\n\x1a\n":
            return 0, 0
        import struct
        w, h = struct.unpack(">II", raw[16:24])
        return int(w), int(h)
    except Exception:
        return 0, 0


def camera_mf_grab(out_png: Path, width: int = 1280, height: int = 720,
                   timeout: float = 30.0) -> bool:
    """用 MediaFoundation（PowerShell + Windows.Media.Capture）拍一张。

    VFW（avicap32）在一些 USB 摄像头上会卡在 DRIVER_CONNECT 不返回；MF 这条路
    Win10/11 自带，实测能出图。
    """
    if not CAMSHOT.is_file():
        return False
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(CAMSHOT),
             "-Out", str(out_png), "-Width", str(int(width)), "-Height", str(int(height))],
            capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)
        out = _decode(proc.stdout or b"").strip()
        return proc.returncode == 0 and out_png.is_file() and out_png.stat().st_size > 1000
    except Exception:
        return False


def camera_grab(index: int, out_png: Path, width: int = 1280, height: int = 720,
                timeout: float = 25.0) -> Dict[str, Any]:
    """抓一帧存 PNG：先试 MediaFoundation，失败再退回老 VFW。"""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    if camera_mf_grab(out_png, width, height, timeout=timeout):
        w, h = png_size(out_png)
        return {"path": out_png, "width": w, "height": h, "via": "mf"}
    return _camera_grab_vfw(index, out_png, width, height, timeout=min(12.0, timeout))


def _camera_grab_vfw(index: int, out_png: Path, width: int = 1280, height: int = 720,
                     timeout: float = 12.0) -> Dict[str, Any]:
    """老路：VFW 抓一帧存 BMP 再转 PNG。卡住/没有摄像头都会抛 SenseError。"""
    now = time.time()
    if _CAM_ERR["msg"] and now - float(_CAM_ERR["at"]) < 60:
        raise SenseError(_CAM_ERR["msg"], "插上摄像头，或者把设置里的「摄像头」关掉。", code="no_camera")
    if not CAMGRAB.is_file():
        raise SenseError(f"少了 {rel(CAMGRAB)}。", "这个包不完整，重新装一次。", code="no_camera")
    tmp_bmp = Path(tempfile.gettempdir()) / f"bab-sense-cam-{os.getpid()}-{int(now * 1000)}.bmp"
    try:
        proc = subprocess.run([sys.executable, str(CAMGRAB), "--grab", str(index), str(tmp_bmp),
                               str(width), str(height)],
                              capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)
        out = _decode(proc.stdout or b"").strip()
        got = json.loads(out.splitlines()[-1] if out else "{}") if out else {}
    except subprocess.TimeoutExpired:
        msg = "摄像头没反应（15 秒都没吐出画面），已经放弃了。"
        _CAM_ERR.update({"at": now, "msg": msg})
        _drop(tmp_bmp)
        raise SenseError(msg, "这台机器可能没有摄像头；有的话检查是不是被别的程序占着。", code="no_camera")
    except Exception as e:
        msg = f"摄像头抓帧出错：{type(e).__name__}: {e}"
        _CAM_ERR.update({"at": now, "msg": msg})
        _drop(tmp_bmp)
        raise SenseError(msg, "把设置里的「摄像头」关掉也行。", code="no_camera")
    if not got.get("ok"):
        msg = str(got.get("error") or "摄像头没给出画面")[:200]
        _CAM_ERR.update({"at": now, "msg": msg})
        raise SenseError(msg, "这台机器可能没有摄像头。", code="no_camera")
    src = Path(str(got.get("path") or tmp_bmp))
    if not src.is_file():
        raise SenseError("摄像头说拍到了，但文件不在。", "再试一次。", code="no_camera")
    try:
        w, h, rows = read_bmp(src)
        out_png.parent.mkdir(parents=True, exist_ok=True)
        out_png.write_bytes(encode_png(w, h, rows))
        return {"path": out_png, "width": w, "height": h}
    finally:
        try:
            src.unlink()
        except OSError:
            pass


def read_bmp(path: Path) -> Tuple[int, int, List[bytes]]:
    """读 24/32 位、不压缩的 BMP（VFW 存出来的就是这种），转成 RGBA 行。"""
    raw = path.read_bytes()
    if raw[:2] != b"BM":
        raise SenseError("摄像头存出来的不是 BMP。", "换个摄像头或者用截屏。", code="no_camera")
    import struct
    off = struct.unpack_from("<I", raw, 10)[0]
    hsize = struct.unpack_from("<I", raw, 14)[0]
    w = struct.unpack_from("<i", raw, 18)[0]
    h = struct.unpack_from("<i", raw, 22)[0]
    bpp = struct.unpack_from("<H", raw, 28)[0]
    comp = struct.unpack_from("<I", raw, 30)[0]
    if comp not in (0, 3) or bpp not in (24, 32):
        raise SenseError(f"这种 BMP 读不了（bpp={bpp}, 压缩={comp}）。", "换个摄像头。", code="no_camera")
    stride = ((w * bpp // 8) + 3) // 4 * 4
    top_down = h < 0
    h = abs(h)
    step = bpp // 8
    rows: List[bytes] = []
    for i in range(h):
        y = i if top_down else (h - 1 - i)
        line = raw[off + y * stride: off + y * stride + w * step]
        row = bytearray(w * 4)
        row[0::4] = line[2::step][:w]
        row[1::4] = line[1::step][:w]
        row[2::4] = line[0::step][:w]
        row[3::4] = b"\xff" * w
        rows.append(bytes(row))
    return w, h, rows
