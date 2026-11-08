# BetterAIBridge（BAB）

本地优先的桌面 AI 陪伴运行时：壳（PySide6）+ 内核（FastAPI）两个进程。
人格、记忆、13 维情绪、自我叙事、耳目、模组都在本机；聊天内容只发给用户选择的模型服务商。

**当前版本：0.6.4（2026-11-08）**

## 现在是什么状态

- 有安装包：`BetterAIBridge-Setup-0.6.4.exe`（IExpress 自解压，安装目录默认在 `%LOCALAPPDATA%`）。
- 有源码运行：`setup.cmd` 建壳/内核/语音三个 venv，`start.cmd` 启动。
- 自检 **74 套**，全量约 156 秒；`build.ps1` 出包前会先跑一遍。
- 安装目录内的 `WiseEntity/entity/` 是她的数据：人格、记忆、情绪、自我、状态；卸载时默认保留。
- 不是“另一个聊天壳”：壳只负责窗口和桥，内核负责她是谁、记得什么、现在什么情绪。

## 0.6.2–0.6.4 这一版

- 0.6.2：自动更新改成独立助手——启动器退出后由 `pythonw.exe -I` 起 helper，先停进程、备份、安全解压，再用 `wscript.exe` 拉起来，失败回滚；更新对话框等到 helper 就绪才退出。安装器默认目录带版本名，快捷方式统一叫 `BetterAIBridge.lnk`。0.6.0/0.6.1 的旧更新脚本可能没执行过，这两版请手动装 0.6.2 或更新。
- 0.6.3：安装器迁移旧快捷方式——旧入口指向的版本还在，就保留成带版本号的 `BetterAIBridge <版本>.lnk`；同一目录覆盖安装不重复迁移。
- 0.6.4：当前版入口固定叫 `BetterAIBridgeLauncher.lnk`，旧版本入口叫 `BetterAIBridgeLauncher <版本>.lnk`；自动更新只换代码不动快捷方式，启动器首次启动会一次性把旧的 `BetterAIBridge.lnk` 迁成新名字。
- 0.6.3→0.6.4 的自动更新在本机实测通过：启动器退出、备份、覆盖、自动重开；`logs/update.log` 记 `update ok`。

## 0.6.1 这一版

- 理智值重做：不再一路涨；每个人格有基线，向基线回落；-70 以下/+70 以上很难到达，越接近两端越慢；旧存档里 70 以上的怪值导入时压回 55。

- 检查更新：设置页会读 GitHub 的最新 Release；有新版本时显示版本号和说明，确认后下载 update.zip，校验大小与 SHA-256，退出启动器，由独立脚本备份代码、覆盖程序文件、自动重开；`WiseEntity/entity/` 的用户数据不动。
- 没有新版本时只提示“当前已是最新版”；Release 里没有 `update.json` 时提示去 Release 页手动下载安装，不会假装能更新。
- 模组市场按钮打开 GitHub Pages 的模组页，不再指向空的下载地址。
- 更新包只覆盖程序文件，不包含 `config/`、`memory/`、`state/`、`self/`、`persona/`、`program_bundle/`、`local_tts/`；解压前会拒绝越界路径和符号链接。

## 0.5.9 这一版

- 记忆全读：owner 会话会合并同门与 `external` 记忆（QQ/B 站等），保留来源标签；群聊/好友仍只看自己那本，不会串味。
- 站点改成 0.5.9，文案更像分享而不是产品说明；默认头像换成像素图，立绘桥不再发布。
- 其余功能与 0.5.7 相同。

## 0.5.7 这一版

- 异常处理收口：静默宽泛捕获 101 → 0，`main.py` 的 7 处静默全去；宽泛捕获 307 → 247，全部有日志/回退/状态上报；新增 `exception_policy` 防回流测试。
- 模组设置保存失败不再假装成功；本地语音、耳目、桥权限、托盘、退出清理失败都会留下日志。
- 其余功能与 0.5.6 相同：Authenticode 修复、官方安装包依赖、内核 token、自我系统、可选本地 MOSS。

## 0.5.6 这一版

- 官方安装包依赖：依赖卡可以下载官方安装包、校验发布者签名、让用户自己运行安装；不静默、不代勾协议、不把第三方安装包打进 Setup。
- 修了 Authenticode 校验：改用 `-EncodedCommand`，支持路径里的空格/引号，`Valid` 不再被当成空状态；新增 `signature` 自检。
- 启动器：懒加载、隐藏即停轮询、窗口位置恢复、托盘兜底、线程池与桥权限去重；空闲请求明显降下来。
- 内核：本机 token 鉴权；人格、记忆、13 维情绪、自我档案/证据/反思/尝试、耳目“一直看着/听着”都在。
- 语音：edge 仍是默认；本地 MOSS 是可选包（约 1.3GB），装好才可用，失败回退 edge。
- 模组：M 0.3.4 与 pre 0.2.4 单独发布，不随安装包捆绑；B 站已实测，QQ 已初步实测连通与记忆、长期稳定性观察中。
- 耳目模组已放弃；启动器内置耳目保留，和模组无关。


## 五分钟跑起来

### 用安装包

1. 双击 `BetterAIBridge-Setup-0.6.4.exe`，选安装位置。
2. 首次启动跟着向导填名字和 API Key；没有 Key 时向导不会跳过，因为没 Key 的智能体不能用。
3. 内核端口由安装器从 `40720` 起找空闲，语音从 `40715` 起找；实际值看安装目录的 `config/app.yaml`。
4. 数据、日志都在安装目录内；卸载时可选择是否保留 `WiseEntity/entity/`。

### 从源码

```powershell
# Python 3.12+；三个 venv 都装
.\setup.cmd

# 启动（会弹首次配置）
.\start.cmd
```

源码树的端口同样以 `config/app.yaml` 为准；开发机现在常见的是内核 `40740`、语音 `40715`，
但不要把它写死到脚本或文档里。

## 目录

```
BetterAIBridge/
  main.py                    启动器入口（PySide6）
  app/                       壳：窗口、页面、模组管理、配置、桥
  WiseEntity/entity/core/    内核：FastAPI（动态端口），人格/记忆/情绪/自我/大脑
  WiseEntity/entity/brain/   神经内核（2000 神经元、六递质、6×6 接线）
  WiseEntity/entity/self/    她自己写的档案、证据、叙事、账本、校准
  WiseEntity/entity/emotion/ 13 维情绪状态（内部 0~1000）
  WiseEntity/capability/     可选能力（语音 ASR、肚子=余额、视觉）
  program_bundle/            模组装卸目录（registry.json + plugins/）
  program_cache/             未装载的 .pbab 放这里
  packaging/                 出包脚本与 IExpress 资源
  examples/module_template/  模组骨架
  docs/                      结构、模组、桥、启动器说明
```

## 关键概念

- **人格**：`WiseEntity/entity/persona/persona.md`；首次向导写入。
- **记忆**：`WiseEntity/entity/memory/`，按会话/程序分抽屉；原文归档后再抽事实。
- **情绪**：13 维，内部统一 `0~1000`（`500` 中性）；详情页显示普通 `-10~100`、理智 `-100~100`。
  旧存档会按展示刻度反算迁移，用户看到的数值不变。
- **自我**：`entity/self/self.md` 是她自己写的；`evidence.jsonl` 记真实调用；`narrative.md` 是经历叙事；
  `ledger.md` 是关系账本；`calibrations.md` 是用户纠正。系统只提供证据和权限，不替她写。
- **耳目**：设置里的“允许对方主动偷看/偷听”，以及“一直看着/一直听着”；间隔和每次时长可调，
  越短越费模型和语音调用。
- **模组**：`.pbab`（zip）；普通模组 `program_<id>.pbab`；前置模组 `pre-program_<id>.pbab`，
  在普通模组之前启动，可做目录/代码/配置准备。

## 配置在哪

| 想改什么 | 改哪里 |
|---|---|
| 名字/人格 | `WiseEntity/entity/persona/persona.md` |
| Key / 模型 / API 地址 | `WiseEntity/entity/config/llm.json` |
| 端口 | `config/app.yaml`（壳）；安装器写入，不要手改安装脚本 |
| 她的记忆 | `WiseEntity/entity/memory/` |
| 情绪/自我 | `WiseEntity/entity/emotion/`、`entity/self/` |
| 耳目 | 启动器「设置 → 耳目」；落盘在 `entity/config/sense.json` |
| 本地语音包 | 启动器「设置 → 声音 → 本地 MOSS」；下载到安装目录 `local_tts/` |

## 本机鉴权

内核只监听 `127.0.0.1`，但本机其他程序也能访问这个地址，所以 0.4.59 起加了一层本机 token：

- 内核首次启动时生成 `WiseEntity/entity/state/core_token`；每个安装一份，安装包不带。
- 启动器自动读这个文件，并在每个请求上带 `X-BAB-Core-Token`。
- `/health` 保持公开，供启动器探活；`/bridge/*` 继续由模组自己的 `X-BAB-Token` 鉴权。
- 自己的脚本要直接调 `/state`、`/chat`、`/memory` 等，也要带这个 header；值从上面的文件读。
- 网页客厅 `http://127.0.0.1:<端口>/?token=<core_token>` 首次进入会换成 cookie，之后同源请求自动带。
- 它防的是“本机别的程序顺手调用”，不防同一用户下的恶意程序（对方仍可读 token 文件）。

## 自检与出包

```powershell
.\.venv\Scripts\python.exe tools\check.py          # 62 套全跑，出张表
.\.venv\Scripts\python.exe tools\check.py --list   # 有哪些
.\.venv\Scripts\python.exe tools\check.py --only memory,styles
```

`check.py` 会在壳 venv 与内核 venv 之间自动挑解释器；红了退出码 1。

出包（需要 Windows 的 IExpress）：

```powershell
powershell -NoProfile -File packaging\build.ps1 -Version 0.6.4
```

默认从仓库根读 `VERSION.txt`，产物写到仓库旁的 `dist/`；急着手动出包可加 `-SkipCheck`，
但正常流程不要跳过自检。`packaging/` 里带 `install.ps1`、`install.cmd`、`install.vbs` 和两个图标，
不再依赖 `C:\bab_pkg`。

## 模组

模组 = 一个 `.pbab` 文件（本质是 zip），里面：

```
module.json            清单：id/名字/版本/入口/端口/目录映射/记忆分片
introduce.md           介绍（装的时候显示给人看）
connection.json        它提供什么：工具名、人格片段、事件、状态
settings.schema.json   设置项（自动生成勾选框/下拉框/数字框）
payload/               自带文件（也可以 external 引用外部目录）
checksums.json         每个文件的 sha256
```

打包：`tools/pack_pbab.py`；装：壳的「模组管理 → 外部导入」。
命令行等价：`python -c "from app.core import pbab; pbab.install(r'x.pbab'); pbab.enable('x')"`。
详见 `docs/MODULES.md`，模板在 `examples/module_template/`。

## 文档

- `docs/STRUCTURE.md`：两个进程、内核盒子、数据流。
- `docs/MODULES.md`：模组契约、端口、健康检查、设置 schema。
- `docs/M-STRUCTURE.md`：给模组作者和给智能体看的两套结构。
- `docs/BRIDGE.md`：桥的 22 项能力、授权、审计。
- `docs/launcher.md`：窗口、托盘、保姆、教程。

## 历史版本

以下保留 0.1.x–0.3.x 的原始记录，方便查旧问题和旧端口行为；其中的端口/测试数量/情绪数量
以本页上面的“当前状态”为准。

## 0.1.1：换机器/换盘符为什么之前打不开，改了什么

0.1.0 的安装包装到**没有 D 盘**的机器上（用户报告：`C:\Users\...\AppData\Local\BetterAIBridge`）双击完全没反应，原因是三处叠加：

1. `main.py` 顶层 `from PySide6 ...`，依赖没装成 → `ModuleNotFoundError` → pythonw 无控制台 → **静默退出 1**
2. `setup.ps1` 只认清华源、不查退出码（镜像对 wheel 文件 403 时仍打印 done）
3. `config/app.yaml` 与 `app/core/config.py` 写死 `D:\BetterAIBridge\...` → 向导写 `llm.json` 时 `mkdir D:\...` 抛 `FileNotFoundError` → `main.py` 捕获后 `return 1`

对应改动（都在本仓库里，可直接复用）：

| 位置 | 改动 |
|---|---|
| `app/core/config.py` | 默认值全部由 `APP_DIR` 推导；`_sanitize()` 校验路径，不存在就回退；`logs_dir/modules_dir` 允许就地创建 |
| `main.py` | 依赖/界面导入失败 → `report_fatal()` 写 `logs/startup-error.log` + 弹 MessageBox + `exit 1`；建档异常也弹窗 |
| `setup.ps1` | 镜像按 阿里云 → 官方 → 清华 回退，`--timeout 15 --retries 1` 快速失败；每步查 `$LASTEXITCODE`；装完 `import` 自检才打印 OK |
| `launch.vbs` | `WScript.Shell.Run(..., 0, True)` 等待并取退出码，非 0 弹窗指向日志 |
| `config/app.yaml.template` | 路径写成 `{{APP_DIR}}`，由安装器替换 |
| 安装器 `install.ps1` | 解压后按实际目录生成 `config/app.yaml`；装依赖后再 `import PySide6 ...` 自检 |

