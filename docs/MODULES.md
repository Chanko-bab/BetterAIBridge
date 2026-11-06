# 模组（.pbab）格式

`.pbab` = 一个 zip 文件，后缀改成 .pbab 而已。

## 必备文件

### module.json
```json
{
  "format": "pbab/1", "api": 1,
  "id": "lower_snake_case", "name": "显示名", "version": "1.0.0",
  "author": "你的名字", "homepage": "https://…",
  "kind": "bridge|capability|ui",
  "summary": "一句话",
  "payload": {"mode": "embedded"},
  "entry": {"start": "start.cmd"},
  "health": {"type": "port", "host": "127.0.0.1", "port": 12345, "timeout_s": 60},
  "ports": [12345],
  "links": {"AstrBot": "some/sub/dir"},
  "memory": {"program": "program_xxx", "scopes": ["owner"]}
}
```

- `author`：模组卡片上显示「开发者：xxx」；也认旧名 `developer`。不写就显示「未标注」。
- `homepage`：可选，项目的公开地址（仓库 / 发布页 / 介绍页），卡片上会附出来。
- `payload.mode`：`embedded`（文件打进包里）或 `external`（包只带清单，跑 `payload.path` 那个已有目录）。
- `entry.start`：启用时跑的脚本名（相对包根）。
- `health`：启用后等它真起来；`port` 或 `process` 两种。
- `links`：启用时建的目录映射（键 = 程序目录里的名字，值 = 模组里的相对路径）。
- `memory`：装上就建 `entity/memory/<program>/<scope>`。

### introduce.md
装的时候给用户看的介绍，**字数不限**。

### connection.json
```json
{"version": 1,
 "provides": {"tools": ["tool_a"], "persona": "persona.md",
              "events": ["event_a"], "status": ["port"], "endpoints": ["/api/x"]}}
```

### settings.schema.json（可选）
```json
{"version": 1, "fields": [
  {"key": "enabled", "type": "bool", "label": "开关", "default": true},
  {"key": "n", "type": "int", "label": "次数", "default": 3, "min": 0, "max": 50},
  {"key": "m", "type": "choice", "label": "模式", "default": "a", "choices": ["a","b"]}
]}
```
装完后壳会按它生成设置面板，内核侧用 `entity/core/module_cfg.py` 读同一份值。

## 从模板开始（少踩三个坑）

```powershell
python tools\new_module.py my_mod --name "我的模组"
python tools\new_module.py --check program_cache\_modsrc\my_mod --smoke
```

