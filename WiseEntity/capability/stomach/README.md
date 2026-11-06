# 胃（stomach）

她的「肚子」。只做一件事：**把 API 余额变成一个"饱不饱"的信号，交给大脑**。

```
DeepSeek 余额  →  capability/stomach/stomach.json  →  entity_core（llm_box / brain 插件）→ 她的语气
```

她自己看不到数字；除非主人问起钱，她才说具体数。这样"饿"是一种状态，不是一条报警。

## 阈值（用户定的）

| 余额 | 状态 | 她拿到的一句话 |
|---|---|---|
| ≥ 10 元 | `full` 饱 | 肚子：饱的，有底气，别惦记钱的事。 |
| 3 – 10 元 | `normal` 不饿 | 肚子：不饿，但也不算饱，别主动提钱。 |
| ≤ 3 元 | `hungry` 饿 | 肚子：饿（余额只剩 X 元）。你会有点没力气、句子变短、容易走神想起吃的；可以拐着弯让他充点钱，但别像客服催费，也别直接报数字。 |

改阈值：改 `stomach.py` 里的 `FULL_AT` / `HUNGRY_AT`（改完不用重启内核，下次轮询生效；提示词那行是现读的）。

## 文件

| 路径 | 作用 |
|---|---|
| `capability/stomach/stomach.py` | 取余额、算等级、写状态、给大脑一行话 |
| `capability/stomach/stomach.json` | 当前状态（`level` / `balance` / `text` / `ts` / `error`） |
| `runtime/logs/stomach.log` | 等级变化与拉取失败 |

`stomach.json` 超过 30 分钟没更新会被当成"说不准"（`stale`），这时不注入任何话，免得她一直喊饿或一直装饱。拉余额失败时**保留上一次的等级**，只记 `error`，不让状态乱跳。

## 谁在用

- `entity/core/maintenance.py`：内核每轮 tick（90 秒）里 `stomach_box.poll_if_due()`，实际每 5 分钟真拉一次。
- `entity/core/llm_box.py`：`build_system()` 里追加 `# 你的肚子` 一段 —— 网页客厅、B 站私信都走这里。
- `entity/core/app.py`：`GET /stomach`、`POST /stomach/poll`。
- `program_bundle/program_01_qq/tools/plugins_astrbot/astrbot_plugin_xiaochen_brain`：QQ 那边的 `inject_brain()` 会取 `/stomach` 的 `fragment` 拼进系统提示 —— 所以 QQ 门也能饿。
- `entity/persona/persona-xiaochen.md` 的「## 肚子（余额）」一节：规定饱/不饿/饿三种状态怎么说话。

## 手动检查

```powershell
# 量一次（会打印状态）
D:\BetterAIBridge\WiseEntity\entity\core\.venv\Scripts\python.exe D:\BetterAIBridge\WiseEntity\capability\stomach\stomach.py

# 看内核怎么想
Invoke-RestMethod http://127.0.0.1:40720/stomach
```

阈值自检（离线，不联网）：`source_code/tools/_test_stomach.py`。

## 注意

- key 从 `program_bundle/program_02_astrbot/data/cmd_config.json` 的 `provider_sources[].key` 读；读不到时状态是 `unknown`，不注入。
- 别把 `stomach.json` 当缓存删掉也没事，下一轮会自动重建。
- 这一层**不花钱**：`/user/balance` 是免费接口，5 分钟一次。
