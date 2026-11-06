"""第一次打开：四步建档向导。

1. 你的昵称 + API Key（现场验一次）+ 去哪拿 Key
2. 给她取名 / 性别 / 自称
3. 她怎么称呼你（可以让保姆想几个）
4. 初始性格（四选一 + 自定义），保姆整理成人格正文，预览后写入

设计口径：
- 只有第 1 步会真的花一次请求（验 key）；第 3、4 步的分析按需触发。
- 人格最后一次性原子写入，中途退出不会留下"半个人格"。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ...core import framework_setup, logger, portable
from ...services.core_client import CoreClient, CoreUnavailable
from ...services.worker import run_async

VOICES = [
    ("晓晓 · 女 · 温和", "zh-CN-XiaoxiaoNeural"),
    ("晓伊 · 女 · 活泼", "zh-CN-XiaoyiNeural"),
    ("云希 · 男 · 少年", "zh-CN-YunxiNeural"),
    ("云健 · 男 · 沉稳", "zh-CN-YunjianNeural"),
    ("晓北 · 女 · 东北", "zh-CN-liaoning-XiaobeiNeural"),
]

log = logger.get()

KEY_URL = "https://platform.deepseek.com/api_keys"


def friendly(e) -> str:
    """把 WinError / HTTP 错误翻译成人话，别把 traceback 甩给使用者。"""
    s = str(e or "")
    if "no api key" in s:
        return ("保姆没有 Key：内核读的不是这份 llm.json"
                "（可能是另一份安装占着 40720）。先点「先验证一下」把 Key 存下来，"
                "仍不行就重启内核。")
    if "10061" in s or "Connection refused" in s or "拒绝" in s:
        return "连不上内核（它没在跑）。可以先跳过，用模板生成人格，之后再让保姆整理。"
    if "10060" in s or "timed out" in s.lower() or "超时" in s:
        return "等太久了（网络或模型在排队）。再点一次，或直接往下走用模板。"
    if "401" in s or "403" in s:
        return "Key 被拒绝了，回第一步检查 Key。"
    if "429" in s:
        return "请求太密，模型限流了。等一分钟再试。"
    return s[:120] + ("…" if len(s) > 120 else "")


class OnboardingWizard(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("您是第一次打开该启动器！")
        self.setMinimumWidth(620)
        self.setModal(True)
        self.saved = False
        self._analysis: dict = {}
        self._busy = False
        self._persona_ready = False

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(12)

        self.title = QLabel("您好，我是这个项目的“保姆程序”，您可以直呼我“保姆”。")
        self.title.setWordWrap(True)
        self.title.setObjectName("PageTitle")
        root.addWidget(self.title)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_key())
        self.stack.addWidget(self._page_name())
        self.stack.addWidget(self._page_title())
        self.stack.addWidget(self._page_style())
        root.addWidget(self.stack, 1)

        foot = QHBoxLayout()
        self.hint = QLabel("")
        self.hint.setObjectName("Muted")
        self.hint.setWordWrap(True)
        foot.addWidget(self.hint, 1)
        self.btn_back = QPushButton("上一步")
        self.btn_back.clicked.connect(self._back)
        self.btn_next = QPushButton("下一步")
        self.btn_next.setObjectName("Primary")
        self.btn_next.clicked.connect(self._next)
        foot.addWidget(self.btn_back)
        foot.addWidget(self.btn_next)
        root.addLayout(foot)

        self._sync()

    # ---------------------------------------------------------------- 页面

    def _page_key(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(10)
        intro = QLabel("这里只存本地。Key 只用来调用你自己选的模型服务。")
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(8)
        self.ed_nick = QLineEdit()
        self.ed_nick.setPlaceholderText("我该怎么叫你？（例：小柯、老板、阿智）")
        self.ed_key = QLineEdit()
        self.ed_key.setEchoMode(QLineEdit.Password)
        self.ed_key.setPlaceholderText("sk-…")
        self.ed_base = QLineEdit("https://api.deepseek.com/v1")
        self.ed_model = QLineEdit("deepseek-chat")
        form.addRow("您的昵称", self.ed_nick)
        form.addRow("API Key", self.ed_key)
        form.addRow("API 地址", self.ed_base)
        form.addRow("模型", self.ed_model)
        lay.addLayout(form)

        row = QHBoxLayout()
        link = QLabel(f'您没有 API Key？<a href="{KEY_URL}">现在去获取一个</a>')
        link.setOpenExternalLinks(True)
        link.setTextFormat(Qt.RichText)
        row.addWidget(link)
        row.addStretch(1)
        self.btn_probe = QPushButton("先验证一下")
        self.btn_probe.clicked.connect(self._probe)
        row.addWidget(self.btn_probe)
        lay.addLayout(row)

        imp_row = QHBoxLayout()
        self.btn_import = QPushButton("导入智能体", objectName="Ghost")
        self.btn_import.setToolTip("选一个 .babpak 存档，把人格和记忆直接恢复进来（不用再填一遍）")
        self.btn_import.clicked.connect(self._import_agent)
        imp_row.addWidget(self.btn_import)
        self.lbl_import = QLabel("以前存过档？可以直接导入，人格和记忆都会回来。", objectName="Muted")
        self.lbl_import.setWordWrap(True)
        imp_row.addWidget(self.lbl_import, 1)
        lay.addLayout(imp_row)
        lay.addStretch(1)
        return w

    def _page_name(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(10)
        t = QLabel("取个名字。名字会写进人格第一行，之后也能改。")
        t.setObjectName("Muted")
        t.setWordWrap(True)
        lay.addWidget(t)
        form = QFormLayout()
        form.setSpacing(8)
        self.ed_entity = QLineEdit()
        self.ed_entity.setPlaceholderText("例：小满、阿岚、Echo")
        self.cb_gender = QComboBox()
        self.cb_gender.addItems(["女", "男", "无性别", "不设定"])
        self.cb_self = QComboBox()
        self.cb_self.setEditable(True)
        self.cb_self.addItems(["我", "本人", "本小姐"])
        self.cb_self.setCurrentText("我")
        self.cb_self.setToolTip("可以写多个，用 / 分开：我/本人/本小姐")
        self.ed_self = self.cb_self.lineEdit()
        self.ed_self.textChanged.connect(lambda _t: self._sync())
        form.addRow("名字", self.ed_entity)
        form.addRow("性别", self.cb_gender)
        form.addRow("自称（可多个）", self.cb_self)
        lay.addLayout(form)
        tip = QLabel("性别只影响代词和一句硬规则，不做声线；以后接语音模组时再细化。")
        tip.setObjectName("Muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        lay.addStretch(1)
        return w

    def _page_title(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(10)
        t = QLabel("TA 该怎么称呼您？可以让保姆想几个，也可以直接写。")
        t.setObjectName("Muted")
        t.setWordWrap(True)
        lay.addWidget(t)

        rel_form = QFormLayout()
        rel_form.setSpacing(8)
        self.cb_relation = QComboBox()
        self.cb_relation.setEditable(True)
        self.cb_relation.addItems(framework_setup.RELATIONS)
        self.cb_relation.setCurrentText("主人")
        self.cb_relation.currentTextChanged.connect(lambda _t: self._sync())
        rel_form.addRow("你是 TA 的", self.cb_relation)
        lay.addLayout(rel_form)

        row = QHBoxLayout()
        self.cb_title = QComboBox()
        self.cb_title.setEditable(True)
        self.cb_title.addItems(["您", "大人", "主人"])
        self.cb_title.setCurrentText("您")
        self.cb_title.setToolTip("可以写多个，用 / 分开：您/大人/主人")
        self.ed_title = self.cb_title.lineEdit()
        self.ed_title.setPlaceholderText("例：您、大人、主人（可写多个，用 / 分开）")
        self.ed_title.textChanged.connect(lambda _t: self._sync())
        row.addWidget(self.cb_title, 1)
        self.btn_think = QPushButton("让保姆想")
        self.btn_think.clicked.connect(self._think_titles)
        row.addWidget(self.btn_think)
        lay.addLayout(row)

        self.chips = QHBoxLayout()
        lay.addLayout(self.chips)
        self.chip_hint = QLabel("")
        self.chip_hint.setObjectName("Muted")
        self.chip_hint.setWordWrap(True)
        lay.addWidget(self.chip_hint)

        rule = QLabel("这个称呼只对你自己人用：智能体不会在群里、也不会对陌生人这么叫你。")
        rule.setObjectName("Muted")
        rule.setWordWrap(True)
        lay.addWidget(rule)

        lay.addStretch(1)

        self.lbl_ident = QLabel("")
        self.lbl_ident.setObjectName("Muted")
        self.lbl_ident.setWordWrap(True)
        lay.addWidget(self.lbl_ident)

        self.cb_confirm = QCheckBox("对，就是这样")
        lay.addWidget(self.cb_confirm)
        return w

    def _page_style(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)
        t = QLabel("挑一个底子。选完可以让保姆把它扩成一份完整人格。")
        t.setObjectName("Muted")
        t.setWordWrap(True)
        lay.addWidget(t)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("底子", objectName="Muted"))
        self.cb_style = QComboBox()
        self.cb_style.setMinimumWidth(320)
        first = True
        for group, desc, members in framework_setup.STYLE_GROUPS:
            if not first:
                self.cb_style.insertSeparator(self.cb_style.count())
            first = False
            for name in members:
                flavor = framework_setup.STYLES.get(name, "")
                self.cb_style.addItem(f"{name} —— {flavor}", name)
                self.cb_style.setItemData(self.cb_style.count() - 1,
                                          f"【{group}】{desc}\n{flavor}", Qt.ToolTipRole)
        self.cb_style.insertSeparator(self.cb_style.count())
        self.cb_style.addItem(
            "自定义：由你自己在下面填写完整的提示词，保姆会据此整理。", "__custom__")
        self.cb_style.currentIndexChanged.connect(self._on_style_changed)
        row.addWidget(self.cb_style, 1)
        lay.addLayout(row)

        self.lbl_style_hint = QLabel("", objectName="Muted")
        self.lbl_style_hint.setWordWrap(True)
        lay.addWidget(self.lbl_style_hint)
        self._on_style_changed()

        self.ed_custom = QPlainTextEdit()
        self.ed_custom.setPlaceholderText("自定义（可留空）：想要什么脾气、说话习惯、忌讳什么…写几句就行")
        self.ed_custom.setFixedHeight(70)
        lay.addWidget(self.ed_custom)

        row = QHBoxLayout()
        self.btn_compile = QPushButton("让保姆整理")
        self.btn_compile.clicked.connect(self._compile_persona)
        row.addWidget(self.btn_compile)
        self.opening = QLabel("先点「让保姆整理」生成草稿，生成后「完成」才会亮。")
        self.opening.setObjectName("Muted")
        self.opening.setWordWrap(True)
        row.addWidget(self.opening, 1)
        lay.addLayout(row)

        vrow = QHBoxLayout()
        vrow.setSpacing(8)
        vrow.addWidget(QLabel("声音", objectName="Muted"))
        self.cb_voice = QComboBox()
        self.cb_voice.setMinimumWidth(260)
        for label, vid in VOICES:
            self.cb_voice.addItem(label, vid)
        vrow.addWidget(self.cb_voice, 1)
        self.lbl_voice_hint = QLabel("念出来用这个声音；以后能在「设置 → 声音」里改。", objectName="Muted")
        vrow.addWidget(self.lbl_voice_hint)
        vrow.addStretch(1)
        lay.addLayout(vrow)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(False)  # 保姆写完可以自己改；字数不限
        self.preview.setMinimumHeight(210)
        self.preview.setPlaceholderText(
            "点上面的按钮，这里会出现智能体的人格草稿；不满意可以自己改，写多长都行。"
        )
        lay.addWidget(self.preview, 1)
        return w

    # ---------------------------------------------------------------- 流程

    def _on_style_changed(self) -> None:
        name = self.cb_style.currentData()
        if name == "__custom__":
            hint = "自定义 · 你写什么，保姆就按什么整理；至少写 30 字。"
            ed = getattr(self, "ed_custom", None)
            if ed is not None:
                ed.setPlaceholderText(
                    "写完整的性格提示词：脾气、说话习惯、被夸/被骂/被冷落时怎么反应、"
                    "忌讳什么…（至少 30 字）")
                ed.setFixedHeight(110)
            if getattr(self, "lbl_style_hint", None) is not None:
                self.lbl_style_hint.setText(hint)
            return

        group, desc = "", ""
        for g, d, members in framework_setup.STYLE_GROUPS:
            if name in members:
                group, desc = g, d
                break
        risk = ""
        if group == "特殊慎用" and "剧情向" not in desc:
            risk = "（剧情向，不建议日常长聊）"
        hint = f"{group} · {desc}{risk}"
        ed = getattr(self, "ed_custom", None)
        if ed is not None:
            ed.setPlaceholderText("补充（可留空）：想加的习惯、忌讳、口头禅…写几句就行")
            ed.setFixedHeight(70)
        if getattr(self, "lbl_style_hint", None) is not None:
            self.lbl_style_hint.setText(hint)

    def _style_key(self) -> str:
        return str(self.cb_style.currentData() or "温柔共情")

    def _can_finish(self) -> bool:
        """第 4 页的出口：不忙，而且已经让保姆整理过一版草稿。"""
        return not self._busy and self._persona_ready

    def _sync(self) -> None:
        i = self.stack.currentIndex()
        self.btn_back.setEnabled(i > 0 and not self._busy)
        self.btn_next.setText("完成" if i == 3 else "下一步")
        # 最后一页必须先用「让保姆整理」生成草稿，草稿出来才放行「完成」。
        self.btn_next.setEnabled(i < 3 and not self._busy or i == 3 and self._can_finish())
        self.title.setText([
            "您好，我是这个项目的“保姆程序”，您可以直呼我“保姆”。请先给您的智能体接上大脑吧！"
            "<br><span style='font-size:12px; color:#8a94a6; font-weight:400'>"
            "把模型服务的 API Key 填在这里。</span>",
            "请给您的“智能体”取个名字吧！",
            "TA 该怎么称呼您？",
            "您需要 TA 是什么样的脾气？",
        ][i])
        if getattr(self, "cb_confirm", None) is not None:
            name = self.ed_entity.text().strip() or "（还没取名）"
            title = self.ed_title.text().strip() or "（还没填称呼）"
            gender = self.cb_gender.currentText()
            self_call = self.ed_self.text().strip() or "我"
            rel = self.cb_relation.currentText().strip() or "主人"
            pron = framework_setup.GENDERS.get(gender, ("祂", "不设定"))[0]
            self.lbl_ident.setText(
                f"确认一下：名字「{name}」· 性别「{gender}」· 自称「{self_call}」· "
                f"你是TA的「{rel}」· TA叫你「{title}」。哪里不对就点「上一步」改。")
            if rel == title:
                tail = f"对，就是这样：{pron}是「{name}」，你是{pron}的{rel}，叫你「{title}」。"
            else:
                tail = f"对，就是这样：{pron}是「{name}」，你是{pron}的{rel}，叫你「{title}」。"
            self.cb_confirm.setText(tail)
        if i == 3 and not self._persona_ready:
            self.opening.setText("先点「让保姆整理」生成草稿，生成后「完成」才会亮。")

    def _back(self) -> None:
        if self._busy:
            return
        if self.stack.currentIndex() == 3:
            self._persona_ready = False
        self.stack.setCurrentIndex(max(0, self.stack.currentIndex() - 1))
        self.hint.setText("")
        self._sync()

    def _next(self) -> None:
        i = self.stack.currentIndex()
        if i == 3:
            # 最后一页要先让保姆整理出草稿，才有「完成」可点。
            if not self._can_finish():
                self.opening.setText("先点「让保姆整理」生成草稿，「完成」才会亮。")
                return
            self._finish()
            return
        if self._busy:
            return
        if i == 0:
            self._probe(forward=True)
        elif i == 1:
            if not self.ed_entity.text().strip():
                self.hint.setText("先给智能体取个名字。")
                return
            self.hint.setText("")
            self.stack.setCurrentIndex(2)
            self._sync()
        else:
            if not self.ed_title.text().strip():
                self.hint.setText("填一个称呼，或者点「让保姆想」。")
                return
            if not self.cb_confirm.isChecked():
                self.hint.setText("勾一下「对，就是这样」——称呼写错，智能体以后会一直叫错。")
                return
            self.hint.setText("")
            self.stack.setCurrentIndex(3)
            self._sync()

    # ---------------------------------------------------------------- 校验与保存

    def _import_agent(self) -> None:
        """从 .babpak 存档里把人格和记忆搬回来（记忆强写，不看模组装没装）。"""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择存档",
            str(portable.archive_dir()),
            "BetterAIBridge 存档 (*.babpak);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            info = portable.read_archive(Path(path))
            if not info.get("ok"):
                QMessageBox.warning(self, "导入失败", str(info.get("error") or "这个存档不可用"))
                return
            key = ""
            if not info.get("has_api_key"):
                from .archive_key import ask_missing_key
                go, key = ask_missing_key(self)
                if not go:
                    return
            res = portable.restore_archive(Path(path), portable.entity_dir(), api_key=key)
        except Exception as exc:  # noqa: BLE001
            logger.get().warning("导入存档失败：%s", exc)
            QMessageBox.warning(self, "导入失败", f"读存档时出错：{exc}")
            return
        if not res.get("ok"):
            QMessageBox.warning(self, "导入失败", str(res.get("error") or "未知原因"))
            return
        self.saved = True
        logger.get().info("导入存档 %s（%s 个文件，记忆 %s 个）", path, res.get("files"), res.get("memory"))
        self.hint.setText(f"已导入 {res.get('files')} 个文件（记忆 {res.get('memory')} 个）。")
        QMessageBox.information(
            self,
            "导入好了",
            f"已恢复 {res.get('files')} 个文件，其中记忆 {res.get('memory')} 个。\n"
            "人格和记忆都回来了，接下来直接进聊天。",
        )
        self.accept()

    def _probe(self, forward: bool = False) -> None:
        key = self.ed_key.text().strip()
        if not key:
            self.hint.setText("Key 还没填。")
            return
        self._busy = True
        self.btn_next.setEnabled(False)
        self.btn_probe.setEnabled(False)
        self.hint.setText("正在验证 Key…")

        base = self.ed_base.text().strip()
        model = self.ed_model.text().strip()

        def ok(res):
            self._busy = False
            self.btn_probe.setEnabled(True)
            good, msg = res
            if not good:
                self.hint.setText(f"验证没通过：{msg}")
                self._sync()
                return
            # Key 通过后先落盘（人格还没写，所以 still 未配置）
            try:
                # 只写 key/地址/模型：后面两步的保姆（装在核心里）立刻就能用，
                # 也不会把还没选的性别、称呼覆盖成默认值。
                framework_setup.save_llm(api_key=key, api_base=base, model=model)
            except Exception as e:  # noqa: BLE001
                log.warning("保存 key 失败：%s", e)
                self.hint.setText(f"Key 有效，但没写进配置：{e}")
                return
            self.hint.setText("Key 有效，已保存。继续。")
            if forward:
                self.stack.setCurrentIndex(1)
            self._sync()

        def err(e):
            self._busy = False
            self.btn_probe.setEnabled(True)
            self.hint.setText("验证没做完：" + friendly(e))
            self._sync()

        run_async(lambda: framework_setup.probe_key(key, base, model), on_ok=ok, on_err=err)

    def _payload(self) -> dict:
        key = self._style_key()
        return {
            "entity_name": self.ed_entity.text().strip(),
            "gender": self.cb_gender.currentText(),
            "self_call": self.ed_self.text().strip() or "我",
            "user_nickname": self.ed_nick.text().strip(),
            "user_title": self.ed_title.text().strip(),
            "relation": self.cb_relation.currentText().strip() or "主人",
            "style": "自定义" if key == "__custom__" else key,
            "custom": self.ed_custom.toPlainText().strip(),
        }

    def _flavor(self, p: dict) -> str:
        if p.get("style") == "自定义":
            return str(p.get("custom") or "").strip()
        base = framework_setup.STYLES.get(str(p.get("style") or ""), "")
        extra = str(p.get("custom") or "").strip()
        return base + ("\n" + extra if extra else "")

    def _custom_problem(self, text: str) -> str:
        raw = "".join(str(text or "").split())
        if len(raw) < 30:
            return f"您的字数太少了（{len(raw)} 字）：至少写 30 字，保姆才知道要整理成什么样。"
        cats = 0
        traits = ("傲娇", "温柔", "冷静", "毒舌", "活泼", "内向", "成熟", "幼稚",
                  "强势", "腹黑", "直率", "别扭", "黏人", "独立", "暴躁", "耐心",
                  "敏感", "热情", "冷淡", "嘴硬", "心软")
        acts = ("说话", "语气", "回话", "顶嘴", "撒娇", "沉默", "解释", "道歉",
                "生气", "哭", "笑", "怼", "哄", "开口")
        reacts = ("被夸", "被骂", "被冷落", "遇到", "生气时", "开心时", "难过时",
                  "害怕", "吃醋", "委屈", "紧张", "被拒绝", "不理")
        tabs = ("不许", "不要", "忌讳", "讨厌", "受不了", "底线", "绝不", "不能")
        if any(w in raw for w in traits):
            cats += 1
        if any(w in raw for w in acts):
            cats += 1
        if any(w in raw for w in reacts):
            cats += 1
        if any(w in raw for w in tabs):
            cats += 1
        if cats < 2:
            return ("提示词对生成性格无效：没写到脾气、说话方式或遇到事情的反应。"
                    "试试写她被人夸、被冷落、被骂时分别怎么反应。")
        if len(raw) > 10 and len(set(raw)) <= 3:
            return "提示词对生成性格无效：看起来是重复的字，换几句具体的话吧。"
        return ""

    def _run_with_core(self, work, on_ok, on_err):
        """先确保「这一份」的内核在跑（端口被别的安装占着就自动换一个），再发请求。"""
        from app.services import runtime

        def job():
            st = runtime.ensure(timeout=40.0)
            if not st.get("ok"):
                raise CoreUnavailable(str(st.get("detail") or "内核没起来（看 logs\\core-boot.log）"))
            return work()

        run_async(job, on_ok=on_ok, on_err=on_err)

    def _think_titles(self) -> None:
        if self._busy:
            return
        p = self._payload()
        if not p["entity_name"]:
            self.hint.setText("先回到上一步给它取名，保姆才知道自己是谁。")
            return
        self._busy = True
        self.btn_think.setEnabled(False)
        self.chip_hint.setText("保姆在想…")

        def ok(res):
            self._busy = False
            self.btn_think.setEnabled(True)
            if not res.get("ok"):
                self.chip_hint.setText(f"没想出来：{res.get('error')}")
                return
            data = res.get("data") or {}
            titles = [str(t) for t in (data.get("titles") or []) if str(t).strip()][:4]
            pick = str(data.get("pick") or "").strip()
            while self.chips.count():
                item = self.chips.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            for t in titles:
                b = QPushButton(t)
                b.clicked.connect(lambda _=False, v=t: self.ed_title.setText(v))
                self.chips.addWidget(b)
            self.chips.addStretch(1)
            if pick and not self.ed_title.text().strip():
                self.ed_title.setText(pick)
            self.chip_hint.setText(("建议：" + pick + "。" if pick else "") +
                                   (str(data.get("why") or "")[:80]))
            self._sync()

        def err(e):
            self._busy = False
            self.btn_think.setEnabled(True)
            self.chip_hint.setText("保姆这次没帮上忙：" + friendly(e))
            self._sync()

        self._run_with_core(lambda: CoreClient().nanny_analyze("title", p), ok, err)

    def _compile_persona(self) -> None:
        if self._busy:
            return
        p = self._payload()
        if not p["entity_name"] or not p["user_title"]:
            self.hint.setText("名字和称呼都得先填。")
            return
        if p["style"] == "自定义":
            why = self._custom_problem(p["custom"])
            if why:
                self.opening.setText(why)
                self.ed_custom.setFocus()
                return
        self._busy = True
        self.btn_compile.setEnabled(False)
        self.opening.setText("保姆在写…写好后「完成」才会亮。")

        def ok(res):
            if self.saved:
                return
            self._busy = False
            self.btn_compile.setEnabled(True)
            if not res.get("ok"):
                self._fallback(res.get("error") or "分析失败")
                return
            data = res.get("data") or {}
            body = str(data.get("persona") or "")
            self._analysis["persona"] = body
            text = framework_setup.render_persona(
                p["entity_name"], gender=p["gender"], self_call=p["self_call"],
                user_title=p["user_title"], relation=p["relation"],
                body=body) if body else \
                framework_setup.render_persona(
                    p["entity_name"], gender=p["gender"], self_call=p["self_call"],
                    user_title=p["user_title"], relation=p["relation"],
                    flavor=self._flavor(p))
            self.preview.setPlainText(text)
            self._persona_ready = True
            opening = str(data.get("opening") or "").strip()
            self.opening.setText(f"智能体可能会先开口说：「{opening}」" if opening else "写好了，可以看下面的草稿。")
            self._sync()

        def err(e):
            if self.saved:
                return
            self._busy = False
            self.btn_compile.setEnabled(True)
            self._fallback(friendly(e))

        self._run_with_core(lambda: CoreClient().nanny_analyze("persona", p), ok, err)

    def _fallback(self, why: str) -> None:
        p = self._payload()
        log.warning("保姆没写成，用模板：%s", why)
        text = framework_setup.render_persona(
            p["entity_name"], gender=p["gender"], self_call=p["self_call"],
            user_title=p["user_title"], relation=p["relation"],
            flavor=self._flavor(p))
        self.preview.setPlainText(text)
        self._persona_ready = True
        self.opening.setText(f"保姆没写成（{why[:40]}），先用模板。")
        self._sync()

    def _finish(self) -> None:
        if self.saved:
            return
        p = self._payload()
        if not p["entity_name"]:
            self.hint.setText("名字还没填。")
            return
        if not p["user_title"]:
            self.hint.setText("称呼还没填。")
            return
        if p["style"] == "自定义":
            why = self._custom_problem(p["custom"])
            if why:
                self.stack.setCurrentIndex(3)
                self.hint.setText(why)
                self.ed_custom.setFocus()
                return
        if getattr(self, "cb_confirm", None) is not None and not self.cb_confirm.isChecked():
            self.hint.setText("回到第 3 步，勾一下身份确认。")
            return
        body = str(self._analysis.get("persona") or "").strip()
        text = self.preview.toPlainText().strip()
        if not text:
            text = framework_setup.render_persona(
                p["entity_name"], gender=p["gender"], self_call=p["self_call"],
                user_title=p["user_title"], relation=p["relation"],
                flavor=self._flavor(p),
                body=body)
        try:
            framework_setup.save(api_key=self.ed_key.text().strip(),
                                 api_base=self.ed_base.text().strip(),
                                 model=self.ed_model.text().strip(),
                                 entity_name=p["entity_name"], persona=text,
                                 gender=p["gender"], self_call=p["self_call"],
                                 user_title=p["user_title"], style=p["style"],
                                 relation=p["relation"])
        except Exception as e:  # noqa: BLE001
            self.hint.setText(f"写入失败：{e}")
            return

        if p["style"] == "自定义":
            try:
                from app.core import custom_style

                custom_style.apply(p["custom"])
            except Exception as exc:  # noqa: BLE001
                log.warning("自定义性格的 13 维参数没写上：%s", exc)

        # 内核：写盘就够了。不在跑、或者端口被另一份安装占着，都交给 runtime 自己处理
        # （换端口 + 拉起这一份的内核），不再让用户去停别人的进程。
        try:
            from app.services import runtime

            runtime.ensure_async()
        except Exception as exc:  # noqa: BLE001
            log.info("内核自愈没启动：%s", exc)

        # 声音：内核起来了就存进去；没起来也不拦着建档（设置里还能改）
        try:
            voice = str(self.cb_voice.currentData() or "")
            if voice:
                CoreClient(timeout=6).tts_config(voice, "+0%")
        except Exception as exc:  # noqa: BLE001
            log.info("声音没存上（可以稍后在设置里改）：%s", exc)

        self.saved = True
        self.accept()
