"""时间感：让她知道现在几点、隔了多久没说话、这次是不是关了又开。

不猜、不写死：只读两处事实——
- 当前时间：本机时钟；
- 上一次说话：sessions.json 里该门最后一条 user 的 ts（chat_core 已经在写）。

关闭时间由启动器在托盘「退出」时 POST /time/shutdown 写入；运行中每 60 秒
POST /time/heartbeat 续一次 last_alive_at，所以即使被强杀，也能从心跳估出
关闭了多久。
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from . import settings as S

STATE_PATH = S.STATE_DIR / "time_sense.json"

# 4 小时 30 分没收到消息，才提“过了多久没说话”。
IDLE_SEC = 4 * 3600 + 30 * 60
# 托盘退出后 40 分钟内重开，不提“距离上次关闭”，因为太短。
BOOT_QUIET_SEC = 40 * 60

_WEEK = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def _state() -> dict:
    data = S.read_json(STATE_PATH, {}) or {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    S.write_json(STATE_PATH, data)


def _clock(ts: float) -> str:
    return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")


def _now_text(ts: float) -> str:
    d = datetime.fromtimestamp(float(ts))
    return f"{d:%Y-%m-%d} {_WEEK[d.weekday()]} {d:%H:%M}"


def _when_text(ts: float) -> str:
    d = datetime.fromtimestamp(float(ts))
    today = datetime.now().date()
    if d.date() == today:
        return f"今天 {d:%H:%M}"
    if (today - d.date()).days == 1:
        return f"昨天 {d:%H:%M}"
    return f"{d.month} 月 {d.day} 日 {d:%H:%M}"


def _gap_text(seconds: float) -> str:
    sec = max(0, int(seconds))
    days, rest = divmod(sec, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days} 天 {hours} 小时" if hours else f"{days} 天"
    if hours:
        return f"{hours} 小时 {minutes} 分钟" if minutes else f"{hours} 小时"
    return f"{max(1, minutes)} 分钟"


def _last_user_at(session: str) -> float:
    data = S.read_json(S.SESSIONS_PATH, {}) or {}
    rows = data.get(session) if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return 0.0
    for row in reversed(rows):
        if not isinstance(row, dict) or row.get("role") != "user":
            continue
        raw = str(row.get("ts") or "")
        try:
            return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S").timestamp()
        except ValueError:
            continue
    return 0.0


def boot() -> dict:
    """启动器启动时调一次：算出这次关掉了多久。"""
    now = time.time()
    data = _state()
    prev = max(float(data.get("last_shutdown_at") or 0),
               float(data.get("last_alive_at") or 0))
    gap = max(0.0, now - prev) if prev else 0.0
    show = bool(prev) and gap >= BOOT_QUIET_SEC
    data.update({
        "boot_at": now,
        "boot_gap_s": round(gap, 1),
        "boot_from_at": prev,
        "boot_pending": show,
        "last_alive_at": now,
    })
    _save(data)
    return {"ok": True, "gap_s": round(gap, 1), "show": show,
            "quiet_sec": BOOT_QUIET_SEC}


def shutdown() -> dict:
    """托盘「退出」时调一次；被强杀时靠心跳兜底。"""
    now = time.time()
    data = _state()
    data.update({
        "last_shutdown_at": now,
        "last_alive_at": now,
        "boot_pending": False,
    })
    _save(data)
    return {"ok": True}


def heartbeat() -> dict:
    data = _state()
    data["last_alive_at"] = time.time()
    _save(data)
    return {"ok": True}


def consume_boot() -> None:
    """这句话已经带给模型了，就别在下一轮重复。"""
    data = _state()
    if data.get("boot_pending"):
        data["boot_pending"] = False
        _save(data)


def fragment(session: str = "web:owner") -> str:
    """每轮提示词里的时间块；可能只有“现在几点”。"""
    now = time.time()
    data = _state()
    lines = ["# 时间", f"现在是 {_now_text(now)}。"]

    last_shutdown = float(data.get("last_shutdown_at") or 0)
    from_at = float(data.get("boot_from_at") or last_shutdown)
    if data.get("boot_pending") and from_at:
        gap = max(0.0, now - from_at)
        lines.append(
            f"距离上一次关闭启动器已经过了 {_gap_text(gap)}"
            f"（上次关闭是 {_when_text(from_at)}）。"
            "这是重新打开后的第一句话。"
        )
        return "\n".join(lines)

    last = _last_user_at(session)
    if last:
        gap = max(0.0, now - last)
        if gap >= IDLE_SEC:
            lines.append(
                f"距离上一次说话已经过了 {_gap_text(gap)}"
                f"（上次是 {_when_text(last)}）。"
            )
    return "\n".join(lines)


def status() -> dict:
    """给测试/排查看，不进提示词。"""
    data = _state()
    return {
        "ok": True,
        "boot_pending": bool(data.get("boot_pending")),
        "boot_gap_s": float(data.get("boot_gap_s") or 0),
        "last_shutdown_at": float(data.get("last_shutdown_at") or 0),
        "last_alive_at": float(data.get("last_alive_at") or 0),
        "idle_sec": IDLE_SEC,
        "boot_quiet_sec": BOOT_QUIET_SEC,
    }
