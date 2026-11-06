# M 的结构、边界与可能的功能

这份文档回答三个问题：**谁能看见什么**、**M 由哪些零件组成**、**M 还能长出什么**。
写新模组时把它当说明书读；它和 `MODULES.md`（契约与坑）是互补的。

---

## 一、两套受众，两条通道

同一个模组，对两类读者说两套话。这两套话分别走两条完全不同的通道，互不串味。

| | 智能体（她） | 使用者（你） |
|---|---|---|
| 看到什么 | `persona.md` 全文 + `introduce.md` 前 900 字（挂在「## 这份东西是干什么的」下）+ 每个工具的签名（名字/说明/参数） | 模组卡片（名字、版本、开发者、kind、summary、状态/端口/pid）+ `introduce.md` 全文 + 参数开关（`settings.schema.json`）+ 可打开的窗 |
| 从哪进来 | `modules_box.persona_text()` → 系统提示词；`tool_bus._build()` → 工具函数 | 模组页 `/mods` 卡片；`ModuleSettingsDialog`；`QrLoginDialog` / `OwnerMidDialog` / `PendingDialog`；`ModuleLogDialog` |
| 什么时候 | 只有**已安装且已启用**的模组才进提示词；没装时一个字都看不到（`wall()` 还会把「哔哩哔哩/B站/QQ」换成泛称） | 装了就能看（停了也能看），装之前只在「本地还有 N 个包没装」里见到文件名 |
| 说话方式 | 第一人称、说能力不说平台："我能看网页""我能看你的 B 站" | 说明书口吻：装什么、要什么权限、参数什么意思、出问题看哪里 |

一句话：**她的这一份是"我能做什么"，你的那一份是"这东西是什么、怎么调"。** 开发者写两份文案（`persona.md` / `introduce.md`），外壳负责把对的那份递给对的人。

## 二、谁站在中间

不是一个人，是两个角色，合起来才是你在界面上看到的「保姆程序」：

- **桥 = `core/bridge.py`**（那扇门）。只认两样东西：`X-BAB-Token`（每个模组一份，装的时候发）和 `module.json` 的 `bridge.wants`（白名单）。它做的事是**鉴权 → 分发 → 审计**（`state/bridge_audit.jsonl` 一行一次）。模组越不过它去碰 BAB 的内部。
- **保姆 = `core/nanny.py`**（门房兼账房）。管的是**账**和**人**：registry 里谁装了、谁在跑、谁 degraded（`check_once` 真去连 `runtime_port`）；谁要动副作用（点赞/收藏/给陌生人发私信）先压进待批队列（`drain_pending`）；模组掉了、恢复、肚子饿了，往保姆栏写一条带时间的提醒（`notice.push` 走的就是这条）。

所以在数据流上：**模组 → 桥（鉴权/审计）→ BAB 内核；模组 → 保姆（状态/待批/提醒）→ 使用者。** 你不能绕过桥去读她的情绪，也不能绕过保姆去替使用者做决定。

## 三、M 的零件

```
program_M.pbab/
├─ module.json        身份与契约：id=m、版本、端口、health、memory.program、
│                     bridge.wants（要哪几个 cap）、subscribes（订哪些事件）、settings.schema
├─ connection.json    对智能体的"手"：11 个工具 ↔ 11 个端点，一一对齐
│                     （名字、说明、参数、超时；tool_bus 靠它生成函数）
├─ introduce.md       对使用者的说明书（她也能看到前 900 字，装了之后）
├─ persona.md         对她说的行为约束（她怎么用这只手）
├─ settings.schema.json  使用者能调的开关（note_category、quiet）→ 模组从桥的 manifest 读
├─ server.py          模组本体：标准库 HTTP 服务，把工具翻成对桥的调用
├─ start.cmd          启动器：端口先读 %BAB_MODULE_PORT%，没有才退回 40733
└─ README.md          给开发者看的（怎么照它改一个自己的模组）
```

M 自己**不做业务**。它是"接口全集"的可运行样例：凡是外壳允许模组碰到的地方，M 都碰一遍，并把结果如实翻给模型。

## 四、M 现在能碰到的十一处

| 组 | 工具 | 端点 | 实际做的事 |
|---|---|---|---|
| 看状态 | `m_state` | `GET /state` | 先走桥 `brain.snapshot`；桥不通就退回 mood + presence 拼一份，`source` 说明来源 |
| | `m_mood` | `GET /mood` | 13 个情绪值 + mood 词 |
| | `m_presence` | `GET /presence` | 你在不在（online / busy / away） |
| 记忆 | `m_memory_search` | `POST /memory/search` | 只搜自己抽屉（`external/program_m/**`） |
| | `m_memory_note` | `POST /memory/note` | 往自己抽屉写一条，分类默认取设置里的 `note_category` |
| 桥的元信息 | `m_bridge_call` | `POST /bridge` | 万能口：把 cap + 参数原样递给保姆；没申请的 cap 会 403，原话带回 |
| | `m_bridge_caps` | `GET /bridge/caps` | 能力总清单 + 自己被允许的（wants） |
| | `m_events` | `GET /events` | 订阅事件（现在只有 `memory.written`），可长轮询 0–20 秒 |
| 提醒 | `m_notice` | `POST /notice` | 往保姆栏记一条（带时间）；`chat=true` 也在她聊天里说一句 |
| 自省 | `m_self` | `GET /self` | 自己的 id / 版本 / 端口 / Python / BAB 根 / 有没有 token |
| | `m_doctor` | `GET /doctor` | 自检：token、桥、两个关键 cap、日志大小，给一句 verdict |

