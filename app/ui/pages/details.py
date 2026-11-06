"""查看详情：门状态 / 情绪 / 现在想干什么 / 肚子 / 记忆（从「设置」进）。"""
from __future__ import annotations

import logging
from typing import Any, Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QScrollArea,
    QVBoxLayout, QWidget,
)

from ..widgets.see_through import see_through, see_through_widget
from ...services.core_client import CoreClient
from ...services.worker import run_async

log = logging.getLogger("xiaochen.details")

# 6 基础 / 6 复合 / 1 基线（平静）——顺序与内核 emotion_core.TYPE 一致
BASIC = [
    ("joy", "快乐"), ("sadness", "悲伤"), ("anger", "愤怒"),
    ("fear", "恐惧"), ("disgust", "厌恶"), ("surprise", "惊讶"),
]
COMPOUND = [
    ("love", "爱意"), ("pride", "自豪"), ("anxiety", "焦虑"),
    ("shame", "羞耻"), ("envy", "嫉妒"), ("confusion", "困惑"),
]
CALM = ("calm", "理智")
EMO = BASIC + COMPOUND + [CALM]
EMO_MIN, EMO_MAX = -10, 100
SAN_MIN, SAN_MAX = -100, 100
BANDS = ["几乎没有", "有一点", "明显", "很强", "到顶了"]
BAND_COLORS = ["#c9d3dd", "#8fb9d9", "#5b95c9", "#d98b3f", "#c2402f"]
DRIVE_NAME = {"seek": "想找点事", "reach": "想找你", "share": "想说点开心事",
              "explore": "想看看新东西", "rest": "想歇着", "hide": "想躲一躲"}


