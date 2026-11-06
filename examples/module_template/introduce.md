# 示例模组

## 这是什么
一句话说清这个模组给 agent 装了点什么。

## 你能拿它干什么
- 能力 A：……
- 能力 B：……

## 什么时候用 / 什么时候别用
……

## 装卸会发生什么
装：解包到 `program_bundle/plugins/template_module`，登记到 `program_bundle/registry.json`，
建记忆抽屉 `entity/memory/program_template/owner`。
启用：建 `links` 里的目录映射，跑 `entry.start`，等健康检查。
停用：杀进程、拆链接，文件保留。完全卸载：连文件一起删。

## 已知限制
……