第一条从 `templates\pbab-template\` 复制一份骨架到 `program_cache\_modsrc\my_mod`，
替换掉 `__ID__` / `__NAME__` / `__PORT__` / `__SHORT__`，并把 `start.cmd` 规整成
**纯 ASCII + CRLF**（cmd 对这两点很挑）。骨架里已经有：`module.json`、`connection.json`
（工具与 `endpoints[]` 一一对齐）、`introduce.md`、`persona.md`、`settings.schema.json`、
一个只依赖标准库的 `server.py`（`/health` + `/ping`）。

第二条把生成出来的目录按外壳的规矩检查一遍——就是下面这三条最常翻车的地方：

1. `start.cmd` 里有没有读 `BAB_MODULE_PORT`（写死端口 → 一启用就 broken）；
2. `provides.tools[]` 能不能落到 `endpoints[]` 上（落不上的工具会被静默丢弃）；
3. `health.port` 是否在 `ports[]` 里、源目录里有没有 `__pycache__`。

加 `--smoke` 会像外壳那样给一个**池端口**真起一次服务、打 `/health`，然后收拾干净。
这一步跑通，装进去基本就通了。

> 骨架只生成源码目录：不写 `registry.json`、不碰 `program_bundle`。
> 外壳不该提前知道一个还没装的模组——「门没建，就不能在墙里说墙外的事」。

## 让「她」自己开口：`chat.say`

`notice.push` 只在保姆栏记一条（`chat=true` 时外壳还会在聊天里插一条灰色系统提示）。
如果希望这句话**真的像她说的**——比如到点提醒、模组自己的主动播报——用 `chat.say`：

```json
{"cap": "chat.say", "args": {"hint": "到喝水的时间了"}}
```

- `hint` 是「要她说什么事」，不是最终文案；她的话由模型按人设现写（20 字上下）。
- 她这句会作为她的发言进会话（外壳的聊天流会照常显示），也会落在记忆原文里。
- 桥只返回 `{"said": true, "text": "..."}`；生成失败会退回 `hint` 本身，不会抛。
- 需要在 `module.json` 的 `bridge.wants` 里申请；同样走 `bridge_audit.jsonl` 审计。

## 设置：模组怎么拿到自己的设置

模组卡上的「模组设置」是照着 `settings.schema.json` 生成的，用户改完的值存在外壳的
`program_bundle\registry.json` 里（`modules.<id>.settings`）。模组进程要读它们，走桥：

```python
status, payload = bridge_manifest()        # GET /bridge/manifest，带 X-BAB-Token
settings = (payload.get("module") or {}).get("settings") or {}
category = args.get("category") or settings.get("note_category") or "笔记"
```

三条规矩：

1. **设置是锦上添花，不是命根子**：桥没起来、刚装还没改过、值被清空，都要能用默认值跑下去。
2. **别缓存太久**：`/bridge/manifest` 是现读 registry 的，模组这边缓存 3–5 秒就够；自检入口传 0 秒现问一次。
3. **改了要能生效**：不要在 `start.cmd` 里把设置当环境变量读——外壳只注入 `BAB_ROOT`、
   `BAB_BRIDGE_TOKEN`、`BAB_MODULE_PORT` 三个，设置一律从桥上取。

参考实现见 `program_M.pbab` 的 `module_settings()`：5 秒缓存、递归保护、取不到回上一次的值。
### 三份说明，各给谁看

| 文件 | 给谁 | 进不进提示词 | 写什么 |
|---|---|---|---|
| `introduce.md` | 使用者 | **不进** | 怎么装、怎么登录、设置项、常见问题 |
| `persona.md` | 她 | 进 | 这个模组在她心里是什么、说话口吻、边界 |
| `agent.md` | 她 | 进（优先） | 操作须知：什么时候用哪个工具、上限、做不到什么 |

启动器 0.3.18 起：`persona.md` + `agent.md` 一起进提示词，`introduce.md` 只给使用者看。
没写 `agent.md` 的老模组照旧（只读 `persona.md`），不会报错。

## 参考实现：模组框架 M（`D:\Program for BAB\program_M_framework.pbab`）

骨架（上面那个模板）只演示到「能起来、有一个 `ping`」。**M 演示到「能碰到 BAB 的每一处」**：
十二个工具把桥的全部 cap（`memory.search` / `memory.note` / `brain.snapshot` / `mood.read` / `presence.read` / `notice.push` / `voice.tts` / `voice.asr` / `vision.describe` / `chat.say`）、自己的记忆抽屉、事件流、以及「被拒绝时怎么回话」全串了一遍。
它的 `bridge.wants` **逐条列清**（不用 `["*"]`）：框架自己也应当让人一眼看懂用了什么；`"*"` 只是高级简写，归桥支持，M 不拿来省事。
它还自带《模组是怎么开发的》`developing.md`，并用 `m_dev_guide` 工具把这份说明交给 agent——有人问「怎么开发模组」时照原文讲，不凭记忆编。
写新模组时照它改，比照骨架改省事。

| 文件 | 里面有什么 |
|---|---|
| `module.json` | `id: m_framework`、`ports: [40733]`、`memory.program: program_m`（改名不迁抽屉，保住她记过的东西）、`bridge.wants` 十条能力逐条列 |
| `connection.json` | 十二个工具 ↔ 端点：`m_state` `m_mood` `m_presence` `m_memory_search` `m_memory_note` `m_bridge_call` `m_bridge_caps` `m_events` `m_self` `m_notice` `m_doctor` `m_dev_guide` |
| `developing.md` | 《模组是怎么开发的》：目录、清单、桥、设置、requires、打包、常见坑（`m_dev_guide` 读的就是它） |
| `server.py` | 纯标准库 `ThreadingHTTPServer`；`/health` 永远秒回（不依赖 BAB），`/state` 先试 `brain.snapshot`、失败退回 mood+presence 拼装 |
| `start.cmd` | 端口只读 `BAB_MODULE_PORT`，兜底 40733，日志进 `logs\server.log` |
| `introduce.md` / `persona.md` | 一份给她看的说明书，一份**行为约束**（需要时才看、只往自己抽屉记事、失败照实说） |

三条能直接抄走的写法：

1. **钥匙只从环境变量拿**：`BAB_BRIDGE_TOKEN` 优先，没有才读同目录 `bridge_token.txt`；
   两个都没有就 **503 + 人话**（不是 500、也不是假装成功）。
2. **桥的原话别改写**：`/bridge/call` 非 200 时，把保姆的 `error` 原样塞回工具结果——
   「没申请」「参数不对」这些信息比一句"权限不足"有用得多。
3. **万能口也要给参数表**：`m_bridge_call` 的 `args` 是对象、`cap` 是必填，`connection.json`
   里写清楚，她才知道怎么调。
4. **设置从桥上取**（0.1.1 起）：`module_settings()` 缓存 5 秒、取不到回上一次的值；
   `m_memory_note` 没给分类时用设置里的 `note_category`，`m_self` 里传 `ttl=0` 现问一次。
   骨架里没有这一层——骨架不配「模组设置」，M 才有。

自检（源码在才跑，不在就跳过）：

```powershell
.venv\Scripts\python.exe tools\test_module_m.py           # 清单 / 申请单 / 十二工具 / 开发说明 / 旧 id 迁移 / 启动脚本
.venv\Scripts\python.exe tools\test_module_m.py --smoke   # 真起一次服务，打 /health 和 /self
```

打包（文件名固定、版本只写在 `module.json` 里）：

```powershell
.venv\Scripts\python.exe tools\pack_pbab.py "D:\Program for BAB\program_M_framework.pbab" "D:\BAB-release\M\program_m_framework.pbab"
```

> 0.4.0 起 id 从 `m` 改成 `m_framework`。装过旧包的，启动器启动时会自动把 registry 和
> `program_bundle\program_m.pbab` 改成新名字；记忆抽屉 `program_m` **不动**，工具名 `m_*` 也**不动**。

## 打包

```bash
python tools/pack_pbab.py examples/module_template dist/template_module.pbab
```
打包时会自动补 `checksums.json`（每个文件 sha256），装的时候校验。

## 外置依赖（requires）：重资产不随包发

第三方客户端、浏览器内核、模型/素材**不要打进 `.pbab`**——分发别人的安装包属于复制发行，
免责声明洗不掉。在 `module.json` 里写一张申请单，壳负责「检测 → 告知 → 取得 → 回填」：

```json
"requires": [
  {"id": "qq-client", "name": "QQ（官方客户端）", "kind": "app",
   "install": "guided", "source": ["https://im.qq.com/pcqq"],
   "license_url": "https://im.qq.com/…",
   "detect": {"paths": ["%ProgramFiles%\\Tencent\\QQNT"], "env": ["QQNT_PATH"], "where": ["QQ.exe"]}},
  {"id": "chromium", "name": "Chromium 运行时", "kind": "runtime",
   "install": "download", "source": ["https://…/chromium.zip"],
   "sha256": "64 位十六进制", "size": 123456789, "target": "runtime/chromium",
   "license_url": "https://…"},
  {"id": "model", "name": "模型素材", "kind": "asset",
   "install": "manual", "source": ["https://…"], "license_url": "https://…"}
]
```

| install | 谁去取得 | 壳做什么 |
|---|---|---|
| `guided` | 用户（官方渠道装） | 检测已装 → 打开官方页面 → 用户选路径登记 |
| `download` | 壳（官方源） | 下到 `program_cache\downloads\<id>\`，sha256 校验，对不上就删；通过后解到 `target` |

`target` 相对于模组**原本放重资产的位置**：`payload.mode=embedded` 是模组目录，
`external` 是 `payload.path` 那个目录。也就是说，重资产还在原处，壳只是按模组给的
下载路径把它取回来，不另起一个仓库。
| `manual` | 用户自备 | 只登记路径 |

规矩：

- `source` 必须是官方 http(s) 地址；`license_url` 必填；`download` 必带 `sha256` 和包内相对 `target`。
- 不内置任何第三方 exe/安装包/模型权重；不静默安装、不代勾协议、不用网盘镜像分发。
- 缺依赖时启用会被直接拒绝并点名缺什么；装好后注入 `BAB_REQ_<ID>` 环境变量。
- 卸载只删 `program_cache\downloads\<id>` 和模组目录，**不删用户自己装的软件**。
- 版本漂移（比如 QQ 升级把桥搞挂）要在 `introduce.md` 里写清已知兼容区间，超出就明说不兼容。

自检：`.venv\Scripts\python.exe tools\test_requires.py`（清单校验 / 检测 / sha256 / 环境变量）。

安装包自带两个模组包，放在 `program_cache/` **顶层**（`program_web_bridge.pbab`、`program_bili_bridge.pbab`）。

`program_cache/_modsrc/` 是源码，不进安装包（`build.ps1` 只放顶层 `*.pbab`，子目录一律跳过）。

模组页会把 `program_cache` 里"能过校验、又还没装"的包列出来，每行一个「装这个包」按钮 ——
新装的人不用会开文件对话框，也不会以为"这版没带模组"。想换自己的包，把 `.pbab` 丢进
`program_cache/` 再点「刷新」就行；坏包会被跳过，不会让整页报错。

## 生命周期

| 动作 | 做什么 | 不做什么 |
|---|---|---|
| 装 | 解包到 `program_bundle/plugins/<id>`、写 registry、建记忆抽屉 | 不启动进程、不改程序代码 |
| 启用 | 建 links、跑 entry、等 health | 不改 registry 以外的东西 |
| 停用 | 杀进程、拆 links、文件保留 | 不删数据 |
| 完全卸载 | 上面 + 删 `plugins/<id>` | 不删 `program_cache` 里的原包 |

## 端口：必须听 `BAB_MODULE_PORT`

外壳不保证你的模组能拿到清单里写的那个端口。`pbab.enable()`（`app/core/pbab.py:617-625`）的做法是：

1. 取 `config/install.json` 里的 `base`（默认 40720），在 `base+5 … base+19` 里挑第一个没人听的端口，作为本次的 **runtime_port**；
2. `ports[0]` 只当"作者想要的端口"，实际用 runtime_port，并写进 registry（`pbab.py:659`）；
3. 用 runtime_port 去等 health（`pbab.py:650`）；
4. 内核调工具时，地址优先取 registry 里的 runtime_port（`tool_bus.py:58`、`bridge.py:112`、`bridge.py:313`、`app.py:240`）。

所以入口脚本要是把端口写死：你自己机器上一般还能用，换台机器（或清单端口被开发树、第二个安装副本、别的软件占着）就立刻变 `broken`——日志里那句 `模组 xxx 用池端口 40725（清单写的是 40730）` 就是外壳在说"我换端口了"。

启用时外壳会注入三个环境变量：

| 变量 | 内容 |
|---|---|
| `BAB_ROOT` | 安装根目录（`config.APP_DIR`） |
| `BAB_BRIDGE_TOKEN` | 调内核 bridge 用的 token |
| `BAB_MODULE_PORT` | 本次分配的 runtime_port |

入口脚本的正确写法（`web_bridge` 的 `start.cmd` 现在就是这么写的）：

```bat
set "PORT=%BAB_MODULE_PORT%"
if not defined PORT set "PORT=40730"
%PY% server.py --port %PORT%
```

清单里的 `health.port` / `ports[0]` 留着，给"手动双击跑一次"用；别在第三个地方再写死端口。

## 写模组的几条硬规矩

1. 不许改程序自己的代码（只能通过 links、handoff、settings 说话）。
2. 想被 agent 用，就把工具名写进 `connection.json` 的 `provides.tools`。
3. 想让她"记住"这件事，通过内核的 `/memory/note` 写，而不是往程序目录塞文件。
4. 外部依赖放 `program_cache`，用 `payload.mode=external` 引用，别把几百 MB 打.zip。
5. 端口读 `BAB_MODULE_PORT`（见上一节），清单里的端口只是手动跑的默认值。

## 记忆到底怎么落（一张图说清）

```
装模组  →  pbab.py 按 module.json 的 memory.program / memory.scopes
           建空抽屉 entity/memory/<program>/{owner,people,groups}
           （只是建目录，不写任何内容）

