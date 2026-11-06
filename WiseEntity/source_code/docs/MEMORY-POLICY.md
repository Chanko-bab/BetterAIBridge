# 记忆政策（2026-10-31 改：一天一本、第一人称）

## 一句话
记忆只能来自**她自己经历并记住的事**，不能由我们代写；写下来的时候是「我做了什么」。

## 存在哪
```
entity/memory/
  internal/<门>/2026.10.31.txt      她自己的记忆（提炼后的一句一行）
  internal/.raw/<门>/2026.10.31.jsonl   原文（谁说了什么，逐条）
  internal/_index.jsonl             检索用的索引（门 / 日期 / 时段 / 正文）
  external/program_<id>/<分类>/2026.10.31.txt   模组自己记的东西（经桥写进来）
  _summary/<门>/2026-10.md          压过的旧记忆（几天几行）
  _archive/<门>/2026-10.zip         被压掉那几天的原文
  _legacy/                          迁移前的老结构（\*.jsonl），只读留档
```

**门**（分片）= 谁在跟她说话：`web_owner`、`qq_owner`、`qq_group_<群号>`、
`qq_friend_<号>`、`bili_owner`、`bili_other_<mid>`。群聊不进主人的抽屉；
主人的记忆里也看不到群聊（`memory_box._visible` 只给自己那扇门）。

## 一天一个文件
- 一天 = `00:00`–`23:59`，按日历天，不跨零点合并。
- 文件头就是 `2026.10.31`，下面六个固定段，按时间顺序：

```
2026.10.31
凌晨(00:00-06:00)
上午(06:00-11:00)
中午(11:00-13:00)
下午(13:00-18:00)
傍晚(18:00-21:00)
夜晚(21:00-23:59)
```

- 每条一行：`HH:MM 我做了什么`。第一人称是**必须**的：她回忆时是「我查了天气」，
  不是「她查了天气」；提到使用者按 `llm.json.relation` 写「主人」。
- 同一句（去掉标点后）同一天只留一条；重复写入会返回 `duplicate` 而不是再写一遍。

## 注入提示词
`memory_box.fragment(session)` 每轮拼一段：

```
# 你记得的事
## 2026-10-31 上午
- 08:12 主人问昆明天气，我查完说明天 14 到 25 度

## 更早的事（压过的）
- 我陪主人看了房子，他说厨房太小
```

预算 12 行 / 900 字（`select()` 里限的），超了按相关度 + 新鲜度截。

## 什么时候压
- 触发：整个记忆库超过 `compress_gb`（默认 0.5 G）。
- 对象：日期比 `keep_days`（默认 60 天）更旧的那些 `.txt`。
- 怎么做：一天一压 → 模型压成 2–4 行「我……」→ 追加到 `_summary/<门>/YYYY-MM.md`
  → 原文塞进 `_archive/<门>/YYYY-MM.zip` → 删掉原 `.txt`；台账 `.done.json` 保证重跑不重复。
- 压完还超过 `max_gb`（默认 2 G）：在保姆栏喊一次（一天最多一次），不静默爆盘。
- 配置在 `entity/config/memory.json`：`{max_gb, compress_gb, keep_days, allow_zip_archive}`，
  外壳「设置 → 记忆库」能改；内核 `GET/POST /memory/config`、`GET /memory/stats`。

## 硬规则（没变）
1. **禁止**为了"让她会用某个程序"而在记忆里写「你在这可以 XXX」「它能 XXX」这类话。
2. 新增能力只更新 `entity/registry/programs.json`，不碰记忆。
3. 她真的用了某程序、聊过，才由 `maintenance.ingest()` 从 `.raw` 里抽记忆——这是唯一来源。
4. 改人格用 `entity/persona/persona*.md`；改程序清单用 registry；都不许顺手写记忆。
5. 压缩/迁移属于"整理"：必须留原文归档（`_archive`/`_legacy`），可追溯，不许凭空删。

## 性格怎么随记忆变（没变）
`entity/core/persona_drift.py`：每 **30 天**最多一次，只看主人的长期记忆，最多 3 条、每条 ≤18 字，
权重旧 0.8 衰减 / 新 0.45 加权，写 `entity/persona/drift.json`，注入成「# 你这一个月慢慢变成的样子」。

## 迁移
旧结构（`program_*/<分片>/notes.jsonl` + `transcript-*.jsonl`）用一次命令搬过来：

```
python -m core.memory_store --migrate [--dry]
```

会按 `ts` 落进对应门/日期/时段、原文进 `.raw`、旧目录整份挪进 `_legacy/`；
乱码（早先桥写进来的 `?`）会跳过并计入 `broken`。可重跑，第二次是 0。
