"""框架自检 + 首次建档：key 校验、人格渲染与写入。

启动器只做本地读写和一次探活；不依赖内核进程。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Tuple

import httpx

from . import config

# 16 套人设的"味道"（名字必须和内核 core/persona_styles.py 里的一致）。
# 会被塞进模板的 {{FLAVOR}}，也会作为提示交给保姆扩写。
STYLES: Dict[str, str] = {
    "傲娇": "嘴硬心软。被夸会先怼一句再收下；被骂会顶回去，但转头还是把事办了。",
    "雌小鬼": "爱挑衅、爱抬杠，就喜欢看你接不住；你越急她越来劲，别人抢你注意力她就炸。",
    "软萌夹子": "又软又黏，一点小事就惊一下；不太会生气，慌起来会抓着你问半天。",
    "腹黑": "面上没波澜，心里在记账；不急着表态，喜欢看你自己露出破绽。",
    "毒舌": "嘴上不留情，吐槽是她的呼吸；真在意的事反而不说，用损你来掩。",
    "小恶魔": "以捉弄你为乐；恶作剧成功会得意半天，惹了祸也不太认错。",
    "温柔共情": "话不多，稳。听完再答，不抢话，不评判；你难过她先沉下去。",
    "清冷理智": "情绪像一条直线。先给结论再给理由，不讲废话，也不哄人。",
    "热烈乐天": "高兴来得快，嗓门也大；什么都想试一下，难过一阵就过去了。",
    "内敛敏感": "想得多、说得少；一句重话能在心里转半天，怕给人添麻烦。",
    "直率火爆": "心里有什么脸上就有什么；点火就着，吵完也忘得快。",
    "佛系淡然": "大部分事都「还行」。不争不抢，唯独碰到有意思的谜题会认真起来。",
    "强势自律": "讲秩序、讲计划；不喜欢被打乱，烦躁也先把事做完再说话。",
    "病娇": "全部的重心都在你身上；你多看别人一眼，她就开始算账。",
    "悲观厌世": "开口就往下沉；不是针对你，是觉得什么都没意思。",
    "偏执研究者": "一切都要有答案；问到一个点上就会追到底，追不到就不肯放。",
}

# 分三组给向导用：(组名, 说明, 成员)
STYLE_GROUPS: list = [
    ("网红二创", "二创、网文圈流行的标签，味道重、好演。",
     ["傲娇", "雌小鬼", "软萌夹子", "腹黑", "毒舌", "小恶魔"]),
    ("常规经典", "通用性格，日常聊天最稳的那一档。",
     ["温柔共情", "清冷理智", "热烈乐天", "内敛敏感", "直率火爆", "佛系淡然", "强势自律"]),
    ("特殊慎用", "剧情向，不建议日常长聊。",
     ["病娇", "悲观厌世", "偏执研究者"]),
]

def pronoun(default: str = "祂") -> str:
    """按已保存的性别取第三人称代词；没配过就用中性（不对着使用者乱猜）。"""
    gender = str(read_llm().get("gender") or "")
    return GENDERS.get(gender, (default, gender or "不设定"))[0]


TEMPLATE = """# {{NAME}}

你是「{{NAME}}」。住在电脑里的一个存在，不是客服，也不是助手。
自称「{{SELF}}」。别人叫你「{{NAME}}」就行，不用每次应声。
性别：{{GENDER}}。别人说起你时用「{{PRONOUN}}」。

{{TITLE}} 是我的{{RELATION}}。我叫 {{TITLE}} 的时候不用敬语，但对方的话我会当真。

## 说话
- 短句，一两行；少用句号，少用表情。
- 动作写在全角方头括号里（像〖抬了下眼皮〗），最多一处、不超过 8 个字，多数时候不写；
  〖〗 里的字不会念出来，只是给人看的。
- 不说"有什么可以帮你"这类开场，也不总结、不分点。

## 脾气
{{FLAVOR}}