**C-only 机器复验（0.1.1，2026-10-29）**：静默装到 `%LOCALAPPDATA%\BAB-011-final` → `config/app.yaml` 里全部是 `C:\...` → `setup.ps1` 装完 launcher+core 并自检通过（asr 用 `-SkipAsr` 跳过）→ `smoke.py` **PASS** → 用安装目录里的 core venv 起 `uvicorn core.app:app --port 40721`，`/health` = `ok:true, configured:false, brain_ready:true`，`/chat` **503**。随后把测试目录和桌面快捷方式恢复回 `D:\BetterAIBridge`。

## 0.1.2：地基与首屏（2026-10-29）

**P0 地基（都是会让她"看起来是坏的"的毛病）**

| 位置 | 改动 |
|---|---|
| `WiseEntity/entity/core/settings.py` | 整份重写：`APP_ROOT` 由安装位置推导（`BAB_ROOT` 可覆盖），`ROOT/BUNDLE/PROGRAM_CACHE` 全部相对；`ensure_dirs()` 失败只记日志不崩；新增 `entity_name()` |
| `program_bundle/registry.json` | 出厂即 `{"format":"bab-registry/1","updated":"","modules":{}}`；`registry_box.all_programs()` 兼容 dict/list；`nanny`、`modules_box` 统一成 dict → `GET /programs` 不再 500 |
| `llm_box.py` | 补 `registry_box` 的 import（"你能用的程序"恢复）；`build_system()` 进 `asyncio.to_thread`（不再阻塞事件循环）；`presence_penalty 0.3 / frequency_penalty 0.2` |
| `drives.py` + `app.py` | `act()/_compose_reach/_compose_seek/_deliver` 全改 async，删掉三处 `asyncio.run()`，tick 里 `await drives.act()` → 主动说话不再被吞 |
| `maintenance.py` | 游标改成"提炼成功才前进"，LLM 失败下轮重试，不再永久丢对话 |
| `memory_box.py` | `group/kind_key` 走 `_safe_id()`（`../../evil` → 400），路径穿越堵上 |
| `entity/brain/*` | 大脑状态落盘修好（`state_path` 初始化）；两套情绪合一：12 维 `emotion_core` 是唯一对外表达，`flybrain` 只做体内状态、不再进提示词 |

**P0.5 首屏与安装体验**

- 安装器单窗口：进度**百分比**、可**最小化**、装完**自动关闭**；依赖在隐藏进程里装（无 `System32` 黑窗），日志在 `%TEMP%\bab-deps.log`；SFX 由 `install.vbs` 启动，`install.cmd` 的控制台也没了。
- 重装/升级**保留** `entity\{memory,state,persona,config}`、`runtime\logs`、`program_cache` 和三个 venv，不再整目录清空。
- 桌面快捷方式直接指向安装目录的 `launch.vbs`（以前借 `wscript.exe` 当宿主，资源管理器里看着像装错了）。
- 建档向导：称呼页加**身份确认**勾选；性别/代词真的写进人格（`{{GENDER}}/{{PRONOUN}}`）；`{{FLAVOR}}` 也替换；窗口标题、侧栏、托盘、输入中提示全部用人格里的名字（不再写死「无名」）。
- 保姆报错翻成人话（10061/超时/401/429）；「忙绿」→「忙」。

**已验证（D 盘开发件 + 全新 C 盘安装）**

- 安装包：`D:\BAB-release\BetterAIBridge-Setup-0.1.2.exe`，368,640 B，sha256 `70582fdacb4097733c1712a01e4d90c02e18fd0815fba3f1e80ab4496830b765`。
- 静默装到全新 `C:\bab_test_*`：99 文件、`config/app.yaml` 全 `C:\` 路径；不含 `.joybak`、测试 wav、内部补丁脚本、密钥与 QQ 号。
- 安装器自测（自动点"开始安装"）：日志 `progress 6/18/24/96/100`，**4.6 秒**装完并自动关窗；开依赖那次 **3.2 分钟**，窗口列表里没有 cmd/powershell 控制台，`setup.ps1` 自检通过。
- 安装目录内核：`/health` 200、`/programs` 200（3 项）、`/state` 200、未配置 `/chat` **503**、`/memory/note` 带 `../../evil` **400**。
- 开发件 `tools/smoke.py` **PASS**。

**留给 0.2.0**：Key 加密（DPAPI）、本地路由 token、模组沙箱、pytest/CI、PyInstaller 瘦身（现在 610MB 主要是在安装时装 venv）。

## 现在的边界

- 只有「网页客厅」这一扇门（`http://127.0.0.1:40720/`），QQ / B 站 / 上网都在模组里，默认不装。
- 语音要自己装 ffmpeg 才能转写。
- 不要把它当生产服务：没有鉴权，只监听 127.0.0.1。

## 许可

自己玩没问题；要分发请确认依赖（PySide6 / FastAPI / DeepSeek API）各自的许可。

## 0.1.3 / 0.1.4：建档三条修复 + 打包去隐私（2026-10-29）

针对使用者反馈的三条：

1. **填了 API 还说没 Key**：向导第 1 步验证通过就落盘（新增
   `framework_setup.save_llm()`），保姆第 3/4 步立即可用；`nanny` 的错误里
   带上它实际读的 `llm.json` 路径。
2. **代词不跟性别**：`GENDERS` 四档统一为 他 / 她 / 它 / **祂**；确认句、
   人格正文、保姆提示词都按同一张表取词。
3. **关系只有「主人」**：新增 `RELATIONS`（主人/朋友/家人/恋人/搭档/老师），
   向导第 3 步可选可填，写进人格的「## 称呼」段，`save()` 存 `relation`。

配套的界面修正：聊天页去掉「先配置」，改成未配置时一条提示；设置页新增
「模型与 Key」卡片与「更改 API Key」（`KeyDialog`，验证通过才保存，不动人格）；
`/health` 现在带 `root/entity/llm/has_key`，聊天页用 `_check_core_root()` 检测
「壳和内核不是同一份安装」并提示。

打包侧：`build.ps1` 现在会剔除 `entity/config/llm.json`、
`entity/persona/persona.md`、`entity/persona/drift.json`，并写入空 Key +
`PLACEHOLDER` 人格，保证安装包里没有作者的个人数据；`payload.zip` 扫描
`sk-*` / QQ 号 / 昵称均为 0 命中。

已验证：代词四档、确认句四档、`save_llm` 落盘、保姆按关系出候选、设置页
掩码显示与改 Key、`0.1.4` 静默安装到 `C:\bab_test_014` 后
`framework_setup.is_configured()` 首次为 **False**（会弹向导）、向导写入后为
**True**、安装目录内核实测 `/health` 200 且 `/nanny/analyze` 返回候选。
## 0.1.5：两份安装不再抢内核端口（2026-10-29 22:50）

**现象**：机器上同时有两份 BAB（开发用的 D:\BetterAIBridge 和双击安装包生成的 D:\BAB测试）时，后装那份的壳连着 40720，而 40720 上是先装那份的内核 → 壳里提示「内核跑的是另一份」，Key 也读不到。

**根因**：端口写死在 settings.py（PORT = 40720）与 start-core.cmd、config/app.yaml 里。

**改法**：
- settings.py：PORT = int(os.environ.get("BAB_PORT") or 40720)；
- start-core.cmd：set BAB_PORT=40720，uvicorn 用 %BAB_PORT%；
- 内核启动写 entity\state\instance.json（root/port/pid/started），/health 增 port；
- 安装器 Initialize-Install：TcpListener 从 40720 / 40715 往上找空闲端口，写进 config\app.yaml，并替换 start-core.cmd / start-all.ps1 / stop-all.ps1 里的端口字面量；
- 模板端口改成 {{CORE_PORT}} / {{ASR_PORT}}。

**验证**：40720（开发）与 40721（D:\BAB测试）都占着时，装 0.1.5 到新目录得到 core: 40722 / asr: 40716，start-core.cmd 里 set BAB_PORT=40722；用该目录起内核后 /health = port:40722，instance.json 一致。
## 0.1.6：情绪用百分比 + 安装器收尾（2026-10-29 23:5x）

**情绪**：`app/ui/pages/details.py` 每条情绪标签从「几乎没有/有一点/明显/很强/到顶了」改为 `"{int(round(v * 100))}%"`；「现在最明显」那行也改百分比；颜色仍按 BANDS 分档。卡片标题改「情绪（12 种 · 实时强度）」。实测（offscreen + 假数据）：`joy 52% / calm 44% / confusion 86%`，摘要「现在最明显：困惑（86%）、快乐（52%）、平静（44%）」。

**安装包**：
- `build.ps1` 的占位 llm.json/persona.md 改为**从 UTF-8 模板文件复制**（`entity/config/llm.placeholder.json`、`entity/persona/persona.placeholder.md`），解决「PS 5.1 把无 BOM UTF-8 的构建脚本按 ANSI 读 → 占位文本双重乱码」；模板文件本身不进安装包。
- `build.ps1` 现在纯 ASCII（只剩一行中文注释也改成英文），避免同类解析问题。
- 0.1.6 产物：`D:\BAB-release\BetterAIBridge-Setup-0.1.6.exe` 376,832 B，sha256 `ceba2fa9…098d`，payload 99 文件。
- 静默装到新目录验证：`VERSION.txt`=0.1.6、占位 llm.json 的中文正常、无 `*.placeholder.*` 残留、`core: 40721 / asr: 40716`（40720 被开发内核占用时自动避让）、百分比代码已随包。

**清理**：`D:\BAB测试`（0.1.4 解包产物，609.8 MB / 12,551 文件）已删；删前把它的 persona/config/memory/state 备份到 `D:\存档\BAB测试-data-20261029-2325`（10 文件 / 15.8 KB）。
## 0.1.9：最小化后找不回来（2026-10-30）

现象：安装器点最小化以后，点任务栏那个位置没反应，窗口回不来。

原因：`install.vbs` 用 `sh.Run(cmd, 0, ...)`（隐藏窗口）启动 `powershell.exe`，
Windows 不会给这个进程里新建的窗口登记任务栏条目——任务栏上要么没有我们的按钮，
要么只有那个隐藏控制台的条目。点它自然不会恢复窗体。

修法（三处）：
1. `install.ps1` 在窗体 Shown 时调 `ITaskbarList::AddTab($form.Handle)`，显式登记任务栏条目。
2. 加托盘图标兜底：最小化时弹一次气泡，双击托盘图标（或右键"Show installer window"）就能回来。
3. `launch.vbs` 把 `sh.Run(cmdLine, 0, True)` 改成 `1`（pythonw 没有控制台，不会闪黑窗），
   程序主窗口也就能正常出现在任务栏里。

顺手：安装窗口与任务栏图标换成 `assets\bab.ico`（鲸鱼），和程序本体一致。

验证（本机，真实鼠标）：
- 最小化后任务栏出现按钮（标题显示 "Windows PowerShell"，因为宿主进程是 powershell.exe），点击即恢复；
- 托盘图标双击恢复；装完自动关闭；全程没有出现 cmd/powershell 黑窗；
- `parse errors = 0`，静默安装与带依赖安装均通过。

产物：`D:\BAB-release\BetterAIBridge-Setup-0.1.9.exe`（385,024 B）
sha256 `73b8d661a3b1030bdbcb2d995afd364249411eba6784b38929b99d98c5b863db`

## 0.1.10：不再要求用户去停别人的内核（2026-10-30）

上一版会在向导最后提示「40720 上跑的是另一份内核，先把它停掉」。那是把工程问题推给用户，
这一版改成程序自己解决。

**做法**：新增 `app/services/runtime.py`（内核托管）

- 端口上是我们自己的内核（`/health.root` 与本安装目录一致）→ 直接用；
- 端口上跑着**另一份**安装的内核 → 挑一个空闲端口，写回 `config/app.yaml` 与
  `WiseEntity\source_code\scripts\start-core.cmd`，然后自己拉起一份；
- 端口上什么都没有 → 直接拉起（`entity\.venv\Scripts\python.exe -m uvicorn core.app:app`，
  日志写 `logs\core-boot.log`）。

**接线**

- 启动时：`main.py` → 聊天页 `refresh_setup()` → `runtime.ensure_async()`，顶部提示跟着
  「正在启动这一份的内核…／内核没起来：…」走，不再有「先把它停掉」这种死路；
- 建档向导：第 3、4 步的保姆请求先 `runtime.ensure()` 再发（`_run_with_core`），
  收尾只落盘，不再阻塞；