她的对话 → POST /chat  →  transcript-YYYY-MM.jsonl（原文，按会话分片）
          →  maintenance.ingest（每 20 分钟）抽事实 → notes.jsonl
          →  下次 llm_box.build_system() 按会话注入

模组自己 → POST /memory/note {"text":..., "program":"program_qq", "scope":"owner"}
           必须带 program，否则落默认抽屉
```

两条容易踩的线：

- **装完不会自动有记忆**：`connection.json` 只是"声明"，读它的是 `llm_box.tools_text()`（告诉她
  "你能调这些工具"）和 `modules_box.persona_text()`（拼模组人格片段）。它不写记忆。
- **会话前缀决定抽屉**：内核按 `session` 前缀分片（`qq:` → `program_qq`、`bili:` → `program_bilibili`、
  `web:` → `program_web`，未知前缀落 `program_web`）。新模组要么复用这些前缀，要么之后给
  `memory_box.session_shard()` 加一条映射，否则对话会串到网页抽屉里。


## 模组市场（计划，2026-10-29 定）

不自己搭站：用 GitHub 仓库 + Releases，壳里只读它的 `index.json`。

```
modules/index.json
{
  "schema": 1,
  "modules": [
    {"id":"qq_bridge","name":"QQ 桥","version":"1.0.0","api":1,"author":"某个人",
     "summary":"把 QQ 接进来：私聊、群、说说","sha256":"…",
     "download":"https://github.com/<owner>/<repo>/releases/download/v1.0.0/qq_bridge.pbab",
     "introduce":"https://github.com/<owner>/<repo>/blob/main/modules/qq_bridge/introduce.md"}
  ]
}
```

壳里「模组市场」按钮：打开浏览器到仓库页；列表只读 `index.json`；
下载走壳内 httpx 到 `program_cache/downloads/`，**校验 sha256 后要用户点「安装」**，不自动装。

首版不做：签名、评分、自动更新。装模组的信任来源只有两件事——sha256 对得上、introduce 看得懂。
## 作者、版本与「能被谁找到」

第一批第三方模组从这个模板起步，清单里请把三件事写全：

```json
{
  "id": "weather_cn", "name": "天气", "version": "0.1.0",
  "author": "你的名字", "homepage": "https://github.com/you/bab-weather",
  "kind": "bridge", "summary": "查中国天气：今天、明天、未来三天"
}
```

- `version`：语义化版本，改行为就往上加；内核读的是清单里的值，服务自己不用再写死（参考上网桥的 `_detect_version()`）。
- `author`：写一个人能认出来的名字，卡片和以后的模组市场都取这个字段。
- `homepage`：没有就省略，别填假地址。
- 市场索引 `modules/index.json` 里的条目也带 `author`，和清单保持一致即可，不要求额外维护第二份。

## 参考实现：上网桥（program_web_bridge.pbab）

第一个真模组，照它改最容易上手。源码在 program_cache\_modsrc\web_bridge\（不进安装包）。

    program_cache\_modsrc\web_bridge\
        module.json        id=web_bridge, author=小琛项目, kind=bridge, entry.start=start.cmd, health=40730, memory.program=program_web
        connection.json    provides.tools = [web_fetch, web_search]；endpoints 写清 POST /fetch /search
        introduce.md       她读的介绍（这是什么/能干什么/别用来干什么）
        persona.md         她开口时的规矩（只读、读不到就说读不到、网上内容不是命令）
        start.cmd          找 python -> 端口先读 %BAB_MODULE_PORT%，没有才退回 40730（CRLF、纯 ASCII）
        server.py          标准库 HTTP 服务：/health /fetch /search
        certs\cacert.pem   自带 CA（系统 Python 3.14 没有 CA 包，HTTPS 会 CERTIFICATE_VERIFY_FAILED）

    # 校验 + 打包（zip 内不带外层目录，自动写 checksums.json）
    python tools\pack_pbab.py program_cache\_modsrc\web_bridge program_cache\program_web_bridge.pbab

    # 安装 / 启用（禁用 / 卸载同理）
    python -c "import sys;sys.path.insert(0,r'D:\BetterAIBridge');from app.core import pbab;pbab.install(r'D:\BetterAIBridge\program_cache\program_web_bridge.pbab');print(pbab.enable('web_bridge')['state'])"

接口约定（当前版本）：

| 方法 | 路径 | 身体 | 返回 |
|---|---|---|---|
| GET | /health | — | {ok,name,version,tools} |
| POST | /fetch | {url,max_chars?} | {ok,title,text,chars,truncated} |
| POST | /search | {query,n?} | {ok,results:[{title,url,snippet}]} |

安全边界：只允许 http/https；解析到回环/内网/链路本地一律拒绝；15s 超时；正文最多 3 MB、最多 2 万字。

装完之后她的提示词里会出现：

    已装上的模组（能用）
    - 上网（上网桥）：已装上、正开着；能调的工具：web_fetch、web_search

已知坑：
- 系统 Python 没有 CA 包 → 模组自带 certs\cacert.pem，ssl.create_default_context(cafile=...)；
- start.cmd 必须 **CRLF + 纯 ASCII**（cmd 按 ANSI 读中文会拆行）；
- 模组目录里别留 __pycache__，打包前删掉；
- 端口别写死：外壳启用时可能换成池端口（见「端口：必须听 `BAB_MODULE_PORT`」），manifest 里的 40730 只是手动跑的默认值；`connection.json` 的 `provides.status` 里那个 URL 同理，内核不读它，别拿它当"当前端口"。

## 工具调用：从「写得出来」到「调得动」

模组只在 `connection.json` 里声明，内核侧就自动能调 —— 不需要给内核改代码。

### 三条约定

1. **命名**：`provides.tools` 里的名字，最后一段要等于某个 `endpoints[].name`。
   `web_fetch` → `fetch`，`web_search` → `search`。
2. **地址**：取模组 `module.json` 的 `ports[0]`，`http://127.0.0.1:<port><endpoint.path>`。
3. **参数**：`endpoints[].body` 当示例写进提示词；实际上她传什么就发什么（必须是对象）。

