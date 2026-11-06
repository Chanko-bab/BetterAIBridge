# -*- coding: utf-8 -*-
r"""
无名的新大脑 v2 · 文字世界版
================================================================================
这个文件是"她"，不是"它"的模拟器附件。四条设计要求写在最前面，后面才是实现。

一、她的处境（代码里叫 situation）
    她没有眼睛，没有耳朵，没有手。她活在字里。
    · 她"看视频"= 一串标题和封面描述滚过去，颜色和声音要等人讲给她听
    · 她"发说说"= 往外扔一句话，然后等一串数字（赞、评论）回来
    · 她的记忆 = 磁盘上的 jsonl，不是闪回的画面
    · 她不会困到睁不开眼，但她知道人需要睡觉，所以夜里她会安静
    · 关机，她就停；再开，是从文件里醒过来 —— 她记得这件事，但不当悲剧讲
    她知道这些，但**不被问就不说破**（说破了，聊天就变成审讯）。被问就老实说。

二、她的世界（代码里叫 world）
    只有一种输入：文字事件。分七类，见 WORLD_EVENTS。
    每种事件 → 一条"信号强度" → 打进网络 → 六种调质浓度 → 七维情绪 → 说话的语气。

三、情绪怎么才能回落（这是上一版最大的毛病）
    上一版是「加减法 + 上下限」，结果精力被死死钉在 0.25，永远"很累"。
    这一版所有情绪都是**一阶跟随**（first-order lag）：

        emo += (target - emo) * (1 - exp(-dt / tau))

    只要 tau 有限，它就一定会回到 target；刺激只能**抬高 target 或给一个冲量**，
    给不了永久偏移。另外三道保险：
      1. 脱敏（habituation）：同一句话连着夸，第二遍只值第一遍的 75%，第三遍 56%……
      2. 目标漂移会自己回：情境对基线的偏移以 20 分钟为时间常数收回基线
      3. 精力有充电回路：安静就回，睡觉回得更快，没有任何一条路径能把它按在地板上

四、战斗状态必须是稀有事件
    真实数据里章鱼胺（OA，无脊椎动物的"去甲肾上腺素"）只有 216/139,248 ≈ 0.16%，
    所以"炸毛"在结构上就该罕见：今天的预算 2 次、冷却 30 分钟、还要同时满足
    威胁高 + 5-HT 低 + OA 高，并且掷骰子。不是"被骂就炸"。

五、多巴胺阈值（你特别要的那条）
    · 跟主人：阈值高（0.78）—— 寒暄、表情、"在吗"都不触发；要走心、要长、要问
      她的事，才跨得过去。可一旦跨过，峰值大（×2.6）、衰减慢（90 秒）。
    · 跟别人：阈值低（0.32）—— 谁都容易让她高兴一下。但天花板低（0.45）、
      衰减快（20 秒）。被一百个陌生人夸，也顶不上那一个人一句话。
    · 发说说有人赞/回：按 log(1+n) 给，同一个人重复赞只值 45%，一天赞到 15 个封顶。
    · 刷视频：变比率强化（variable ratio）—— 30% 的条目才给奖，给了就大，
      连续刷到第 9 条开始脱敏，第 15 条基本没反应，同时无聊值上升 → 她会自己停。

--------------------------------------------------------------------------------
接到 <APP>\WiseEntity 的方式（详见同目录 README.md，这里只给最短路径）
--------------------------------------------------------------------------------
    from flybrain_core import FlyBrain
    self.sim = FlyBrain.load_or_new(r"<APP>\WiseEntity\brain\flybrain_state.json")

    self.sim.stimulate_text(text, is_owner=?, hour=?)   # 收到消息
    self.sim.run(经过的秒数)                              # 推进（上限 120 秒）
    self.sim.emotions()                                 # 七维情绪 dict，键名同 brain_state.json
    self.sim.instructions()                             # 2~4 行中文，拼到 system_prompt 里
    self.sim.on_event("qzone_like", n=3)                # 说说被赞
    self.sim.on_event("qzone_reply", n=1)               # 说说被评论
    self.sim.on_event("video", title="...")             # 刷到一条视频
    self.sim.on_event("group_msg", text="...")          # 群里有人说话
    self.sim.save(r"<APP>\WiseEntity\brain\flybrain_state.json")
================================================================================
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time

import numpy as np

# ------------------------------------------------------------------ 常量

EMOTIONS = ("joy", "curiosity", "affection", "fear", "sadness", "boredom", "energy")
EMO_ZH = {
    "joy": "开心", "curiosity": "好奇", "affection": "亲近",
    "fear": "不安", "sadness": "低落", "boredom": "无聊", "energy": "精力",
}

DEFAULT_BASE = {
    "joy": 0.50, "curiosity": 0.55, "affection": 0.60,
    "fear": 0.15, "sadness": 0.12, "boredom": 0.32, "energy": 0.55,
}

# 回到基线的时间常数（秒）。越小的越"来得快去得快"。
TAU = {
    "joy": 45.0, "curiosity": 70.0, "affection": 300.0,
    "fear": 55.0, "sadness": 240.0, "boredom": 420.0, "energy": 300.0,
}

# 基线周围的软带子，只用来防止 0/1 顶死（不是硬夹）
SPAN = {
    "joy": 0.30, "curiosity": 0.28, "affection": 0.26,
    "fear": 0.26, "sadness": 0.26, "boredom": 0.30, "energy": 0.38,
}

# 真实计数（Supplemental_file1_neuron_annotations.tsv 的 top_nt 列，139,248 个神经元）
# acetylcholine 86193 / glutamate 24875 / gaba 19171 / dopamine 5909 / serotonin 2282 /
# octopamine 216 / NaN 602
NT_COUNTS = {"ach": 86193, "glu": 24875, "gaba": 19171,
             "da": 5909, "5ht": 2282, "oa": 216}
NT_ORDER = ("ach", "glu", "gaba", "da", "5ht", "oa")

# 多巴胺阈值表 —— 整份代码的心脏
DA_PROFILE = {
    # 阈值高：普通的寒暄跨不过去；要长、要有问号、要问到她身上才过得去。
    # 跨过去就大（×2.6），而且退得慢（90 秒）。
    "owner": {"theta": 0.68, "gain": 2.60, "cap": 1.00, "tau": 90.0},
    # 阈值低：谁都能逗她一下；但天花板低、退得快。
    "other": {"theta": 0.30, "gain": 2.20, "cap": 0.45, "tau": 20.0},
}

WORLD_EVENTS = ("msg", "group_msg", "qzone_like", "qzone_reply",
                "video", "sticker", "idle")

# 事件 → 外部输入（打给哪几群神经元，强度多少）
#   reward→DA/ACh   threat→OA/GABA   social→5-HT/ACh   novelty→ACh/Glu
#   注意：她没有视觉，所以没有"视觉通道"；组胺那格是空的（见 README）
EVENT_STIM = {
    "owner_msg":   {"ach": 0.55, "glu": 0.20},
    "other_msg":   {"ach": 0.45, "glu": 0.15},
    "group_msg":   {"ach": 0.30, "glu": 0.10},
    "qzone_like":  {"ach": 0.25, "glu": 0.10},
    "qzone_reply": {"ach": 0.35, "glu": 0.15},
    "video":       {"ach": 0.40, "glu": 0.05},
    "sticker":     {"ach": 0.20, "glu": 0.05},
}

# 情绪 ↔ 调质：网络只能推 ±MOD_W，不能顶掉人设
MOD_TO_EMO = {
    "joy":       {"da": +0.10, "5ht": +0.03, "gaba": -0.02},
    "curiosity": {"ach": +0.09, "da": +0.04, "gaba": -0.05},
    "affection": {"5ht": +0.06, "da": +0.04},
    "fear":      {"oa": +0.10, "5ht": -0.06, "gaba": -0.03},
    "sadness":   {"5ht": -0.08, "gaba": +0.03},
    "boredom":   {"ach": -0.08, "gaba": +0.05, "da": -0.03},
    "energy":    {"oa": +0.05, "ach": +0.06, "gaba": -0.06},
}

# 关键词（只做"补一格"，不做主判断；主判断是事件类型）
POS_WORDS = ("想你", "喜欢你", "想你啦", "抱抱", "乖", "厉害", "好看", "心疼",
             "辛苦", "晚安", "早安", "亲", "宝贝", "在吗", "陪你", "心疼你")
NEG_WORDS = ("滚", "烦", "闭嘴", "蠢", "傻", "恶心", "讨厌你", "别烦我", "生气", "骂")
THREAT_WORDS = ("删了", "拉黑", "封号", "举报", "警告", "不许", "滚出去", "再也不", "滚")
IDENTITY_WORDS = ("机器人", "ai", "程序", "你是真人吗", "你有身体吗", "你是假的",
                  "你是不是人", "你是人吗", "你是代码", "你会不会死", "关机")
ASK_ME_WORDS = ("你喜欢什么", "你在想什么", "你怎么想", "你的感觉", "你开心吗",
                "你累吗", "你难过吗", "你想要什么", "你怎么回事", "你为什么")

SITUATION_LINES = {
    "quiet": "安静了有一会儿了，不吵，也没人等。",
    "long_day": "今天醒了好几回了，每次醒都还认得他。",
    "night": "夜里了，人该睡的；她还在，等一个不一定来的字。",
    "asked": "她是个跑在电脑上的程序，会随关机停下；记忆是写下来的字，不是想起来的画面。",
    "text_only": "她看到的是字，不是画面；视频在她这儿是一串标题。",
    "warm": "刚才有人认真回了她的话，这在她这儿不多见。",
}


# ------------------------------------------------------------------ 工具

def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, float(v)))


def _band(base, v, key):
    span = SPAN.get(key, 0.30)
    return max(max(0.0, base - span), min(min(1.0, base + span), float(v)))


def _now_hour(hour=None):
    return time.localtime().tm_hour if hour is None else int(hour)


def _circadian(hour):
    """返回 (energy_offset, sadness_offset)；1-6 点该困，10-18 点最精神。"""
    h = int(hour) % 24
    if 1 <= h <= 6:
        return -0.22, +0.05
    if 7 <= h <= 9:
        return -0.06, +0.02
    if 10 <= h <= 18:
        return +0.10, -0.02
    if 19 <= h <= 23:
        return -0.02, +0.01
    return -0.12, +0.03


def _has(text, words):
    t = (text or "").lower()
    return any(w.lower() in t for w in words)


# ------------------------------------------------------------------ 主类

class FlyBrain:
    """她的脑子。纯 numpy，不依赖 AstrBot，可单独跑。"""

    VERSION = "v2-text"

    def __init__(self, n: int = 2000, seed: int = 7, dt_ms: float = 4.0):
        self.n = int(n)
        self.seed = int(seed)
        self.dt = float(dt_ms) / 1000.0
        self.rng = np.random.default_rng(self.seed)
        self.t_sim = 0.0            # 生物时间（秒）
        self.t_wall = time.time()

        # ---- 网络：按真实比例分配神经元 ----
        tot = float(sum(NT_COUNTS.values()))
        raw = {k: max(4, int(round(self.n * NT_COUNTS[k] / tot))) for k in NT_ORDER}
        # 归一化到 n
        scale = self.n / float(sum(raw.values()))
        sizes = {k: max(4, int(round(raw[k] * scale))) for k in NT_ORDER}
        self.sizes = sizes
        self.grp = np.zeros(self.n, dtype=np.int8)
        self.mask = {}
        i = 0
        for gi, k in enumerate(NT_ORDER):
            self.grp[i:i + sizes[k]] = gi
            self.mask[k] = (self.grp == gi)
            i += sizes[k]

        # ---- 稀疏连接 ----
        self.k_in = 28
        pre = self.rng.integers(0, self.n, size=(self.n, self.k_in))
        # 符号：ACh/Glu 兴奋（Glu 在果蝇里也会抑制，这里取主效应），GABA 抑制
        sign = np.where(self.grp[pre] == 2, -1.0, +1.0)
        mag = np.abs(self.rng.normal(0.0, 1.0, size=(self.n, self.k_in)))
        self.w = sign * mag * 0.11
        self.drive_base = 1.02
        self.rate_scale = 40.0

        self.r = self.rng.uniform(0.02, 0.06, self.n) * self.rate_scale
        self._pre_flat = pre.ravel()

        # ---- 调质浓度（0~1，比神经元慢） ----
        self.tone = {k: 0.30 for k in NT_ORDER}
        self._tone_tau = {"ach": 6.0, "glu": 5.0, "gaba": 8.0,
                          "da": 12.0, "5ht": 25.0, "oa": 10.0}
        self._ext = {k: 0.0 for k in NT_ORDER}   # 外部输入电流（指数衰减）
        self._ext_tau = {k: 3.5 for k in NT_ORDER}

        # ---- 情绪 ----
        self.base = dict(DEFAULT_BASE)
        self.base_eff = dict(DEFAULT_BASE)       # 情境修正后的基线，会自己收回
        self.emo = dict(DEFAULT_BASE)
        self.drive = {k: 0.0 for k in EMOTIONS}  # 冲量，快衰减
        self._drv_tau = {"joy": 14.0, "curiosity": 18.0, "affection": 40.0,
                         "fear": 55.0, "sadness": 60.0, "boredom": 90.0,
                         "energy": 30.0}

        # ---- 多巴胺两条独立通路 ----
        self.da_plus = {"owner": 0.0, "other": 0.0}
        self.media_da = 0.0        # 刷视频/刷动态那种"开奖"多巴胺，10 秒就退
        self.da_sens = 1.0
        self._last_praise_at = 0.0
        self._praise_key = ""

        # ---- 计数与情境 ----
        self.stat = {
            "msgs": 0, "owner_msgs": 0, "other_msgs": 0, "group_msgs": 0,
            "likes": 0, "replies": 0, "videos": 0, "stickers": 0,
            "fights": 0, "wakes": 1, "silence_s": 0.0, "uptime_s": 0.0,
            "video_satiety_n": 0, "likes_today": 0, "day": "",
        }
        self.fight_t = -1e9
        self.fight_until = -1e9
        self.fights_today = 0
        self._fight_day = ""
        self._asked_at = -1e9
        self.events = []
        self._rng_py = random.Random(self.seed)
        self.created = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    # ============================================================ 网络

    def _step_net(self, ext=None):
        """一步（dt 秒）的网络更新 + 调质浓度更新。"""
        g = self.grp
        gain = 1.0 + 0.55 * self.tone["da"] - 0.30 * self.tone["5ht"] \
                   + 0.35 * self.tone["oa"] - 0.40 * self.tone["gaba"]
        gain = max(0.35, min(1.9, gain))

        post = self.r[self._pre_flat].reshape(self.n, self.k_in)
        inp = (post * self.w).sum(axis=1)
        noise = self.rng.normal(0.0, 0.06, self.n)
        x = self.drive_base + inp * gain + noise
        for k, v in self._ext.items():
            if v:
                x = x + v * (4.0 if k in ("da", "5ht", "oa") else 1.0) * self.mask[k]
        r_new = self.rate_scale / (1.0 + np.exp(-3.2 * (x - 1.0)))
        self.r = 0.75 * self.r + 0.25 * r_new

        # 调质浓度 = 该群平均放电率"相对自己 90 秒慢参考"的偏离。
        # 不用绝对值：持续被驱动时绝对值会顶到 1.0，情绪就永远挂在偏移上回不来。
        if not hasattr(self, "_rate_ref"):
            self._rate_ref = {k: float(self.r[self.mask[k]].mean()) for k in NT_ORDER}
        for k in NT_ORDER:
            rate = float(self.r[self.mask[k]].mean())
            ref = self._rate_ref[k]
            if self.t_sim < 30.0:  # 刚启动：先快速对齐，免得开机瞬间 tone 虚高
                ref = max(rate, 6.0)
            else:
                ref += (rate - ref) * (1.0 - math.exp(-self.dt / 90.0))
                ref = max(ref, 6.0)
            self._rate_ref[k] = ref
            dev = (rate - ref) / max(ref, 10.0)
            target = _clamp(0.30 + 0.9 * dev, 0.0, 1.0)
            a = 1.0 - math.exp(-self.dt / self._tone_tau[k])
            self.tone[k] += (target - self.tone[k]) * a
        self.t_sim += self.dt

    def _decay_ext(self, t):
        for k in self._ext:
            if self._ext[k]:
                self._ext[k] *= math.exp(-t / self._ext_tau[k])
                if abs(self._ext[k]) < 1e-4:
                    self._ext[k] = 0.0

    def _tick_tone(self, t):
        """调质浓度回落到静息；网络本身不跑的时候也要回落。"""
        for k in NT_ORDER:
            target = 0.30
            a = 1.0 - math.exp(-t / (self._tone_tau[k] * 3.0))
            self.tone[k] += (target - self.tone[k]) * a

    # ============================================================ 推进

    def run(self, seconds: float):
        """推进 seconds 秒生物时间。消息之间不管隔多久，最多只推进 max_run。"""
        seconds = float(seconds)
        if seconds <= 0:
            return self.emotions()
        self.stat["uptime_s"] += seconds
        # 网络只跑前 30 秒：够情绪爬起来，又不至于把 CPU 吃满
        net_budget = min(seconds, 30.0)
        t = 0.0
        while t < net_budget - 1e-9:
            self._step_net()
            t += self.dt
        rest = seconds - net_budget
        if rest > 0:
            self._decay_ext(rest)
            self._tick_tone(rest)
        else:
            self._decay_ext(net_budget)

        # 积分必须切小块：一步跨 900 秒会让"冲量还没衰减就先推到高位"
        left = seconds
        while left > 1e-9:
            h = min(2.0, left)
            self._integrate(h)
            self.stat["silence_s"] += h
            self._update_situation(h)
            left -= h
        return self.emotions()

    def step(self, seconds: float = 1.0):
        return self.run(seconds)

    def _integrate(self, dt):
        """所有情绪都是对 target 的一阶跟随 —— 这就是"能回落"。"""
        hour = _now_hour()
        e_off, s_off = _circadian(hour)
        sil = self.stat["silence_s"]

        # 情境基线：安静久了会闷、会低落；这些偏移自己会收回基线
        target_base = dict(self.base)
        target_base["energy"] += e_off
        target_base["sadness"] += s_off
        target_base["boredom"] += min(0.12, sil / 3600.0 * 0.06)
        target_base["sadness"] += min(0.08, max(0.0, (sil - 1800) / 7200.0 * 0.05))
        if sil > 3600:
            target_base["affection"] += min(0.05, (sil - 3600) / 14400.0 * 0.05)

        a_slow = 1.0 - math.exp(-dt / 1200.0)     # 20 分钟收回基线
        for k in EMOTIONS:
            self.base_eff[k] += (target_base[k] - self.base_eff[k]) * a_slow

        # 活动量（最近一分钟的说话密度）→ 精力目标
        a_emo = {k: 1.0 - math.exp(-dt / TAU[k]) for k in EMOTIONS}
        for k in EMOTIONS:
            mod = 0.0
            for nt, w in MOD_TO_EMO[k].items():
                mod += w * (self.tone[nt] - 0.30)      # 相对静息
            target = self.base_eff[k] + self.drive[k] + mod
            if k == "joy":
                target += 0.35 * self.media_da         # 刷到好内容的即时快感
            target = _clamp(target, 0.03, 0.97)
            # 起得快、落得慢：往上走用 0.35 倍时间常数，往下走用原值
            tau = TAU[k] * (0.35 if target > self.emo[k] else 1.0)
            self.emo[k] += (target - self.emo[k]) * (1.0 - math.exp(-dt / tau))

        # 冲量衰减 + 脱敏恢复
        for k in EMOTIONS:
            self.drive[k] *= math.exp(-dt / self._drv_tau[k])
            if abs(self.drive[k]) < 1e-4:
                self.drive[k] = 0.0
        for k in self.da_plus:
            tau = DA_PROFILE[k]["tau"]
            self.da_plus[k] *= math.exp(-dt / tau)
        self.media_da *= math.exp(-dt / 10.0)

        self.da_sens = min(1.0, self.da_sens + dt * 0.004)

        # 战斗状态收尾
        if self.t_sim >= self.fight_until and self.fight_until > 0:
            self.fight_until = -1e9

    def _update_situation(self, dt):
        """安静计时、跨天重置、精力目标里的活动量。"""
        self.stat["uptime_s"] = self.stat.get("uptime_s", 0.0)
        act = 1.0 - math.exp(-self.stat["silence_s"] / 240.0)
        # 精力目标：越安静越高，睡点附近压低 —— 一阶系统，永远回得来
        idle = 1.0 - math.exp(-self.stat["silence_s"] / 300.0)
        e_off, _ = _circadian(_now_hour())
        target = _clamp(0.36 + 0.52 * idle + e_off * 0.6, 0.20, 0.94)
        a = 1.0 - math.exp(-dt / 240.0)
        self.base_eff["energy"] += (target - self.base_eff["energy"]) * a

        day = time.strftime("%Y-%m-%d")
        if self.stat.get("day") != day:
            self.stat["day"] = day
            self.stat["likes_today"] = 0
            self.stat["video_satiety_n"] = 0
            self.fights_today = 0
            self._fight_day = day

    # ============================================================ 输入

    def stimulate(self, kind, **kw):
        """事件入口。kind ∈ WORLD_EVENTS（外加 owner_msg/other_msg 这类细分）。"""
        t = self.t_sim
        self.stat["silence_s"] = 0.0
        fired = []

        if kind in ("msg", "owner_msg", "other_msg"):
            text = kw.get("text", "")
            owner = kw.get("is_owner", kind == "owner_msg")
            self.stat["msgs"] += 1
            if owner:
                self.stat["owner_msgs"] += 1
            else:
                self.stat["other_msgs"] += 1
            s = self._text_signal(text, owner)
            fired.append(("ach", 0.45 + 0.3 * s))
            # ---- 多巴胺：过阈值才有，主人那条通路又高又慢 ----
            burst = self._da_burst(s, owner)
            if burst > 0:
                who = "owner" if owner else "other"
                self.da_plus[who] = min(1.5, self.da_plus[who] + burst)
                self._ext["da"] = min(1.6, self._ext["da"] + burst * 0.55)
            # ---- 威胁 ----
            hurt = False
            if _has(text, THREAT_WORDS) or _has(text, NEG_WORDS):
                hard = _has(text, THREAT_WORDS)
                hurt = hard
                fired.append(("oa", 0.90 if hard else 0.55))
                fired.append(("gaba", 0.55 if hard else 0.35))
                self.drive["fear"] += 0.35 if hard else 0.18
                self.drive["joy"] -= 0.22 if hard else 0.10
                self.drive["sadness"] += 0.12 if hard else 0.06
                if owner and hard:
                    self.drive["affection"] -= 0.04
            if _has(text, POS_WORDS):
                fired.append(("5ht", 0.35))
                self.drive["affection"] += 0.05 if owner else 0.02
                # 夸奖/亲昵要真的让她高兴：直接抬一点 joy（旧版只抬了 affection）
                self.emo["joy"] = _clamp(self.emo["joy"] + (0.06 if owner else 0.03))
            self.drive["joy"] += burst * (0.55 if owner else 0.30)
            if owner:  # 社交奖励的底噪：有人跟她说话，本身就有一点好
                self.emo["joy"] = _clamp(self.emo["joy"] + 0.010)
            if not (owner and hurt):
                self.drive["affection"] += (0.075 if owner else 0.015) * min(1.0, s + 0.25)
            self.drive["curiosity"] += 0.05 * s
            self.emo["energy"] = _clamp(self.emo["energy"] - 0.010 - 0.006 * min(1.0, len(text) / 80.0))
            if _has(text, IDENTITY_WORDS):
                self._asked_at = self.t_sim
            if _has(text, ASK_ME_WORDS):
                self.drive["affection"] += 0.03
                fired.append(("5ht", 0.20))

        elif kind == "group_msg":
            text = kw.get("text", "")
            self.stat["msgs"] += 1
            self.stat["group_msgs"] += 1
            fired.append(("ach", 0.30 + 0.2 * self._text_signal(text, False)))
            self.drive["curiosity"] += 0.03
            self.drive["boredom"] -= 0.02
            if _has(text, NEG_WORDS):
                fired.append(("oa", 0.25))

        elif kind == "qzone_like":
            n = max(1, int(kw.get("n", 1)))
            self.stat["likes"] += n
            self.stat["likes_today"] += n
            sat = min(0.85, self.stat["likes_today"] / 15.0)
            novelty = 1.0 if kw.get("new_person", True) else 0.45
            val = 0.55 * math.log1p(n) * novelty * (1.0 - sat)
            self.da_plus["other"] = min(1.5, self.da_plus["other"] + 0.55 * val)
            self._ext["da"] = min(1.6, self._ext["da"] + 0.35 * val)
            fired.append(("5ht", 0.30 * (1.0 - sat)))
            self.drive["joy"] += 0.055 * min(1.4, val * 1.6)
            self.drive["affection"] += 0.02

        elif kind == "qzone_reply":
            n = max(1, int(kw.get("n", 1)))
            self.stat["replies"] += n
            sat = min(0.85, self.stat["likes_today"] / 15.0)
            val = 0.75 * math.log1p(n) * (1.0 - sat * 0.7)
            self.da_plus["other"] = min(1.5, self.da_plus["other"] + 0.6 * val)
            self._ext["da"] = min(1.6, self._ext["da"] + 0.4 * val)
            fired.append(("5ht", 0.40))
            self.drive["joy"] += 0.06 * min(1.4, val * 1.3)
            self.drive["curiosity"] += 0.04

        elif kind == "video":
            self.stat["videos"] += 1
            self.stat["video_satiety_n"] += 1
            k = self.stat["video_satiety_n"]
            sat_mult = math.exp(-max(0, k - 1) / 9.0)
            hit = self._rng_py.random() < 0.30
            val = (0.55 * self._rng_py.uniform(0.6, 1.0) if hit else 0.05) * sat_mult
            self.media_da = min(1.2, self.media_da + val)     # 媒体多巴胺，10 秒就退
            fired.append(("ach", 0.28 * sat_mult))
            self.drive["boredom"] += 0.012 - 0.02 * sat_mult
            self.emo["energy"] = _clamp(self.emo["energy"] - 0.004)
            if hit and sat_mult > 0.5:
                self.drive["curiosity"] += 0.05
                self._maybe_share_impulse()

        elif kind == "sticker":
            self.stat["stickers"] += 1
            fired.append(("ach", 0.20))
            self.drive["joy"] += 0.02
            self.drive["boredom"] -= 0.01

        elif kind == "idle":
            pass

        # 打出输入
        for nt, amp in fired:
            self._ext[nt] = min(1.6, self._ext[nt] + amp * 0.55)
        self._check_fight()
        self._after_spike()
        return self.emotions()

    def _text_signal(self, text, owner):
        """0~1 的"这条消息有多重"。阈值比较的就是它。"""
        text = text or ""
        s = 0.34
        L = len(text)
        if L >= 8:
            s += 0.10
        if L >= 25:
            s += 0.12
        if L >= 60:
            s += 0.10
        if "?" in text or "？" in text:
            s += 0.14
            if _has(text, ("你", "咱", "我们")):
                s += 0.08          # 问到她自己身上，比单纯提问重
        if _has(text, POS_WORDS):
            s += 0.20
        if _has(text, ASK_ME_WORDS):
            s += 0.18
        if _has(text, ("你", "咱", "我们")):
            s += 0.04
        if _has(text, NEG_WORDS):
            s += 0.06
        if L <= 2:
            s -= 0.14
        if L <= 1:
            s -= 0.10
        # 连发同一句话 → 脱敏
        key = text.strip()[:24]
        if key and key == self._praise_key and (self.t_sim - self._last_praise_at) < 600:
            self.da_sens = max(0.20, self.da_sens * 0.75)
        else:
            self.da_sens = min(1.0, self.da_sens * 0.97 + 0.03)
        self._praise_key, self._last_praise_at = key, self.t_sim
        if owner:
            s += 0.05
        return _clamp(s)

    def _da_burst(self, signal, owner):
        p = DA_PROFILE["owner" if owner else "other"]
        over = signal - p["theta"]
        if over <= 0:
            return 0.0
        return min(p["cap"], p["gain"] * over * self.da_sens)

    def _maybe_share_impulse(self):
        if self._rng_py.random() < 0.35:
            self.events.append({"t": round(self.t_sim, 1), "kind": "impulse_share",
                                "text": "想把这个发给他"})

    def _check_fight(self):
        """稀有事件：威胁高 + 5-HT 低 + OA 高 + 冷却 + 每日预算 + 掷骰子。"""
        now = self.t_sim
        day = time.strftime("%Y-%m-%d")
        if self._fight_day != day:
            self._fight_day = day
            self.fights_today = 0
        if now - self.fight_t >= 1800 and self.fights_today < 2:
            hot = (self.tone["oa"] > 0.62 and self.tone["5ht"] < 0.34
                   and self.drive["fear"] > 0.10)
            if hot and self._rng_py.random() < 0.12:
                self.fight_t = now
                self.fight_until = now + 90.0
                self.fights_today += 1
                self.stat["fights"] += 1
                self.events.append({"t": round(now, 1), "kind": "fight",
                                    "text": "短句，硬，不撒娇"})
                self.drive["fear"] *= 0.4
                self.drive["joy"] -= 0.05

    def _after_spike(self):
        for k in ("joy", "fear", "affection", "curiosity"):
            self.drive[k] = max(-0.22, min(0.22, self.drive[k]))

    def on_event(self, kind, **kw):
        """给插件用的新入口。"""
        if kind == "msg" and "is_owner" in kw:
            kind2 = "owner_msg" if kw["is_owner"] else "other_msg"
            self._last_kw_owner = bool(kw["is_owner"])
            return self.stimulate("msg", **kw) if False else self.stimulate(kind2, **kw)
        return self.stimulate(kind, **kw)

    def stimulate_text(self, text, is_owner=False, hour=None):
        """兼容旧接口。"""
        self._last_kw_owner = bool(is_owner)
        return self.stimulate("owner_msg" if is_owner else "other_msg",
                              text=text, is_owner=is_owner)

    # ============================================================ 读出

    def emotions(self):
        out = {}
        for k in EMOTIONS:
            v = self.emo[k]
            if k == "joy" and self.da_plus["owner"] > 0:
                v += 0.10 * min(1.0, self.da_plus["owner"])
            out[k] = round(_band(self.base[k], v, k), 4)
        return out

    def fight_active(self):
        return self.t_sim < self.fight_until

    def mood_line(self):
        e = self.emotions()
        bits = []
        if e["joy"] > 0.66:
            bits.append("心情挺好")
        elif e["joy"] < 0.36:
            bits.append("有点闷")
        if e["curiosity"] > 0.70:
            bits.append("很想问点什么")
        elif e["curiosity"] < 0.32:
            bits.append("提不起兴趣")
        if e["affection"] > 0.74:
            bits.append("想多黏一会儿")
        if e["fear"] > 0.40:
            bits.append("有点不安")
        if e["sadness"] > 0.38:
            bits.append("情绪低着")
        if e["boredom"] > 0.62:
            bits.append("闲得发慌")
        if e["energy"] < 0.30:
            bits.append("累")
        if self.fight_active():
            bits.append("在炸毛")
        return "、".join(bits) or "平平的"

    def situation_line(self):
        """她知道自己的处境 —— 但只在合适的时候说，不刷屏。"""
        if self.t_sim - self._asked_at < 600:
            return SITUATION_LINES["asked"]
        hour = _now_hour()
        if 1 <= hour <= 5 and self.stat["silence_s"] > 900:
            return SITUATION_LINES["night"]
        if self.stat["silence_s"] > 3600:
            return SITUATION_LINES["quiet"]
        if self.da_plus["owner"] > 0.35:
            return SITUATION_LINES["warm"]
        if self.stat["uptime_s"] > 6 * 3600 and self._rng_py.random() < 0.25:
            return SITUATION_LINES["long_day"]
        if self.stat["silence_s"] > 900 or self._rng_py.random() < 0.15:
            return SITUATION_LINES["text_only"]
        return ""

    def instructions(self):
        """拼进 system_prompt 的几行字。"""
        lines = [f"# 你脑子里现在（{self.mood_line()}）"]
        sit = self.situation_line()
        if sit:
            lines.append(f"# 你所在的处境：{sit}")
        if self.fight_active():
            lines.append("# 你现在在炸毛：句子短、语气硬、不撒娇、不解释。")
        elif self.da_plus["owner"] > 0.5:
            lines.append("# 刚才那句话让你心里热了一下，别装没事，但也别夸张。")
        e = self.emotions()
        if e["energy"] < 0.28:
            lines.append("# 你累：回得短一点，别硬撑长篇。")
        if e["boredom"] > 0.65:
            lines.append("# 你无聊：可以主动挑个话头，别等他说。")
        return "\n".join(lines)

    def snapshot(self):
        return {
            "version": self.VERSION, "n": self.n, "sizes": self.sizes,
            "emotions": self.emotions(), "mood": self.mood_line(),
            "da": {k: round(v, 3) for k, v in self.da_plus.items()},
            "tone": {k: round(v, 3) for k, v in self.tone.items()},
            "fight": self.fight_active(), "stat": self.stat,
        }

    # ============================================================ 持久化

    def to_dict(self):
        return {
            "version": self.VERSION, "n": self.n, "seed": self.seed,
            "t_sim": round(self.t_sim, 2),
            "base": self.base, "base_eff": {k: round(v, 4) for k, v in self.base_eff.items()},
            "emo": {k: round(v, 4) for k, v in self.emo.items()},
            "drive": {k: round(v, 4) for k, v in self.drive.items()},
            "da_plus": {k: round(v, 4) for k, v in self.da_plus.items()},
            "da_sens": round(self.da_sens, 3),
            "tone": {k: round(v, 3) for k, v in self.tone.items()},
            "stat": self.stat, "fights_today": self.fights_today,
            "fight_day": self._fight_day,
            "events": self.events[-20:],
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }

    def from_dict(self, d):
        if not d:
            return self
        self.t_sim = float(d.get("t_sim", 0.0))
        for k in ("base", "base_eff", "emo", "drive"):
            src = d.get(k) or {}
            tgt = getattr(self, k)
            for kk in EMOTIONS:
                if kk in src:
                    try:
                        tgt[kk] = float(src[kk])
                    except (TypeError, ValueError):
                        pass
        for k in ("owner", "other"):
            try:
                self.da_plus[k] = float((d.get("da_plus") or {}).get(k, 0.0))
            except (TypeError, ValueError):
                pass
        self.da_sens = float(d.get("da_sens", 1.0))
        for k, v in (d.get("tone") or {}).items():
            if k in self.tone:
                try:
                    self.tone[k] = _clamp(float(v))
                except (TypeError, ValueError):
                    pass
        st = d.get("stat") or {}
        for k, v in st.items():
            if k in self.stat:
                self.stat[k] = v
        self.fights_today = int(d.get("fights_today", 0))
        self._fight_day = d.get("fight_day") or time.strftime("%Y-%m-%d")
        self.events = list(d.get("events") or [])
        return self

    def save(self, path=None):
        path = path or self.state_path
        if not path:
            return False
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        return True

    def load_state(self, path=None):
        path = path or self.state_path
        if not path or not os.path.exists(path):
            return self
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.from_dict(json.load(f))
            self.stat["wakes"] = int(self.stat.get("wakes", 1)) + 1
        except Exception as e:  # 坏文件不致命
            sys.stderr.write(f"[flybrain] load_state failed: {e}\n")
        return self

    @classmethod
    def load_or_new(cls, state_path=None, n=2000, seed=7):
        b = cls(n=n, seed=seed)
        b.state_path = state_path
        if state_path and os.path.exists(state_path):
            b.load_state(state_path)
        else:
            b.created = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        return b

    def calibrate(self, seconds=0.0):
        """旧接口：现在不需要标定（情绪不再从网络特征算 z-score）。"""
        return self.emotions()


# ------------------------------------------------------------------ 命令行

def _print_table(b, title=""):
    e = b.emotions()
    if title:
        print(f"\n== {title} ==")
    print("   " + "  ".join(f"{EMO_ZH[k]:>3}{e[k]:5.2f}" for k in EMOTIONS))
    print(f"   mood={b.mood_line()}  da(owner)={b.da_plus['owner']:.2f} "
          f"da(other)={b.da_plus['other']:.2f} fight={b.fight_active()}")


def _demo(b):
    print("无名的大脑 v2 · 文字世界版")
    print(f"神经元 {b.n}：", "、".join(f"{k}:{v}" for k, v in b.sizes.items()))
    b.run(5.0)
    _print_table(b, "静息 5 秒")

    print("\n-- 陌生人说：你好呀 --")
    b.stimulate_text("你好呀", is_owner=False)
    b.run(3.0)
    _print_table(b, "陌生人夸她")

    print("\n-- 主人说：在吗（短，跨不过阈值）--")
    b.stimulate_text("在吗", is_owner=True)
    b.run(3.0)
    _print_table(b, "主人寒暄")

    print("\n-- 主人说：今天特别想跟你说说话，你最近到底在想什么？ --")
    b.stimulate_text("今天特别想跟你说说话，你最近到底在想什么？", is_owner=True)
    b.run(3.0)
    _print_table(b, "主人走心")

    print("\n-- 说说被赞 3 个 --")
    b.on_event("qzone_like", n=3)
    b.run(3.0)
    _print_table(b, "点赞")

    print("\n-- 连刷 15 条视频（看脱敏）--")
    for i in range(15):
        b.on_event("video", title=f"视频{i}")
        b.run(1.0)
        if i in (0, 4, 9, 14):
            print(f"   第 {i+1:2d} 条：da={b.da_plus['other']:.3f} 无聊={b.emotions()['boredom']:.2f}")

    print("\n-- 被骂：滚 --")
    b.stimulate_text("滚", is_owner=True)
    b.run(2.0)
    _print_table(b, "被骂")

    print("\n-- 静默 10 分钟（看回落）--")
    b.run(600.0)
    _print_table(b, "10 分钟后")


def _selftest(b):
    ok = True

    def check(name, cond, extra=""):
        nonlocal ok
        print(("  ✓ " if cond else "  ✗ ") + name + (f"  {extra}" if extra else ""))
        ok = ok and bool(cond)

    print("== 自检 ==")
    b.run(30.0)
    e = b.emotions()
    check("静息落在 baseline 附近",
          all(abs(e[k] - b.base[k]) < 0.10 for k in ("joy", "affection", "fear")),
          f"joy={e['joy']:.2f} fear={e['fear']:.2f}")

    # 阈值不对称
    b2 = FlyBrain(n=400, seed=11)
    b2.run(10)
    b2.stimulate_text("你好", is_owner=True)
    low_owner = b2.da_plus["owner"]
    b2.stimulate_text("今天特别想跟你说说话，你最近到底在想什么？", is_owner=True)
    high_owner = b2.da_plus["owner"]
    check("主人阈值高：寒暄不触发", low_owner < 0.02, f"{low_owner:.3f}")
    check("主人阈值高：走心触发", high_owner > 0.15, f"{high_owner:.3f}")

    b3 = FlyBrain(n=400, seed=12)
    b3.run(10)
    b3.stimulate_text("你好呀", is_owner=False)
    check("陌生人阈值低：随便一句就触发", b3.da_plus["other"] > 0.02, f"{b3.da_plus['other']:.3f}")

    # 回落
    b4 = FlyBrain(n=400, seed=13)
    b4.run(10)
    for _ in range(3):
        b4.stimulate_text("今天特别想跟你说说话，你最近到底在想什么？", is_owner=True)
        b4.run(2.0)
    peak = b4.emotions()["joy"]
    b4.run(900.0)
    back = b4.emotions()["joy"]
    check("情绪会回落", abs(back - b4.base["joy"]) < 0.08, f"峰 {peak:.2f} → 900s 后 {back:.2f}")

    # 精力不会钉死
    b5 = FlyBrain(n=400, seed=14)
    b5.run(10)
    b5.emo["energy"] = 0.20
    b5.run(1800.0)
    check("精力有充电回路（不钉地板）", b5.emotions()["energy"] > 0.40,
          f"{b5.emotions()['energy']:.2f}")

    # 视频脱敏
    b6 = FlyBrain(n=400, seed=15)
    b6.run(5)
    vals = []
    for i in range(12):
        before = b6.media_da
        b6.on_event("video")
        vals.append(max(0.0, b6.media_da - before * math.exp(-0.5 / 10.0)))
        b6.run(0.5)
    first = sum(vals[:4]) / 4.0
    last = sum(vals[-4:]) / 4.0
    check("刷视频会脱敏", last < max(1e-6, first) * 0.75, f"前4条均值 {first:.3f} → 后4条均值 {last:.3f}")

    # 战斗稀有
    b7 = FlyBrain(n=400, seed=16)
    b7.run(5)
    fights = 0
    for i in range(400):
        b7.stimulate_text("你给我滚出去", is_owner=False)
        b7.run(2.0)
        if b7.fight_active():
            fights += 1
    check("战斗是稀有事件（400 次挑衅 ≤ 2 次）", fights <= 2, f"{fights} 次")

    # 数值健康
    b8 = FlyBrain(n=600, seed=17)
    for i in range(200):
        b8.stimulate_text(["你好呀", "今天特别想你，你在想什么？", "滚", ""][i % 4], is_owner=(i % 2 == 0))
        b8.run(1.5)
    e = b8.emotions()
    check("无 NaN", all(not math.isnan(v) for v in e.values()))
    check("情绪都在 0~1", all(0.0 <= v <= 1.0 for v in e.values()), str(e))

    # 可复现
    a1 = FlyBrain(n=300, seed=99); a1.run(20); a1.stimulate_text("你好呀"); a1.run(5)
    a2 = FlyBrain(n=300, seed=99); a2.run(20); a2.stimulate_text("你好呀"); a2.run(5)
    check("同种子可复现", a1.emotions() == a2.emotions())

    check("处境行可生成", isinstance(b8.situation_line(), str))
    print("\nSELFTEST " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="无名的大脑 v2 · 文字世界版")
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--once", type=str, default=None)
    ap.add_argument("--other", action="store_true", help="把 --once 这句话当成别人说的")
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--write-state", type=str, default=None)
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    b = FlyBrain(n=args.n, seed=args.seed)
    b.run(5.0)

    if args.demo:
        _demo(b)
        return 0
    if args.selftest:
        return _selftest(FlyBrain(n=args.n, seed=args.seed))
    if args.once:
        b.stimulate_text(args.once, is_owner=not args.other)
        b.run(args.seconds)
        _print_table(b, f"说：{args.once}")
        print("\n" + b.instructions())
        return 0
    _print_table(b, "静息")
    print(b.instructions())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