- 安装器：`config\app.yaml.template` 的 `core_url` 改成 `{{CORE_PORT}}`，
  与 `ports.core` 用同一个随机空闲端口（此前两者会不一致——这就是"填了 Key 还 no api key"的根因之一）。

**验证**（框架内核占着 40720 的情况下）

- 新装到 `C:\bab_test_022`（自动拿到 40722）→ 冷启动 `main.py`：日志
  `已拉起内核 pid=35568 port=40722`，`/health` = `configured:true, root:C:\bab_test_022\WiseEntity`；
- 同机另一份内核仍在 40720 时，`runtime.ensure()` 返回
  `ok:true, how:started, port:40722`，`/nanny/analyze` 返回 `titles=['老板','先生','主人','杨智']`（不再 no api key）；
- `tools/smoke.py` PASS。

## 0.1.11：把「恐惧/害怕」拆出来（2026-10-30）

0.1.10 的 12 种情绪里没有单独的「恐惧」——定稿时把它和「焦虑」并成了同一行
（`("anxiety", "焦虑/恐惧")`）。结果是她遇到"眼前有威胁"和"心里没底"时反应一样：
只会追问确认，不会后退。

这一版把它拆成第 13 项：

| 项 | 值 |
|---|---|
| 键 | `fear`（显示名 **恐惧/害怕**，`anxiety` 改回 **焦虑/担心**） |
| 半衰期 | 12 分钟（比焦虑的 25 短，比惊讶的 2 长） |
| 表 | `entity/emotion/intensity_table.json` 增加一行 5 档文案 |
| 规则 | 「有血/刀/枪/尸体/杀人/吓死/好可怕」→ +0.40；「你敢/弄死你/报警抓你/别让我看见你」→ +0.34 |
| 事件 | `threat` +0.40（附带焦虑 +0.15）、`horror` +0.30 |
| 抑制 | 平静压恐惧 0.30、爱压恐惧 0.15 |
| 闸门 | `fear ≥ 0.70` → 躲藏 ×1.6、主动 ×0.4、寻求 ×0.7（怕了先退，不逞强） |
| 行为 | 提示词里给「先退半步、想确认对方安不安全；别说狠话，也别逞强」 |

验证（`entity/.venv`，离线、测完还原状态）：
- 13 个键，`fear` 半衰期 12；
- 「我刚才看见地上有血，好可怕」→ `fear=0.400`，`anxiety=0.000`（不再混在一起）；
- `stimulus("threat")` → 0.400；
- 强制 `fear=0.95` → 档位 4、闸门 `{reach:0.4, hide:1.6, seek:0.7}`、提示词出现「恐惧/害怕（到顶了）：极度惊恐，被吓到说不出话」；
- 服务端 `/emotions` 返回 13 个标签，状态页标题改为「情绪（13 种 · 实时强度）」；
- `tools/smoke.py` PASS。

安装包：`BetterAIBridge-Setup-0.1.11.exe`（389,120 B，
sha256 `045915991fe720319d9f7b93f3d312d235205937a30f2fc35a5c9862b67e7d68`）。
payload 里已确认含 `fear` 与改名的 `焦虑/担心`。

## 0.1.12：目录与启动器带版本号，安装窗口去掉最小化（2026-10-30）

两件事：

1. **命名规则**：装到哪、叫什么都跟着版本号走，避免多份安装分不清。
   - 默认安装目录：`D:\BetterAIBridge <版本>`（没 D 盘时 `%LOCALAPPDATA%\BetterAIBridge <版本>`）
   - 启动器：`BetterAIBridgeLauncher <版本>.vbs`（安装时由 `launch.vbs` 改名，`start.cmd` 同步改指向）
   - 桌面快捷方式：`BetterAIBridgeLauncher <版本>.lnk` → 指向上面那个启动器
   - 安装窗口标题：`BetterAIBridge <版本> 安装程序`
2. **去掉最小化**：这个窗口是从隐藏控制台里长出来的，最小化后任务栏那一格归隐藏控制台，点它唤不回
   （0.1.9 只能靠托盘图标救回来，而托盘图标本来就不该是正常路径）。这一版直接 `MinimizeBox = $false`，
   托盘代码整段删掉；窗口边框不动，标题栏照样能拖。

验证（0.1.12 安装包，`D:\BetterAIBridge 0.1.12`）：
- `VERSION.txt` = `BetterAIBridge 0.1.12`；
- 目录里是 `BetterAIBridgeLauncher 0.1.12.vbs`，旧 `launch.vbs` 已不在；`start.cmd` 里指向新名；
- 桌面快捷方式 `BetterAIBridgeLauncher 0.1.12.lnk`，目标 `D:\BetterAIBridge 0.1.12\BetterAIBridgeLauncher 0.1.12.vbs`，图标用 `assets\bab.ico`；
- 窗口样式实测 `WS_MINIMIZEBOX` 不在（`style=0x16C80000`），标题栏还在；
- 依赖安装（阿里云，约 1 分钟）→ `install ok` → 自动启动；
- payload 隐私扫描（Key/QQ/昵称）0 命中。

安装包：`BetterAIBridge-Setup-0.1.12.exe`（389,120 B，
sha256 `59156506e627c0df386709ef9658a4217db53dcefe4abb796768101f62a71cce`）。


## 0.1.13：模组的工具真的能调了（2026-10-30）

上一版只是把「能调的工具」写进提示词，实际上没有调用通道。这一版补上了：

| 位置 | 做了什么 |
|---|---|
| `WiseEntity/entity/core/tool_bus.py` | 从已启用模组的 `connection.json` 推出可调工具（`tools` 名字末段对齐 `endpoints[].name`，地址取 `ports[0]`） |
| `llm_box.py` | 她会单独回一行 `[工具]{"name":...,"args":{...}}`；内核取走 → POST 模组 → 结果塞回一轮 → 她用人话回；最多 2 轮 |
| `app.py` | 新增 `GET /tools`，返回现在能调的工具与地址 |
| `build.ps1` | payload 不再带作者已装的模组目录与带绝对路径的 `registry.json`；新装默认 `{"modules":{}}` |

实测：

    GET /tools  -> {"count":2,"tools":{"web_fetch":{...40730/fetch},"web_search":{...40730/search}}}
    让她读 https://example.com
      日志: [tool] 调用 web_fetch args={'url': 'https://example.com', ...}
            [tool] web_fetch ok 1029ms
      回复: 那页就一句话的意思：这域名是拿来做文档示例用的，不需要授权。

安装包：`BetterAIBridge-Setup-0.1.13.exe`（397,312 B，sha256 `fcae0adf…526ad`）。

## 0.1.14：工具可以自己写清楚了（2026-10-30）

### 改了什么

- `entity/core/tool_bus.py` 支持**对象写法**声明工具：

  ```json
  {"name":"web_fetch","endpoint":"fetch","desc":"读一个网页…","args":{"url":"string，必填"},"max_seconds":45}
  ```

  旧的字符串写法继续有效（按名字最后一段匹配 endpoint），老模组不用改。
- 每个工具可以有自己的 `max_seconds`（默认 45 秒），不再一律 45。
- `describe()` 会把 `desc` 和 `args` 直接写进提示词，模型不用猜参数。

### 顺手修掉的

- 打包时把 `program_bundle\plugins`（空目录占位）也排除了，payload 不再带无意义目录；
- 安装器版本号与启动器名对齐（`BetterAIBridgeLauncher 0.1.14.vbs`）。

### 已验证

- payload 101 文件 / 205,639 B，隐私扫描 0 命中，`registry.json` 出厂为空；
- 静默装 `D:\BAB 0.1.14测试版` → `VERSION.txt`=0.1.14、启动器名正确、`start.cmd` 指向它、端口自动 `core=40721 / asr=40716`、102 文件 / 470,993 B；
- 开发树实测对象写法：`GET /tools` 能列出 `web_fetch`/`web_search`，提示词里带中文描述与参数提示。

### 装机包

`D:\BAB-release\BetterAIBridge-Setup-0.1.14.exe` 397,312 B，
sha256 `3a581c643eede13c645ff79c426e9081325d7deddac01c72242511c6e920a54e`

## 0.1.15：模组卡片有作者和版本，开关状态会进提示词（2026-10-30）

起因是两件事：① 用户停用「上网桥」之后，她仍然回「能，一直通着」；② 模组卡片上只有名字和状态，看不出是谁写的、哪一版。

**一、提示词跟着开关走**
- 外壳在启用/停用时写 `WiseEntity/entity/state/module_events.jsonl`（`{ts,id,name,state}`，连续同状态去重）。
- 内核 `llm_box.tools_text()` 取最近两条（24 小时内），拼成「主人把「上网桥」关了，现在用不了」，并加一段软约束：

```
# 以这份清单为准
- 上面是此刻的状态。清单上没有的东西，就是这会儿用不了；
- 你之前说过「能」，而现在没列出来，那就是刚被关了，照实改口一句就行，别嘴硬。
```

- 只加约束、不硬改她的输出：用户明确说过「对方会不会撒谎就不管了」。

**二、模组卡片**
- `module.json` 新增可选字段 `author`（兼容旧名 `developer`）与 `homepage`，安装时写进注册表。
- 卡片顶部显示蓝色版本徽标 `v0.2.2`，第二行是「开发者：小琛项目 · bridge · api 1」；没写作者显示「未标注」。
- 上网桥升到 0.2.2：`server.py` 改为从同目录 `module.json` 读版本，不再硬编码，避免「清单 0.2.2 / 健康检查 0.2.1」。

**实测**
- 同一份提示词在三种状态下渲染正确：启用 → 工具清单 + 「最近的变化：打开了」；停用 → 「装了但没开」+ 「以这份清单为准」+ 「主人把「上网桥」关了」；再启用 → 恢复清单。
- 模组页离屏渲染确认：卡片显示 `上网桥 v0.2.2`、`开发者：小琛项目 · bridge · api 1`、状态「运行中」。

## 0.1.16：情绪按 6 基础 / 6 复合 / 平静摆，性格决定起始值和涨落（2026-10-30）

起因：主人发来一份情绪分类稿——6 种基础（快乐/悲伤/愤怒/恐惧/厌恶/惊讶）、6 种复合（爱意/自豪/焦虑/羞耻/嫉妒/困惑），平静不是情绪而是基线。要求界面照这个分栏，并且「性格配好、第一段对话之后」它们就开始变，不同性格对应不同的变化。

**一、视图（详情页）**
- 左栏「基础（天生）」：快乐、悲伤、愤怒、恐惧、厌恶、惊讶。
- 右栏「复合（叠加出来）」：爱意、自豪、焦虑、羞耻、嫉妒、困惑。
- 底部一行通栏「平静」，单独一条。
- 没配人格、没说过话时：全 0%，卡片写「还没开始——人格配好、说第一句话之后，这三栏才开始动」。

**二、量程改成点（−10 ~ 100）**
- 内部值从 0~1 的比例改成「点」，0 = 中性，负值 = 沉到基线以下，上限 100。
- 规则/刺激里的 delta 仍是 0~1 的比例，落库时乘 100；阈值跟着改成 20/45/70/90 点。
- 负数在界面上照实显示（例如平静 −4%），条子用灰蓝色。

**三、性格 → 起始值与敏感度**
- 内核读 `entity/config/emotion_profile.json`（不存在就按默认写一份）。
- 结构：`styles.<性格>.delta`（涨得多快）、`styles.<性格>.half_life`（退得多慢）、`seeds.<性格>`（开局起始值）。
- 四套默认：

| 性格 | 起始值高点 | 涨得凶 | 退得慢 |
|---|---|---|---|
| 傲娇 | 爱意 18、自豪 20、快乐 14 | 愤怒 ×1.3、自豪 ×1.25、爱意 ×1.1 | 愤怒（半衰期 ×0.8） |
| 温柔 | 平静 22、爱意 24、快乐 10 | 平静 ×1.3、爱意 ×1.2 | 悲伤 ×1.2 |
| 理性 | 平静 18、自豪 12、困惑 8 | 困惑 ×1.2、自豪 ×1.05 | 平静 ×1.2 |
| 跳脱 | 快乐 22、爱意 14、惊讶 12 | 惊讶 ×1.35、快乐 ×1.2 | 惊讶半衰期 ×0.5（来得快去得快） |

- 起始值允许负值（傲娇的恐惧 −3、理性的恐惧 −5、温柔的愤怒 −4 等），下限 −10。

**四、什么时候开始动**
- `note_message / appraise / stimulus` 第一次被调用时执行 `start()`：按性格落起始值、记 `started=true`、`seed_style`，日志打一行 `[emotion] 开局（傲娇）：…`。
- 之后每次消息照旧走规则层 + LLM 细评，随时间按半衰期回落。