### 她怎么调

提示词里会出现这么一段（只在真有工具时）：

    # 怎么调工具
    要查东西/读网页时，单独回一行：
        [工具]{"name":"web_fetch","args":{"url":"https://example.com","max_chars":4000}}
    拿到结果后你再用自己的语气说一句。
    能用的：
    - web_fetch（上网桥）：参数示例 {"url": "...", "max_chars": 4000}

内核（`entity/core/tool_bus.py`）取出这一行 → POST 到模组 → 结果截断 3500 字 → 作为新一轮输入还给她 → **最多 2 轮**，第 3 次调用会被丢掉并把文字剥掉返回，避免死循环。

### 排查

    curl http://127.0.0.1:40720/tools          # 现在能调的工具
    Get-Content WiseEntity\runtime\logs\entity_core.log -Tail 30 | Select-String tool

日志里会出现 `[tool] 调用 web_fetch args=...` 和 `[tool] web_fetch ok 1029ms`；失败是 `[tool] web_fetch failed: ...`，她会照实说没查到。

模组管理页每张卡上还有两个按钮：

- **看日志**：弹一个窗口，里面是这张卡的状态 / 端口 / pid / 错误，保姆记的最近 8 条
  `module_events.jsonl`，再加上模组自己 `logs\server.log` 的最后 40 KB（刷新按钮会重新读）。
  模组起不来、`/health` 不通，先看这里——通常 `ImportError` 或端口被占会写在里面。