def card(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame(objectName="Card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(16, 12, 16, 14)
    lay.setSpacing(6)
    lay.addWidget(QLabel(title, objectName="CardTitle"))
    return frame, lay


BELLY_LABEL = {"full": "饱", "normal": "不饿", "hungry": "饿", "unknown": "不知道"}


def stomach_state(info: Dict[str, Any]) -> Dict[str, Any]:
    """把内核 /stomach 的回包摊平。

    内核回的是 {"state": {...}, "fragment": "…"}（胃是薄接线盒，里面套着
    stomach.py 的 state），而老版本的外壳按扁平字段读 —— 这里两种都认。
    """
    st = info.get("stomach") if isinstance(info, dict) else None
    if not isinstance(st, dict):
        return {}
    inner = st.get("state")
    if isinstance(inner, dict) and inner:
        return inner
    return st


class DetailsPage(QWidget):
    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(14)

        head = QHBoxLayout()
        self.title = QLabel("智能体现在", objectName="PageTitle")
        self.mood = QLabel("mood —", objectName="Muted")
        head.addWidget(self.title)
        head.addSpacing(10)
        head.addWidget(self.mood)
        head.addStretch(1)
        outer.addLayout(head)

        scroll = QScrollArea()
        see_through(scroll)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 6, 0)
        grid.setSpacing(14)

        # 门
        f, lay = card("门")
        self.gates: Dict[str, QLabel] = {}
        for key, text in [("core", "内核 40720"), ("asr", "语音 40715")]:
            lab = QLabel(f"{text}　—", objectName="Muted")
            lay.addWidget(lab)
            self.gates[key] = lab
        grid.addWidget(f, 0, 0)

        # 肚子
        f2, lay2 = card("肚子")
        self.belly = QLabel("—", objectName="CardValue")
        self.belly_text = QLabel("—", objectName="Muted")
        self.belly_text.setWordWrap(True)
        lay2.addWidget(self.belly)
        lay2.addWidget(self.belly_text)
        grid.addWidget(f2, 0, 1)

        # 记忆
        f3, lay3 = card("记忆")
        self.notes = QLabel("—", objectName="CardValue")
        self.sessions = QLabel("—", objectName="Muted")
        lay3.addWidget(self.notes)
        lay3.addWidget(self.sessions)
        grid.addWidget(f3, 0, 2)

        # 情绪：左 6 基础 / 右 6 复合 / 下 1 平静
        f4, lay4 = card("情绪（6 基础 · 6 复合 · 理智）")
        self.emo_now = QLabel("—", objectName="Muted")
        self.emo_now.setWordWrap(True)
        lay4.addWidget(self.emo_now)

        self.bars: Dict[str, tuple[QProgressBar, QLabel]] = {}
        cols = QHBoxLayout()
        cols.setSpacing(22)

        def column(title: str, items):
            box = QVBoxLayout()
            box.setSpacing(4)
            box.addWidget(QLabel(title, objectName="CardTitle"))
            for key, name in items:
                row = QHBoxLayout()
                row.setSpacing(5)
                lab = QLabel(name)
                lab.setFixedWidth(44)
                bar = QProgressBar()
                bar.setRange(EMO_MIN, EMO_MAX)
                bar.setTextVisible(False)
                bar.setFixedWidth(190)
                val = QLabel("—", objectName="Muted")
                val.setFixedWidth(44)
                val.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                row.addWidget(lab)
                row.addWidget(bar)
                row.addSpacing(6)
                row.addWidget(val)
                row.addStretch(1)
                box.addLayout(row)
                self.bars[key] = (bar, val)
            return box

        cols.addLayout(column("基础", BASIC), 1)
        cols.addLayout(column("复合", COMPOUND), 1)
        lay4.addLayout(cols)

        base_row = QHBoxLayout()
        base_row.setSpacing(5)
        base_lab = QLabel(CALM[1])
        base_lab.setFixedWidth(40)
        base_bar = QProgressBar()
        base_bar.setRange(SAN_MIN, SAN_MAX)
        base_bar.setTextVisible(False)
        base_val = QLabel("—", objectName="Muted")
        base_val.setFixedWidth(40)
        base_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        base_row.addWidget(base_lab)
        base_row.addWidget(base_bar, 1)
        base_row.addWidget(base_val)
        self.bars[CALM[0]] = (base_bar, base_val)
        lay4.addSpacing(6)
        lay4.addLayout(base_row)
        lay4.addStretch(1)
        grid.addWidget(f4, 1, 0, 2, 2)

        # 现在想干什么
        f5, lay5 = card("现在想干什么")
        self.drives = QLabel("—", objectName="Muted")
        self.drives.setWordWrap(True)
        lay5.addWidget(self.drives)
        lay5.addStretch(1)
        grid.addWidget(f5, 1, 2)

        # 运行时长
        f6, lay6 = card("内核")
        self.uptime = QLabel("—", objectName="Muted")
        self.uptime.setWordWrap(True)
        lay6.addWidget(self.uptime)
        lay6.addStretch(1)
        grid.addWidget(f6, 2, 2)

        # 对方自己写的（不显示标题：这一栏只放对方自己的话）
        f7 = QFrame(objectName="Card")
        lay7 = QVBoxLayout(f7)
        lay7.setContentsMargins(16, 12, 16, 14)
        lay7.setSpacing(6)
        self.self_text = QLabel("对方还没写过自己的档案。再聊几轮，对方会自己写第一版。", objectName="Muted")
        self.self_text.setWordWrap(True)
        self.self_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.self_text.setMinimumHeight(58)
        self.self_meta = QLabel("", objectName="Muted")
        lay7.addWidget(self.self_text)
        lay7.addWidget(self.self_meta)
        grid.addWidget(f7, 3, 0, 1, 3)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        scroll.setWidget(body)
        see_through_widget(body)
        outer.addWidget(scroll, 1)

    # ---------- 渲染 ----------
    def set_gates(self, ports: Dict[str, bool]) -> None:
        names = {"core": "内核 40720", "asr": "语音 40715"}
        marks = {"core": "core", "asr": "asr"}
        for key, lab in self.gates.items():
            up = bool(ports.get(marks[key]))
            lab.setText(f"{names[key]}　{'在线' if up else '离线'}")
            lab.setStyleSheet("color:#1a9d5b;" if up else "color:#c2402f;")

    def apply_state(self, info: Dict[str, Any]) -> None:
        if not info.get("ok"):
            self.mood.setText("内核不可达")
            return
        brain = info.get("brain") or {}
        health = info.get("health") or {}
        emo = brain.get("emotions") or {}
        mood = brain.get("mood") or health.get("mood") or "—"
        self.mood.setText(f"mood {mood}")
        self.title.setText("智能体现在")

        em = info.get("emotions") or {}
        vals = em.get("display") or em.get("values") or emo or {}
        lvs = em.get("levels") or em.get("bands") or {}
        started = bool(em.get("started"))
        style = str(em.get("style") or "")
        for key, (bar, lab) in self.bars.items():
            v = float(vals.get(key) or 0.0)
            bar.setValue(int(round(v)))
            b = int(lvs.get(key) or 0)
            color = BAND_COLORS[min(b, 4)] if v >= 0 else "#9aa7b4"
            bar.setStyleSheet(f"QProgressBar::chunk{{background:{color};border-radius:4px;}}")
            lab.setText(f"{int(round(v))}")
        if em.get("mood"):
            self.mood.setText(f"mood {em.get('mood')}")
            name_of = dict(EMO)
            top = [(k, float(vals.get(k) or 0)) for k, _ in EMO if float(vals.get(k) or 0) >= 20]
            top.sort(key=lambda x: -x[1])
            head = f"性格「{style}」" if style else ""
            if not started:
                self.emo_now.setText("还没开始——人格配好、说第一句话之后，这三栏才开始动")
            elif top:
                self.emo_now.setText((head + "　·　" if head else "") + "现在最明显：" + "、".join(
                    f"{name_of[k]}（{float(vals.get(k) or 0):.0f}）" for k, _ in top[:3]))
            else:
                self.emo_now.setText((head + "　·　" if head else "") + "现在没什么特别强的情绪")

        drives = info.get("drives") or {}
        active = drives.get("active") or []
        if active:
            text = "\n".join(f"· {DRIVE_NAME.get(d.get('name'), d.get('name'))} （{float(d.get('urgency') or 0):.2f}）"
                             for d in active[:4])
        else:
            text = "没什么特别想干的"
        self.drives.setText(text)

        st = stomach_state(info)
        level = str(st.get("level") or "unknown")
        self.belly.setText(BELLY_LABEL.get(level, level))
        bal = st.get("balance")
        stale = bool(st.get("stale"))
        err = str(st.get("error") or "")
        if bal is not None:
            tail = "（数据有点旧）" if stale else "（只看不报数字给对方）"
            self.belly_text.setText(f"余额 {float(bal):.2f} 元{tail}")
        elif err:
            hint = "还没配 API Key" if "no api key" in err else err[:40]
            self.belly_text.setText(f"量不到：{hint}")
        elif stale:
            self.belly_text.setText("还没量过（内核起来几分钟后才有数）")
        else:
            self.belly_text.setText("—")

        self.notes.setText(str(health.get("notes", "—")))
        self.sessions.setText(f"会话 {health.get('sessions', '—')}")
        up = float(brain.get("uptime") or 0)
        self.uptime.setText(f"脑龄 {up / 60:.0f} 分钟 · 就绪 {brain.get('ready')} · 战斗 {brain.get('fight')}")

    def apply_self(self, data: Dict[str, Any]) -> None:
        if not data or not data.get("ok"):
            self.self_meta.setText("内核不可达，暂时读不到。")
            return
        text = str(data.get("self") or "").strip()
        self.self_text.setText(text or "对方还没写过自己的档案。再聊几轮，对方会自己写第一版。")
        st = data
        self.self_meta.setText(
            f"能力证据 {int(st.get('evidence') or 0)} 条 · "
            f"经历 {int(st.get('episodes') or 0)} 条 · "
            f"账本 {int(st.get('ledger') or 0)} 条")

    def _load_self(self) -> None:
        def work():
            return CoreClient().self_state()

        def done(data):
            try:
                self.apply_self(data or {})
            except Exception:  # noqa: BLE001
                log.debug("应用自我卡数据失败", exc_info=True)

        run_async(work, on_ok=done, on_err=lambda _e: None)

    def on_show(self) -> None:
        self.win.refresh_state()
        self._load_self()