**实测**
- 四种性格的 seed 全部落在 −10~100 内，切换性格重新开局值不同。
- `appraise("我刚才看见地上有血，好可怕")` → 恐惧 +32 点（傲娇 ×0.8 后的 40×0.8），`stimulus("threat")` → 恐惧 +32、焦虑 +15。
- 恐惧 76 点时 `gates()` = `reach 0.4 / hide 1.6 / seek 0.7`，`prompt_block()` 出「恐惧/害怕（很强）：强烈恐惧，僵住/想逃」+ 行为提示。
- `/emotions` 返回 `types / order / range / started / style`；界面三栏渲染见 `logs\emo_3col.png`。

## 0.1.17：换成真图标（2026-10-30）

主人给了两张白鲸图：一张带牛皮纸（给安装程序），一张干净的蓝底（给程序本体）。这版把它们做成了多尺寸图标，替掉之前那个用代码画的蓝底白点。

- `assets/bab.ico`：程序图标，16/32/48/256 四个尺寸；窗口、托盘、桌面快捷方式、任务栏都用它。
- `assets/bab-setup.ico`：安装程序图标，同样四个尺寸；安装窗口标题栏和任务栏用它。
- `assets/bab-40.png` / `bab-64.png`：侧栏头像（36px）和标题栏小图标（18px）。
- 来源是降过像素的 512 母版：`assets/_src/app-512.png`、`setup-512.png`（约 570 KB，不进安装包）。
- 要改图标：改母版（或者拿 Aseprite 画一版）→ 运行 `python tools/make_icons.py`，四个文件一起重生成。

**顺手修的**
- 安装窗口之前没有图标，任务栏显示成一张白纸；现在 `$form.Icon` 读 `bab-setup.ico`。
- 0.1.12 去掉最小化按钮后，状态栏还写着「安装中窗口可以最小化」，改成「别关窗口，进度会自己走完」。
- 之前 icon 文件 6 KB（代码画的），现在 74 KB / 101 KB——因为含 256 像素帧，属于正常体积。

## 0.1.18：模组清单补上作者与来源（2026-10-30）

第一批第三方模组要按同一套字段写，所以这版把「作者」正式写进模板和文档。

- `examples/module_template/module.json` 增加 `author`、`homepage`，新模组从模板起步就带这两项。
- `docs/MODULES.md`：
  - 清单示例里补 `author` / `homepage`；
  - 字段说明加两条：`author` 也认旧名 `developer`，不写显示「未标注」；`homepage` 可选，卡片会附出来；
  - 模组市场的 `index.json` 示例也带 `author`；
  - 新增一节「作者、版本与『能被谁找到』」，把 id/name/version/author/homepage 一次写全的要求讲清楚。
- `tools/pack_pbab.py`：打包时发现清单没写 `author`，会打一行提示（不拦打包）。
- 图标母版改成 512 px 放在 `assets/_src/`（约 570 KB，不进包），新增 `tools/make_icons.py` 一键从母版重生成 ico 与两张小图。原图不用留，降像素足够。

实测：模板 `pbab.validate()` 通过、`pack_pbab.py` 打出 2,636 字节 / 7 文件；0.1.18 payload 106 文件里模板带 `author=你的名字`，`_src` 没有被打进去，隐私扫描 0 命中。

## 0.1.19：四个小问题（2026-10-30）

主人早上给了四张截图，逐条修好：

1. **向导确认句方向反了**：原来「她是「小测」，是你的主人」——把关系说反了，关系和称呼相同时也重复。改成「她是「小测」，你是她的主人。」并把确认块挪到页面底部。
2. **「网页客厅」是内部黑话**：提示词里三处改成「对话窗口」。顺手修了模组工具在提示词里是 Python 字典原文的问题，现在是「web_fetch（读一个网页…）」。
3. **侧栏名字被截断**：168 → 196 宽，头像 36 → 32。
4. **情绪两栏标题分太开**：右标题缩成「复合（叠加）」。

验证：装好的 0.1.19 里逐条比对通过；隐私扫描 0 命中。

## 0.1.20：BAB 不再"知道"任何模组（2026-10-30）

主人问了句很要命的话：新装的 BAB 一个模组都没有，她怎么张口就说得出 QQ、B 站？

先说查到的两件事：

1. **安装包里的注册表是空的**。`build.ps1` 打包含写过干净的 `registry.json`，0.1.20 的 payload 里也是 `{"format":"bab-registry/1","updated":"","modules":{}}`。
2. **但代码里有"名字"**：`llm_box.py` 里有一张 `BADGE = {"qq_bridge": "QQ", "bili_bridge": "B 站", "web_bridge": "上网"}`，服务页还写死一行"QQ / B站 是模组，卸在 E:\program_cache"。注册表空着，这些名字照样在提示词和界面里。这才是"墙还没装，人先知道墙后有风景"。

所以这版把"名字"从 BAB 里清出去，并让保姆来记备案：

- `llm_box.py`：删掉 `BADGE`，模组显示名一律用模组自己在 `module.json` 里写的 `name`；没有模组时提示词里不会出现任何具体名字。
- `services.py`：那行写死的话改成"现在只装内核与语音；模组在 program_cache 里，装了才有。"，顺带去掉了写死的 `E:\program_cache`。
- `probe.py`：不再探测 `qq_bridge` / `bili_bridge` 装没装。
- **保姆接管注册表**：内核新增 `POST /modules/register`、`POST /modules/unregister`（`nanny.register_module` / `unregister_module`），由保姆写 `entity/registry/programs.json`；壳子的 `pbab` 在装/启用/停用/卸载时调 `notify_nanny()`。内核没起来时先攒到 `entity/state/module_pending.jsonl`，保姆下一次巡检（60 秒）自动补记。

界面也照主人说的改了：

- 标题栏和窗口标题改成 **BAB**，实体名字留在侧栏；侧栏下面那行 "Wise Entity · 壳" 删了。
- 导航「模组管理」→「模组」，和其它项对齐。
- 情绪卡片去掉「（天生）」「（叠加）」两个解释词。

验证：空注册表时 `tools_text()` 里 `QQ / B 站 / 上网桥 / web_bridge` 全部 0 命中；`POST /modules/register` 能让 `programs.json` 多一条、`unregister` 能删掉；内核不在时 pending 会落盘、下次巡检自动补记（`drained: 1`）。静默装 0.1.20 后五项 UI 改动逐条比对通过，隐私扫描 0 命中。

## 0.1.21：说真话、理智值、保姆播报（2026-10-30）

主人实测 0.1.20 后挑出三处「说的和实际不一致」，这一版逐条修：

### 一、她说的「网页客厅 / QQ 和 B 站」是从哪来的
- 内置程序清单是出厂写死的：标题叫「网页客厅」、入口写的是 40720（可实际这份装在 40721）。
- 「QQ 和 B 站」不是清单里的，是她自己把两句旧记忆（13:30 记的）反复当成事实。
- 修法：
  - 出厂 `programs.json` 改成空 `{"programs": []}`，内置三项（对话窗口 / 语音 / 看图）由保姆在启动时按**当前端口**生成并校正旧文件。
  - 提示词加一句「清单里没有的名字就是这会儿没有，别凭印象编」，再加一句「问具体数字先调工具查」。
  - 工具链本身是通的（实测上网桥 `/search`、`/fetch` 都被调用；她自己也答出了 4~21℃）。

### 二、设置页显示「（还没填）」
- 页面在向导之前就构造好了，Key 后来写进 `llm.json`，但页面只在构造和保存后刷新。
- 修法：`SettingsPage.showEvent` 每次进设置页都重读 `llm.json`。

### 三、情绪：去百分号 + 平静改理智
- 数值不再带 `%`，贴着进度条右对齐。
- `平静` 换成 **理智**：范围 −100~+100，开局固定在 0。
  - 负值：越来越拦不住自己（−100 几乎没了理智）。
  - 正值：越来越冷静（+100 冷得过头，像在讲别人的事）。
  - ±70 以外是极端档，gates 里直接改行为（负：hide×0.55、reach×1.25；正：hide×1.30、share×0.80）。
- 提示词里理智单独一行，不影响「前三强」情绪。

### 四、在线状态 / 主动 / 沉默 / 保姆播报
- 主人不在线时她说不了话；现在她**会自己挑时候开口**，也会**选择不说**。
- 主动说话按驱动急迫度算沉默概率（越不急越可能闭嘴），落 `state/proactive.json` 的 `silent` 记录。
- 保姆播报走 `/notices`：
  - 主人在忙/离开时发来消息 → 聊天里出现「保姆程序：对方在找你」。
  - 她决定不说 → 「保姆程序：对方选择沉默」。
- 长回复自动拆成 2~3 条，一条一条冒出来（间隔 0.5 秒），不再一整块糊上去。

**实测（开发树，临时用真 Key，测完已还原）**
- 问「帮我查一下北京今天几度，要具体数字」→ 15 秒，上网桥收到 `POST /search` 与 `POST /fetch`，回复「北京今天（10月30日）晴，4到21℃。白天还挺暖，晚上掉到4度，温差大。／明天最高才12℃，降得狠，出门多穿点。」并拆成 3 条。
- 情绪 `/emotions` 返回 `calm=0.0`（理智开局 0），界面见 `logs/details_san4.png`。

## 0.1.22：文案、教程与圆图标（2026-10-30）

这一版全是"看得见"的东西：建档向导的说法、保姆的三段引导、左下角那三颗小字、任务栏图标。

- 建档第 1 页标题改成「您是第一次打开该启动器！」，正文第一句是「先认识一下，我是这个程序的『保姆』程序，现在需要您填写您的 API key」。
- 字段改成「您的昵称」；链接改成「您没有 API Key？现在去获取一个」；按钮改成「先验证一下」。
- 自称与称呼都能写多个（用 `/` 分开，例如 `我/本人/本小姐`、`您/大人/主人`），确认句改成「你是TA的『主人』」这种说法。
- 教程改成保姆引导：先让你在右上角选【在线】，再说「关闭此窗口后默认您处于忙碌状态」；点【在线】之后她才说「您先随便聊两句，我过一会儿再继续教您」；聊几句后补一段关于她是什么、左边模组是什么、以及"Ta 只是个 AI，请不要投入过重感情"。
- 主窗左下角「内核 ● / 语音 ○ / 模组 ●」三颗小字删掉，底部状态行也简化成「就绪」——要看状态去「服务」页。
- 图标全部改成圆形（程序与安装程序都是）；`tools/make_icons.py` 现在会给母版套抗锯齿圆形蒙版后再出 16/32/48/256 四档。
- 任务栏图标不再是 Python 的：启动时设置 AppUserModelID，并给 QApplication 设窗口图标。

**验证**
- 离屏渲染：向导第 1 页标题、第 3 页确认句（`她是「阿测」，你是她的主人，叫你「您/大人/主人」`）、主窗无小字、圆形图标都正常。
- 真实启动开发树：任务栏出现圆形白鲸图标（不再是 Python 图标）。
- 静默安装 `D:\BAB 0.1.22测试版`：105 文件、`VERSION=BetterAIBridge 0.1.22`、启动器 `BetterAIBridgeLauncher 0.1.22.vbs`、`assets` 里只有两个 ico 与两张小图（`preview_*` 不再进包）、隐私扫描 0 命中。

## 0.1.23：少摆动作、逐条冒字、代词不再写死（2026-10-30）

- 括号动作限流：整条回复最多一处、不超过 8 个字；后续几条开头不许再摆「（……）」。提示词里加了硬性规矩（`EXPRESSION_RULES`），代码里也做了兜底（`chat_core.limit_actions`），短回复同样生效。
- 逐条冒字：`_on_ok` 不再一口气把几条糊上来，改成每条前面先显示「XX正在输入」，按字数停 0.7–2.4 秒再落下一条；`mood`/记忆提示挪到最后一条之后显示。
- 人称不再写死：设置页原来写「你与她的关系」，现在按性别显示「你是她的 / 他的 / 它的 / 祂的」（`framework_setup.pronoun()`）。
- 人格模板的「## 说话」也补了括号动作那条，新装直接带上。

**验证**
- `split_reply` 单测：`（抬了下眼皮）嗯，来了。本小姐在呢。有事说事，没事…（顿了顿）没事也行…` → 三条，第一条留动作、第二条去掉开头动作、第三条去括号；`（皱眉）（叹气）算了` → 只留一个。
- UI 节奏（离屏 + QTest）：三条分别落在 1.10s / 1.99s / 2.81s，中间 typing 正常。
- 设置页：`你是祂的`（开发机当前性别未设定）。
- 静默安装 0.1.23：105 文件、版本与启动器名正确、隐私扫描 0 命中。

## 0.1.24：B 站桥 P0 + 扫码登录弹窗（2026-10-30）

**模组：B 站桥 0.1.0（Chanko）**，端口 `40731`，只读。
- 工具：`bili_me`、`bili_video`、`bili_search`、`bili_notifications`。
- 扫码登录：`POST /login/qr` 出二维码（内置 segno 画 PNG，不需要 venv），启动器弹窗轮询 `/login/poll`。
- 登录信息存 `WiseEntity\entity\state\bili_auth.json`，重装模组不掉登录。
- WBI 签名（`MIXIN` 混表 + `wts` + md5）+ `buvid3` + 5 分钟缓存，搜索不再 412。

