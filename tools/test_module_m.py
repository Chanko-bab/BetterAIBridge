# -*- coding: utf-8 -*-
r"""模组框架 M 的契约自检（非 pytest，退出码 0/1）。

    D:\BetterAIBridge\.venv\Scripts\python.exe tools\test_module_m.py
    D:\BetterAIBridge\.venv\Scripts\python.exe tools\test_module_m.py --smoke

查什么：清单能不能过 `pbab.validate`、二十三个工具和端点对不对得上、桥的申请单
是不是逐条列清、`developing.md` 是否讲清了模组怎么开发、start.cmd 是不是纯 ASCII+CRLF
且读 BAB_MODULE_PORT、包里有没有混进 __pycache__。`--smoke` 会真起一次服务，打 /health 和 /self。

源码目录可以用环境变量 BAB_M_SRC 指定；默认 D:\\Program for BAB\\program_M_framework.pbab，
找不到时回退到旧目录 program_M.pbab。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

sys.dont_write_bytecode = True  # 别往模组源码目录里留 __pycache__
_M_SRC = os.environ.get("BAB_M_SRC")
if _M_SRC:
    SRC = Path(_M_SRC)
else:
    _new = Path(r"D:\Program for BAB\program_M_framework.pbab")
    SRC = _new if _new.is_dir() else Path(r"D:\Program for BAB\program_M.pbab")

# 桥现在给的能力（和 WiseEntity/entity/core/bridge.py 的 CAPS 对齐）；"*" = 全部
KNOWN_CAPS = {"chat.say", "memory.search", "memory.note", "brain.snapshot", "mood.read", "presence.read", "notice.push", "voice.tts", "voice.asr", "vision.describe", "avatar.get", "sense.devices", "sense.look", "sense.listen", "ui.background.get", "ui.background.set", "ui.mouse.get", "fs.mkdir", "config.write", "persona.style.get", "persona.face.get", "*"}

EXPECTED_TOOLS = 23
EXPECTED_CAPS = KNOWN_CAPS - {"*"}

FAILS: list[str] = []
OKS = 0


def check(ok: bool, msg: str) -> None:
    global OKS
    if ok:
        OKS += 1
    else:
        FAILS.append(msg)


def load(name: str) -> dict:
    p = SRC / name
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        check(False, f"{name} 读不出来：{exc!r}")
        return {}


def free_port() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
    finally:
        s.close()


def check_settings() -> None:
    """设置真的能从桥上读回来，并且用在自己的行为里（不然就是摆设）。"""
    import importlib.util

    path = SRC / "server.py"
    if not path.is_file():
        check(False, "server.py 不存在，没法验设置那条链路")
        return
    spec = importlib.util.spec_from_file_location("m_server_under_test", path)
    srv = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(srv)

    fake_settings = {"note_category": "随笔", "quiet": True}
    srv.bridge_manifest = lambda: (200, {"module": {"settings": fake_settings},
                                        "capabilities": []})  # type: ignore[assignment]
    srv._SETTINGS = {}
    srv._SETTINGS_AT = 0.0

    got = srv.module_settings(ttl=0.0)
    check(got.get("note_category") == "随笔", f"module_settings 没读到 note_category：{got}")
    check(srv.quiet() is True, "quiet 设置没生效")

    seen: dict = {}
    srv.call_cap = lambda cap, args=None: (seen.update({"cap": cap, "args": args or {}}),
                                           (200, {"ok": True, "data": {"saved": True}}))[1]  # type: ignore[assignment]
    st, _payload = srv.tool_memory_note({"text": "记得买牛奶"})
    check(st == 200, f"m_memory_note 失败了：{st}")
    check((seen.get("args") or {}).get("category") == "随笔",
          f"没指定分类时应取设置里的 note_category，实际 {seen.get('args')}")

    srv._SETTINGS_AT = 0.0
    _st, me = srv.tool_self({})
    man = json.loads((SRC / "module.json").read_text(encoding="utf-8"))
    check((me.get("settings") or {}).get("note_category") == "随笔", f"/self 没带设置：{me}")
    check(me.get("version") == man.get("version"),
          f"server VERSION 与清单不一致：{me.get('version')} != {man.get('version')}")
    check("core_token" in me, f"/self 没说明 core token：{me}")

    waits: dict = {}
    srv.bridge_events = lambda since, wait: (waits.update({"wait": wait}),
                                             (200, {"ok": True, "events": []}))[1]  # type: ignore[assignment]
    srv.tool_events({"wait": 15})
    check(waits.get("wait") == 0, f"安静模式下 wait 应压成 0，实际 {waits.get('wait')}")


def smoke() -> None:
    port = free_port()
    env = dict(os.environ)
    env.update({"BAB_MODULE_PORT": str(port), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    env.pop("BAB_BRIDGE_TOKEN", None)
    proc = subprocess.Popen([sys.executable, "server.py", "--port", str(port)], cwd=str(SRC),
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    try:
        base = f"http://127.0.0.1:{port}"
        up = False
        for _ in range(60):
            try:
                with urllib.request.urlopen(base + "/health", timeout=2) as r:
                    if r.status == 200:
                        up = True
                        break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        check(up, "服务没起来（/health 不通）")
        if not up:
            return
        with urllib.request.urlopen(base + "/health", timeout=5) as r:
            health = json.loads(r.read().decode("utf-8"))
        check(bool(health.get("ok")) and health.get("name") == "m_framework",
              f"/health 不对：{health}")
        check(len(health.get("tools") or []) == EXPECTED_TOOLS,
              f"/health 报的工具数应为 {EXPECTED_TOOLS}，实际 {len(health.get('tools') or [])}")
        with urllib.request.urlopen(base + "/self", timeout=5) as r:
            me = json.loads(r.read().decode("utf-8"))
        check(me.get("id") == "m_framework" and int(me.get("port") or 0) == port, f"/self 不对：{me}")
        check(me.get("token") in ("有", "没有"), f"/self 应报有没有钥匙：{me.get('token')}")
        # 没有钥匙时，摸桥要给出人话而不是崩
        st, body = 0, ""
        try:
            with urllib.request.urlopen(base + "/bridge/caps", timeout=20) as r:
                st, body = r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            st, body = exc.code, exc.read().decode("utf-8", "replace")
        check(st in (200, 503), f"没钥匙时 /bridge/caps 的状态码怪：{st}")
        if st != 200:
            low = body.lower()
            check("token" in low or "钥匙" in body or "连不上" in body,
                  f"没钥匙时的报错应说人话，实际 {body[:120]}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            proc.kill()


def check_rename_migration() -> None:
    """0.4.0：旧 id `m` 装过的，启动时要能无痛迁到 `m_framework`。"""
    import shutil

    from app.core import pbab, registry  # noqa: PLC0415

    tmp = Path(tempfile.mkdtemp(prefix="bab-rename-"))
    bundle = tmp / "bundle"
    old_dir = bundle / "program_m.pbab"
    old_dir.mkdir(parents=True)
    (old_dir / "module.json").write_text("{}", encoding="utf-8")
    keep_bd, keep_path = pbab.bundle_dir, registry.path
    pbab.bundle_dir = lambda: bundle
    registry.path = lambda: bundle / "registry.json"
    try:
        registry.save({"format": "bab-registry/1", "modules": {
            "m": {"id": "m", "name": "模组框架 M", "dir": str(old_dir), "state": "disabled",
                  "memory": {"program": "program_m"}},
        }})
        moved = pbab.migrate_legacy_ids()
        check("m->m_framework" in moved, f"应迁移 m（实际 {moved}）")
        check(not old_dir.exists(), "旧安装目录应已改名")
        new_dir = bundle / "program_m_framework.pbab"
        check(new_dir.is_dir(), f"新安装目录应存在：{new_dir}")
        rec = registry.get("m_framework") or {}
        check(rec.get("id") == "m_framework" and rec.get("folder") == new_dir.name,
              f"registry 应指向新 id 和新目录（实际 {rec}）")
        check(registry.get("m") is None, "旧 id 不该还留在 registry")
        check((rec.get("memory") or {}).get("program") == "program_m",
              "记忆抽屉名（program_m）不该跟着改，否则她记过的东西全找不到")
        check(pbab.migrate_legacy_ids() == [], "迁移过一次之后不该重复迁移")

        # 鬼记录：registry 里有 m、但安装目录早没了 → 清掉，不能改名成新模组挂到界面上
        registry.save({"format": "bab-registry/1", "modules": {
            "m": {"id": "m", "name": "模组框架 M", "dir": str(bundle / "program_m.pbab"),
                  "state": "disabled"},
        }})
        again = pbab.migrate_legacy_ids()
        check("m->drop" in again, f"目录不存在的旧记录应清掉（实际 {again}）")
        check(registry.get("m") is None and registry.get("m_framework") is None,
              "清掉之后新旧 id 都不该留在 registry（没装就没有信息）")

        # 通用清理：任何目录不在的模组记录都不该继续挂在界面上
        registry.save({"format": "bab-registry/1", "modules": {
            "ghost": {"id": "ghost", "name": "幽灵", "dir": str(bundle / "program_ghost.pbab")},
            "alive": {"id": "alive", "name": "还在", "dir": str(new_dir)},
        }})
        gone = pbab.prune_missing()
        check("ghost" in gone and "alive" not in gone,
              f"只清目录不在的（实际 {gone}）")
        check(registry.get("ghost") is None and registry.get("alive") is not None,
              "在的那条要留着")
    finally:
        pbab.bundle_dir = keep_bd
        registry.path = keep_path
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    if not SRC.is_dir():
        print(f"skip: 没有 {SRC}")
        return 0

    man = load("module.json")
    conn = load("connection.json")

    # 清单
    check(man.get("format") == "pbab/1", f"format 应为 pbab/1：{man.get('format')}")
    check(man.get("api") == 1, f"api 应为 1：{man.get('api')}")
    check(str(man.get("id") or "") == "m_framework", f"id 应为 m_framework：{man.get('id')}")
    check(bool(man.get("version")), "缺 version")
    entry = (man.get("entry") or {}).get("start") or ""
    check(bool(entry) and (SRC / entry).is_file(), f"entry.start 不存在：{entry}")
    ports = [int(p) for p in (man.get("ports") or []) if str(p).isdigit()]
    hport = int((man.get("health") or {}).get("port") or 0)
    check(hport in ports, f"health.port {hport} 不在 ports {ports} 里")
    check(str((man.get("memory") or {}).get("program") or "") == "program_m",
          f"memory.program 应为 program_m：{man.get('memory')}")

    # 桥的申请单：逐条写清楚（框架也要给人看得懂；"*" 只是高级简写，不在 M 里用）
    wants = [str(x) for x in ((man.get("bridge") or {}).get("wants") or [])]
    check(bool(wants), "bridge.wants 是空的，装了也碰不到东西")
    check("*" not in wants, 'M 自己要用逐条清单，别用 ["*"]（看的人不知道它到底用了什么）')
    unknown = [w for w in wants if w not in KNOWN_CAPS]
    check(not unknown, f"申请了不存在的 cap：{unknown}")
    check(set(wants) == EXPECTED_CAPS,
          f"要逐条申请全部能力（缺 {sorted(EXPECTED_CAPS - set(wants))}，多 {sorted(set(wants) - EXPECTED_CAPS)}）")

    # 工具 ↔ 端点
    provides = conn.get("provides") or {}
    # 0.1.4：三份说明分家——introduce 给人，agent.md 给她
    check((SRC / "agent.md").is_file(), "缺 agent.md（她读的操作须知）")
    if (SRC / "agent.md").is_file():
        doc = (SRC / "agent.md").read_text(encoding="utf-8-sig")
        check(len(doc) > 400, "agent.md 太短")
        check("m_state" in doc and "m_bridge_call" in doc and "m_notice" in doc,
              "agent.md 没讲清工具怎么用")
        check("怎么装" not in doc and "安装" not in doc, "agent.md 里混进了给使用者看的安装步骤")
    intro = (SRC / "introduce.md").read_text(encoding="utf-8-sig")
    check("给你看的说法" in intro or "你会在什么时候看到" in intro,
          "introduce.md 还像写给她看的（应改成给使用者看的）")
    check(str(man.get("version") or "") >= "0.2.1", f"版本应 >= 0.2.1，实际 {man.get('version')}")

    # M 是框架：必须自带一份讲得清的开发说明
    guide = SRC / "developing.md"
    check(guide.is_file(), "缺 developing.md（模组是怎么开发的）")
    if guide.is_file():
        g = guide.read_text(encoding="utf-8-sig")
        check(len(g) > 3000, f"开发说明太短（{len(g)} 字），讲不清")
        for word in ("module.json", "connection.json", "requires", "pack_pbab", "BAB_MODULE_PORT"):
            check(word in g, f"开发说明里没讲到 {word}")
    src_guide = (SRC / "server.py").read_text(encoding="utf-8", errors="replace")
    check("tool_dev_guide" in src_guide, "server.py 里没有 m_dev_guide 工具")
    check("/dev/guide" in src_guide, "server.py 里没有 /dev/guide 路由")

    tools = provides.get("tools") or []
    eps = {str(e.get("name")): e for e in (provides.get("endpoints") or [])}
    check(len(tools) == EXPECTED_TOOLS, f"工具数应为 {EXPECTED_TOOLS}，实际 {len(tools)}")
    src = (SRC / "server.py").read_text(encoding="utf-8")
    check("def tool_doctor" in src, "server.py 里没有 tool_doctor（自检工具）")
    check("/doctor" in src, "server.py 里没有 /doctor 路由")
    check("def rotate_log" in src, "server.py 里没有 rotate_log（日志轮转）")
    check('"uptime_s"' in src and '"last_error"' in src,
          "/health 没带 uptime_s / last_error")
    check("no_token" in src, "错误信封里没有 code（no_token）")

    lost = [t for t in tools if str(t.get("endpoint")) not in eps]
    check(not lost, f"这些工具在 endpoints 里找不到同名端点：{[t.get('name') for t in lost]}")
    for t in tools:
        ep = eps.get(str(t.get("endpoint"))) or {}
        path = str(ep.get("path") or "")
        method = str(ep.get("method") or "").upper()
        check(path.startswith("/"), f"{t.get('name')} 的 path 应以 / 开头：{path}")
        check(method in ("GET", "POST"), f"{t.get('name')} 的 method 应 GET/POST：{method}")

    # 启动脚本
    start = SRC / str(entry or "start.cmd")
    if start.is_file():
        raw = start.read_bytes()
        check(not any(b > 127 for b in raw), "start.cmd 里有非 ASCII 字节（cmd 会乱码）")
        text = raw.decode("ascii", "replace")
        check("\r\n" in text, "start.cmd 应该是 CRLF")
        check("BAB_MODULE_PORT" in text, "start.cmd 没读 BAB_MODULE_PORT（池端口会连不上）")

    # 不给打包添垃圾
    junk = [p for p in SRC.rglob("*") if p.name == "__pycache__" or p.suffix in (".pyc", ".pyo")]
    check(not junk, f"源码目录里不该有这些：{[str(p.relative_to(SRC)) for p in junk]}")

    # 设置表能解析
    schema_name = str((man.get("settings") or {}).get("schema") or "")
    if schema_name:
        check(bool(load(schema_name)), f"{schema_name} 解析不出来")

    # 和外壳的校验器对一遍（能过才算真能装）
    try:
        from app.core import pbab  # noqa: PLC0415

        info = pbab.validate(SRC)
        check(info["manifest"]["id"] == "m_framework",
              f"pbab.validate 认出来的 id 不对：{info['manifest']}")
    except Exception as exc:  # noqa: BLE001
        check(False, f"pbab.validate 过不去：{exc!r}")

    # 设置这条链路：server.py 要真的去读，别只在 schema 里写着
    src_text = (SRC / "server.py").read_text(encoding="utf-8", errors="replace")
    check("module_settings" in src_text, "server.py 里没有 module_settings（设置读不回来）")
    check("note_category" in src_text, "server.py 没把 note_category 用在行为里")
    try:
        check_settings()
    except Exception as exc:  # noqa: BLE001
        check(False, f"设置链路验不过：{type(exc).__name__}: {exc}")

    try:
        check_rename_migration()
    except Exception as exc:  # noqa: BLE001
        check(False, f"旧 id 迁移验不过：{type(exc).__name__}: {exc}")

    if "--smoke" in sys.argv:
        smoke()

    if FAILS:
        print(f"FAIL {len(FAILS)} 条：")
        for f in FAILS:
            print("  -", f)
        print(f"\n{OKS} ok, {len(FAILS)} fail")
        return 1
    print(f"PASS {OKS} 条：清单、桥申请单、二十三个工具↔端点、开发说明、启动脚本、无垃圾文件都对。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
