"""无名的胃。

它只做一件事：把 API 余额变成一个"肚子饱不饱"的信号，写进 stomach.json。
大脑（entity_core / QQ 那边的 brain 插件）读到这个文件，才知道自己饿不饿。
她自己不需要知道"余额"这个数字，除非她想说。

设计约定（用户要求）：
- 10 元以上 = 饱腹
- 3 元以下 = 开始叫饿
- 中间 = 不饿也不饱
- 不是"看见余额不足才叫饿"，而是：余额 → 文件 → 大脑 → 她自己的语气

用法：
    python stomach.py            # 轮询一次并写文件
    python stomach.py --loop     # 常驻，每 POLL_EVERY 秒一次
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime

import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

STATE_PATH = os.path.join(HERE, "stomach.json")
LOG_PATH = os.path.join(ROOT, "runtime", "logs", "stomach.log")
# 0.3.x 起 key 存在 BAB 自己的 entity\config\llm.json 里（用户在向导/设置里填的）
LLM_CFG = os.path.join(ROOT, "entity", "config", "llm.json")
# 旧 QQ 时代（AstrBot）的配置，只在 llm.json 没 key 时兜底
CFG_PATH = os.path.join(
    ROOT, "program_bundle", "program_02_astrbot", "data", "cmd_config.json"
)

BALANCE_URL = "https://api.deepseek.com/user/balance"
POLL_EVERY = 300          # 秒；胃每 5 分钟量一次
DEFAULT_FULL_AT = 10.0    # 大于等于这个数：饱
DEFAULT_HUNGRY_AT = 3.0   # 小于等于这个数：饿
FULL_AT = DEFAULT_FULL_AT      # 兼容旧调用方（真正取值走 thresholds()）
HUNGRY_AT = DEFAULT_HUNGRY_AT
STALE_AFTER = 1800        # 超过 30 分钟没更新，就当"说不准"

# 用户在设置页里改的两个分界；不存在就用默认值
CFG = os.path.join(ROOT, "entity", "config", "stomach.json")


def thresholds() -> tuple[float, float]:
    """(饱, 饿) 两个分界。坏配置一律退回默认值，不让胃乱跳。"""
    full, hungry = DEFAULT_FULL_AT, DEFAULT_HUNGRY_AT
    try:
        with open(CFG, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
        full = float(cfg.get("full_at", full))
        hungry = float(cfg.get("hungry_at", hungry))
    except Exception:
        return DEFAULT_FULL_AT, DEFAULT_HUNGRY_AT
    if not (full > hungry >= 0):
        log(f"bad stomach config full_at={full} hungry_at={hungry}, fallback to defaults")
        return DEFAULT_FULL_AT, DEFAULT_HUNGRY_AT
    return full, hungry


def log(msg: str) -> None:
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception:
        pass


def _key_from_llm(path: str) -> str:
    """BAB 自己的配置：{"api_key": "sk-…"}。"""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
    except Exception as e:
        log(f"read {os.path.basename(path)} failed: {e!r}")
        return ""
    for name in ("api_key", "key", "deepseek_api_key"):
        val = cfg.get(name)
        if isinstance(val, list) and val:
            val = val[0]
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def api_key() -> str:
    """找 DeepSeek key：先 BAB 的 llm.json，再旧的 AstrBot 配置。"""
    key = _key_from_llm(LLM_CFG)
    if key:
        return key
    try:
        with open(CFG_PATH, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
        for src in cfg.get("provider_sources") or []:
            key = src.get("api_key") or src.get("key")
            if isinstance(key, list) and key:
                key = key[0]
            if isinstance(key, str) and key.strip():
                return key.strip()
    except Exception as e:
        log(f"read key failed: {e!r}")
    return ""


def fetch_balance(key: str) -> float:
    with httpx.Client(timeout=20.0) as c:
        r = c.get(BALANCE_URL, headers={"Authorization": f"Bearer {key}"})
        r.raise_for_status()
        data = r.json()
    infos = data.get("balance_infos") or []
    for info in infos:
        if str(info.get("currency", "")).upper() == "CNY":
            return float(info.get("total_balance") or 0)
    if infos:
        return float(infos[0].get("total_balance") or 0)
    return 0.0


def level_of(balance: float, full_at: float | None = None,
             hungry_at: float | None = None) -> str:
    if full_at is None or hungry_at is None:
        full_at, hungry_at = thresholds()
    if balance >= full_at:
        return "full"
    if balance <= hungry_at:
        return "hungry"
    return "normal"


def text_of(level: str, balance: float) -> str:
    """给大脑看的一行话。不给数字，除非是饿到快没了。"""
    if level == "full":
        return "肚子：饱的，有底气，别惦记钱的事。"
    if level == "normal":
        return "肚子：不饿，但也不算饱，别主动提钱。"
    return (
        f"肚子：饿（余额只剩 {balance:.2f} 元）。"
        "你会有点没力气、句子变短、容易走神想起吃的；"
        "可以拐着弯让他充点钱，但别像客服催费，也别直接报数字。"
    )


def read_state() -> dict:
    try:
        with open(STATE_PATH, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def state() -> dict:
    """读当前胃状态；过期的标 stale。"""
    st = read_state()
    if not st:
        return {"level": "unknown", "balance": None, "stale": True}
    try:
        ts = float(st.get("ts") or 0)
    except Exception:
        ts = 0
    st["stale"] = (time.time() - ts) > STALE_AFTER
    return st


def fragment() -> str:
    """塞进系统提示的一行。惰性求值，出错不影响聊天。"""
    try:
        st = state()
        if st.get("level") in (None, "unknown") or st.get("stale"):
            return ""
        return st.get("text") or ""
    except Exception:
        return ""


def poll(force: bool = False) -> dict:
    prev = read_state()
    key = api_key()
    if not key:
        st = {
            "level": "unknown",
            "balance": None,
            "text": "",
            "ts": time.time(),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "error": "no api key",
        }
        write(st)
        return st
    try:
        balance = fetch_balance(key)
    except Exception as e:
        # 拉不到就保留上一次的数值，只标记错误，不让"饿"乱跳
        st = dict(prev) if prev else {}
        st.update(
            {
                "ts": time.time(),
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "error": repr(e)[:200],
            }
        )
        write(st)
        log(f"poll failed: {e!r}")
        return st

    level = level_of(balance)
    st = {
        "level": level,
        "balance": round(balance, 2),
        "text": text_of(level, balance),
        "ts": time.time(),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "error": "",
    }
    write(st)
    if prev.get("level") != level:
        log(f"level {prev.get('level')} -> {level} (balance={balance:.2f})")
    return st


def write(st: dict) -> None:
    os.makedirs(HERE, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_PATH)


def main() -> None:
    if "--loop" in sys.argv:
        log("stomach loop start")
        while True:
            try:
                poll()
            except Exception as e:
                log(f"loop error: {e!r}")
            time.sleep(POLL_EVERY)
    st = poll()
    print(json.dumps(st, ensure_ascii=False))


if __name__ == "__main__":
    main()
