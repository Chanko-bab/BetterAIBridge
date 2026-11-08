"""语音消息的提示词：只出现「对方」，绝不写死关系。

0.6.5 起，主人在聊天窗按住说话，消息会以音频气泡出现；她收到的不是一行字，
而是这段提示 + 自动转写。提示必须中性——她怎么称呼主人由人格卡决定，
这里不能出现「男朋友 / 老公 / 恋人」之类的预设。
"""
from __future__ import annotations

RELATION_WORDS = (
    "男朋友", "女朋友", "男友", "女友", "老公", "老婆", "丈夫", "妻子",
    "恋人", "未婚夫", "未婚妻", "对象", "主人",
)


def seconds_text(ms: int | float) -> str:
    """12000 → 12；12500 → 12.5；不写「12.0 秒」。"""
    sec = max(0.0, float(ms or 0) / 1000.0)
    if abs(sec - round(sec)) < 0.05:
        return str(int(round(sec)))
    return f"{sec:.1f}".rstrip("0").rstrip(".")


def build(transcript: str, ms: int | float, *, failed: bool = False) -> str:
    """生成给模型看的那段提示。

    transcript 为空或 failed=True 时明确说「没听到」，不许她脑补内容。
    """
    text = (transcript or "").strip()
    head = f"【语音消息】对方发来一条 {seconds_text(ms)} 秒的语音。"
    if failed or not text:
        return (head + "自动转写没成功，你没听到内容；请只回应「对方发来一条语音」"
                "这件事本身，不要猜语音里说了什么。")
    return (head + "以下是自动转写（可能有错，按意思理解，不要逐字复述）：\n"
            '"""\n' + text + '\n"""')


def has_relation_word(text: str) -> bool:
    """测试卡用：提示词里一个关系词都不许有。"""
    return any(w in (text or "") for w in RELATION_WORDS)
