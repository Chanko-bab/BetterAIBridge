"""无名的常驻内核 · 配置与路径（entity_core）

设计原则：
- 这个进程是"她"本体：情绪、记忆、人格、说话能力都在这里。
- QQ / B 站 / 网页 只是"门"（door），门关着不影响她活着。
- 不依赖 AstrBot；只依赖 DeepSeek HTTP 接口。
- 所有路径都从**程序自身位置**推导，不写死盘符：整目录搬到 C 盘 / D 盘 / 移动硬盘都能跑。
  需要临时指到别处时设环境变量 BAB_ROOT=<安装根目录>（该目录下应有 WiseEntity\\）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# 安装根目录：<APP>\\WiseEntity\\entity\\core\\settings.py 往上三层
APP_ROOT = Path(os.environ.get("BAB_ROOT") or Path(__file__).resolve().parents[3])
ROOT = APP_ROOT / "WiseEntity"

# 0.4.19 起数据回到安装目录（每个安装一份）；install.json 只留 install_id 与端口。
_INSTALL_PATH = APP_ROOT / "config" / "install.json"
ENTITY = ROOT / "entity"
BRAIN_DIR = ENTITY / "brain"
CORE_DIR = ENTITY / "core"
MEM_DIR = ENTITY / "memory"
STATE_DIR = ENTITY / "state"
PERSONA_PATH = ENTITY / "persona" / "persona.md"
LOGS = ROOT / "runtime" / "logs"
LOG_PATH = LOGS / "entity_core.log"

BUNDLE = APP_ROOT / "program_bundle"
PROGRAM_CACHE = APP_ROOT / "program_cache"

BRAIN_STATE = BRAIN_DIR / "flybrain_state.json"
EVENT_INBOX = BRAIN_DIR / "event_inbox.jsonl"
THOUGHTS = BRAIN_DIR / "thoughts.jsonl"
SESSIONS_PATH = STATE_DIR / "sessions.json"
CORE_STATE = STATE_DIR / "entity_core.json"
BILI_DOOR_CFG = STATE_DIR / "bili_door.json"

HOST = "127.0.0.1"

# ---- 安装身份与端口块 -------------------------------------------------
# 一次安装 = 一个 install_id + 一段连续端口：core=B, asr=B+1, 模组池 B+5..B+19。
# 端口不再写死：换机器、多份安装、端口被占，都靠这里重新分配。
INSTALL_PATH = _INSTALL_PATH


def _yaml_port(name: str, default: int = 0) -> int:
    """从安装目录的 config/app.yaml 里取端口；取不到就回 default。"""
    import re

    try:
        y = (APP_ROOT / "config" / "app.yaml").read_text(encoding="utf-8-sig")
    except Exception:  # noqa: BLE001
        return default
    m = re.search(r"(?m)^\s*" + re.escape(name) + r":\s*(\d+)\s*$", y)
    try:
        return int(m.group(1)) if m else default
    except Exception:  # noqa: BLE001
        return default


def install_info() -> dict:
    """读安装身份；没有就按当前 app.yaml 的 core 端口生成一份。"""
    try:
        doc = json.loads(INSTALL_PATH.read_text(encoding="utf-8-sig"))
        if isinstance(doc, dict) and doc.get("install_id"):
            return doc
    except Exception:  # noqa: BLE001
        pass
    import uuid

    base = _yaml_port("core", 40720)
    asr = _yaml_port("asr", 0)
    doc = {"install_id": uuid.uuid4().hex, "base": base, "maker": "settings"}
    if asr:
        doc["asr"] = asr
    try:
        INSTALL_PATH.parent.mkdir(parents=True, exist_ok=True)
        INSTALL_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return doc


_INSTALL = install_info()
INSTALL_ID = str(_INSTALL.get("install_id") or "")
BASE_PORT = int(_INSTALL.get("base") or 40720)
PORT = int(os.environ.get("BAB_PORT") or BASE_PORT)
ASR_PORT = int(os.environ.get("BAB_ASR_PORT") or _INSTALL.get("asr") or _yaml_port("asr", BASE_PORT + 1))


OWNER_ID = "10001"          # 主人 QQ
BRAIN_N = 1600
BRAIN_SEED = 7
TICK_SECONDS = 90                 # 生物钟：每 90 秒推进 30 秒
TICK_BIOTIC = 30.0

TZ_OFFSET = 8


def ensure_dirs() -> None:
    """缺目录只记一笔，不把内核拖死（新装机 / 只读盘上也能起来）。

    只建"这个程序自己的"目录：状态、日志、大脑、记忆根。
    记忆抽屉（internal/、external/）由真正写入时自己长出来——不替任何模组
    提前摆好位置，也不再预建 `memory/program_qq` 这种"先给模组留一间房"。
    """
    for d in (STATE_DIR, LOGS, CORE_DIR / "static", BRAIN_DIR, MEM_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            log(f"[dirs] 建不了 {d}：{e}")


def log(msg: str) -> None:
    import time
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def read_json(path: Path, default=None):
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception:
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _llm_cfg() -> dict:
    """模型配置：优先她自己的 entity\\config\\llm.json，其次环境变量，最后才找模组里的旧配置。"""
    try:
        cfg = read_json(ENTITY / "config" / "llm.json", {}) or {}
        if cfg.get("api_key"):
            return cfg
    except Exception:
        pass
    return {}


def _legacy_cfg() -> dict:
    for p in (PROGRAM_CACHE / "qq_bridge" / "program_02_astrbot" / "data" / "cmd_config.json",
              APP_ROOT / "modules" / "qq_bridge" / "program_02_astrbot" / "data" / "cmd_config.json"):
        try:
            cfg = read_json(p, {}) or {}
            if cfg.get("provider_sources"):
                return cfg
        except Exception:
            continue
    return {}


def deepseek_key() -> str:
    """她自己的 key（entity\\config\\llm.json），QQ 模组搬走后不再依赖 AstrBot。"""
    env = (os.environ.get("XIAOCHEN_LLM_KEY") or "").strip()
    if env:
        return env
    cfg = _llm_cfg()
    if cfg.get("api_key"):
        key = cfg["api_key"]
        if isinstance(key, list):
            key = key[0] if key else ""
        return str(key)
    old = _legacy_cfg()
    for src in old.get("provider_sources") or []:
        if not isinstance(src, dict):
            continue
        key = src.get("api_key") or src.get("key")
        if isinstance(key, list):
            key = key[0] if key else ""
        if key:
            return str(key)
    return ""


def deepseek_base() -> str:
    cfg = _llm_cfg()
    if cfg.get("api_base"):
        return str(cfg["api_base"]).rstrip("/")
    old = _legacy_cfg()
    for src in old.get("provider_sources") or []:
        if isinstance(src, dict) and src.get("api_base"):
            return str(src["api_base"]).rstrip("/")
    return "https://api.deepseek.com/v1"


def persona_text() -> str:
    try:
        txt = PERSONA_PATH.read_text(encoding="utf-8")
    except Exception:
        return "你是无名。"
    lines = txt.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip()


def llm_cfg() -> dict:
    """框架版的模型配置：entity\\config\\llm.json。"""
    return read_json(ENTITY / "config" / "llm.json", {}) or {}


def relation(default: str = "朋友") -> str:
    """使用者在她这里的身份：开局向导写进 llm.json 的 relation（主人/朋友/家人/恋人/搭档/老师）。"""
    v = str(llm_cfg().get("relation") or "").strip()
    return v[:8] or default


def style(default: str = "") -> str:
    """她的脾气：开局向导写进 llm.json 的 style（傲娇/温柔/活泼…）。

    插话的「四档性格」（followup.PROFILES）靠它挑底表；没有就按常态。
    """
    v = str(llm_cfg().get("style") or "").strip()
    return v[:12] or default


def user_title(default: str = "他") -> str:
    """她平时怎么称呼使用者：user_title 取第一个（"您/大人/主人" → "您"）；没写就用「他」。"""
    raw = str(llm_cfg().get("user_title") or "").strip()
    first = raw.replace("／", "/").split("/")[0].strip()
    return first[:12] or default


def entity_name() -> str:
    """她叫什么：优先 llm.json 的 entity_name，其次人格第一行 '# 名字'，都没有就空。"""
    name = str(llm_cfg().get("entity_name") or "").strip()
    if name:
        return name
    try:
        first = PERSONA_PATH.read_text(encoding="utf-8").splitlines()[0].strip()
    except Exception:
        return ""
    if first.startswith("# "):
        return first[2:].strip()
    return ""


def memory_token() -> str:
    """内核自带的小服务（语音转写）用的全局令牌。

    模组各自有一份 `bridge_token.txt`；ASR 不属于任何模组，所以单开一份，
    位置沿用 Ermu 已经在读的 `entity/memory/bridge_token.json`。
    没有就生成一个，写在盘上，重启后还是同一个。
    """
    path = ENTITY / "memory" / "bridge_token.json"
    try:
        doc = read_json(path, {}) or {}
        tok = str(doc.get("token") or "").strip()
        if tok:
            return tok
    except Exception:  # noqa: BLE001
        pass
    import secrets

    tok = secrets.token_hex(16)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"token": tok}, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log(f"[settings] 写 memory token 失败: {e!r}")
    return tok


def configured() -> tuple[bool, str]:
    """能不能开口说话：有 key、有人格、人格不是占位符。"""
    if not deepseek_key():
        return False, "还没配 API Key：先填 entity\\config\\llm.json 的 api_key"
    try:
        txt = PERSONA_PATH.read_text(encoding="utf-8")
    except Exception:
        return False, "缺人格文件 entity\\persona\\persona.md"
    if "PLACEHOLDER" in txt or "{{NAME}}" in txt:
        return False, "人格还是占位符：改 entity\\persona\\persona.md（或首次启动时填名字）"
    return True, ""