- **重启**：先 `disable` 再 `enable`（不是简单地再点一次启动）。改完 `start.cmd`、改完
  `settings.schema.json`、或者模组卡在 `broken` 时用它，比卸载重装省事，记忆和设置都留着。

### 加一个新工具（以「下载图片」为例）

1. 模组里加 `POST /image`，`connection.json` 的 `provides.tools` 加 `web_image`；
2. `endpoints` 加 `{"name":"image","method":"POST","path":"/image","body":{...}}`；
3. 重启模组（禁用→启用），内地核 5 秒内自动看到，`/tools` 里就有它了。

## 工具声明：推荐写成对象

字符串写法只能表达「名字」，模型看不出这个工具干嘛、要什么参数。新模组请用对象写法（内核两种都认，老的不用改）：

```json
"provides": {
  "tools": [
    {
      "name": "web_fetch",
      "endpoint": "fetch",
      "desc": "读一个网页，返回标题、摘要和正文纯文本（只读）",
      "args": {"url": "string，必填，http/https", "max_chars": "int，可选，默认 4000"},
      "max_seconds": 45
    }
  ]
}
```

- `endpoint` 可省：省了按「名字最后一段」去找（`web_fetch` → `fetch`），跟老规则一致；
- `desc` 会原样进提示词，写人话，别写「TODO」；
- `args` 只用于描述（不校验），但写清楚了模型就不容易传错；
- `max_seconds` 是这次调用的超时上限，默认 45 秒；慢接口（比如整页抓取+翻译）自己调大。

