"""教程：六页小向导。

只负责"讲什么"和"看到第几页"，状态由内核 /tutorial 管：
- 跳过 → seen，永不再弹；
- 看完最后一页 → finish，seen；
- 中途关掉窗口 → 什么也不改，下次还会问。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QTextBrowser,
    QVBoxLayout, QWidget,
)

INTRO = """<p>这是一个把「人格 + 记忆 + 情绪 + 插件」装在自己电脑上的小程序：
由【琛柯】协同 DSH 开发、开源，人格和记忆都会存在本机。</p>
<p>我做它，是想让不懂、不会搞配置的电脑小白，也能轻松养一只自己的
<b>AI 生物</b>——会记事、有情绪，能慢慢长大。</p>
<p>装好之后，你能做三件事：</p>
<ul>
<li>和 TA 聊天（左边「聊天」，注意：内容由 AI 生成）</li>
<li>给 TA 装卸能力（左边「模组」）——装了模组才有这些桥能力，如接入 QQ</li>
<li>看 TA 现在什么状态（「设置」里的「查看详情」，如果你不介意看到智能体的隐私）</li>
</ul>
<p>聊天时，你发的内容会发给你选的模型服务商来生成回话；除此之外的东西都留在本机。</p>
"""

PAGES = [
    ("欢迎来到 BetterAIBridge", INTRO),
    ("人格、记忆、情绪", """
<h3>三样东西，都在本机</h3>
<ul>
<li><b>人格</b>：智能体是谁、怎么说话。第一次配置时可以自己写，也可以之后改
<code>entity/persona/persona.md</code>。</li>
<li><b>记忆</b>：聊过的话会慢慢整理成记忆；想让它一定记住，直接说「记住：……」。</li>
<li><b>情绪</b>：它会因为聊天、时间、事情产生情绪波动，不是每次都一个语气。</li>
</ul>
<p>这三样都保存在你自己的电脑里，不上传到别处。</p>
"""),
    ("聊天怎么用", """
<h3>聊天</h3>
<ul>
<li><b>Enter</b> 发送，<b>Shift+Enter</b> 换行；输入框会跟着行数长高。</li>
<li>右上角「朗读」勾上后，智能体回话会用系统声音念出来（需要联网）。</li>
<li>右上角「<b>您的状态</b>」能选两档：<b>在线</b> / <b>忙碌</b>。</li>
<li>在线时它才会主动找你、偶尔抬眼听一下；忙碌时不打扰，耳目也不动。窗口收进托盘会算忙碌；完全退出程序会算「不在家」，同样不打扰你。</li>
<li>想让它记住一件事，直接说「记住：……」；日常聊天也会被整理成记忆。</li>
</ul>
<p>聊天记录存在本机；回话时，你发的那段内容会发给模型服务商。</p>
"""),
    ("模组是什么", """
<h3>模组 = 给智能体装的能力</h3>
<ul>
<li>左侧「模组」里可以装卸：QQ、B 站、耳目等。</li>
<li>装上，智能体才有对应的能力；卸掉，就只剩这个对话窗口。</li>
<li>模组要用能力，得先在 <code>module.json</code> 里申请（比如看、听、发消息），
    没申请的调不动，调用记录也会留痕。</li>
</ul>
<p>第一次装模组时，保姆栏会告诉你它申请了什么。</p>
"""),
    ("耳目与隐私", """
<h3>看与听</h3>
<ul>
<li>设置 →「耳目」里可以允许智能体偶尔看一眼、听一下。</li>
<li>摄像头可以选「自动」（有摄像头就拍，没有就看屏幕），也可以只看屏幕。</li>
<li>频率跟着「智能体主动说话」那一档走：关掉那档，就完全不看/不听。</li>
<li>每次看/听，保姆栏会提示你一声；它看到的只是一眼、一耳，不是持续监控。</li>
</ul>
<p>这些开关随时可以关；关掉后智能体自己也会知道「现在看不见、听不见」。</p>
"""),
    ("边界与 AI 标识", """
<h3>它能做什么、不能做什么</h3>
<ul>
<li>它的回话、语音都由 <b>AI 生成</b>，聊天页底部会一直标着「内容由 AI 生成」。</li>
<li>它记得住事，但也会记错；重要的事请自己再核对一遍。</li>
<li>它不会替你做决定，也不能替你操作现实里的事情（除非你装了对应的模组并点头）。</li>
<li>数据都在本机；卸载时可以选择是否保留记忆与人格。</li>
</ul>
<p>教程到这里就结束了。随时可以在「设置」里查看状态、改配置。</p>
"""),
]


class TutorialWelcome(QDialog):
    """六页向导：上一页 / 下一页 / 跳过。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("欢迎")
        self.setMinimumSize(620, 480)
        self.setModal(True)
        self.mode = ""  # "skip" | "finish"
        self.page = 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 14)
        lay.setSpacing(10)

        self.stack = QStackedWidget()
        for title, body in PAGES:
            page = QWidget()
            v = QVBoxLayout(page)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(8)
            head = QLabel(title, objectName="TutTitle")
            head.setWordWrap(True)
            v.addWidget(head)
            text = QTextBrowser()
            text.setOpenExternalLinks(True)
            text.setHtml(body)
            v.addWidget(text, 1)
            self.stack.addWidget(page)
        lay.addWidget(self.stack, 1)

        row = QHBoxLayout()
        self.btn_skip = QPushButton("跳过教程")
        self.btn_skip.setObjectName("Ghost")
        self.btn_skip.clicked.connect(lambda: self._done("skip"))
        row.addWidget(self.btn_skip)
        row.addStretch(1)
        self.lbl_page = QLabel("", objectName="Muted")
        row.addWidget(self.lbl_page)
        self.btn_prev = QPushButton("上一页")
        self.btn_prev.clicked.connect(self._prev)
        row.addWidget(self.btn_prev)
        self.btn_next = QPushButton("下一页", objectName="Primary")
        self.btn_next.clicked.connect(self._next)
        row.addWidget(self.btn_next)
        lay.addLayout(row)

        self._update()

    def _update(self) -> None:
        self.page = max(0, min(self.page, len(PAGES) - 1))
        self.stack.setCurrentIndex(self.page)
        self.lbl_page.setText(f"{self.page + 1} / {len(PAGES)}")
        self.btn_prev.setVisible(self.page > 0)
        self.btn_next.setText("完成" if self.page == len(PAGES) - 1 else "下一页")

    def _prev(self) -> None:
        self.page -= 1
        self._update()

    def _next(self) -> None:
        if self.page >= len(PAGES) - 1:
            self._done("finish")
            return
        self.page += 1
        self._update()

    def _done(self, mode: str) -> None:
        self.mode = mode
        self.accept()