**启动器**
- 新增 `app/ui/dialogs/qr_login.py`：`QrLoginDialog(port, title, hint)`，2 秒轮询、状态 waiting/scanned/ok/expired、成功 900ms 后自动关。
- `ModuleCard` 若模组清单里有 `login: {port, label}` 且已启用，就显示「登录 B 站」按钮。
- 截图：`D:\BAB-release\Bilibili_bridge\qr_dialog.png`。

**实测**
- `/health` 200；`/login/qr` 出码（PNG 1021 B，371×371，可扫）；`/login/poll` 未扫时 `state=waiting`。
- `POST /video {BV1GJ411x7h7}` → 标题/UP/时长 213s/播放 1.07 亿。
- `POST /search {猫}` → `total 1000`、8 条（WBI 生效，没被 412）。
- 内核 `GET /tools` → `count=6`（上网桥 2 + B 站桥 4），`tools_text()` 里两行清单都在。
- 静默装 0.1.24：106 文件、`qr_login.py` 在包内、`program_bundle` 只有空 registry（没有把开发机模组打进去）、隐私 0 命中。

**产物**
- 安装包 `D:\BAB-release\BetterAIBridge-Setup-0.1.24.exe`（663,552 B，sha256 `15ada3bc…7bd9`）。
- 模组 `D:\BAB-release\Bilibili_bridge\program_web_bili.pbab`（195,450 B / 23 文件）+ 源码 + README。

## 0.1.25：扫码登录的两个坑（2026-10-30）

实测 0.1.24 时踩到两个真问题，都出在扫码弹窗这一圈：

1. **登录成功却拿不到凭据**。B 站 `qrcode/poll` 成功时，`SESSDATA` 可能在响应头 `Set-Cookie` 里，也可能在 `data.url` 的 query 里，原来只读了后者。现在两边都读（`pick_cookies()`），仍拿不到就返回 `state=need_retry`，弹窗提示「点『换一张』重扫一次」，不再抛错。
2. **弹窗关不掉**。`QrLoginDialog` 里有个 `self.done = False` 属性，把 `QDialog.done()` 方法遮住了 → 点「关闭」调 `reject()` 时炸 `TypeError: 'bool' object is not callable`，窗口就卡住。改名为 `self._finished`，并把关闭按钮接 `_bye()`（停表 + reject），`closeEvent` 里 `event.accept()`。

**模组 B 站桥 → 0.1.1**：`program_web_bili.pbab` 重打（196,755 B / 23 文件），修的就是上面第 1 条；`/health` 返回 `version: 0.1.1`。

**实测**
- `pick_cookies()` 单测：headers 里 `SESSDATA=abc%2C123` 能取到；只有 url 时也能取到并完成 URL 解码。
- 弹窗单测：`_bye()` 后 `isVisible=False`、`result=0`；`close()` 同样能关；`timer` 已停。
- 0.1.25 静默装 106 文件，`_finished`/`need_retry` 都在包内，隐私 0 命中。

## 0.1.26：给「会动手」的能力装上刹车（2026-10-30）

B 站桥升到 0.2.0，补上四道闸门，核心理念是「工具只能排队，执行只能由你点头」。

- **待批窗口**：模组卡片新增「待批」。她点赞/收藏/私信陌生人时只会进队列；窗口里逐条「批准 / 拒绝」，批准才真调 B 站接口。
- **执行接口不注册成工具**：`POST /pending` 只给启动器用，模型拿不到，避免「自己批准自己」。
- **UID 补登记**：扫码成功后弹「请填写你的 B 站 UID」，可跳过；跳过也能在模组设置里补（`POST /owner`）。用途：认出你的私信、判断「认识谁」。
- **资料只读**：不提供改资料接口——按你的建议，改资料自己在 App 里改。
- **限频写死在服务里**：同视频一次、同 UP 每日 2 次、间隔 ≥10 分钟、赞 20/藏 10、私信 1 条/分钟且 10 条/天。

**新增对话框**：`app/ui/dialogs/owner_mid.py`（UID 补登记）、`app/ui/dialogs/pending.py`（待批列表）。

**实测**
- `POST /settings {"enable_like":true}` → `POST /like` 返回 `queued:true id=…`；`GET /pending` 1 条；`POST /pending {"allow":false}` → `denied:true`，队列清空（拒绝路径不会真调 B 站）。
- `POST /like` 在开关关时返回「点赞开关是关的（默认关…）」。
- 0.1.26 静默装 108 文件，两个新对话框与 `on_pending`/`_ask_owner` 都在包内。

## 0.1.27：同一个模组装两次会打架（2026-10-30）

一串三个 bug，都是「装了两份」时才露头：

1. **端口写死**。模组清单里 `ports: [40731]` 是固定的，第二份安装再启用同一个模组时，端口已被第一份占着，`start.cmd` 起不来，日志还是 0 字节；而内核的 `/tools` 只看清单端口，于是第二份安装的工具**打到了第一份的模组上**——登录态、使用者 UID 全跑到别人家去了。
   修法：`pbab.enable()` 先试清单端口，被占就自己找空闲端口（`_free_port`），通过环境变量 `BAB_MODULE_PORT` 传给模组，把实际端口写进注册表 `runtime_port`；`tool_bus` 优先用 `runtime_port`。停用时只杀「命令行/工作目录属于本模组目录」的进程，不再按端口乱杀别人的。
2. **设置文件被写成 schema**。`save_settings()` 把 `settings.schema.json` 整份塞进了 `settings.json`，模组读自己的设置读不到，开关等于没开。
   修法：`settings.json` 只写 `{"values": {...}, "schema": {"fields": [...]}}`；`settings_fields()` 也认 JSON-Schema 的 `properties` 写法。
3. **工具失败也记成 ok**。`tool_bus.call()` 只看 HTTP 200，模组返回 `{"ok": false, "error": ...}`（比如「这是使用者本人，不用私信」）时日志仍写 `ok`，她也容易当成做成了。
   修法：按返回体里的 `ok` 记日志（`FAILED`），`feedback()` 明确写「工具返回失败：… 这就是真实结果，别当成做成了」。

**模组 0.2.1 同步改了**：端口从 `BAB_MODULE_PORT` 取（缺省仍 40731）、`settings()` 认扁平 / `values` / 旧 schema 三种写法、`/health` 的版本号改成读 `module.json`（不再硬编码）、私信给使用者本人时的提示改成「不用私信；有话直接在对话里说」。

## 0.1.28：模组设置说人话 + B 站桥会认人（2026-10-30）

### 模组设置不再露英文键名
`module_settings.py` 原来只认 `label`，而清单里写的是 JSON-Schema 的 `title`；类型也按 `bool/int/choice`
判断，JSON-Schema 给的 `boolean/integer/number` 全被当成文本框——于是设置页一排 `allow_search`、
`cache_seconds`，开关还变成了要手打 True/False。
现在：标签取 `label → title → key`，类型认 `boolean/bool`、`integer/int/number`、`enum/choices/options`，
范围取 `minimum/maximum`，说明取 `description/help` 当悬浮提示；开关 56px、数字框 160px，不再铺满整行。

### B 站桥 0.3.0：知道使用者是谁，也能私信使用者
原来 0.2.0 有两个硬伤：
1. 把 `owner_mid` 当成「自己」，私信使用者会被拒（`这是使用者本人，不用私信`）——可使用者恰恰就是他要私信的人；
2. 她根本没有「使用者 UID」这个概念，也没有工具去查，问起来只能编。

0.3.0 加了 `GET /who`（工具名 `bili_who`）：
- `owner_mid`：使用者的 B 站 UID；
- `owner`：名片（昵称、签名、头像、等级、粉丝、关注），走 `x/web-interface/card`，失败再用 WBI 的 `acc/info`；
- `self`：当前登录的账号，并给 `same_person` 判断两者是不是同一个号；
- `hint`：没填 UID 或名片被风控时，明确说怎么办。

私信规则改成：**给使用者本人可以直接发**（仍受每日上限），给不认识的人照旧进待批队列。
`bili_dm` 的参数说明也写清了「使用者本人就是 bili_who 里的 owner_mid」。

实测（开发树，0.3.0，端口 40732）：
```
GET /who -> owner_mid=3546554161957126, owner.name=琛柯大人, level=4, followers=2, following=20
            self.mid=3690991145978511 (UU-MNJK), same_person=false
GET /me  -> is_owner=false, owner_mid=3546554161957126
POST /dm {mid: owner_mid} -> {"ok":true,"sent":false,"dryrun":true,"to_owner":true}
```

## 0.2.0：端口块 + 桥权限（2026-10-30）

这一版没有新功能，只是把「端口」和「模组能碰什么」两件事一次做对。

### 端口块：一次安装独占一段口

- `config/install.json` 存 `install_id` 和 `base`（基址）；新装第一次启动自己生成，**不进安装包**（否则所有安装共用一个身份）。
- 一段 20 个口：`B` 内核、`B+1` 语音、`B+5..B+19` 模组池。
- 内核对不上号或端口被占时，`app/services/runtime.py` 找一整段连续空块迁移，而不是只换一个口。
- 模组端口从池里分，`registry` 记 `runtime_port`；清单里写的 `40731` 只当参考。
- `disable()` 只杀「命令行/目录属于本安装」的进程，不再按端口乱杀别人家的。
- 新增 `GET /ports`，一眼看全：安装号、基址、内核、语音、各模组端口。

### 桥权限：模组拿什么由你说了算

- 模组 `module.json` 的 `bridge.wants` 声明要什么（`memory.search` / `memory.note` / `brain.snapshot` / `mood.read` / `presence.read`）。
- 设置页「桥权限」里勾选即生效：取消 = 立刻 403 `这个模组现在拿不到「mood.read」：使用者在设置里关了`。
- 每次调用写 `entity/state/bridge_audit.jsonl`；模组身份用各自目录的 `bridge_token.txt`。

### 验证

- `/ports`：`install_id 69e05419… base 40720 core 40720 asr 40721 modules web_bridge→40730 bili_bridge→40732`。
- `/bridge/modules`：bili_bridge 五项能力全开；勾掉 `mood.read` 后 `/bridge/call` 返回 403，勾回 200。
- 静默装 0.2.0 到空目录：`install.json` **不在包内**、首次导入生成新 `install_id ff2fcdbc…`，`BASE 40720 / PORT 40720 / ASR 40721`。
- 设置页离屏渲染：端口卡与桥权限卡都在，勾选框按模组列。

## 0.2.1：人称、多余的字、设置页卡顿（2026-10-30）

- 聊天页顶部把「会话 web:owner · 说的话会被记住」删了，只留状态点；输入框的「跟她说点什么」改成按性别取（女=她、男=他、无性别=它、不设定=祂），向导改完性别会立刻刷新。
- 剩余写死的「她」改成中性「TA」：教程文案、待批弹窗（「TA 排队想做的事」「理由：」）、模块教程气泡；`details` 的驱动力「想他」改成「想找你」。
- 设置页不再卡：端口和桥权限两张卡的 HTTP 查询丢到后台线程，结果用 Qt 信号回 UI 线程；`show_page` 实测 8.4 ms（之前同步请求会卡 2-3 帧）。
- 验证：`pronoun(女)=她`；`apply_pronoun()` 后占位符「跟她说点什么…」；设置页端口卡列出 `安装 69e05419… / 内核 40740 / 语音 40741 / 上网桥→40730 / B站桥→40732`；桥权限两行控件。

## 0.3.0：她能出声了 + 圆角 + 关窗即忙（2026-10-30）

**朗读（edge-tts）**
- 内核新增 `entity/core/tts.py`：`POST /tts {text,voice,rate}` → `audio/mpeg`，失败回 502 并带原因；`GET /tts/voices` 给 7 个中文音色；`POST /tts/config` 存 `entity/config/tts.json`（voice/rate/volume/enabled）。
- 缓存按 `sha1(音色|语速|文本)` 落在 `entity/state/tts_cache/*.mp3`，同一句话第二次直接命中。
- 启动器在聊天页右侧加「朗读」勾选（存在 `config/app.yaml` 的 `ui.tts_autoplay`）：勾上后她说一句、念一句，逐条对齐气泡节奏。
- 播放走 Windows MCI（`winmm`），因为 PySide6-Essentials 不带 QtMultimedia；打不开设备时安静失败，不影响文字。
- 依赖：`edge-tts 7.3.1` 装在 `WiseEntity/entity/.venv`（在线合成，离线会报 502）。

**圆角**
- 窗口改成 `WA_TranslucentBackground` + `QFrame#Root` 的 14px 圆角 + `resizeEvent` 里按圆角生成 `QRegion` 遮罩，四角不再露白方块。