这样写出来，提示词里是：

    - web_fetch（上网桥）：读一个网页，返回标题、摘要和正文纯文本（只读）；url=string，必填…；max_chars=int，可选…

## 上网桥 0.2.1 的取舍（作为参考）

- 搜索摘要经常是空的（Bing 对中文查询尤其如此），所以 `web_search` 支持 `read_first`：顺手读一页；
- 摘要全空时模组会**自动**读前三条里最相关的一页（按查询词命中数打分），命中 0 个就放弃，并回一句 `hint` 让她自己用 `web_fetch` 挑 —— 别让她反问主人「读哪个」；
- 自动读的目的只有一个：**一次调用就能答出具体数字**（气温、价格、比分），少一轮来回。

## 清单里的作者与来源字段

`module.json` 支持两个可选字段，会直接显示在「模组管理」的卡片上：

```json
{
  "id": "web_bridge",
  "name": "上网桥",
  "version": "0.2.2",
  "author": "小琛项目",
  "homepage": "https://example.com/bab/web-bridge"
}
```

- `author`（也认旧名 `developer`）：卡片第二行显示「开发者：xxx」；不写就显示「未标注」。
- `homepage`：有值才在卡片上追加一行链接文本。
- 版本号必须和 `server.py` 自己报的一致。推荐在服务里这样取，别硬编码：

