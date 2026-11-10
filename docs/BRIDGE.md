# 桥（Bridge）：模组与 BAB 之间的交换站

保姆（`nanny`）从「进程保姆」升级成「交换站」：BAB 里发生的事由它往外递，模组的请求由它往里转。
模组永远不直接读 `entity/memory`、也不直接调 `brain_box`，只跟桥说话。

```
模组 M  ──POST /bridge/call──►  保姆（鉴权/限权/审计）──►  memory / brain / mood / presence
        ◄──GET  /bridge/events──  保姆（按订阅分发）    ◄──  事件总线 event_bus
```

## 一、双向语义

| 方向 | 内容 | 现在的实现 |
|---|---|---|
| 模组 → BAB | 读记忆、写记忆、看情绪、看在线状态 | `POST /bridge/call`，5 个能力 |
| 模组 → BAB | 模组自己的介绍、人格片段、工具清单 | 启用时读 `module.json` / `persona.md` / `introduce.md`，拼进提示词 |
| BAB → 模组 | 她收到了消息、她说了话、情绪变了、状态变了、主动开口了 | 事件总线 + 长轮询（`/bridge/events`）或推送（`bridge.events: "push"`） |
| BAB → 模组 | 模组的记忆抽屉 | 启用时建 `entity/memory/program_<x>/`，`memory.note` 写进去 |

「把模组的介绍拿给智能体看」已经接上：`modules_box.persona_text()` 现在会把 `persona.md` 和
`introduce.md`（截断 900 字，加标题「## 这份东西是干什么的」）一起拼进系统提示词。

## 二、假设的模组配置（`module.json` v2）

旧字段全部保留，新增一个 `bridge` 块；不写这个块的模组行为不变。

```json
{
  "format": "pbab/1",
  "api": 1,
  "id": "bili_bridge",
  "name": "B 站桥",
  "version": "0.3.0",
  "author": "Chanko",
  "homepage": "https://github.com/Chanko/bab-bili-bridge",
  "kind": "bridge",
  "summary": "让她能看 B 站，也能替你记一点东西。",

  "entry": { "start": "start.cmd" },
  "health": { "type": "port", "host": "127.0.0.1", "port": 40731, "timeout_s": 25 },
  "ports": [40731],

  "memory": {
    "program": "program_bilibili",
    "create": true
  },

  "login": { "type": "qr", "port": 40731, "label": "登录 B 站", "hint": "用手机 B 站 App 扫码" },

  "bridge": {
    "wants": [
      "memory.search",
      "memory.note",
      "brain.snapshot",
      "mood.read",
      "presence.read"
    ],
    "subscribes": ["message.in", "message.out", "mood.changed"],
    "events": "pull",
    "events_endpoint": "/events"
  },

  "settings": {
    "title": "B 站桥设置",
    "type": "object",
    "properties": {
      "allow_search": { "type": "boolean", "title": "允许搜视频", "default": true },
      "enable_like": { "type": "boolean", "title": "允许点赞（默认关）", "default": false },
      "like_prob": { "type": "number", "title": "点赞概率（0–1，有风险）", "minimum": 0, "maximum": 1, "default": 0 },
      "cache_seconds": { "type": "integer", "title": "缓存秒数", "minimum": 0, "maximum": 3600, "default": 300 }
    }
  }
}
```

字段说明：

| 字段 | 含义 |
|---|---|
| `bridge.wants` | 申请哪些能力；不在列表里的调用会被 403 |
| `bridge.subscribes` | 订阅哪些事件；不在列表里的事件不会推给它 |
| `bridge.events` | `pull`（长轮询）或 `push`（BAB 主动 POST 它的 `events_endpoint`） |
| `bridge.events_endpoint` | `push` 时的接收路径，默认 `/events` |
| `memory.program` | 它的记忆抽屉名（`program_bilibili`）；没写就是 `program_qq` |
| `memory.create` | 启用时是否建抽屉（默认 `true`） |

## 三、端点

### `GET /bridge/manifest`
请求头：`X-BAB-Token: <模组目录里的 bridge_token.txt>`
返回：安装信息、模组信息、能力清单、事件种类。

### `POST /bridge/call`
```json
{ "cap": "memory.search", "args": { "query": "上次聊的猫", "limit": 5 } }
```
返回 `{"ok": true, "cap": "...", "data": ...}`；失败是 `{"detail": "..."}` + 4xx/5xx。

### `GET /bridge/events?since=<seq>&wait=25`
长轮询：有事件立刻返回，没有就等到 `wait` 秒（上限 30）。返回 `{"seq": 最新, "events": [...]}`。

## 四、能力清单（v1）

