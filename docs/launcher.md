# 启动器（壳）

壳只做三件事：**看**（状态、日志）、**说**（聊天）、**管**（模组装卸）。
她不在这里——她住在本体 `WiseEntity\`；壳停了，她还在。

- 位置：`D:\BetterAIBridge`（刻意放在 `WiseEntity` 之外：壳只读本体）
- 启动：双击 `start.cmd`，或
  ```powershell
  .\.venv\Scripts\pythonw.exe main.py
  ```
- 不注册开机自启（脚手架默认不动用户的系统设置）

## 第一次启动

没有 API Key / 人格还是占位符时，壳会弹**四步建档向导**（`app\ui\dialogs\onboarding.py`）：

| 步骤 | 收什么 | 干什么 |
|---|---|---|
| 1 | 你的昵称、API Key、API 地址、模型 | **现场验一次**（`GET /models`，失败再试一次最小对话）；通过才允许下一步，并把 key 先写进 `entity\config\llm.json` |
| 2 | 她的名字、性别（女/男/无性别/不设定）、自称 | 性别只影响代词和一句硬规则，不做声线 |
| 3 | 她怎么称呼你 | 可点「让保姆想」→ 内核 `/nanny/analyze`（kind=title）给 4 个候选 |
| 4 | 初始性格（傲娇/温柔/理性/跳脱 + 自定义） | 点「让保姆整理」→ `/nanny/analyze`（kind=persona）写出人格草稿与开场白，预览后**一次性原子写入** `persona.md` |

要点：

- 中途退出不会留下半个人格；人格只在第 4 步的「完成」那一下写盘。
- 写入后壳会顺手 `POST /setup`（内核不在线也没关系，下次启动读文件）。
- 人格模板里所有 `{{NAME}}/{{TITLE}}/{{SELF}}/{{FLAVOR}}` 都会填掉；`is_configured()` 只认"没有占位符"。

命令行等价：

```powershell
curl -s http://127.0.0.1:40720/health          # configured=false 表示还没配
curl -s -X POST http://127.0.0.1:40720/setup -H "Content-Type: application/json" `
  -d '{"api_key":"sk-...","entity_name":"小蓝"}'
```

## 保姆（nanny）

内核里的 `entity\core\nanny.py`，壳关着也在跑：

- **开局分析**：`POST /nanny/analyze {"kind":"title|persona","payload":{…}}`，只输出称呼候选 / 人格草稿与开场白。
- **驻守**：每 60 秒读 `program_bundle\registry.json` 里"已启用"的模组，按它们声明的 `ports` 做 TCP 探测；连续两次不通 → 该模组标 `degraded` 并写日志（**不自动重启**：重启由壳的模组页做，内核只报告事实，避免两边抢着拉进程）。
- 状态：`GET /nanny/status` → `{ok,last_check,checks,modules[],degraded[]}`；状态落在 `entity\state\nanny.json`。

## 教程

第一次进聊天页弹一次欢迎（`app\ui\dialogs\tutorial.py`）：

- **跳过教程** → 永久不再弹；
- **开始教程** → 先记成 `deferred`（`entity\state\tutorial.json`），等你聊过 6 轮、或她第一次主动开口，再用三条轻气泡讲完（不挡聊天），讲完标 `done`。

接口：`GET /tutorial`、`POST /tutorial {"action":"skip|start|finish|reset","turn":N}`。

## 窗口

- **无边框**：没有系统的 最小化 / 最大化 / 关闭；标题栏自绘（`app\ui\widgets\titlebar.py`，按住可拖）
- 右上角两个内部按钮：`—` 收进任务栏、`×` 收进托盘（不退出）
- 底部状态行：`内核 在线 · 语音 在线 · 模组 N 运行 / M 已装`

## 关闭 = 留在后台

- 点 `×`：窗口隐藏，进程继续跑，托盘留一个图标
- 同时把「您的状态」改成 **忙碌**（她知道这时候别主动找你）
- 托盘菜单：打开 / 我现在忙碌 / 退出程序；双击托盘 = 打开

## 页面

| 页 | 内容 |
|---|---|
| **聊天**（首页） | 你跟她说话；每 5 秒拉一次 `GET /chat/feed`，所以能看到她**主动找你**的话（气泡标「她主动找你」） |
| 模组管理 | 已装模组一横排：状态、启用/停用、模组设置、完全卸载；顶部【外部导入 .pbab】 |
| 服务 | 内核 40720 / 语音 40715 的在线状态与启停、打开模组目录 |
| 日志 | `WiseEntity\runtime\logs` 的尾巴 |
| 设置 | 路径清单 + 查看详情 |
| 查看详情 | 门状态、12 情绪档位、肚子、记忆条数、脑龄、现在想干什么（只在设置里进，不在导航） |

## 「您的状态」

- 聊天页右上角 `【在线】【忙碌】`，互斥高亮
- 打开窗口 → 在线；关窗到托盘 → 忙碌
- 她那边（内核 `presence.fragment()`）会读到：在线=可以自然找你；忙碌=别主动找你、回话短
- 状态文件：`WiseEntity\entity\state\presence.json`

## 她主动说话

- 内核 `entity\core\proactive.py`：presence 在线 + 冷却 45 分钟已过 + 今天没超过 3 条 + 驱动够急时，她自己说一句
- 壳只负责显示（`feed` 里 `proactive: true` 的轮次）
- 手动验证：`curl -X POST "http://127.0.0.1:40720/proactive/send?force=1"`

## 自检

不弹窗口，CI 里也能跑：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe tools\smoke.py     # 页面全建出来 + 模组页渲染 + 配置状态
```

预期输出 `pages=[...] / nav=[...] / mods_cards=N / configured=False (...) / PASS`。

## 端口

| 端口 | 谁 |
|---|---|
| 40720 | 内核 `entity_core`（FastAPI） |
| 40715 | 语音 ASR |

改端口要同时改 `config\app.yaml` 的 `ports` 与 `WiseEntity\entity\core\settings.py` 的 `PORT`。

## 已知待办

- 打包成 exe（PyInstaller）还没做，目前是“绿色目录 + venv”
- 托盘图标与窗口图标现在是代码画的，想换直接替换 `assets\xiaochen.ico`
- 模组页的「外部导入目录」只支持 .pbab 文件与已解包目录，暂不支持从 URL 装