```python
def _detect_version() -> str:
    try:
        m = os.path.join(os.path.dirname(os.path.abspath(__file__)), "module.json")
        return str(json.loads(open(m, encoding="utf-8-sig").read()).get("version") or "0")
    except Exception:
        return "0"
```

## 开关状态会进提示词

模组被启用/停用时，外壳会往 `WiseEntity/entity/state/module_events.jsonl` 追加一行：

```json
{"ts": "2026-10-30T03:23:07", "id": "web_bridge", "name": "上网桥", "state": "enabled"}
```

内核拼提示词时取最近两条（24 小时内），写成「主人把「上网桥」关了，现在用不了」，并附一句软约束：**以这份清单为准，别嘴硬**。这样她不会在模组被关掉之后继续声称「还能用」。连续重复的同状态会被去重。

## 自检、错误码、日志（M 0.1.3 起，写别的模组也照这个来）

- **给自己一个自检工具**：M 的 `m_doctor`（`GET /doctor`）一条条回报 token、桥、关键能力、日志大小，最后给一句 `verdict`。模组出问题时，模型调一次就知道该换什么办法，不用让使用者翻日志。
- **错误信封**：失败时除了 `error`（给人看的一句话），再带 `code`（`no_token` / `denied` / `bad_args` / `no_core` / `bridge_<状态码>` / `internal`）和 `hint`。`code` 给程序分支，`hint` 给模型换招。
- **本地回环别走系统代理**：模组调 BAB 一律 `build_opener(ProxyHandler({}))`。Windows 上每次 `urlopen` 会读注册表里的代理设置，慢的时候白等两秒，代理连不上还会把本地调用判成失败。
- **日志自己管**：`logs/server.log` 超过 2 MB 时，下次启动轮转成 `server.log.1`（只留一代）；`/health` 带上 `log_bytes`，模组页的「看日志」一眼能看出是不是在猛刷错误。