| 能力 | 参数 | 说明 |
|---|---|---|
| `audio.play` | `path` | 让启动器放一段安装目录里的音频（mp3/wav），开始播就回，不挡调用 |
| `audio.stop` | — | 停掉启动器正在放的音频 |
| `avatar.get` | — | 她现在的头像：文件路径、是不是主人换的、什么时候换的 |
| `brain.snapshot` | — | 她的此刻：情绪值、理智、驱力、在线状态、记忆总数 |
| `chat.say` | `hint` | 让她用自己的话说一句（会真的作为她的发言出现，不是系统提示） |
| `config.write` | `key`, `value` | 改一项界面配置（只开放 ui.*，例如 ui.background.opacity） |
| `fs.mkdir` | `path` | 在 BAB 安装目录里建一个目录（只建目录，不能写文件、不能出安装目录） |
| `memory.note` | `text`, `scope`, `group`, `kind_key` | 往自己的抽屉里记一条（写进 notes.jsonl，也会进她的事件流） |
| `memory.search` | `query`, `limit` | 在 BAB 给这个模组留的抽屉里搜记忆（只看得到自己这个程序的抽屉） |
| `mood.read` | — | 只看情绪：mood 词 + 13 个值 |
| `notice.push` | `text`, `chat` | 让保姆栏记一条提醒（带时间）；chat=true 时也在她的聊天里插一句短话 |
| `persona.face.get` | — | 性格脸谱的规格（四个维度、发色、表情），可以照着画一张 |
| `persona.style.get` | — | 主人写的自定义性格：摘要、13 维情绪参数、脸谱规格 |
| `presence.read` | — | 使用者在不在（online/busy/away） |
| `project.apply` | `ops`, `reason` | 前置模组改程序文件/代码：不再逐次确认，先整包备份再写，记审计；可建目录、写任意文件；只支持 mkdir/write/delete |
| `sense.devices` | — | 问启动器：这台机器有几个摄像头、几个麦克风，现在选的是哪台 |
| `sense.look` | `question` | 让启动器的耳目看一眼（有摄像头用摄像头，没有就看屏幕），回文字描述 |
| `sense.status` | — | 启动器耳目现在什么样：眼睛开没开、多久看一次、选的是哪台摄像头/麦克风 |
| `tts.speak` | `text`, `voice`, `rate` | 合成她的声音并让启动器当场念出来（返回音频路径、时长、是否播出） |
| `ui.background.get` | — | 看启动器现在的背景设置（开关、效果、跟随、点击、浓淡、速度） |
| `ui.background.set` | `enabled`, `effect`, `follower`, `click`, `click_style`, `opacity`, `speed` | 改启动器的背景观感（只改观感，不能塞本地图片/视频路径） |
| `ui.mouse.get` | — | 鼠标在启动器窗口里的位置（窗口外 inside=false，坐标归零） |
| `ui.notify` | `text`, `title`, `level` | 弹一条启动器通知（托盘气泡），不进聊天、不进保姆栏；最多 240 字 |
| `vision.describe` | `image`, `question` | 让她看一眼图并说出来（可以直接给图片路径） |
| `voice.asr` | `path`, `audio`, `hint` | 把一段音频转成文字（内核自带的语音服务；没装模型会告诉你） |
| `voice.message` | `path`, `audio`, `duration_ms`, `keep`, `session` | 把一段 5–90 秒的语音发进主人的聊天框（自动转写，以可播放的音频气泡出现） |
| `voice.tts` | `text`, `voice`, `rate` | 把一句话合成她的声音（edge-tts），回 mp3 的路径；一分钟最多 6 段 |
| `warehouse.libraries` | — | 列出你申报到的仓库库：id、标题、用途、配额、已用 |
| `warehouse.list` | `kind`, `query`, `library` | 列你自己仓库库里的文件；看不到主人和别的模组 |
| `warehouse.mkdir` | `name`, `library` | 在你自己的仓库库里建一个子目录 |
| `warehouse.put` | `name`, `base64`, `path`, `kind`, `library` | 往你自己申报的仓库库里放一个文件（图片/文档/文件）；library 是你的库 id |
| `warehouse.read` | `id`, `library` | 读你自己仓库库里一个文本文件；PDF/DOCX 只存不读 |

## 五、事件（v1）

`message.in`、`message.out`、`mood.changed`、`drive.urge`、`memory.written`、`presence.changed`、`proactive.spoke`、`world.event`、`voice.play.started`、`voice.level`、`voice.play.ended`

## 六、安全与审计

- **通行证**：模组启用时在它目录写 `bridge_token.txt`（16 字节 hex），同时通过环境变量 `BAB_BRIDGE_TOKEN` 传入；请求必须带 `X-BAB-Token`。
- **白名单**：只认 `bridge.wants` 里写过的能力。
- **抽屉隔离**：`memory.search` 只搜 `memory.program` 指的那个抽屉；读不到主人的私聊、也读不到别的模组。
- **审计**：每次调用写一行 `entity/state/bridge_audit.jsonl`（`module / cap / ok / size / why`）。
- **写入默认进记忆流**：`memory.note` 会触发 `memory.written`，别人也能看到这件事发生了。

## 七、兼容

- 没有 `bridge` 块的旧模组：工具照旧（`connection.json` + `tool_bus`），不参与桥。
- 有 `bridge` 但没写 `wants`：只能调 `manifest`，调用能力一律 403。
- 端口：临时端口 + 身份校验 + `install_id` 已落地；桥按 `install_id` 校验，不认别的安装。

## 八、状态

已实现并实测：`manifest`、`memory.note`、`memory.search`、`brain.snapshot`、`mood.read`、
`presence.read`、`/bridge/events` 长轮询、`403` 越权拦截、审计落盘、模组介绍进提示词。
已写但未实测：`bridge.events: "push"` 的推送路径（`fanout()`）。
未做：`asr.transcribe`、`tts.speak` 的桥能力；设置页的「桥权限」面板、`install_id`、端口块已落地。
