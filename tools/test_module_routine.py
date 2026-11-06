# -*- coding: utf-8 -*-
"""日常事务模组（program_routine）的自检。

用法：
    python tools\\test_module_routine.py            # 静态 + 行为（不联网、不起服务）
    python tools\\test_module_routine.py --smoke    # 再真起一次服务打 /health 与几个接口

源码目录默认 `D:\\Program for BAB\\program_routine.pbab`，可用环境变量 `BAB_R_SRC` 覆盖。
找不到源码时打印 skip 并以 0 退出（装好的副本里没有源码，这是正常的）。
"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get("BAB_R_SRC") or r"D:\Program for BAB\program_routine.pbab")

FAILS: list[str] = []
OKS = 0


def check(ok: bool, msg: str) -> bool:
    global OKS
    if ok:
        OKS += 1
        print("ok  " + msg)
    else:
        FAILS.append(msg)
        print("FAIL " + msg)
    return bool(ok)


def skip(msg: str) -> None:
    print("skip " + msg)


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


KNOWN_CAPS = {"chat.say", "memory.search", "memory.note", "brain.snapshot", "mood.read", "presence.read", "notice.push"}
EXPECTED_TOOLS = 13

CASES = {
    "明天 9:00": ("2026-11-01 09:00", None),
    "明天早上7点": ("2026-11-01 07:00", None),
    "后天下午3点": ("2026-11-02 15:00", None),
    "后天 15:30": ("2026-11-02 15:30", None),
    "大后天 8:00": ("2026-11-03 08:00", None),
    "3小时后": ("2026-10-31 15:00", None),
    "45分钟后": ("2026-10-31 12:45", None),
    "半小时后": ("2026-10-31 12:30", None),
    "3分钟后": ("2026-10-31 12:03", None),
    "一会儿": ("2026-10-31 12:10", None),
    "今晚 8 点": ("2026-10-31 20:00", None),
    "周五 10 点": ("2026-11-06 10:00", None),
    "下周三 9:00": ("2026-11-04 09:00", None),
    "11月3日 下午2点": ("2026-11-03 14:00", None),
    "11月3号 14:00": ("2026-11-03 14:00", None),
    "每天 8:00": ("2026-11-01 08:00", {"kind": "daily", "at": "08:00"}),
    "每周一 10:00": ("2026-11-02 10:00", {"kind": "weekly", "dow": 0, "at": "10:00"}),
    "每月 1 号 09:00": ("2026-11-01 09:00", {"kind": "monthly", "dom": 1, "at": "09:00"}),
    "每 2 小时": ("2026-10-31 14:00", {"kind": "every", "seconds": 7200}),
    "每 30 分钟": ("2026-10-31 12:30", {"kind": "every", "seconds": 1800}),
}

BAD_WHENS = ["我也不知道啥时候", "二十五点", "13月 8 号 10:00", ""]


def static_checks() -> None:
    for name in ("module.json", "connection.json", "settings.schema.json", "server.py",
                 "start.cmd", "introduce.md", "persona.md", "README.md"):
        check((SRC / name).exists(), "文件在：%s" % name)

    mod = json.loads((SRC / "module.json").read_text(encoding="utf-8"))
    check(mod.get("format") == "pbab/1", "module.json: format = pbab/1")
    check(mod.get("api") == 1, "module.json: api = 1")
    check(mod.get("id") == "routine", "module.json: id = routine")
    check(bool(mod.get("name")) and bool(mod.get("version")), "module.json: 有 name 和 version")
    check(str(mod.get("version")) >= "0.1.2", "module.json: 版本 >= 0.1.2（%s）" % mod.get("version"))
    check(bool(mod.get("author")), "module.json: 有 author")
    check(bool(mod.get("summary")), "module.json: 有 summary")
    start = str((mod.get("entry") or {}).get("start") or "")
    check(bool(start) and (SRC / start).exists(), "module.json: entry.start 指向真实文件")
    health = mod.get("health") or {}
    ports = [int(p) for p in (mod.get("ports") or []) if str(p).isdigit()]
    check(int(health.get("port") or 0) in ports, "module.json: health.port 在 ports 里")
    check((mod.get("memory") or {}).get("program") == "program_routine", "module.json: memory.program")
    wants = (mod.get("bridge") or {}).get("wants") or []
    check(bool(wants) and set(wants) <= KNOWN_CAPS, "module.json: wants 都是已知 cap")
    check("notice.push" in wants and "memory.note" in wants, "module.json: 申请了 notice.push 与 memory.note")

    schema = json.loads((SRC / "settings.schema.json").read_text(encoding="utf-8"))
    fields = schema.get("fields") or []
    check(len(fields) == 5, "settings.schema: 五个设置项")
    keys = [f.get("key") for f in fields]
    check("remind_when_away" in keys and "allow_web" in keys and "search_level" in keys,
          "settings.schema: 三个必需项都在")
    check("quiet_hours" in keys, "settings.schema: 有免打扰时段（0.1.2）")
    choice = [f for f in fields if f.get("type") == "choice"]
    check(bool(choice) and len(choice[0].get("options") or []) >= 2, "settings.schema: choice 有选项")
    check(all(f.get("key") and f.get("type") and "default" in f for f in fields),
          "settings.schema: 每项都有 key/type/default")

    conn = json.loads((SRC / "connection.json").read_text(encoding="utf-8"))
    provides = conn.get("provides") or {}
    tools = provides.get("tools") or []
    endpoints = {e.get("name"): e for e in (provides.get("endpoints") or [])}
    check(len(tools) == EXPECTED_TOOLS, "connection.json: %d 个工具" % EXPECTED_TOOLS)
    check(len(endpoints) == EXPECTED_TOOLS, "connection.json: %d 个端点" % EXPECTED_TOOLS)
    lost = []
    for tool in tools:
        ep_name = tool.get("endpoint") or str(tool.get("name") or "").rsplit("_", 1)[-1]
        ep = endpoints.get(ep_name)
        if not ep:
            lost.append(tool.get("name"))
            continue
        if not str(ep.get("path") or "").startswith("/"):
            lost.append("path:" + str(ep.get("path")))
        if str(ep.get("method") or "GET").upper() not in ("GET", "POST"):
            lost.append("method:" + str(ep.get("method")))
    check(not lost, "connection.json: 工具都能对上端点（%s）" % (lost or "全解析"))
    check(all(isinstance(t.get("args"), dict) and
              all(isinstance(v, dict) and v.get("type") for v in (t.get("args") or {}).values())
              for t in tools),
          "connection.json: args 是「参数名 → 类型」的字典")

    names = [t.get("name") for t in tools]
    check("rt_today" in names, "connection.json: 有 rt_today（0.1.2）")
    agent_md = SRC / "agent.md"
    check(agent_md.exists(), "agent.md: 存在（给她看的操作说明）")
    if agent_md.exists():
        doc = agent_md.read_text(encoding="utf-8")
        check("rt_today" in doc and "rt_remind_add" in doc, "agent.md: 提到主要工具")
        check("quiet_hours" in doc, "agent.md: 讲清楚免打扰时段")
        check("introduce" not in doc.lower(), "agent.md: 不混入使用者说明")

    cmd = (SRC / "start.cmd").read_bytes()
    text = cmd.decode("ascii", "replace")
    check(all(b < 128 for b in cmd), "start.cmd: 纯 ASCII")
    check(b"\r\n" in cmd, "start.cmd: CRLF")
    check("BAB_MODULE_PORT" in text, "start.cmd: 读 BAB_MODULE_PORT")
    check("server.py" in text, "start.cmd: 启动 server.py")

    server_py = (SRC / "server.py").read_bytes()
    check(b"BAB_MODULE_PORT" in server_py, "server.py: 也认 BAB_MODULE_PORT 兜底")
    check(not any(p.name == "__pycache__" for p in SRC.rglob("*")), "源码目录没有 __pycache__")
    check(not list(SRC.rglob("*.pyc")), "源码目录没有 .pyc")


def time_checks(srv) -> None:
    base = datetime(2026, 10, 31, 12, 0, 0).timestamp()
    for text, (want, want_repeat) in CASES.items():
        try:
            got = srv.parse_when(text, base=base)
        except Exception as exc:
            check(False, "parse_when(%r) 抛了 %s" % (text, exc))
            continue
        stamp = datetime.fromtimestamp(got["ts"]).strftime("%Y-%m-%d %H:%M")
        check(stamp == want, "parse_when(%r) = %s（应为 %s）" % (text, stamp, want))
        if want_repeat:
            rep = got.get("repeat") or {}
            same = all(rep.get(k) == v for k, v in want_repeat.items())
            check(same, "parse_when(%r) 的 repeat = %s" % (text, rep))
        else:
            check(got.get("repeat") is None, "parse_when(%r) 不是重复规则" % text)

    for text in BAD_WHENS:
        try:
            srv.parse_when(text, base=base)
            check(False, "parse_when(%r) 应该报看不懂" % text)
        except Exception:
            check(True, "parse_when(%r) 体面报错" % text)

    def after(rule, stamp):
        return datetime.fromtimestamp(srv.next_after(rule, datetime.strptime(stamp, "%Y-%m-%d %H:%M").timestamp()))

    check(after({"kind": "daily", "at": "08:00"}, "2026-10-31 09:00") == datetime(2026, 11, 1, 8, 0),
          "next_after daily")
    check(after({"kind": "weekly", "dow": 0, "at": "10:00"}, "2026-10-31 12:00") == datetime(2026, 11, 2, 10, 0),
          "next_after weekly")
    check(after({"kind": "monthly", "dom": 31, "at": "09:00"}, "2026-10-31 12:00") == datetime(2026, 11, 30, 9, 0),
          "next_after monthly 没有 31 号就取月末")
    check(after({"kind": "monthly", "dom": 1, "at": "09:00"}, "2026-10-31 12:00") == datetime(2026, 11, 1, 9, 0),
          "next_after monthly 1 号")
    check(after({"kind": "every", "seconds": 7200}, "2026-10-31 12:00") == datetime(2026, 10, 31, 14, 0),
          "next_after every 2 小时")


def behavior_checks(srv) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_cap(cap, args=None):
        calls.append((cap, dict(args or {})))
        if cap == "presence.read":
            return {"state": "online"}
        return {"ok": True}

    srv.call_cap = fake_cap
    srv._SETTINGS.update(dict(srv.DEFAULT_SETTINGS))
    srv._SETTINGS_AT = time.time()

    db_path = Path(srv.DB_PATH)
    if db_path.exists():
        db_path.unlink()
    bak = Path(srv.BACKUP_PATH)
    if bak.exists():
        bak.unlink()

    now = time.time()
    with srv.DB_LOCK:
        db = srv.load_db()
        db["reminders"].append({"id": "1", "text": "吃药", "next_at": now - 5, "done": False,
                                "repeat": None, "created_at": now - 100})
        srv.save_db(db)
    check(Path(srv.BACKUP_PATH).exists(), "存册子时留了 .bak")
    fired = srv.tick(now=now)
    check(fired == 1, "到点的提醒被触发（%d）" % fired)
    caps = [c for c, _a in calls]
    check("notice.push" in caps, "触发了 notice.push")
    check("memory.note" in caps, "往记忆抽屉写了镜像")
    pushed = [a for c, a in calls if c == "notice.push"]
    check(bool(pushed) and pushed[0].get("chat") is False, "保姆栏永远先记一条（不靠聊天）")
    check(any(c == "chat.say" for c, _a in calls), "在线时让她本人开口说一句")
    with srv.DB_LOCK:
        db = srv.load_db()
        check(db["reminders"][0]["done"] is True, "一次性提醒触发后标记完成")

    calls.clear()
    srv._SETTINGS["remind_when_away"] = False
    srv._PRESENCE.update({"value": "busy", "at": time.time()})
    now2 = time.time()
    with srv.DB_LOCK:
        db = srv.load_db()
        db["reminders"].append({"id": "2", "text": "喝水", "next_at": now2 - 1, "done": False, "repeat": None})
        srv.save_db(db)
    srv.tick(now=now2)
    pushed = [a for c, a in calls if c == "notice.push"]
    check(bool(pushed) and pushed[-1].get("chat") is False, "关掉「离线也提醒」且人不在线时只进保姆栏")
    with srv.DB_LOCK:
        db = srv.load_db()
        pending = db["meta"].get("pending_chat") or []
    check(len(pending) == 1, "离线期间压了一条待补的聊天（%d）" % len(pending))

    calls.clear()
    srv._PRESENCE.update({"value": "online", "at": time.time()})
    srv.flush_pending_chat()
    check(any(c == "chat.say" for c, _a in calls), "回到在线时补发也由她开口")
    with srv.DB_LOCK:
        db = srv.load_db()
    check(not (db["meta"].get("pending_chat") or []), "补发后清空待办队列")

    # 0.1.2：免打扰时段
    srv._SETTINGS["quiet_hours"] = "23:00-07:00"
    check(srv.in_quiet(datetime(2026, 11, 1, 23, 30)) is True, "免打扰：跨零点的夜里算静音")
    check(srv.in_quiet(datetime(2026, 11, 2, 6, 59)) is True, "免打扰：凌晨也算静音")
    check(srv.in_quiet(datetime(2026, 11, 2, 7, 0)) is False, "免打扰：到点就解除")
    check(srv.in_quiet(datetime(2026, 11, 2, 12, 0)) is False, "免打扰：白天不静音")
    srv._SETTINGS["quiet_hours"] = ""
    check(srv.in_quiet(datetime(2026, 11, 2, 3, 0)) is False, "免打扰：留空就不静音")
    srv._SETTINGS["quiet_hours"] = "乱写"
    check(srv.in_quiet(datetime(2026, 11, 2, 3, 0)) is False, "免打扰：写坏了当没开")

    calls.clear()
    srv._SETTINGS["quiet_hours"] = "00:00-23:59"
    with srv.DB_LOCK:
        db = srv.load_db()
        db["reminders"].append({"id": "9", "text": "静音测试", "next_at": time.time() - 1,
                                "done": False, "repeat": None})
        srv.save_db(db)
    srv.tick()
    pushed = [a for c, a in calls if c == "notice.push"]
    check(bool(pushed) and pushed[-1].get("chat") is False, "免打扰：保姆栏照样记一笔")
    check(not any(c == "chat.say" for c, _a in calls), "免打扰：不开口")
    with srv.DB_LOCK:
        db = srv.load_db()
    check(not (db["meta"].get("pending_chat") or []), "免打扰：不压待补的聊天（不是离线）")
    srv._SETTINGS["quiet_hours"] = ""

    srv._SETTINGS["allow_web"] = False
    out = srv.search_web("昆明 天气")
    check(out.get("code") == "web_off", "关掉上网后查询直接报 web_off")
    srv._SETTINGS["allow_web"] = True

    for bad in ("http://127.0.0.1:8000/x", "http://localhost/x", "http://192.168.1.1/", "http://10.0.0.2/",
                "file:///C:/Windows/win.ini"):
        ok, _why = srv._is_public(bad)
        check(not ok, "拦内网/非法地址：%s" % bad)

    out = srv.tool_note_save({"text": "路由器密码在抽屉第二层"})
    check(out[0] == 200 and out[1].get("category") == "笔记", "记事写进册子并回分类")
    out = srv.tool_note_find({"query": "密码"})
    check(out[0] == 200 and out[1].get("count") == 1, "记事能按关键词翻到")
    out = srv.tool_remind_add({"text": "x", "when": ""})
    check(out[0] == 400 and out[1].get("code") == "bad_args", "空 when 报 bad_args")
    out = srv.tool_remind_add({"text": "x", "when": "我也不知道"})
    check(out[0] == 400 and out[1].get("code") == "bad_when", "看不懂的时间报 bad_when")

    srv.bridge_manifest = lambda: {"module": {"settings": {"note_category": "随笔", "search_level": "较弱搜索"}}}
    srv._SETTINGS_AT = 0.0
    got = srv.module_settings()
    check(got.get("note_category") == "随笔", "从桥上读到自己改过的设置")
    check(got.get("search_level") == "较弱搜索", "choice 设置也读得到")

    code, today = srv.tool_today({})
    check(code == 200 and today.get("summary"), "today 回一句概览")
    check(isinstance(today.get("today_reminders"), list), "today 带回今天的提醒列表")
    check("quiet_hours" in today and "quiet_now" in today, "today 带上免打扰状态")

    code, doc = srv.tool_doctor({})
    check(code == 200 and doc.get("ok") is True, "doctor 能自己报状态")
    check(doc.get("open_todos") == 0 and doc.get("notes", 0) >= 1, "doctor 里的计数对得上")
    check("quiet_hours" in doc, "doctor 报免打扰设置")


def smoke_checks() -> None:
    py = ROOT / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        py = Path(sys.executable)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    env = dict(os.environ)
    env["BAB_MODULE_PORT"] = str(port)
    env["BAB_ROOT"] = str(ROOT / "WiseEntity")
    env["BAB_BRIDGE_TOKEN"] = ""
    proc = subprocess.Popen([str(py), "server.py", "--port", str(port)], cwd=str(SRC), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(80):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.3).close()
                break
            except OSError:
                time.sleep(0.2)
        import urllib.request
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def call(path, payload=None, timeout=15):
            data = None
            headers = {}
            if payload is not None:
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                headers["Content-Type"] = "application/json"
            req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data,
                                         headers=headers, method="POST" if data else "GET")
            try:
                with opener.open(req, timeout=timeout) as res:
                    return res.status, json.loads(res.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as exc:
                return exc.code, json.loads(exc.read().decode("utf-8", "replace") or "{}")

        code, health = call("/health")
        check(code == 200 and health.get("version"), "冒烟：/health 通")
        code, add = call("/remind/add", {"text": "冒烟提醒", "when": "明天 9:00"})
        check(code == 200 and "09:00" in str(add.get("echo")), "冒烟：/remind/add 回了时间")
        code, lst = call("/remind/list")
        check(code == 200 and lst.get("count") >= 1, "冒烟：/remind/list 能列出来")
        code, doc = call("/doctor")
        check(code == 200 and doc.get("ok") is True, "冒烟：/doctor 通")
        code, today = call("/today")
        check(code == 200 and today.get("summary"), "冒烟：/today 通")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()


def main(argv: list[str]) -> int:
    if not SRC.exists():
        skip("没有源码目录（%s），只查包" % SRC)
        return 0
    static_checks()
    srv = load(SRC / "server.py", "routine_server_under_test")
    check(srv.VERSION and srv.MODULE_ID == "routine", "server.py: 版本与 id")
    check(len(srv.TOOLS) == EXPECTED_TOOLS, "server.py: 声明了 %d 个工具" % EXPECTED_TOOLS)
    time_checks(srv)
    behavior_checks(srv)
    if "--smoke" in argv:
        smoke_checks()
    print("")
    if FAILS:
        print("FAILED %d 项：" % len(FAILS))
        for item in FAILS:
            print("  - " + item)
        return 1
    print("PASS %d 项" % OKS)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
