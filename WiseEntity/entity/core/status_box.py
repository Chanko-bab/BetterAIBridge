"""各程序现在什么状态：给她一句人话，让她知道缺什么、该找主人帮什么。

- QQ：先看 qq_bridge 模组装没装；装了才看它自己的 6199 有没有 ESTABLISHED
- B 站：拿 sites.json 里的 cookie 打 nav，-101 就是登录过期

结果缓存（QQ 60 秒 / B 站 600 秒），失败一律按"不知道"处理，不抛给对话。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import modules_box, settings as S

QQ_MODULE_DIR = S.BUNDLE / "program_01_qq"
BILI_MODULE_FILE = S.CORE_DIR / "bili_door.py"
import time

import httpx

_qq_cache = {"ts": 0.0, "text": ""}
_bili_cache = {"ts": 0.0, "text": ""}


def _mod_on(mid: str) -> bool:
    """模组是否"已启用"（registry 说了算，不看文件在不在）。"""
    try:
        return any(str(m.get("id")) == mid and str(m.get("state")) == "enabled"
                   for m in modules_box.modules())
    except Exception:
        return False


def _netstat_6199() -> bool:
    try:
        cp = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                            encoding="gbk", errors="ignore",
                            timeout=8, creationflags=0x08000000)
        for line in (cp.stdout or "").splitlines():
            if ":6199" in line and "ESTABLISHED" in line.upper():
                return True
    except Exception:
        return False
    return False


def _qq_alive() -> bool:
    try:
        cp = subprocess.run(["tasklist", "/FI", "IMAGENAME eq QQ.exe", "/NH"],
                            capture_output=True, text=True, encoding="gbk", errors="ignore",
                            timeout=8, creationflags=0x08000000)
        return "QQ.exe" in (cp.stdout or "")
    except Exception:
        return False


def qq_line() -> str:
    if not _mod_on("qq_bridge"):
        return "模组没装（QQ 桥还在 program_cache 里歇着）"
    now = time.time()
    if now - _qq_cache["ts"] > 60:
        link = _netstat_6199()
        alive = _qq_alive()
        if link:
            text = "在线，能发消息"
        elif alive:
            text = "程序开着但没登进去（多半要你在电脑上扫码/点一下登录）"
        else:
            text = "没开（要你在桌面点「启动QQ-无名」那个快捷方式）"
        _qq_cache.update(ts=now, text=text)
    return _qq_cache["text"]


def _bili_cookies() -> dict:
    data = S.read_json(S.MEM_DIR / "sites.json", {}) or {}
    bili = (data.get("bilibili") or {}) if isinstance(data, dict) else {}
    cookies = bili.get("cookies") or {}
    return cookies if isinstance(cookies, dict) else {}


def bili_line() -> str:
    if not _mod_on("bili_bridge"):
        return "模组没装（B 站还在 program_cache 里歇着）"
    now = time.time()
    if now - _bili_cache["ts"] > 600:
        cookies = _bili_cookies()
        if not cookies.get("SESSDATA"):
            text = "没有登录信息（要你把 SESSDATA 那几项给我）"
        else:
            try:
                r = httpx.get("https://api.bilibili.com/x/web-interface/nav",
                              cookies={k: str(v) for k, v in cookies.items()},
                              headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"},
                              timeout=12.0)
                code = (r.json() or {}).get("code")
                if code == 0:
                    text = "登录有效，能发私信、看视频"
                elif code == -101:
                    text = "登录过期了（要你重新给我 cookie，或我出个二维码你扫）"
                else:
                    text = f"接口回了个 {code}，暂时说不清"
            except Exception:
                text = "这会儿连不上 B 站，可能断网了"
        _bili_cache.update(ts=now, text=text)
    return _bili_cache["text"]


def fragment() -> str:
    return ("# 各程序现在什么状态（说话前先对一下，别硬撑）\n"
            f"- QQ：{qq_line()}\n"
            f"- B 站：{bili_line()}")
