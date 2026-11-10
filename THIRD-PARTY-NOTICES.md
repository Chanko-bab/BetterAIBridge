# 第三方组件与许可证

BetterAIBridge 本体按 MIT 发布（见 `LICENSE`，Copyright (c) 2026 琛柯 (Chanko)）。
但它**运行时会带着别人的代码**，其中两个是 LGPL、一个是 Apache-2.0，三者都要求随分发
保留声明，所以这份清单是发行义务的一部分，不是可选的文档。

许可证信息来自各组件安装目录里的元数据与 LICENSE 文件，不是凭印象写的：

| 组件 | 版本 | 许可证 | 来源 |
|---|---|---|---|
| PySide6-Essentials | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pypi.org/project/PySide6-Essentials/ |
| shiboken6 | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pypi.org/project/shiboken6/ |
| edge-tts | 7.3.1 | LGPLv3（仅 `srt_composer.py` 为 MIT） | https://github.com/rany2/edge-tts |
| MOSS-TTS-Nano（随包内置的本地 TTS） | main 分支快照 | Apache-2.0 | https://github.com/OpenMOSS/MOSS-TTS-Nano |
| fastapi | 0.162.0 | MIT | https://github.com/fastapi/fastapi |
| uvicorn | 0.54.0 | BSD-3-Clause | https://github.com/Kludex/uvicorn |
| starlette | 1.10.0 | BSD-3-Clause | https://github.com/Kludex/starlette |
| httpx | 0.28.1 | BSD-3-Clause | https://github.com/encode/httpx |
| httpcore / h11 | 1.0.9 / 0.16.0 | BSD-3-Clause / MIT | https://github.com/encode/httpcore , https://github.com/python-hyper/h11 |
| pydantic / pydantic_core | 2.14.2 / 2.50.2 | MIT | https://github.com/pydantic/pydantic |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://github.com/numpy/numpy |
| certifi | 2026.10.23 | MPL-2.0 | https://github.com/certifi/python-certifi |
| PyYAML | 6.0.3 | MIT | https://pyyaml.org/ |
| psutil | 7.2.2 | BSD-3-Clause | https://github.com/giampaolo/psutil |
| miniaudio | 1.72 | MIT | https://pypi.org/project/miniaudio/ |
| aiohttp / aiosignal / frozenlist / multidict / propcache / yarl | 见内核 venv | Apache-2.0（aiohttp 为 Apache-2.0 AND MIT） | https://github.com/aio-libs |
| faster-whisper（可选，ASR） | 由 `requirements-asr.txt` 安装 | MIT | https://github.com/SYSTRAN/faster-whisper |
| onnxruntime（可选，本地 TTS） | 随 MOSS 环境安装 | MIT | https://github.com/microsoft/onnxruntime |
| torch（可选，本地 TTS） | 随 MOSS 环境安装 | BSD-3-Clause | https://github.com/pytorch/pytorch |

## LGPL 部分要特别遵守的三件事

PySide6 / shiboken6 与 edge-tts 是 LGPLv3。LGPL 允许闭源软件带它一起发布，但要求：

1. **动态链接，不许静态合并**：安装包里 Qt 是独立 DLL，BAB 自己的代码不并入 Qt，
   这一点现在的打包方式（直接把 `site-packages` 里的 DLL 原样放进目录）已经满足。
2. **保留许可证与版权声明**：本文件 + 安装目录里的 `LICENSE`、`THIRD-PARTY-NOTICES.md`
   就承担这个作用；`packaging/build.ps1` 会把它们带进 payload。
3. **可替换**：用户有权用自己编译的 Qt 替换掉这些 DLL。安装包不做完整性签名校验
   覆盖 DLL、不阻止替换文件，因此满足；如果以后加了"程序文件哈希白名单"，必须先
   把 Qt/edge-tts 的目录排除在外，否则就违反 LGPL。

Qt 源码与许可证全文：https://www.qt.io/licensing/open-source-lgpl-obligations
LGPLv3 全文：https://www.gnu.org/licenses/lgpl-3.0.html

## Apache-2.0 部分

MOSS-TTS-Nano 是 Apache-2.0，要求保留 LICENSE、标注改动。当前用法是原样内置
（`local_tts` 首次运行按需下载/解压），没有修改其源码；`_moss_src` 只在开发树里，
不随安装包发布。如果以后修改了 MOSS 的源码，必须在 `_moss_src` 里注明改了哪些文件。

## 这份清单怎么维持

`tools/test_architecture.py` 会检查 `requirements-*.txt` 里出现的每个包是否在本文件
里露过面——加了新依赖却忘了写许可证，自检会红。
