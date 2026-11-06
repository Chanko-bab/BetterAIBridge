# -*- coding: utf-8 -*-
"""记忆库回归测试（非 pytest，退出码 0/1）。

跑法（一定要用内核那套解释器，它才有 fastapi/httpx）：

    D:\\BetterAIBridge\\WiseEntity\\entity\\.venv\\Scripts\\python.exe tools\\test_memory.py

测什么：分桶边界、一天一个文件的结构、第一人称原样保留、去重、门之间不串味、
.raw 原文、索引、统计、配置校验、旧数据迁移（可重跑）。
"""
from __future__ import annotations

import datetime as _dt
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "WiseEntity" / "entity"))

from core import settings as S  # noqa: E402
from core import memory_store as store  # noqa: E402
from core import memory_box as memory_box  # noqa: E402

FAILS: list[str] = []
OKS = 0


def check(ok: bool, msg: str) -> None:
    global OKS
    if ok:
        OKS += 1
    else:
        FAILS.append(msg)


def store_dt() -> _dt.datetime:
    """现在的本地时间（压缩测试要造 100 天前的文件）。"""
    return _dt.datetime.now()


def temp_root() -> Path:
    d = Path(tempfile.mkdtemp(prefix="bab-mem-"))
    S.MEM_DIR = str(d / "memory")
    S.ENTITY = str(d / "entity")
    (d / "memory").mkdir(parents=True, exist_ok=True)
    (d / "entity" / "config").mkdir(parents=True, exist_ok=True)
    return d


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def main() -> int:
    # ---------------- 1. 分桶
    cases = [((3, 12), "凌晨"), ((5, 59), "凌晨"), ((6, 0), "上午"), ((10, 59), "上午"),
             ((11, 0), "中午"), ((12, 59), "中午"), ((13, 0), "下午"), ((17, 59), "下午"),
             ((18, 0), "傍晚"), ((20, 59), "傍晚"), ((21, 0), "夜晚"), ((23, 59), "夜晚")]
    for (hh, mm), want in cases:
        got = store.bucket_of(_dt.datetime(2026, 10, 31, hh, mm))
        check(got == want, f"bucket_of({hh:02d}:{mm:02d}) = {got}，应为 {want}")

    # ---------------- 2. 一天一个文件 + 结构
    tmp = temp_root()
    res = store.append("web_owner", "主人问昆明天气，我查完说明天 14 到 25 度",
                       ts="2026-10-31T08:12:00")
    check(res.get("ok") and not res.get("duplicate"), "第一次 append 应该成功")
    check(res.get("bucket") == "上午", f"08:12 应落在上午，实际 {res.get('bucket')}")
    p = store.day_path("web_owner", "2026.10.31")
    check(p.exists(), f"应生成 {p}")
    text = read_text(p)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    check(lines[0] == "2026.10.31", f"第一行应是日期头，实际 {lines[0]!r}")
    heads = [ln for ln in lines if ln.startswith(("凌晨", "上午", "中午", "下午", "傍晚", "夜晚"))]
    check(heads == ["凌晨(00:00-06:00)", "上午(06:00-11:00)", "中午(11:00-13:00)",
                    "下午(13:00-18:00)", "傍晚(18:00-21:00)", "夜晚(21:00-23:59)"],
          f"六个时段头顺序不对：{heads}")
    check("08:12 主人问昆明天气，我查完说明天 14 到 25 度" in text, "条目应是 `HH:MM 正文`")
    check("我查完" in text, "第一人称「我」要原样保留")

    # 凌晨那条要插到文件最前面那一段
    store.append("web_owner", "我半夜醒着，念叨了一句冷", ts="2026-10-31T03:11:00")
    lines = [ln for ln in read_text(p).splitlines() if ln.strip()]
    i_chen = lines.index("凌晨(00:00-06:00)")
    i_shang = lines.index("上午(06:00-11:00)")
    i_entry = next(i for i, ln in enumerate(lines) if ln.startswith("03:11 "))
    check(i_chen < i_entry < i_shang, "凌晨的条目要落在凌晨段里")

    # 同一段里按时间追加
    store.append("web_owner", "我泡了杯茶", ts="2026-10-31T09:40:00")
    lines = [ln for ln in read_text(p).splitlines() if ln.strip()]
    check(lines.index("09:40 我泡了杯茶") > lines.index("08:12 主人问昆明天气，我查完说明天 14 到 25 度"),
          "同段内后写的应排在后面")

    # ---------------- 3. 去重
    dup = store.append("web_owner", "主人问昆明天气，我查完说明天 14 到 25 度",
                       ts="2026-10-31T08:50:00")
    check(dup.get("duplicate") is True, "同一句重复写应报 duplicate")
    check(read_text(p).count("主人问昆明天气") == 1, "重复句不应写第二遍")

    # ---------------- 4. .raw 原文
    rp = store.raw_append("web:owner", "你好", "user", ts="2026-10-31T08:10:00")
    check(rp.name == "2026.10.31.jsonl" and rp.parent.name == "owner", f"原文路径不对：{rp}")
    rec = json.loads(read_text(rp).splitlines()[0])
    check(rec["role"] == "user" and rec["text"] == "你好" and rec["ts"].startswith("2026-10-31"),
          f"原文记录不对：{rec}")

    # ---------------- 5. 门与隐私
    # 0.3.20：主人自己的入口归一成一扇 owner 门；群和别人的私聊仍各是一扇
    pairs = {"web:owner": "owner", "qq:owner": "owner", "qq:group:12345": "qq_group_12345",
             "qq:friend:678": "qq_friend_678", "bili:owner:9": "owner",
             "bili:other:777": "bili_other_777", "": "owner"}
    for session, want in pairs.items():
        got = store.door_of(session)
        check(got == want, f"door_of({session!r}) = {got}，应为 {want}")

    store.append("qq_group_12345", "我在群里看到他们在聊猫", ts="2026-10-31T10:00:00")
    check(any("群里" in str(r.get("text")) for r in store.entries("qq:group:12345")),
          "群门应看得见群里的记忆")
    check(not any("群里" in str(r.get("text")) for r in store.entries("web:owner")),
          "主人的门不该看见群里的记忆")

    # ---------------- 6. 索引
    idx = store.index_records()
    check(len(idx) >= 3, f"索引条数偏少：{len(idx)}")
    one = [r for r in idx if "昆明" in str(r.get("text"))][0]
    check(one.get("door") == "web_owner" and one.get("bucket") == "上午",
          f"索引字段不对：{one}")

    # ---------------- 7. 统计 / 配置
    st = store.stats()
    check(st["used_bytes"] > 0 and st["files"] >= 2, f"统计不对：{st}")
    check(st["max_gb"] == 2.0 and st["keep_days"] == 60, f"默认配置不对：{st}")
    cfg = store.set_config(max_gb=4.0, compress_gb=1.0, keep_days=90)
    check(cfg["max_gb"] == 4.0 and cfg["keep_days"] == 90, f"写配置失败：{cfg}")
    check(store.config()["compress_gb"] == 1.0, "配置应能读回来")
    bad = 0
    for kwargs in ({"compress_gb": 9.0, "max_gb": 1.0}, {"keep_days": 0}, {"max_gb": 0}):
        try:
            store.set_config(**kwargs)
        except ValueError:
            bad += 1
    check(bad == 3, f"坏配置应全部拒绝，只拒了 {bad} 个")

    # ---------------- 8. 迁移（可重跑）
    tmp2 = temp_root()
    legacy_owner = Path(S.MEM_DIR) / "program_web" / "owner"
    legacy_owner.mkdir(parents=True, exist_ok=True)
    (legacy_owner / "notes.jsonl").write_text(
        json.dumps({"text": "主人喜欢喝美式", "ts": "2026-10-29T14:05:00", "scope": "owner"},
                   ensure_ascii=False) + "\n"
        + json.dumps({"text": "??? ??????,????", "ts": "2026-10-29T15:00:00"}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (legacy_owner / "transcript-2026-10.jsonl").write_text(
        json.dumps({"ts": "2026-10-29T14:00:00", "role": "user", "text": "在吗"}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    rep1 = store.migrate(apply=True)
    check(rep1["notes"] == 1, f"应只搬 1 条（乱码那条跳过），实际 {rep1['notes']}")
    check(rep1["broken"] == 1, f"应跳过 1 条乱码，实际 {rep1['broken']}")
    day = store.day_path("web_owner", "2026.10.29")
    check(day.exists() and "14:05 主人喜欢喝美式" in read_text(day), "搬过来的记忆应带 HH:MM")
    raw = store.raw_path("owner", "2026.10.29")
    check(raw.exists() and "在吗" in read_text(raw), "原文应搬进 .raw")
    check(not (Path(S.MEM_DIR) / "program_web").exists(), "旧目录应被移走")
    rep2 = store.migrate(apply=True)
    check(rep2["notes"] == 0, f"第二次迁移不该重复搬，实际 {rep2['notes']}")
    check(read_text(day).count("主人喜欢喝美式") == 1, "迁移后不该有重复行")

    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(tmp2, ignore_errors=True)

    # ---------------- 9. 压缩：旧的那几天压成几行、原文进 zip、可重跑
    from core import memory_compact as compact  # noqa: E402
    from core import memory_box as mbox  # noqa: E402

    tmp3 = temp_root()
    old1 = (store_dt() - _dt.timedelta(days=100)).strftime("%Y.%m.%d")
    old2 = (store_dt() - _dt.timedelta(days=101)).strftime("%Y.%m.%d")
    today = store_dt().strftime("%Y.%m.%d")
    for d, txt in ((old1, "我陪主人去看房子"), (old2, "我记住了主人不吃香菜"), (today, "我今天在收拾桌子")):
        store.append("web_owner", txt, ts=d.replace(".", "-") + "T10:00:00")

    calls: list[list[str]] = []

    def fake_sum(lines):
        calls.append(list(lines))
        return ["我陪主人看了房子，他说厨房太小"]

    compact._summarise = fake_sum
    rep = compact.run(force=True)
    check(rep.get("compressed_days") == 2, f"应压掉 2 天，实际 {rep}")
    check(not store.day_path("web_owner", old1).exists(), "压完旧文件应被删掉")
    check(store.day_path("web_owner", today).exists(), "今天这份不该被压")
    md = compact.summary_dir("web_owner") / f"{old1[:7].replace('.', '-')}.md"
    check(md.exists() and "我陪主人看了房子" in read_text(md), f"摘要文件不对：{md}")
    zp = compact.archive_dir("web_owner") / f"{old1[:7].replace('.', '-')}.zip"
    check(zp.exists() and zp.stat().st_size > 0, f"原文应进 zip：{zp}")
    import zipfile
    with zipfile.ZipFile(zp) as zf:
        names = zf.namelist()
    check(any(n.endswith(f"{old1}.txt") for n in names), f"zip 里应有那天的原文：{names}")
    again = compact.run(force=True)
    check(again.get("compressed_days", 0) == 0, f"第二次不该再压，实际 {again}")
    check(store.summary_lines("web_owner"), "summary_lines 应读得到压过的几行")
    blk = mbox.fragment("房子", "web:owner")
    check("## 更早的事（压过的）" in blk and "我陪主人看了房子" in blk,
          "提示词里应带上压过的那几行")

    shutil.rmtree(tmp3, ignore_errors=True)

    # ---------------- 10. 外部抽屉：谁写的就落在谁的程序名下
    tmp4 = temp_root()
    r1 = mbox.add_note("M 的握手记录", program="program_m", category="握手", target="external")
    rp = str(r1.get("path") or "").replace("\\", "/")
    check("/external/program_m/" in rp, f"外部抽屉应落在 external/program_m 下，实际 {rp}")
    check(str(r1.get("where") or "").startswith("external/program_m/"),
          f"where 应报真实程序名，实际 {r1.get('where')}")

    # 主人的门要能读到外部抽屉；群/好友门仍然不串味
    owner_blk = mbox.fragment("", "web:owner")
    check("M 的握手记录" in owner_blk and "【握手】" in owner_blk,
          f"主人应读到外部记忆并带来源，实际 {owner_blk!r}")
    group_blk = mbox.fragment("", "qq:group:999")
    check("M 的握手记录" not in group_blk,
          f"群门不应读到别处的记忆，实际 {group_blk!r}")

    # 怪名字必须被洗干净，不能写到别人的抽屉里
    for bad in ("../evil", "program_m/../../etc", "C:\\Windows", "Program M!!"):
        r = mbox.add_note("洗一下", program=bad, category="x", target="external")
        p = str(r.get("path") or "").replace("\\", "/")
        tail = p.split("/external/")[-1]
        check(tail.startswith("program_") and ".." not in tail and ":" not in tail and " " not in tail,
              f"怪名字 {bad!r} 应被洗成合法程序名，实际 {tail}")
    shutil.rmtree(tmp4, ignore_errors=True)


    # ---------------- 11. 不替模组预设房间（program_qq 那种空抽屉）
    tmp5 = temp_root()
    keep = {k: getattr(S, k) for k in
            ("STATE_DIR", "LOGS", "CORE_DIR", "BRAIN_DIR", "MEM_DIR")}
    try:
        S.STATE_DIR = tmp5 / "state"
        S.LOGS = tmp5 / "logs"
        S.CORE_DIR = tmp5 / "core"
        S.BRAIN_DIR = tmp5 / "brain"
        S.MEM_DIR = tmp5 / "memory"
        S.ensure_dirs()
        check(S.MEM_DIR.is_dir(), "ensure_dirs 应把记忆根建出来")
        left = [d.name for d in S.MEM_DIR.iterdir()] if S.MEM_DIR.is_dir() else ["<缺>"]
        check(left == [], f"记忆根里不该预建任何模组抽屉，实际 {left}")
        check(not (S.MEM_DIR / "program_qq").exists(),
              "不该再预建 memory/program_qq（那是给没装的模组留房）")
    finally:
        for k, v in keep.items():
            setattr(S, k, v)
    shutil.rmtree(tmp5, ignore_errors=True)

    # 安装侧同理：_ensure_memory_shards 只保证两个根，不按 program 建三层目录
    src = (ROOT / "app" / "core" / "pbab.py").read_text(encoding="utf-8")
    head = src.split("def _ensure_memory_shards", 1)[-1].split("\n# ----", 1)[0]
    check('"internal"' in head and '"external"' in head,
          "_ensure_memory_shards 应只建 internal/external 两个根")
    check('"people"' not in head and '"owner"' not in head,
          "安装时不该再建 owner/group/people 那套旧分片目录")


    # 桥的兜底也不该把"没写 memory.program"的模组塞进 QQ 抽屉：
    # 现在按 id 现起名字，靠的还是同一把 program_key 洗名。
    check(memory_box.program_key("program_Ping-Test!") == "program_ping_test",
          f"program_key 应把 id 洗成合法抽屉名，实际 {memory_box.program_key('program_Ping-Test!')}")
    check(memory_box.program_key("program_") == "program_qq" or
          memory_box.program_key("program_").startswith("program_"),
          "program_key 对空名要有兜底，且兜底也是 program_ 开头")
    src_bridge = (ROOT / "WiseEntity" / "entity" / "core" / "bridge.py").read_text(encoding="utf-8")
    tail = src_bridge.split("def _program_of", 1)[-1].split("\ndef ", 1)[0]
    check('or "program_qq"' not in tail, "桥的 _program_of 不该再兜底 program_qq")
    check("program_key" in tail, "桥应按 id 现起抽屉名（走 memory_box.program_key）")

    # ---------------- 汇总
    if FAILS:
        print(f"FAIL {len(FAILS)} 条：")
        for f in FAILS:
            print("  -", f)
        print(f"\n{OKS} ok, {len(FAILS)} fail")
        return 1
    print(f"PASS {OKS} 条：分桶、一天一文件、第一人称、去重、门不串味、索引、统计、配置、迁移都对。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