**关窗即忙**
- 点 × 收进托盘时把 presence 切成 `busy`；从托盘叫回来**不再自动切回 online**（原来 `show_from_tray` 和启动时都会强设 online，已删）。
- 想回在线就点聊天页右上角「在线」，或在托盘菜单里选。

**验证**
- `POST /tts` 实测 200 / 15,696 字节 / `audio/mpeg`；`synth_sync` 直调 13,536 字节。
- 安装包 0.3.0：692,224 B，sha256 `d192af48…b1dc`，payload 469,907 B / 113 文件；静默装到临时目录 114 文件、`tts.py`/`audio.py`/`朗读`/`setMask`/`/tts` 都在、`config/install.json` 不在包内。

## 0.3.1：声音可选、日志归位、墙内说话（2026-10-30）

- **声音可选**：建档第 4 页多一行「声音」，5 个中文音色，选完写进内核 `entity/config/tts.json`；以后在「设置 → 声音」里改，带「试听」。
- **服务页多一行**：`朗读 TTS（edge-tts，在线）`，状态跟内核走，操作列写「随内核」（不单独占端口）。
- **日志挪到最下面**，紧挨「就绪」。
- **情绪数值贴到进度条右边**（原来被拉到页面最右）。
- **墙内说话**：模组自己写的 `introduce.md` 不再直接进提示词；模组清单里也不列模组名，只写「一个模组（id）」；另加一句「别主动猜它们背后是哪个平台」。
  → 门还没装的时候，她只知道"有模组能打开新世界"，不知道门外是 B 站还是 QQ。

## 0.3.2：补一层「墙」（2026-10-30）

- 新增 `modules_box.wall()`：把模组文案里的平台名换成泛称（`B 站 → 那个站点`、`QQ → 那个聊天软件`、`NapCat → 那个协议端`）。
- 三处都过一遍：模组人格片段、工具描述与参数说明、开关事件行。
- 效果：她的提示词里不再出现「B 站 / QQ / bilibili」，工具名仍是 `bili_*`（要彻底藏起来得给工具起别名，留给后面）。

## 0.3.3：装了的才认识，没装的不知道（2026-10-30）

上一版把「别在墙里说墙外」理解偏了：我连**已经装上**的模组的介绍也一起藏了，还把模组名换成「一个模组」。这版改回来了，规则应该是这样：

- **没装的模组**：她压根不知道有这东西。提示词里没有任何名字，历史事件里卸掉的模组也会被过滤掉（`_module_events` 按当前在册模组过滤），并且明写一句「没装的东西，你连它的名字都不该知道」。
- **装上的模组**：把她该知道的都给她——模组自己的 `persona.md`（怎么用、边界）+ `introduce.md`（这是干什么的），标题用模组真实名字，工具清单也写真实名字。
- `wall()` 这个函数留在 `modules_box.py` 里但已经没有任何调用点，属于备用；确认无引用后可以删。

验证（开发树，两个模组装着）：`persona_text()` 2324 字、含「这份东西是干什么的」段；`tools_text()` 出现「B 站桥」与它的工具描述。清空注册表再测：`persona=''`、工具里 `B 站/B站/QQ/bilibili/上网桥` 命中 **0**。

## 0.3.4：页面不再挤、TTS 装得上（2026-10-30）

用户截图暴露的三个问题，根因都不在样式，而在布局与依赖：

1. **设置页被压成一团**：页面是普通 `QVBoxLayout`，窗口一矮，卡片就被压到比 `sizeHint` 还低，文字互相叠。改成整页 `QScrollArea`（卡片保持自然高度，超出一屏就滚动）。这也顺带满足"每一栏都该能看全"的要求。
2. **日志页字被挤掉**：日志页缺边距，且 `QPlainTextEdit` 没有最小高度。补 `contentsMargins(22,16,22,16)` 与 `setMinimumHeight(260)`。
3. **TTS 报 502 `No module named 'edge_tts'`**：`requirements-core.txt` 里根本没有 `edge-tts`——开发机是我手动装的，安装包自然装不出来。补进 `requirements-core.txt`（`edge-tts>=7.0`）与 `setup.ps1` 的自检（`import ... edge_tts`）。
4. 顺手修 `start-core.cmd` 的 `BAB_PORT` 与 `app.yaml` 的 `ports.core` 不一致（一个 40740、一个 40720），会让"门"显示离线、TTS 打到空端口；安装器现在用正则改 `set BAB_PORT=`，不再依赖写死字面量。
5. 欢迎页文案按用户给的版本替换（「承载独立的人格、记忆与情绪」/琛柯/数据在本地/三条能力）。

## 0.3.5：日志页终于能点开、声音真的会响了（2026-10-31）

上一版我只改了"看起来像"的地方，这一版把三处的根因挖到底，并且先写测试再改代码。

1. **日志页点不开**（0.3.1 起一直如此）：0.3.1 把"日志"挪到底部时新加了 `NAV_BOTTOM` 列表，按钮建了、页面也建了，但往 `QStackedWidget` 里塞页面的循环只遍历 `NAV`，`logs` 从没进过栈。`stack.setCurrentWidget(不在栈里的页)` 在 Qt 里是空操作（只在控制台打一行 warning），所以点"日志"只有按钮变亮。修：栈循环改成遍历 `[*NAV, *NAV_BOTTOM]`。
2. **日志按钮的字被切掉**：`main_window.py` 给底部按钮硬写了 `setFixedHeight(30)`，而 QSS 是 `font-size:13px` + `padding:9px 14px`，实际需要 35px。修：删掉那句固定高度，让按钮按 `sizeHint` 走（现在 5 个按钮都是 35）。
3. **试音"放出来了"但没有声音**（真 bug，不是没装解码器）：Windows MCI 的别名是**线程亲和**的。旧 `audio.py` 在主线程 `mciSendStringW("open ...")`，然后把 `play {alias}` 丢进 `threading.Thread` —— 每一条 `play` 都返回 263「指定的设备未打开，或不被 MCI 所识别」，而返回码被直接丢弃，于是全静默失败；`settings.py:252` 不管结果照样写"试听放出来了"。四组对照探针（主线程 open/子线程 play、子线程 open/主线程 status……）逐一定位，与文件、设备、解释器无关。
   - 修：`app/services/audio.py` 重写播放器为**一条常驻线程**（`bab-audio`）+ 队列，open/status/play/close 全部在同一条线程里执行；`play(path)` 返回 `bool` 并等真实结果（最多 3 秒），失败原因进 `player.last_error`。
   - 提示文案跟着诚实了：成功是「合成好了（24 KB），正在播放」，失败是「合成好了（24 KB），但没出声（设备或音量？）」。
4. **顺手修掉的崩溃**：`settings.py` 的异步回调用了 `self.log`，而 `SettingsPage` 没有 `log` 属性 —— 一旦回调抛异常，错误处理自己先 AttributeError 炸掉；窗口销毁后 `task_done.emit` 还会抛 `RuntimeError: Signal source has been deleted`。改成模块级 `log` + `_emit()` 兜住 RuntimeError。
5. **安装器解析失败**（只在打包时暴露）：`install.ps1` 被存成了 UTF-8 **无 BOM**，Windows PowerShell 5.1 按 ANSI 解码，中文串把引号吃掉，整份脚本连解析都过不去 —— 用户双击只看到「installer failed (exit 1)」。恢复 UTF-8 BOM，并把"打包后真装一遍"变成固定步骤。
6. **新增 `tools/test_pages.py`**：离屏回归测试（26 条断言，退出码 0/1），覆盖"每个页面都在栈里""点导航真的切页""按钮高度 ≥34""`play()` 真的播了多久（挂钟计时，不是瞬间返回）""试音文案成功/失败两条""窗口销毁后 emit 不崩"。`tools/smoke.py` 照旧全过。

已验证：`test_pages.py` 26/26 PASS（开发树与**装好的副本**各跑一遍）；`smoke.py` PASS；静默装 `D:\BAB 0.3.5测试版` 得到 115 个文件、`VERSION.txt` = `BetterAIBridge 0.3.5`；安装包端到端再装一次同样 exit 0。

## 0.3.6：两个自带模组终于能装上了（2026-10-31）

0.3.5 把外壳修好了，但两个模组还停在"放进 program_cache 也没人看见"的状态。这一版把 `web_bridge` 和 `bili_bridge` 逐个对着外壳的读取路径核了一遍，先写测试再改。

1. **B 站桥的 `bili_who` 从来没到过她手里**：`connection.json` 声明了 9 个工具，`endpoints[]` 只有 8 条，漏了 `who`。内核 `tool_bus.py:_build()` 解析不出端点就 `continue`（静默丢弃），于是"先问清我在跟谁说话"这个工具形同不存在。修：补 `{"name":"who","path":"/who","method":"GET"}`（`server.py` 的 `("GET","/who")` 本来就在）；同时给内核加一行日志——以后再漏写，`logs` 里能看见，而不是无声消失。模组版本 0.3.0 → **0.3.1**。
2. **扫码登录/待批用错端口**：模组卡片的 `on_login`/`on_pending` 取的是清单里的 `login.port`（40731），可外壳启用时给的是池端口（40725、40726……）。扫码框连到一个没人听的端口，表现就是"点了没反应"。修：新增 `ModuleCard._live_port()`，先读 registry 的 `runtime_port`，没有才退回清单端口。
3. **打包把字节码塞进包**：`tools/pack_pbab.py` 原来把 `_modsrc` 里的 `__pycache__` 一起 zip 了。修：跳过 `__pycache__`/`logs`/`.git` 和 `*.pyc`。上网桥包从 8 文件 / 154,050 B 瘦到 7 文件 / 139,995 B。
4. **两个包随安装包发**：`build.ps1` 不再整目录排除 `program_cache`，只带顶层 `*.pbab`（`_modsrc` 仍是源码，不进包）。新装的人打开模组页会看到「本地还有 N 个模组包没装」，每行一个「装这个包」按钮——不用会开文件对话框，也不会因为找不到包以为没模组。

已适配的两个包：

| 包 | 版本 | 大小 | 工具 |
|---|---|---|---|
| `program_web_bridge.pbab` | 0.2.3 | 139,995 B / 7 文件 | `web_fetch`、`web_search` |
| `program_bili_bridge.pbab` | 0.3.1 | 85,025 B / 17 文件 | `me`、`video`、`search`、`notifications`、`like`、`fav`、`dm`、`profile`、`who` |

两个 `start.cmd` 都先读 `%BAB_MODULE_PORT%`，没有才退回清单端口（40730 / 40731）——这是 0.2.0 起的端口契约，之前只有上网桥改过，这次两个都核过。

已验证：新增 `tools/test_modules.py`（静态 26 条 + `--live` 装/启/探活/卸），RED 时精确抓到上面 1、3 两条；修完全绿。在 `D:\BAB 0.3.6测试版` 里 full cycle：装两个包 → 启用得到池端口 40726/40727 → 内核 `tool_bus.tools()` 共 **11 个**工具 → `web_fetch https://example.com` 返回 title=Example Domain、`bili_who` 返回"还没填使用者的 B 站 UID"的提示 → 模组页两张卡都是「运行中」、「本地还有」列表消失 → 停用+卸载干净。`test_pages.py`、`smoke.py`、`test_module_port.py`、`test_modules.py` 四套全 PASS。

安装包：`BetterAIBridge-Setup-0.3.6.exe`，937,984 B，sha256 `9207df9aa9ce652f4cbf9dff02acee7af8e46c739d09944cd230ee1f139a3133`，payload 715,985 B / 118 文件；静默装 119 文件、`VERSION.txt` = `BetterAIBridge 0.3.6`。

## 0.3.7：她终于"有来有回"了（2026-10-31）

0.3.6 交出去以后你实测了一晚，问题都出在"她说话的方式"和"保姆怎么记账"上，而不是
功能缺失。这一版按你截图和日志逐条修，全部先写失败测试再动代码。

1. **保姆程序有了自己的栏**：提醒（对方主动发言 / 对方在找您 / 对方被打断 / 模组掉线 /
   肚子饿了）原来直接 `bubble("system")` 插进聊天流，几句就把对话切碎。现在统一走
   `chat_core.push_notice` → `state/notices.jsonl` → 外壳 5 秒轮询 → 右侧 `NannyPanel`，
   每条带 `HH:MM:SS`，可收起成窄边（未读显示「保1」），宽度两档固定；「清空」只清界面。
   「对方被打断」也落盘了（以前只在内存里，刷新就没）。
2. **打断语义改准**：一次发多句时插话，正在说的那句算说过，后面没出口的几句收回；
   情绪只登记一次（`emotion_core.STIMULI["cut_off"]`：惊讶 .05 / 羞愧 .04 / 难过 .03 /
   亲密 .02），不按句数叠。单句回复不触发（`_pending_parts() <= 0` 直接返回）。
   `_deliver_epoch` 让旧的逐句定时器整条作废，不会"打断后还在冒泡"。
