# -*- coding: utf-8 -*-
"""她的「动作」怎么写、怎么显示、怎么念。

约定：动作（神态、小动作）只准写在全角方头括号 〖 〗 里，例如：

    〖抬了下眼皮〗您问这个干什么，怪突然的。

这三个符号（〖 〗）在平时的中文聊天里几乎不会出现，所以不存在"这句到底是动作
还是正文"的歧义——外壳只认它们，不再把（）里的内容当动作（（）留给正常的插入语）。

这一份被三处共用：
- chat.py 画气泡：〖…〗 缩小、变灰，跟说的话区分开；
- chat.py 念出来：读之前把〖…〗整段删掉，所以 TTS 永远不会念动作；
- 教程/自检：判断一句话里到底有没有动作。
"""
from __future__ import annotations

import html
import re

ACTION_OPEN = "〖"
ACTION_CLOSE = "〗"

# 一行里的动作：最长 60 个字，不许跨行、不许嵌套
_ACTION_RE = re.compile(r"〖[^〖〗\n]{0,60}〗")


def segments(text: str) -> list[tuple[str, bool]]:
    """把一句话切成 [(片段, 是不是动作), …]，顺序保持原样。"""
    text = str(text or "")
    out: list[tuple[str, bool]] = []
    pos = 0
    for m in _ACTION_RE.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], False))
        out.append((m.group(0), True))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], False))
    return out


def has_action(text: str) -> bool:
    return bool(_ACTION_RE.search(str(text or "")))


def spoken(text: str) -> str:
    """念出来的版本：动作整段丢掉，再把多出来的空白收一收。"""
    return re.sub(r"\s{2,}", " ", _ACTION_RE.sub("", str(text or ""))).strip()


def is_action_only(text: str) -> bool:
    """这句除了动作什么都没有——那就别合成、别等它念。"""
    return not spoken(text)


def to_html(text: str) -> str:
    """给气泡用的富文本：动作缩小、变灰，仍保留括号本身，让人看得出那是动作。"""
    chunks = []
    for piece, is_act in segments(text):
        safe = html.escape(piece).replace("\n", "<br/>")
        if is_act:
            chunks.append(f'<span style="color:#7c869c;font-size:11px;">{safe}</span>')
        else:
            chunks.append(safe)
    return "".join(chunks)
