# __NAME__ 模组

从 `templates/pbab-template` 生成的骨架，改这几个文件就能变成你的模组：

| 文件 | 改什么 |
| --- | --- |
| `module.json` | `id` / `name` / `version` / `ports` 与 `health.port` / `memory.program` |
| `connection.json` | `tools` 与 `endpoints` **两边同时加**，不然工具会被静默丢掉 |
| `server.py` | 真正的活；`/health` 永远秒回，别在里面等网络 |
| `introduce.md` | 写给智能体看的介绍 |
| `persona.md` | 她该怎么用这个模组 |
| `settings.schema.json` | 需要在模组卡里让人改的项 |

三个坑（都真踩过）：

1. **端口**：只认 `BAB_MODULE_PORT`，别写死；清单里的 `ports` 只是"作者想要的"。
2. **工具与端点**：`tools[].endpoint` 要对得上 `endpoints[].name`，对不上就是"工具不存在"。
3. **编码**：`start.cmd` 必须是纯 ASCII + CRLF，中文注释会让它解析失败。

打包（文件名固定、版本只写在 `module.json` 里）：

```
python tools\pack_pbab.py <这个目录> D:\BAB-release\<分类>\program___ID__.pbab
```