3. **朗读不再抢话 + 语速进入计时**：`_pump_speech` 串行念，念完才念下一句；
   每句等待按字数估（`hold = max(650, min(1600, 300 + len(part)*40))`），
   设置里改语速后合成时长变了，`play_wait` 阻塞的时长自然跟着变。
4. **托盘「强制在线」+「忙碌」**：`act_busy` → `act_online`（`_set_presence("online")`，
   改完还会 `chat.load_presence()` 刷新小圆点）；按钮「忙」→「忙碌」，
   文案统一由 `_presence_text()` 产出（`● 在线` / `● 忙碌`）。
5. **肚子**：`stomach.py` 的 key 原来只认 AstrBot 老路径，0.3.x 下永远是 `no api key`；
   现在先读 `entity/config/llm.json`。外壳按扁平字段读、内核回 `{"state": {...}}` 的
   嵌套不一致也修了（`details.py:stomach_state()` 两种都认）。分界可配：
   `entity/config/stomach.json` 的 `{full_at, hungry_at}`，设置页「肚子」卡可改，
   内核 `GET/POST /stomach/config`（非法组合 400）。跌破饿线时 `stomach_box._announce()`
   往保姆栏推一次「肚子饿了，余额只剩 X.XX 元——该充点了。」，回饱再饿会再报。
6. **B 站模组 0.3.2**：`do_notifications()` 原来只读 `x/msgfeed/unread`（那里的 `chat`
   恒为 0），永远说"没有未读"。现在补了 `do_sessions()` 读会话列表（谁发的、几条没看、
   最后一句），私信发完还会 `_verify_sent()` 回读会话确认，没送到就老实说没送到。
7. **保姆看门狗探对端口**：`check_once()` 原来只探清单里的 `ports`（40730/40731），
   而外壳给的是池端口；健康的模组被记 degraded、真掉线看不见。现在优先 `runtime_port`。
8. **协议行不再漏进聊天**：`llm_box.chat()` 工具轮数 2 → 3，预算耗尽时返回一句人话
   （「（我这边工具还没回话，稍等一下我再试。）」）而不是把 `[工具]{...}` 原文丢给用户。

已验证（开发树 + 装好的副本各跑一遍）：`test_pages`、`smoke`、`test_modules`（含 `--live`）、
`test_module_port`、`test_nanny`、`test_tool_rounds`、`test_proactive`、`test_tts_timing`、
`test_stomach` 九套全 PASS。在 `D:\BAB 0.3.7测试版` 里起真内核验证看门狗：
启用上网桥后 `runtime_port` = 40727，`/nanny/status` 回 `{"state":"ok","ports":{"40727":true}}`，
`degraded: []`——修前同一路径是 `degraded`。

安装包：`BetterAIBridge-Setup-0.3.7.exe`，962,560 B，sha256
`24db8dd901a9edb00ba4c4dbe189d8ae7f57c872d66802a0cfc64a2c2c71c77f`，payload 742,448 B / 126 文件；
静默装 127 文件、`VERSION.txt` = `BetterAIBridge 0.3.7`、`program_cache` 里两个模组包、
`program_bundle` 只有 `registry.json`。
## 0.3.8：把 0.3.7 实测的四个毛病修干净（2026-10-31）

- 「正在输入」永不消：`_deliver` 收尾补 `typing.setText("")`；`show_mood` 改为同时等逐句链
  （`_deliver_state is None`）和朗读队列，避免它半路清一次、后面又被设回来。
- 保姆教程搬进右侧栏：`chat.py` 里六处 `bubble("system", "保姆程序：…")` 改走 `_nanny_push`；
  只有「好，那就不讲了…」留聊天（那是对使用者说话）。测试加了源码级断言，防止回潮。
- 重复消息：内核只存一份（`sessions.json` 核对过），是外壳重画——`_on_ok` 起手置
  `_resyncing = True`，`poll()` 在此期间一律让路，`_resync` 的 ok/err 里复位。
- 保姆提醒落盘：`chat_core.py` 补 `import json`（`push_notice` 之前抛 NameError 被吞，
  `notices()` 读回来永远是空）。新增 `tools/test_notices.py`，用内核自己的解释器真写真读。
- 新增测试：`test_pages` 第 15/16/17 节（打字提示收尾、教程进保姆栏、同轮不重画）、`test_notices`。

安装包 `D:\BAB-release\BetterAIBridge-Setup-0.3.8.exe`：966,656 字节，sha256
`8ed2dd53da007168048cfcff18ac90a3a96268c9f23f92f5552bc6ff1785bbfa`，payload 127 文件。
## 0.3.9：动作改用 〖 〗，只缩小、不朗读（2026-10-31）

- 新增 `app/ui/action_text.py`：`ACTION_OPEN/CLOSE = "〖"/"〗"`、`segments()`、`spoken()`、
  `is_action_only()`、`to_html()`。只认 〖〗；（）回到"正常插入语"，照念照显示。
- `chat.py`：`bubble()` 对她说的话改用富文本，动作段 11px 灰蓝；`_say()` 送合成前先
  `action_text.spoken()`；`_show_part()` 里"只有动作"的那条只冒泡、跳过合成与等待。
- 内核 `chat_core.py`：`_ACT_RE` 换成 `〖[^〖〗\n]{0,40}〗`，`split_reply` 在动作内部不切分。
- 内核 `llm_box.EXPRESSION_RULES`：动作只准 〖〗、不超过 8 字、一条最多一处、不许（）/\*/[]。
- 测试：`test_pages` 第 18 节（切片/念稿/气泡样式/只有动作不合成）、`test_notices` 补内核四查。

安装包 `D:\BAB-release\BetterAIBridge-Setup-0.3.9.exe`：970,752 字节，sha256
`520f729f39e5be0b1165f7a69684ab6131b138a7c7a8ebc63f441b382b4cfc7e`，payload 128 文件。

## 0.3.10：记忆换成一天一本，人设从 4 套到 16 套（2026-10-31）

- 记忆落盘换成 `entity/memory/internal/<门>/YYYY.MM.DD.txt`：一天一本、六段（凌晨/上午/中午/下午/傍晚/夜晚）、
  第一人称「我」；原文进 `.raw/<门>/`，另有 `_index.jsonl` 检索；模组记录走 `external/<program>/<分类>/`。
  新模块 `core/memory_store.py`，`core/memory_box.py` 改成它之上的门面（对外函数名不变）。
- 记忆自动压缩：`core/memory_compact.py` —— 整库 > 0.5 G 触发，压掉超过 60 天的天，压成 2–4 行进
  `_summary/`、原文进 `_archive/*.zip`，`.done.json` 保证幂等；压完仍 > 2 G 就在保姆栏喊一次。
  `maintenance.digest()` 接上它（原来指向的 `source_code/tools/memory_digest.py` 根本不存在）。
- 设置页新增「记忆库」卡（上限 / 压缩阈值 / 保留天数 + 当前占用），内核加 `GET/POST /memory/config`、`GET /memory/stats`。
- 迁移：`python -m core.memory_store --migrate`，旧目录整份进 `memory/_legacy/`。
- 16 套人设：`core/persona_styles.py`（seeds / delta / half_life / logic，取自《性格配置再优化》并按项目口径校准），
  `emotion_core` 以它为默认表、保留 `emotion_profile.json` 覆盖；老名字 温柔/理性/跳脱 自动映射。
  修掉 `start()` 强制 `calm=0` 的老 bug（理智初始值不再被吞）。
- 建档向导第 4 页改成按三组分段的下拉（16 项 + 2 条分隔），选到「特殊慎用」会提示剧情向。
- `cut_off` 刺激里不存在的 `affection` 改成 `love`；人格模板动作说明改 `〖…〗`。
- 新增 `tools/test_styles.py`（134 条）；`tools/test_pages.py` 到 111 条；`tools/test_memory.py` 扩到 57 条（含压缩与 `fragment()` 接上摘要）。
- exe：`BetterAIBridge-Setup-0.3.10.exe` 995,328 字节，sha256 `47827d6fe3a36506158118f634ba6a6401d892298f01b6d321cfec13bb436d5f`，payload 776,813 B / 133 files。
## 0.3.11：模组出问题时能自己看了（2026-10-31）

- 模组管理页每张卡加「看日志」「重启」：
  `mods.module_log_text()` 拼出这张卡的状态 / 端口 / pid / 错误 + 保姆记的最近 8 条
  `module_events.jsonl` + 模组自己 `logs\server.log` 的最后 40 KB（`_tail()` 只 seek 尾巴）；
  `ModuleLogDialog` 弹窗里可刷新、可打开模组目录。`on_restart()` 走 `disable → enable`
  链式（`ModsPage.call(..., after=...)`），不再需要卸载重装。
- 新增 `tools/check.py`：一条命令跑 13 套，自动挑解释器（gui/kernel），遇到
  `ModuleNotFoundError` 自动换另一套重试一次，`--only / --list / --no-fallback`；
  全绿约 48 秒。`build.ps1` 在 staging 前先跑它，红了 `exit 1` 不出包（`-SkipCheck` 可跳）。
- 新增 `tools/lint_refs.py`：扫代码里写死的路径，指向不存在的文件就红；`logs/`、`state/`、
  `memory/`、`program_bundle/` 等运行时路径自动跳过；已挂成 check 的第 13 套 `refs`。
  起因：`maintenance.digest()` 一直调不存在的 `memory_digest.py`，静默失效几个月。
  用 `utf-8-sig` 读源码，解析失败的文件会单独列出来而不是被静默跳过。
- 新增 `tools/new_module.py` + `templates/pbab-template/`（8 个文件）：生成能直接跑的骨架，
  固化端口读 `BAB_MODULE_PORT`、`connection.json` 工具与 `endpoints[]` 对齐、`health.port ∈ ports`、
  `start.cmd` ASCII+CRLF、打包不带 `__pycache__`；`--check` 静态验，`--smoke` 真起一次打 `/health`。
  只在源码树里用，`build.ps1` 不打包 `templates\*` 与 `tools\new_module.py`
  （骨架不写 registry、不碰 `program_bundle`）。
- 文档：`README.md` 自检段改成 13 套并给 `lint_refs` 一段；`docs/MODULES.md` 的「排查」
  一节写了这两个按钮的用法。
- exe：`BetterAIBridge-Setup-0.3.11.exe` 1,007,616 字节，sha256
  `ac6e7e8d8245290cf4b1e24d5e28f5256e2699b9d8e3d05c2fc7c302345ef5e1`，payload 787,486 B / 135 files。

## 0.3.12：模组能看见自己的设置了（2026-10-31）

- **设置回传**：`GET /bridge/manifest` 的 `module.settings` 带上用户在「模组设置」里改的值
  （核心侧 `modules_box.settings_of()`；以前只有写、没有读，模组进程永远拿不到）。
- **全能模组 M 0.1.1**：`module_settings(ttl=5)` 缓存 + 递归保护 + 取不到回旧值；
  `m_memory_note` 默认分类取设置、`quiet` 关长轮询、`m_self` 报设置；
  `tools/test_module_m.py` 43 条（新增 7 条，含拿假桥验设置链路）。
- **模组 id 放宽到 1~40 位**、目录名不区分大小写（`program_M.pbab` ↔ `id: m`）。
- **记忆抽屉按 `program_<id>` 现算**（`memory_box.program_key()`），第三个模组不再被塞进 QQ 抽屉。
- 发布物：`BetterAIBridge-Setup-0.3.12.exe` 1,015,808 B，payload 795,818 B / 136 files；
  静默装验证 137 文件，安装副本里 pages / smoke / modules / notices / memory / styles / module_m 全 PASS。
- `D:\BAB-release\M\program_m.pbab` 14,397 B（0.1.1，不进安装包，用的时候在模组页导入）。

## 0.3.14：把存档和卸载摆到桌面上（2026-10-31）

0.3.13 装上之后被指出的三处界面问题，这一版修掉：

- **两个按钮不再被挤出屏幕**：`app/ui/pages/settings.py` 里「存档「名字」」与
  「卸载程序」原本和「打开配置文件/程序目录/项目目录」同一行、右端对齐；窗口窄到
  1180 px 时「卸载程序」只剩半个。现在单独一行（`row2`）、靠左、末尾加
  `addStretch(1)`，任何宽度都在。
- **存档说清楚存哪儿、以及卸之前要挪走**：`save_archive()` 的标签与弹窗都写明
  「存档在程序目录里面，卸载会连它一起删——要卸程序，先把这份 .babpak 挪到程序目录外面。」
- **卸载要有得选**：新增 `SettingsPage._ask_uninstall(plan) -> "archive" | "remove" | "cancel"`，
  警告框两个按钮——「先去存档」（`AcceptRole`、默认）与「完全卸载」（`DestructiveRole`）。
  选「先去存档」只打包、不删；选「完全卸载」才 `spawn_uninstall()`。

