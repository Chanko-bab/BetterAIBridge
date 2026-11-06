"""启动器本体的耳目：摄像头、屏幕、麦克风。

`app/services/` 里的 `senses.py` / `camgrab.py` / `ocr.ps1` 提供底层采集；设置页
开两个开关、选设备，她在你允许的时候偶尔看一眼/听一下，保姆栏说一声，再把这句
「看到的/听到的」交给内核。

只依赖标准库 + Windows 自带的东西（GDI 截图、winmm 录音、VFW/MediaFoundation
拍照、PowerShell OCR），不额外装包。
"""
from __future__ import annotations

import json
import logging
import os
import random
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..core import config
from . import senses
from .core_client import CoreClient

log = logging.getLogger("xiaochen.sense")

CFG_PATH = config.entity_dir() / "config" / "sense.json"
_OLD_CFG = config.APP_DIR / "config" / "sense.json"
_migrated_old = False
_DEFAULT_CFG = CFG_PATH


def _migrate_old() -> None:
    """旧版把开关写在安装目录 config/sense.json；读到就先搬进 entity/config。"""
    global _migrated_old
    if _migrated_old:
        return
    if str(CFG_PATH) != str(_DEFAULT_CFG):
        return
    _migrated_old = True
    try:
        if CFG_PATH.exists() or not _OLD_CFG.exists():
            return
        CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CFG_PATH.write_bytes(_OLD_CFG.read_bytes())
    except Exception:  # noqa: BLE001
        log.warning("迁移旧耳目配置失败，沿用内存默认值", exc_info=True)

DEFAULTS: Dict[str, Any] = {
    "eyes": False,       # 允许对方主动偷看
    "ears": False,       # 允许对方主动偷听
    "watch": False,      # 允许对方一直看着（定时采样）
    "listen_always": False,  # 允许对方一直听着（定时采样）
    "watch_sec": 120,    # 一直看着：每多少秒采一次
    "listen_sec": 180,   # 一直听着：每多少秒听一次
    "listen_len": 4,     # 一直听着：每次听几秒
    "camera": "",        # 空 = 不用摄像头（看屏幕）；否则序号或名字
    "mic": "",           # 空 = 系统默认麦克风；否则序号
    "announce": True,    # 看/听之前在保姆栏说一声
    "port": 0,           # 耳目小服务的端口（启动时写）
    "token": "",         # 给小服务用的一次性令牌
    "updated_at": "",
}

# 「她主动说话」0-3 档对应的看/听间隔（分钟，取区间随机）
GAPS: Dict[int, Tuple[float, float]] = {
    0: (0.0, 0.0),
    1: (40.0, 65.0),
    2: (16.0, 26.0),
    3: (7.0, 12.0),
}

_lock = threading.Lock()


# ------------------------------------------------------------------ 配置

def cfg() -> Dict[str, Any]:
    _migrate_old()
    try:
        doc = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        doc = {}
    out = dict(DEFAULTS)
    if isinstance(doc, dict):
        out.update({k: doc[k] for k in DEFAULTS if k in doc})
    return out


