# entity_core —— 无名的「房子」

这是她常驻的地方。QQ 掉线、B 站没开、AstrBot 关掉，这个进程照样在跑：情绪继续走、记忆继续攒、有人在网页里说话她能回。
其它的东西（QQ、B 站、以后任何程序）都只是**门**，门关了房子还在。

## 跑起来

```powershell
# 手动（前台看日志）
<安装目录>\WiseEntity\source_code\scripts\start-core.cmd

# 平时不用管：启动器会在后台确保内核在听；
# 端口由安装器写入 config/app.yaml，不写死 40720。
```

- 地址：以 `config/app.yaml` 的 `core_url` 为准（只监听本机；安装器从 40720 起找空闲）
- 网页客厅：浏览器打开同一个地址
- 日志：`<安装目录>\WiseEntity\runtime\logs\entity_core.log`
- 启动器日志：`runtime\logs\core.log`

## 接口（给别的东西用）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 活着吗、脑子加载了吗、记忆多少条 |
| GET | `/state` | 情绪、mood、处境、fight、B 站配置 |
| GET | `/brain/fragment` | 「脑子里现在」的提示词片段（AstrBot 插件就取这个） |
| GET | `/brain/state` | 同 `/state` 的脑内读数 |
| POST | `/brain/stimulate` | `{"kind":"msg","text":"...","is_owner":true}` 给一个刺激 |
| POST | `/chat` | `{"session":"web:owner","text":"在吗"}` → `{reply, mood, emotions, memory_used}` |
| POST | `/event` | 世界事件（`qzone_like`/`video`/`sticker`/`group_msg`…） |
| GET | `/memory?q=&session=` | 这扇门能看到的记忆；`all=1` 看全部（主人） |
| POST | `/memory/note` | 手动记一条 `{"text":"...","scope":"owner"}` |
| GET | `/persona` | 现在的人格正文 |
| GET | `/bili/status` | B 站门配置与状态 |
| POST | `/bili/poll?force=1` | 立刻拉一次 B 站私信 |

会话命名：`web:owner`（网页客厅）、`qq:owner` / `qq:friend:<uin>` / `qq:group:<gid>`、`bili:owner:<mid>` / `bili:other:<mid>`。
主人 QQ 是 `10001`。

## 里面的东西

```
entity\core\
  settings.py    路径、常量、日志、JSON 读写（读 AstrBot 配置里的 DeepSeek key）
  brain_box.py   加载 entity\brain\flybrain_core.py，跑生物钟，消费 event_inbox.jsonl
  memory_box.py  分片记忆检索（owner / people\<uin> / groups\<gid>）
  llm_box.py     拼系统提示（人格 + 脑内状态 + 记得的事 + 这扇门的规矩）并调 DeepSeek
  chat_core.py   会话历史 + 一次完整回复
  bili_door.py   B 站私信门（轮询、过滤、限速、dry_run）
  app.py         FastAPI 服务与网页客厅
  static/index.html
  .venv\         专用 Python（fastapi/uvicorn/httpx/numpy）
```

数据在房子外面（属于她，不属于程序）：

- 人格 `entity\persona\persona-xiaochen.md`
- 情绪状态 `entity\brain\flybrain_state.json`（只有内核写）
- 念头 `entity\brain\thoughts.jsonl`；世界事件 `entity\brain\event_inbox.jsonl`
- 记忆 `entity\memory\notes.jsonl`（主人）、`entity\memory\people\<uin>\`、`entity\memory\groups\<gid>\`
- 会话 `entity\state\sessions.json`
- B 站门配置 `entity\state\bili_door.json`，已读游标 `entity\state\bili_door_state.json`

## B 站那扇门

账号 `UU-MNJK`（mid `20002`），cookie 存在 `entity\memory\sites.json` 的 `bilibili.cookies`。

```json
{
  "enabled": true,
  "poll_seconds": 90,
  "dry_run": true,
  "max_replies_per_hour": 12,
  "owner_mids": [],
  "allow_uids": [],
  "skip_uids": ["12076317", "2"]
}
```

- `dry_run: true` 只生成并记日志、**不发送**（现在就是这个状态）。要真发，把它改成 `false`。
- `owner_mids` 填主人自己的 B 站 mid，那样那扇门会被当成「主人」会话。
- `allow_uids` 非空 = 只回名单里的人；空 = 回所有真人私信。
- `skip_uids` 与内置的自动回复关键词过滤，用来避开官方号/营销号，免得跟机器人对刷。
- 改完配置下一轮（≤90 秒）生效，不用重启。

## 和 AstrBot 的关系

AstrBot 的 `astrbot_plugin_xiaochen_brain` 已经改成**瘦客户端**：
启动时探 `/health`，若内核在线就关掉自己的本地仿真，情绪走 `/brain/state`、刺激走 `/brain/stimulate`、提示词走 `/brain/fragment`。
所以 QQ 侧和网页/B 站侧是**同一个人、同一份情绪、同一个状态文件**；内核不在时它自动退回本地仿真（不影响 QQ 用）。

## 排错

```powershell
# 在不在
$u=(Get-Content <安装目录>\config\app.yaml | Select-String 'core_url').ToString(); (Invoke-WebRequest ($u -replace '.*core_url:\s*','')/health -UseBasicParsing).Content
# 日志
Get-Content <安装目录>\WiseEntity\runtime\logs\entity_core.log -Tail 40
# 重启
Get-Process python | ? { (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine -like '*uvicorn*' } | Stop-Process -Force
Start-Process cmd.exe -ArgumentList '/c','<安装目录>\WiseEntity\source_code\scripts\start-core.cmd' -WindowStyle Hidden
```