底层只有 6 个 cap：`memory.search`、`memory.note`、`brain.snapshot`、`mood.read`、`presence.read`、`notice.push`。
M 的十一个工具是把这 6 个 cap 掰开、包上人话的结果——这也是给新模组的第一条建议：**先想清楚要用哪几个 cap，再决定暴露几个工具**。

## 五、M 现在做不到的（边界，不是 bug）

- **不能自己弹窗、弹提示、开浏览器**。四扇窗（扫码、补登记 UID、待批、设置）都是外壳渲染的，模组只供数据；想加第五扇窗，得先在外壳加 cap。
- **不能读别人的抽屉**。`memory.search` 只看得到 `external/<自己的 program>/**`；群聊与主人的记忆对她（BAB）可见，对模组不可见。
- **不能替使用者做决定**。点赞/收藏/给陌生人私信一律先进待批；拒绝就是拒绝。
- **不能改自己的设置**。设置是使用者改、模组读（`/bridge/manifest` 的 `module.settings`），模组只能建议。
- **不能越过 wants**。没申请的能力调过去就是 403，错误原样带回给你看——M 的 `/doctor` 会把这类问题直接指出来。

## 六、M 还能长出什么

### A. 不需要外壳改动，M 自己就能加

1. **定时提醒**：一条常驻线程 + 一个 `reminders.json`，到点调 `notice.push`，同时 `memory.note` 记一笔。这就是"提醒/日程"模组的全部骨架。
2. **本地笔记/文件抽屉**：`note_category` 已经能把记忆分门别类；再加一个 `m_notes_list`（读自己抽屉的最近几条）与 `m_notes_export`（导出成 markdown 到 `logs/`）。
3. **事件驱动的反应**：`m_events` 已经能长轮询 `memory.written`；收到就回写一条"我看到了"，做成"她记事时我也记"的联动。
4. **状态镜像**：定时把 `m_state` 的快照写进自己抽屉（一天一份），以后回答"上周我心情怎么样"就有据可查。
5. **自检扩展**：`m_doctor` 加"最近 24 小时错误次数""平均响应毫秒"，变成模组的体检报告。

### B. 需要外壳新增 cap（要先在 `bridge.py` 的 `CAPS` 里加，再给 M 加工具）

| 想要的能力 | 建议的 cap | 语义 |
|---|---|---|
| 让模组请使用者开一个网页/窗口 | `ui.open_url` | 只允许 http(s)，外壳弹确认，记事到保姆栏 |
| 让模组读最近几句聊天 | `chat.recent` | 只给已启用的模组，按条数/字数限额，敏感内容脱敏 |
| 让模组给她递一句话 | `chat.say` | 走和工具调用同一条通道，进她的上下文 |
| 让模组看人设与性格 | `persona.read` | 只读（风格名、当前情绪、关系称呼），不给内部参数 |
| 让模组请求一次确认 | `approve.request` | 进待批队列，结果回给模组（点赞那套的通用版） |

加 cap 的规矩和现在一样：**进 `CAPS` 表、进 wants 白名单、写审计、失败给 `code`**。

### C. 明确不建议做的

- 给模组一个"万能执行"入口（能跑任意命令/读任意文件）——那就不是门了。
- 让模组自己维护一份模组列表/注册信息。**装没装、装了什么，永远以 registry 为准**；模组只描述自己。

## 七、照 M 做一个新模组，要改的六处

1. `module.json`：`id` / `name` / `version` / `ports` 与 `health.port` / `memory.program` / `bridge.wants`（只申请真用得上的 cap）。
2. `connection.json`：加 `tools[]` 与 `endpoints[]` 的**同一对**（名字、路径、方法一一对齐；对不上会被 tool_bus 静默丢掉——这是最容易踩的坑）。
3. `server.py`：写 `tool_xxx(args)`，用 `call_cap` / `_fail(code, hint)`，别自己拼 JSON 错误。
4. `persona.md`：用第一人称写"我怎么用这只手"（她会读这段）。
5. `introduce.md`：写给使用者的说明书（他会在模组设置里读全文；她只读前 900 字）。
6. `settings.schema.json`：只放真需要的开关，模组通过 `/bridge/manifest` 读。

跑通的标准：`python tools\new_module.py --check --smoke`、`python tools\test_module_m.py`（照它改一份自己的）、再 `python tools\check.py` 全绿。