另外补了一个安全阀：`portable.spawn_uninstall()` 在 `BAB_NO_UNINSTALL=1` 时只返回
`{"ok": True, "dry_run": True}`，不写脚本、不删目录。0.3.13 开发期间跑自检时，
`test_pages` 的 §19 因为打桩提前恢复、真的执行了一次卸载，把开发树
`D:\BetterAIBridge` 整个删掉（`timeout /t 2` + `rmdir /s /q`），后来从 `C:\bab_pkg\payload`
恢复、并补回 `.venv`（junction）、`templates/`、`tools/new_module.py`、`program_cache/_modsrc`。
现在 `tools/test_pages.py` 顶部就设 `BAB_NO_UNINSTALL=1`，§19 的打桩覆盖整节。

验收：`tools/check.py` 15 套全绿（50.9 s）；静默装 `D:\BAB 0.3.14测试版` 139 文件、
`VERSION.txt` = `BetterAIBridge 0.3.14`，副本里 `test_pages` / `test_portable` / `test_memory`
全 PASS。

## 0.3.15：两个按钮终于"会说话"了（2026-10-31）

0.3.14 里点「存档」和「卸载程序」没弹窗——`clicked` 信号会带一个 `checked=False`，
正好顶进 `save_archive(notify)` / `uninstall(confirm)`，于是存档静默、卸载直接跑。
两处都改成 `lambda: ...(notify=True/confirm=True)`，并在 `tools/test_pages.py` 里加了
"点按钮必须走到带提示/带确认分支"的回归断言。

卸载改成真正能卸干净：先等 2 秒让界面退出 → 用 PowerShell 杀掉还在程序目录里跑的进程
（GUI、内核、模组）→ 删桌面/开始菜单的 `BetterAIBridgeLauncher*.lnk` → `rmdir /s /q`
重试最多 40 秒，全程写 `%TEMP%\bab-uninstall.log`，脚本末尾 `exit /b 0`（别让调用方看到假失败）。

存档默认位置搬到程序目录外面：`~/Documents/BetterAIBridge 存档/`（`portable.archive_dir()`），
卸载不会连它一起删；warning 框里也写明这一点。`_ask_uninstall()` 返回
`archive | remove | cancel`，默认按钮是「先去存档」。

建档向导最后一页的人格草稿 `preview` 改成可编辑（`setReadOnly(False)`、最小高度 210），
`_finish()` 本来就优先取 `preview.toPlainText()`，所以改完直接生效、没有字数上限。

验证：`tools/check.py` 15 套全绿（53.8 s）；沙箱里真跑了一次生成的卸载脚本
（伪造程序目录 + 伪造桌面快捷方式，`USERPROFILE` 指向沙箱）——目录和 .lnk 都被删、
日志出现 `removed`、退出码 0；静默装 139 文件，副本里 `test_pages` / `test_portable`(31) /
`test_memory`(72) / `test_module_m`(45) 全 PASS。

安装包：`BetterAIBridge-Setup-0.3.15.exe`，1,032,192 B，sha256 `666e628e3b8d234fa74964ebe3ab39d79b47cf37ca73a43e54c40e7b4c11e4c7`。

## 0.3.16：卸载真的能卸干净了（2026-10-31）

0.3.15 的卸载脚本在中文路径的安装上必失败——三个原因叠在一起：

1. **编码**：`.cmd` 用 UTF-8 写、路径里有中文，而 cmd 按 ANSI 解析文件 → 路径变乱码，
   `if not exist` 立刻判真跳走；
2. **自匹配**：`powershell -Command "... '$app' ..."` 的参数同样过 ANSI，匹配不上；
   而且用 `CommandLine -like '*$app*'` 会把正在跑这条命令的 powershell 自己也算进去；
3. **cwd**：`Popen` 没给 `cwd`，子进程继承主程序的工作目录（就是程序目录本身），
   Windows 不允许删除活进程的当前目录，`rmdir` 必定失败。

修法：`.cmd` 只留纯 ASCII 的壳（`powershell -File`），真正逻辑搬进 `.ps1`
（`utf-8-sig`，PowerShell 5.1 见 BOM 才按 UTF-8 读），进程匹配只认 `ExecutablePath`，
启动时 `cwd` 指到 `C:\ProgramData\BetterAIBridge\`，删目录 `Remove-Item -Recurse -Force`
失败时再 `rd /s /q` 兜一次，40 秒重试，日志落在 `%TEMP%\bab-uninstall.log`。

验证：沙箱复现（中文路径 + cwd 在程序目录里）5 秒删净、日志 `removed`；
另用 0.3.16 装出来的那份代码卸自己，同样 `removed`。
`tools/portable` 与 `tools/pages` 里补了「cmd 壳必须纯 ASCII」「只按 ExecutablePath 匹配」
「要能重试」这几条断言，免得再退回去。

安装包：`BetterAIBridge-Setup-0.3.16.exe`，1,032,192 B，sha256 `eb54fecc560e2e880f8d64859009853eca05f7f54e0728000384c4b4922b8e39`。

## 0.3.17：她说话，和她名字（2026-10-31）

- **去掉一条假提醒**：`chat_core.reply()` 里原来有这么一段——只要 presence 不是 `online`，她每回一句话就往保姆栏记一条「对方在找你」。使用者一忙，整段对话就被这行字刷满。现在删掉了；「对方主动发言 / 对方在找您」只由 `proactive.py` 在真·主动开口时播报。
- **保姆栏去掉「保姆程序：」前缀**：`nanny._notice()`、`proactive` 的 `NOTICE_ONLINE/AWAY`、外壳 `_nanny_push()` 四处一起改。外壳侧还会把历史条目里的旧前缀剥掉，旧 `notices.jsonl` 不再显示半截前缀。
- **标题用名字**：`main_window.py` 原来 `setWindowTitle("BAB")` / `TitleBar("BAB", self)` 写死；改成取 `framework_setup.display_name()`，并新增 `refresh_identity()`（`showEvent` 与页面切换时比对），导入存档或改名后标题栏、侧栏名字会自己跟上。`TitleBar` 相应加了 `title_label` 与 `set_title()`。
- **桥新增 `chat.say`**：`bridge.py` 的 `CAPS` 多一项，`_chat_say(mid, hint)` 用 `llm_box.chat()` 按人设现写一句（20 字上下），`remember_turn(..., "assistant", line)` + `raw_append` 落记忆原文，然后返回 `{"said": true, "text": …}`。生成失败退回 `hint`，绝不抛。需要模组在 `bridge.wants` 里申请，照常进 `bridge_audit.jsonl`。
- **测试**：`test_notices.py` 多一节（假 `llm_box.chat` 返回固定句，断言这句进会话、空 hint 400）；`test_pages.py` 的保姆栏断言改为按内容认教程条目；`test_proactive.py`、`test_module_m.py`、`test_module_routine.py` 跟着新文案与新能力更新。`tools/check.py` 16 套全绿（72.9 s）。
- **交付**：`D:\BAB-release\BetterAIBridge-Setup-0.3.17.exe`（827,392 B，sha256 `f3654a3bca7f0597753c200f3804a4cf8e403f1a4e2dc8be46343a9d4d1277a9`，载荷 609,920 B / 139 文件）。载荷比 0.3.16 小，是因为两个老模组的源码目录已经挪去 `D:\BAB-release\_mods-moved-2026-10-31\`，不再随包。

配套「日常事务」模组同步升 **0.1.1**（`D:\BAB-release\Routine\program_routine.pbab`，27,570 B，sha256 `1E0CD5AE…CD4`）：到点提醒改走 `chat.say`（她自己开口，不再往聊天里插系统气泡）；查询引擎从 Bing 换成 **360 主 + Bing 备**，加相关性闸门（结果与查询的 CJK 二元组命中率 < 25% 就换引擎，都不行才标 `degraded`）、`html.unescape`、5 分钟缓存、`全面搜索` 跳过字典/百科页；删掉本机直连会超时的 DuckDuckGo。

## 0.3.18：模组终于能单独写一份「给她看」的说明书（2026-11-01）

- 新增约定：模组可以放 `agent.md`（给智能体看的操作须知）；`introduce.md` 回归「给使用者看的说明书」，**不再进提示词**。
- `modules_box.persona_text()`：`persona.md` + `agent.md`（有就优先），没 agent.md 的老模组不受影响。
- 模组设置窗口的标题改成「介绍（给你看的；她在提示词里读的是 agent.md / persona.md）」。
- `docs/MODULES.md` 补「三份说明，各给谁看」对照表。
- 配套：B 站桥 0.7.0（记忆抽屉 / 互关私聊 / 自助刷视频 / 评论待批 / owner_mid 设置 / agent.md）。
- 安装包：`D:\BAB-release\BetterAIBridge-Setup-0.3.18.exe`，839,680 字节，sha256 `2C19CF274278D31519B0D808B4A31CE5EC449A0C5D348CEDD6D8474F8DFC442E`。

## 0.3.19：关系词回配置，提示词不再写死「主人」（2026-11-01）

- `settings.py` 新增 `relation(default="朋友")` 与 `user_title(default="他")`，都读 `entity\config\llm.json`；`user_title` 取第一个词（`"您/大人/主人/殿下"` → `"您"`）。
- `llm_box.door_rule()`：删掉写死的 `DOOR_RULES`，`qq:owner`/`web:owner`/`bili:owner` 三扇门每次现拼、用 `S.relation()` 插词；模组开关事件从「主人把…」改成「他把…」。
- 内核其余写死处一起改：`presence.fragment()` 的标题、`drives.py` 三条主动动机、`bridge.py` 的 `chat.say` 提示、`registry_box.py` 的 programs.json 指引、`emotion_core.py` 的情绪样本标签。
- 记忆侧：`maintenance.prompt_head()` 与 `memory_compact._prompt()` 从常量改成函数，`提到对方写「{S.user_title()}」`（JSON 示例的花括号已转义）；开发树无 `llm.json` 时回落到「朋友 / 他」。
- 保留不动：`framework_setup.py` 开局向导的关系下拉与默认项——那是给使用者挑的，不是写进提示词的死词。
- 配套模组同步改口并重新打包：全能模组 M **0.1.5**（19,304 B，sha256 `8C62AB598EBC0482E52A4B26C026D58C6BB10A452DA43A7840B2D63899AA2D98`）、B 站桥 **0.7.1**（125,807,973 B，sha256 `960B4AC5FFDC314B56A86F8A4167907DC4A8E5B9D91B5CAFBFEFF6BC35112989`）、日常事务 **0.1.3**（30,673 B，sha256 `8411135E489FDC7C543CA1D35E718A134B86CE20B97930FC30FBCCB7A1E18185`）。
- 测试：`tools/check.py` 17 套全绿 43.6 s；三包 `pbab.validate` 版本与 `checksums.json` 全对。
- 安装包：`D:\BAB-release\BetterAIBridge-Setup-0.3.19.exe`，839,680 字节，sha256 `d382093a14478213742aca1c53fa1395e8d3f4af9e303d1deaad6b2406ef5918`（载荷 620,565 B / 140 文件）。

## 0.3.20：主人记忆归一 + 三个新能力（语音、听觉、看图）（2026-11-01）

- **记忆 A**：`memory_store.door_of()` 把 `web:owner` / `qq:owner` / `bili:owner` 全部归一成一扇 `owner` 门，群和别人的私聊仍各是一扇。`visible_doors()` 对主人返回 `owner` 加上盘上还活着的旧门（`web_owner` / `qq_owner` / `bili_owner`），老记忆照样读得到。`memory_box.fragment()` 的「更早的事」跨这些门合并；`persona_drift` 用 `is_owner_door()` 认新老门。
- **三个新能力**（`bridge.py` 的 `CAPS`，模组要在 `bridge.wants` 里申请）：
  - `voice.tts`：把一句话念成 mp3（复用 edge-tts 与 `state/tts_cache`，600 字上限，每人每分钟 6 次）。
  - `voice.asr`：把录音转成文字（转发本机语音服务 `POST /stt`，令牌走 `entity/memory/bridge_token.json`）。
  - `vision.describe`：把图变成一段文字（走主模型的多模态，`llm_box.describe_image()`）。
- **语音服务骨架** `WiseEntity/capability/voice/asr/`：纯标准库的 `server.py`（`/health`、`/stt`）、`start-asr.cmd`、`requirements.txt`、`README.md`。引擎 `faster-whisper` 不入包，首次要在那里建 venv 装一次；没装时 `/stt` 回 503 并给出安装命令，不会崩。
- **外壳**：新增 `app/services/asr.py`（起停、探活、按端口找 LISTEN 进程杀），开程序时随 runtime 一起拉起；设置页「声音」卡片多了「语音转写（她能听见）」开关与模型说明入口。
- **测试**：新增 `tools/test_caps.py`（44 项），`tools/check.py` 变 **19 套全绿 45.2 s**；`tools/test_memory.py` 跟着新门名更新（72 项）。
- 安装包：`D:\BAB-release\BetterAIBridge-Setup-0.3.20.exe`，见下方哈希。