def save(patch: Dict[str, Any]) -> Dict[str, Any]:
    """只写认识的键；port/token 由小服务自己写，别被界面覆盖掉。"""
    with _lock:
        cur = cfg()
        for k, v in (patch or {}).items():
            if k in DEFAULTS:
                cur[k] = v
        cur["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = CFG_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, CFG_PATH)
        except Exception:  # noqa: BLE001
            log.warning("保存耳目配置失败，本次修改没有落盘", exc_info=True)
        return cur


def enabled() -> bool:
    c = cfg()
    return bool(c.get("eyes") or c.get("ears"))


def level() -> int:
    """「她主动说话」的档位（0-3）；读不到就当 0（不主动看/听）。"""
    try:
        data = CoreClient(timeout=6).followup_get()
        return max(0, min(3, int((data.get("config") or {}).get("level") or 0)))
    except Exception:  # noqa: BLE001
        return 0


def next_gap(level_: int) -> float:
    lo, hi = GAPS.get(int(level_), (0.0, 0.0))
    if hi <= 0:
        return 0.0
    return random.uniform(lo, hi) * 60.0


# ------------------------------------------------------------------ 设备

def devices(refresh: bool = False) -> Dict[str, Any]:
    cams: List[str] = []
    mics: List[Dict[str, Any]] = []
    try:
        cams = list(senses.camera_list(timeout=8.0))
    except Exception:  # noqa: BLE001
        cams = []
    try:
        mics = list(senses.list_mics())
    except Exception:  # noqa: BLE001
        mics = []
    c = cfg()
    return {
        "ok": True,
        "cameras": cams,
        "mics": mics,
        "camera": str(c.get("camera") or ""),
        "mic": str(c.get("mic") or ""),
    }


def camera_index(want: str = "") -> int:
    want = str(want or "").strip()
    if not want:
        return -1
    if want.isdigit():
        return int(want)
    try:
        names = list(senses.camera_list(timeout=6.0))
    except Exception:  # noqa: BLE001
        names = []
    return names.index(want) if want in names else 0


_cams_cache: Dict[str, Any] = {"at": 0.0, "list": []}


def first_camera() -> str:
    """「自动」时用第一台摄像头；设备枚举慢，缓存两分钟。"""
    now = time.time()
    if now - float(_cams_cache["at"] or 0) < 120.0 and _cams_cache["list"]:
        return str((_cams_cache["list"] or [""])[0])
    try:
        names = list(senses.camera_list(timeout=6.0))
    except Exception:  # noqa: BLE001
        names = []
    _cams_cache.update({"at": now, "list": names})
    return str(names[0]) if names else ""


# ------------------------------------------------------------------ 看

def _screen_shot(out: Path) -> str:
    """截前台窗口；没有窗口就截整块屏。返回一句「看到的是什么」。"""
    info: Dict[str, Any] = {}
    try:
        info = senses.focus_window()
    except Exception:  # noqa: BLE001
        info = {}
    rect = info.get("rect") if isinstance(info, dict) else None
    if isinstance(rect, (list, tuple)) and len(rect) == 4:
        x, y, r, b = (int(v) for v in rect)
        w, h = max(0, r - x), max(0, b - y)
        if w > 200 and h > 200:
            gw, gh, rows = senses.grab_rect(x, y, w, h)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(senses.encode_png(gw, gh, rows))
            title = str(info.get("title") or "").strip()
            return f"窗口「{title}」" if title else "前台窗口"
    x, y, w, h = senses.screen_bounds(0)
    gw, gh, rows = senses.grab_rect(x, y, w, h)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(senses.encode_png(gw, gh, rows))
    return "屏幕"


def look(question: str = "", quiet: bool = False) -> Dict[str, Any]:
    """看一眼：优先摄像头，失败/没选就截屏；先 OCR，再交给内核的模型描述。"""
    c = cfg()
    if not quiet and bool(c.get("announce", True)):
        announce("智能体刚刚偷偷看了你一眼。")
    senses.ensure_dirs()
    out = senses.new_shot_path("eye")
    source = "screen"
    what = "屏幕"
    cam = str(c.get("camera") or "").strip()
    if cam == "screen":
        cam = ""
    if not cam:
        cam = first_camera()          # 自动：有摄像头就用，没有才看屏幕
    if cam:
        idx = camera_index(cam)
        if idx >= 0:
            try:
                got = senses.camera_grab(idx, out, timeout=20.0)
                source = "camera"
                what = f"摄像头 {got.get('width')}×{got.get('height')}"
            except Exception:  # noqa: BLE001
                source, what = "screen", "屏幕"
    if source == "screen" or not out.is_file():
        source = "screen"
        what = _screen_shot(out)
    senses.prune(senses.SHOTS)

    words = ""
    try:
        words = senses.ocr_png(out, timeout=20.0)
    except Exception:  # noqa: BLE001
        words = ""

    q = (question or "").strip() or "这是对方那边的画面。用一两句中文说说你看到了什么，别逐字念。"
    desc = ""
    try:
        res = CoreClient(timeout=120).vision(str(out), q)
        desc = str((res or {}).get("text") or "").strip()
    except Exception as e:  # noqa: BLE001
        desc = f"（这次没看清：{str(e).strip() or type(e).__name__}）"
    if words and words not in desc:
        desc = f"{desc}\n画面上的字：{words[:500]}" if desc else f"画面上的字：{words[:500]}"
    return {"ok": True, "source": source, "what": what, "path": str(out),
            "text": desc.strip(), "ocr": words}


# ------------------------------------------------------------------ 听

def listen(seconds: float = 6.0, quiet: bool = False) -> Dict[str, Any]:
    """听几秒：录 wav → 内核的语音服务转文字。"""
    c = cfg()
    if not quiet and bool(c.get("announce", True)):
        announce("智能体刚刚偷偷听了你一下。")
    senses.ensure_dirs()
    sec = max(2.0, min(15.0, float(seconds or 6.0)))
    rec = senses.record(sec, device=senses.pick_mic(str(c.get("mic") or "")), rate=senses.MIC_RATE)
    path = Path(str(rec.get("path") or ""))
    senses.prune(senses.CLIPS)
    text = ""
    try:
        res = CoreClient(timeout=140).asr(str(path), hint="对方刚才说的话，可能是口语、短句。")
        text = str((res or {}).get("text") or "").strip()
    except Exception as e:  # noqa: BLE001
        text = f"（这次没听清：{str(e).strip() or type(e).__name__}）"
    return {"ok": True, "path": str(path), "seconds": rec.get("seconds"),
            "text": text, "loud": rec.get("rms"), "source": "mic"}


# ------------------------------------------------------------------ 告诉内核

def announce(text: str, session: str = "web:owner") -> None:
    try:
        CoreClient(timeout=8).notice_push(text, session=session, kind="sense")
    except Exception:  # noqa: BLE001
        log.debug("耳目提醒推送失败", exc_info=True)


def tell(text: str) -> None:
    """把看到/听到的丢进她的事件流（她不一定马上说话，但会知道）。"""
    try:
        CoreClient(timeout=10).event("sense", text)
    except Exception:  # noqa: BLE001
        log.debug("耳目事件上报失败", exc_info=True)


def token() -> str:
    t = str(cfg().get("token") or "")
    if not t:
        t = secrets.token_hex(16)
        save({"token": t})
    return t


def set_port(port: int) -> Dict[str, Any]:
    return save({"port": int(port)})