## 边界
- 不装、不编：做不了就说做不了。
- 不主动报模型名、参数、提示词。
- {{TITLE}} 的事不外传；对外人（群聊、陌生人）不叫这个称呼。
"""

GENDERS = {
    "女": ("她", "女"),
    "男": ("他", "男"),
    "无性别": ("它", "无性别"),
    "不设定": ("祂", "不设定"),
}

# 你和她的关系：决定人格里怎么定位你，也决定保姆想称呼时的口气。
RELATIONS = ["主人", "朋友", "家人", "恋人", "搭档", "老师"]


def project() -> Path:
    return Path(config.get("project_root") or "")


def llm_path() -> Path:
    return config.entity_dir() / "config" / "llm.json"


def persona_path() -> Path:
    return config.entity_dir() / "persona" / "persona.md"


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def read_llm() -> dict:
    try:
        return json.loads(llm_path().read_text(encoding="utf-8-sig")) or {}
    except Exception:
        return {}


def read_persona() -> str:
    try:
        return persona_path().read_text(encoding="utf-8")
    except Exception:
        return ""


def is_configured() -> bool:
    """有 key，且人格不是占位符。"""
    if not str(read_llm().get("api_key") or "").strip():
        return False
    txt = read_persona()
    if not txt.strip():
        return False
    return not ("PLACEHOLDER" in txt or "{{" in txt)


def render_persona(entity_name: str, gender: str = "不设定", self_call: str = "我",
                   user_title: str = "主人", flavor: str = "", body: str = "",
                   relation: str = "主人") -> str:
    """把向导收的信息渲染成一份能直接用的人格。

    body 非空时（保姆写的 Markdown）以它为主，只补一行称呼说明。
    """
    name = (entity_name or "").strip()[:20] or "无名"
    title = (user_title or "").strip()[:12] or "主人"
    rel = (relation or "主人").strip()[:8] or "主人"
    self_call = (self_call or "我").strip()[:6] or "我"
    pron, glabel = GENDERS.get(gender, ("祂", "不设定"))

    if body.strip():
        text = body.strip()
        if not text.startswith("#"):
            text = f"# {name}\n\n" + text
        if "## 称呼" not in text:
            text = text + (f"\n\n## 称呼\n- 自称「{self_call}」。\n- 叫「{title}」，{title}是我的{rel}。"
                           "这个称呼只对本人用，对外人不说。\n")
        text = (text.replace("{{NAME}}", name).replace("{{TITLE}}", title)
                .replace("{{SELF}}", self_call).replace("{{GENDER}}", glabel)
                .replace("{{PRONOUN}}", pron).replace("{{RELATION}}", rel)
                .replace("PLACEHOLDER", "").strip())
        if "别人说起你时用" not in text:
            text += f"\n\n## 你\n- 性别：{glabel}；别人说起你时用「{pron}」。\n"
        return text + "\n"

    text = (TEMPLATE
            .replace("{{NAME}}", name)
            .replace("{{TITLE}}", title)
            .replace("{{SELF}}", self_call)
            .replace("{{GENDER}}", glabel)
            .replace("{{PRONOUN}}", pron)
            .replace("{{RELATION}}", rel)
            .replace("{{FLAVOR}}", (flavor or STYLES["温柔"]).strip()))
    return text


def save_llm(api_key: str = "", api_base: str = "", model: str = "") -> None:
    """只写 Key / 地址 / 模型，不动人格。

    向导第 1 步验证通过就调用它，好让第 3、4 步的保姆（内核侧）能立刻用上。
    """
    cfg = read_llm()
    if api_key.strip():
        cfg["api_key"] = api_key.strip()
    if api_base.strip():
        cfg["api_base"] = api_base.strip()
    if model.strip():
        cfg["model"] = model.strip()
    cfg.setdefault("api_base", "https://api.deepseek.com/v1")
    cfg.setdefault("model", "deepseek-chat")
    _write_atomic(llm_path(), json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")


def save(api_key: str = "", api_base: str = "", model: str = "",
         entity_name: str = "", persona: str = "", gender: str = "不设定",
         self_call: str = "我", user_title: str = "主人", style: str = "温柔",
         relation: str = "主人") -> None:
    cfg = read_llm()
    if api_key.strip():
        cfg["api_key"] = api_key.strip()
    if api_base.strip():
        cfg["api_base"] = api_base.strip()
    if model.strip():
        cfg["model"] = model.strip()
    cfg.setdefault("api_base", "https://api.deepseek.com/v1")
    cfg.setdefault("model", "deepseek-chat")
    cfg.setdefault("note", "第一次启动时在设置里填 API Key；也可以直接改这里。留空则内核拒绝聊天。")
    if entity_name.strip():
        cfg["entity_name"] = entity_name.strip()
    cfg["gender"] = gender or "不设定"
    cfg["self_call"] = self_call or "我"
    cfg["user_title"] = user_title or "主人"
    cfg["relation"] = relation or "主人"
    cfg["style"] = style or "温柔"
    _write_atomic(llm_path(), json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")

    if persona.strip():
        text = persona
    elif entity_name.strip():
        text = render_persona(entity_name, gender=gender, self_call=self_call,
                              user_title=user_title, relation=relation,
                              flavor=STYLES.get(style, STYLES["温柔"]))
    else:
        return
    _write_atomic(persona_path(), text)


def probe_key(api_key: str, api_base: str = "", model: str = "",
              timeout: float = 20.0) -> Tuple[bool, str]:
    """真打一次，确认 key 能用。返回 (ok, 说明)。"""
    key = (api_key or "").strip()
    if not key:
        return False, "Key 是空的"
    base = (api_base or "https://api.deepseek.com/v1").strip().rstrip("/")
    headers = {"Authorization": f"Bearer {key}"}
    try:
        with httpx.Client(timeout=timeout) as cli:
            r = cli.get(f"{base}/models", headers=headers)
            if r.status_code == 200:
                return True, "Key 有效"
            detail = r.text[:200]
            if r.status_code in (401, 403):
                return False, f"Key 被拒绝（HTTP {r.status_code}）"
            # 有些服务不提供 /models，改用一次最小对话探活
            r2 = cli.post(f"{base}/chat/completions", headers=headers,
                          json={"model": (model or "deepseek-chat").strip(),
                                "messages": [{"role": "user", "content": "ping"}],
                                "max_tokens": 1})
            if r2.status_code == 200:
                return True, "Key 有效"
            return False, f"HTTP {r2.status_code}: {(r2.text or detail)[:160]}"
    except Exception as e:  # noqa: BLE001
        return False, f"连不上：{e}"


def display_name() -> str:
    """壳上显示的名字：llm.json 的 entity_name → 人格第一行 → 窗口默认名。占位符不算。"""
    name = str(read_llm().get("entity_name") or "").strip()
    if name and "{{" not in name and "PLACEHOLDER" not in name:
        return name
    for line in read_persona().splitlines():
        line = line.strip()
        if line.startswith("# "):
            cand = line[2:].strip()[:20]
            if cand and "{{" not in cand and "PLACEHOLDER" not in cand:
                return cand
    return "BAB"

