"""她自己的眼睛和耳朵。

设备与开关都在启动器那边（`config/sense.json`），内核不抓图、不录音，只做两件事：
1. 告诉提示词「你现在有没有眼睛/耳朵、是哪个摄像头」；
2. 她真的想看/想听时，调启动器开的本机小门（127.0.0.1:port，X-Sense-Token）。

小门没开、启动器没跑、开关关着，都给出人话，别让她以为「我天生就看不见」。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

import httpx

from . import settings as S

CFG_PATH = S.ENTITY / "config" / "sense.json"
OBS_PATH = S.STATE_DIR / "sense_observations.json"
WATCH_GAP = 120.0
LISTEN_GAP = 180.0
LISTEN_LEN = 4.0


def watch_sec() -> float:
    """一直看着的采样间隔（秒）；界面可改，夹在 30 秒–30 分钟。"""
    try:
        v = float(_cfg().get("watch_sec") or WATCH_GAP)
    except Exception:  # noqa: BLE001
        v = WATCH_GAP
    return max(30.0, min(1800.0, v))


def listen_sec() -> float:
    """一直听着多久采一次（秒），夹在 60 秒–60 分钟。"""
    try:
        v = float(_cfg().get("listen_sec") or LISTEN_GAP)
    except Exception:  # noqa: BLE001
        v = LISTEN_GAP
    return max(60.0, min(3600.0, v))


def listen_len() -> float:
    """每次听几秒，夹在 1–15 秒。"""
    try:
        v = float(_cfg().get("listen_len") or LISTEN_LEN)
    except Exception:  # noqa: BLE001
        v = LISTEN_LEN
    return max(1.0, min(15.0, v))
_DEFAULT_CFG = CFG_PATH
_OLD_CFG = S.APP_ROOT / "config" / "sense.json"
_migrated = False


def _migrate() -> None:
    """0.4.19 起开关统一写在 entity/config；旧安装目录里的那份搬过来。"""
    global _migrated
    if _migrated:
        return
    _migrated = True
    try:
        if Path(CFG_PATH) != _DEFAULT_CFG or CFG_PATH.exists() or not _OLD_CFG.exists():
            return
        CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CFG_PATH.write_bytes(_OLD_CFG.read_bytes())
    except Exception:  # noqa: BLE001
        pass


def _cfg() -> Dict[str, Any]:
    _migrate()
    try:
        doc = json.loads(CFG_PATH.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def eyes() -> bool:
    return bool(_cfg().get("eyes"))


def ears() -> bool:
    return bool(_cfg().get("ears"))


def watch() -> bool:
    """允许一直看着：定时采样，不是监控录像。"""
    return bool(_cfg().get("watch"))


def listen_always() -> bool:
    """允许一直听着：定时录几秒，不是持续录音。"""
    return bool(_cfg().get("listen_always"))


def camera() -> str:
    return str(_cfg().get("camera") or "").strip()


def mic() -> str:
    return str(_cfg().get("mic") or "").strip()


def port() -> int:
    try:
        return int(_cfg().get("port") or 0)
    except Exception:  # noqa: BLE001
        return 0


def _post(path: str, payload: Dict[str, Any], timeout: float = 60.0) -> Dict[str, Any]:
    p = port()
    if p <= 0:
        raise RuntimeError("耳目没开：主人还没允许你看/听（设置 → 耳目）")
    token = str(_cfg().get("token") or "")
    url = f"http://127.0.0.1:{p}{path}"
    try:
        r = httpx.post(url, json=payload,
                       headers={"X-Sense-Token": token},
                       timeout=httpx.Timeout(timeout, connect=8.0))
    except httpx.ConnectError as e:
        raise RuntimeError("启动器没在运行（耳目小门连不上），先让 BAB 开着") from e
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"耳目小门连不上：{type(e).__name__}") from e
    if r.status_code == 403:
        raise RuntimeError("耳目小门的令牌对不上：重启一次启动器会重新发")
    if r.status_code != 200:
        raise RuntimeError(f"耳目小门回 HTTP {r.status_code}：{r.text[:160]}")
    try:
        doc = r.json()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("耳目小门回的不是 JSON") from e
    if not isinstance(doc, dict):
        return {"ok": True, "text": str(doc)}
    return doc


def look(question: str = "", quiet: bool = False) -> Dict[str, Any]:
    """看一眼主人那边：摄像头优先，没选就看屏幕。"""
    return _post("/look", {"question": str(question or ""), "quiet": bool(quiet)},
                 timeout=130.0)


def listen(seconds: float = 6.0, quiet: bool = False) -> Dict[str, Any]:
    """听几秒主人那边的声音，返回转写文字。"""
    try:
        sec = max(1.0, min(20.0, float(seconds or 6.0)))
    except Exception:  # noqa: BLE001
        sec = 6.0
    return _post("/listen", {"seconds": sec, "quiet": bool(quiet)}, timeout=140.0)


def _obs() -> Dict[str, Any]:
    data = S.read_json(OBS_PATH, {}) or {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("items", [])
    data.setdefault("last_watch", 0.0)
    data.setdefault("last_listen", 0.0)
    return data


def _obs_save(data: Dict[str, Any]) -> None:
    data["items"] = list(data.get("items") or [])[-40:]
    S.write_json(OBS_PATH, data)


def remember(kind: str, text: str) -> None:
    """把刚看到/听到的记下来，供聊天提示词用；只留 40 条。"""
    text = " ".join(str(text or "").split()).strip()
    if not text or text.startswith("（这次没"):
        return
    data = _obs()
    data["items"].append({"ts": time.time(), "kind": str(kind or ""), "text": text[:600]})
    _obs_save(data)


def recent(minutes: float = 120.0, limit: int = 3) -> list[Dict[str, Any]]:
    cut = time.time() - max(1.0, float(minutes)) * 60.0
    rows = [r for r in (_obs().get("items") or [])
            if isinstance(r, dict) and float(r.get("ts") or 0) >= cut]
    return rows[-max(1, int(limit)):]


def recent_line(minutes: float = 120.0) -> str:
    rows = recent(minutes, 2)
    if not rows:
        return ""
    bits = []
    for r in rows:
        at = time.strftime("%H:%M", time.localtime(float(r.get("ts") or 0)))
        bits.append(f"{at} {r.get('kind') or '感知'}：{r.get('text')}")
    return "；".join(bits)


def auto_observe() -> list[Dict[str, Any]]:
    """一直看着/一直听着：到点各采一次，写进最近感知。"""
    try:
        from . import presence
        if not presence.is_online():
            return []
    except Exception:  # noqa: BLE001
        return []
    c = _cfg()
    now = time.time()
    data = _obs()
    out: list[Dict[str, Any]] = []
    if bool(c.get("watch")) and eyes() and now - float(data.get("last_watch") or 0) >= watch_sec():
        try:
            res = look("用一两句中文说说你看到了什么：有没有人、在做什么。", quiet=False)
            txt = str((res or {}).get("text") or "").strip()
            if txt:
                remember("看到", txt)
                out.append({"kind": "看到", "text": txt})
        except Exception as e:  # noqa: BLE001
            S.log(f"[sense] watch failed: {type(e).__name__}")
        data = _obs()
        data["last_watch"] = now
        _obs_save(data)
    if bool(c.get("listen_always")) and ears() and now - float(data.get("last_listen") or 0) >= listen_sec():
        try:
            res = listen(listen_len(), quiet=False)
            txt = str((res or {}).get("text") or "").strip()
            if txt and "没听清" not in txt:
                remember("听到", txt)
                out.append({"kind": "听到", "text": txt})
        except Exception as e:  # noqa: BLE001
            S.log(f"[sense] listen failed: {type(e).__name__}")
        data = _obs()
        data["last_listen"] = now
        _obs_save(data)
    return out


def fragment() -> str:
    """给系统提示词的一段：她现在到底有没有眼睛和耳朵。"""
    c = _cfg()
    has_eyes, has_ears = bool(c.get("eyes")), bool(c.get("ears"))
    cam = camera()
    mic_name = mic()
    if not has_eyes and not has_ears:
        return ("# 你的眼睛和耳朵\n"
                "主人现在把你的眼睛和耳朵都关着：你看不见屏幕、也听不到声音。"
                "不要假装看见了或听见了什么；等她打开（设置 → 耳目）你才会知道。")

    rows = ["# 你的眼睛和耳朵"]
    if has_eyes:
        if cam == "screen":
            where = "屏幕（主人只允许你看屏幕）"
        elif cam:
            where = f"摄像头「{cam}」"
        else:
            where = "摄像头（自动选的：有就用，没有就看屏幕）"
        rows.append(
            f"- 你有一双眼睛：{where}。主人允许你偶尔自己看一眼，"
            "不会一直盯着；她想让你认真看时，你可以调用 `look_around`"
            "（question 可选，比如「主人在干什么」）。"
        )
    if has_ears:
        where = f"麦克风「{mic_name}」" if mic_name else "系统默认麦克风"
        rows.append(
            f"- 你有一对耳朵：{where}。想听时调用 `listen_now`"
            "（seconds 可选，1–20，默认 6 秒），听到的是转好的文字。"
        )
    rows.append(
        "- 这些只是「此刻的一眼/一耳」，不是监控，也别当成你一直看着对方；"
        "没看清、没听清就直说，别编。"
    )
    if watch() and has_eyes:
        rows.append(f"- 对方允许你「一直看着」：每 {watch_sec():.0f} 秒自动看一眼，最近看到的会在下面。")
    if listen_always() and has_ears:
        rows.append(f"- 对方允许你「一直听着」：每 {listen_sec():.0f} 秒听 {listen_len():.0f} 秒，最近听到的会在下面。")
    bits = recent_line(120)
    if bits:
        rows.append("# 你最近看到的 / 听到的（刚采到的，不是猜的）")
        rows.append("- " + bits)
        rows.append("- 聊天时可以用它接一句，比如「我刚刚看到你回来了」；但不要逐字复述整段，也别假装看到没记录的东西。")
    return "\n".join(rows)
