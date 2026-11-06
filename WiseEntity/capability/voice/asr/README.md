# 语音转写（ASR）

给「听声音」用的一个很小的本机服务：一段 wav 进去，一句话出来。
它不属于任何模组——内核用自己的全局令牌敲它，模组通过能力 `voice.asr` 转手。

## 接口

| | |
|---|---|
| `GET /health` | 引擎装没装、模型下没下、有没有加载过 |
| `POST /stt` | `{"path": "C:\\...\\a.wav"}` 或 `{"audio": "<base64>"}` → `{"text": "...", "seconds": 1.2}` |

请求要带 `x-bridge-token`，值来自 `WiseEntity\entity\memory\bridge_token.json`（内核第一次用到时自动生成）。

## 第一次装

1. 这里开一个终端：

   ```bat
   cd /d <安装目录>\capability\voice\asr
   python -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

2. 回 BAB：设置 → 语音 → 勾上「语音转写」。下次启动它就会用 `.venv` 里的解释器。
3. 第一次转写会下模型（small ≈ 480 MB，落在 `models\`）；下完就不再联网。

没装引擎时服务照样能起，`/health` 会说「没装 faster-whisper」，`/stt` 回 503 并把安装命令写清楚——不会偷偷下东西。

## 手动跑

```bat
start-asr.cmd
```

端口默认 40715（`install.json` 的 `asr`，或环境变量 `BAB_ASR_PORT`）。
日志在 `logs\asr.log`、`logs\asr-boot.log`。

## 已知限制

- 只吃 wav（16 kHz 单声道最稳）；mp3/ogg 先转一下。
- CPU 推理：一句话大约 1–3 秒（small、int8）。
- 中文识别对术语不敏感，认不准的时候把原话给她，让她自己接。
