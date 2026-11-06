# 结构

## 两个进程

| 进程 | 端口 | 干什么 | 起法 |
|---|---|---|---|
| 壳 `main.py` | — | 窗口、聊天页、模组管理、状态灯、建档向导 | `start.cmd` |
| 内核 `entity/core/app.py` | 动态（安装器从 40720 起找空闲） | 说话、记忆、情绪、自我、大脑、网页客厅、保姆驻守 | `source_code/scripts/start-core.cmd` |
| 语音 `capability/voice/asr/server.py` | 动态（从 40715 起找空闲） | 把语音转文字（可选） | `start-asr.cmd` |

## 内核里的盒子

| 文件 | 作用 |
|---|---|
| `llm_box.py` | 拼系统提示、调 DeepSeek |
| `brain_box.py` | 载 `entity/brain/flybrain_core.py`，每 90 秒推进一次 |
| `emotion_core.py` | 13 维情绪，内部 0~1000（500 中性）；详情页 -10~100 / 理智 -100~100 |
| `memory_box.py` | 分片记忆（按程序/人/群分抽屉） |
| `modules_box.py` | 读 `program_bundle/registry.json` 和模组声明 |
| `module_cfg.py` | 读模组设置（`program_<id>.pbab/settings.json`），给插件做开关 |
| `presence.py` / `proactive.py` / `drives.py` | 在线状态、主动说话、情绪驱动行为 |
| `self_store.py` / `self_reflect.py` / `self_trials.py` | 自写档案、证据、叙事/账本/校准、尝试循环 |
| `sense.py` | 耳目：按需看/听，以及“一直看着/听着”的后台观察 |
| `nanny.py` | 开局分析（称呼/人格草稿）+ 每 60 秒驻守模组端口 |
| `tutorial.py` | 教程状态机（跳过=永久；开始=延后到第 6 轮） |
| `chat_core.py` | 会话历史与回复 |
| `app.py` | FastAPI 路由（/chat /health /memory /emotions /setup /nanny/* /tutorial …） |

## 数据流

```
消息 → chat_core.reply
        ├─ emotion_core.note_message    （情绪先动）
        ├─ brain_box.stimulate_text     （神经也动）
        ├─ llm_box.chat                 （人格 + 记忆 + 此刻 + 工具 + 门规矩）
        └─ memory/transcript-*.jsonl    （原文归档，之后维护器压成 notes）
```

模组写记忆只有两条路（别让模组直接翻文件）：

1. 把对话送内核 `POST /chat`，落 transcript，之后 `maintenance.ingest` 抽事实；
2. 直接 `POST /memory/note`，**必须带 `program`**（`program_qq` / `program_bilibili` / `program_web`），
   否则会落进默认抽屉。

## 目录约定

- `entity/`：她自己的东西（人格、记忆、情绪、自我、大脑、状态、建档中间态）
- `capability/`：可选能力（语音、余额、视觉）
- `program_bundle/`：模组（`plugins/<id>` + `registry.json`）
- `program_cache/`：模组缓存与解包来源
- `WiseEntity/source_code/`：脚本与工具
- `WiseEntity/runtime/`：日志、下载、备份
