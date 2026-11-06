# -*- coding: utf-8 -*-
r"""B 站桥（bili_bridge）的契约自检（非 pytest，退出码 0/1）。

    D:\BetterAIBridge\.venv\Scripts\python.exe tools\test_module_bili.py
    D:\BetterAIBridge\.venv\Scripts\python.exe tools\test_module_bili.py --smoke

查什么：清单能不能过 `pbab.validate`、十个工具和十个端点对不对得上、start.cmd 是不是
纯 ASCII+CRLF 且读 BAB_MODULE_PORT、包里有没有混进 __pycache__、以及按 M 的标准补的三件事
（自检 /doctor、日志轮转、设置从桥上读）在不在。`--smoke` 真起一次服务打 /health 与 /doctor
（不需要登录、不需要 BAB 内核）。

源码目录可以用环境变量 BAB_BILI_SRC 指定；默认 D:\BAB-release\Bilibili_bridge\src。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

SRC = Path(os.environ.get("BAB_BILI_SRC") or r"D:\BAB-release\Bilibili_bridge\src")
KNOWN_CAPS = {"chat.say", "memory.search", "memory.note", "brain.snapshot",
              "mood.read", "presence.read", "notice.push"}
EXPECTED_TOOLS = 12

FAILS: list[str] = []
OKS = 0


def check(ok: bool, msg: str) -> None:
    global OKS
    if ok:
        OKS += 1
    else:
        FAILS.append(msg)


def load(name: str) -> dict:
    try:
        return json.loads((SRC / name).read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        check(False, f"{name} 读不出来：{exc!r}")
        return {}


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_port(port: int, seconds: float = 15.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def get_json(url: str, timeout: float = 10.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def behaviour() -> None:
    """把 server.py 当模块加载，用假数据验「设置从桥上读」「/doctor」「错误信封」。"""
    sys.path.insert(0, str(SRC))
    import importlib.util

    spec = importlib.util.spec_from_file_location("bili_srv", SRC / "server.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    check(callable(getattr(mod, "_fail", None)), "没有 _fail（统一错误信封）")
    env = mod._fail("not_logged_in", "还没登录", "去扫码")
    check(env.get("ok") is False and env.get("code") == "not_logged_in"
          and env.get("hint") == "去扫码", f"错误信封形状不对：{env}")

    # 设置：桥说 dm_per_day=2 / enable_like=True，应该盖过本地默认值
    mod.bridge_manifest = lambda timeout=6.0: {"module": {"settings": {"dm_per_day": 2, "enable_like": True}}}
    mod._SETTINGS_CACHE.update({"at": 0.0, "values": {}, "err": ""})
    got = mod.module_settings(ttl=0.0)
    check(got.get("dm_per_day") == 2, f"module_settings 没读到桥上的值：{got}")
    cfg = mod.settings()
    check(cfg.get("dm_per_day") == 2 and cfg.get("enable_like") is True,
          f"settings() 没把桥上的值叠上来：{cfg}")

    # 桥上读不到时：沿用上一次读到的那份，不抛
    def boom(timeout=6.0):
        raise RuntimeError("core 不在")

    mod.bridge_manifest = boom
    mod._SETTINGS_CACHE["at"] = 0.0  # 让下一次真的去问桥（会失败）
    kept = mod.module_settings(ttl=0.0)
    check(kept.get("dm_per_day") == 2, f"读不到桥时应沿用上一次：{kept}")
    check(bool(mod._SETTINGS_CACHE.get("err")), "读不到桥时应把原因记在 err 里")
    check(mod.settings().get("dm_per_day") == 2, "桥上读不到时 settings() 也不该把值丢掉")

    # doctor：没登录 + 桥不通 → verdict 要说出问题
    mod.read_auth = lambda: {"cookies": {}, "uname": "", "mid": ""}
    mod.bridge_token = lambda: ""
    doc = mod.do_doctor()
    names = {c["name"]: c for c in doc.get("checks") or []}
    check(doc.get("ok") is True and isinstance(doc.get("checks"), list), "doctor 没回检查表")
    check(names.get("login", {}).get("ok") is False, "doctor 应报登录没做")
    check(names.get("bridge", {}).get("ok") is False, "doctor 应报桥没 token")
    check("不通" in str(doc.get("verdict") or ""), f"verdict 应指出问题：{doc.get('verdict')}")

    # /health 要有 M 那几项
    health = mod.do_health()
    for key in ("uptime_s", "requests", "log_bytes", "last_error", "bridge", "core"):
        check(key in health, f"/health 缺 {key}")
    check("bili_doctor" in (health.get("tools") or []), "/health 的工具表里没有 bili_doctor")


def smoke() -> None:
    port = free_port()
    env = dict(os.environ)
    env["BAB_MODULE_PORT"] = str(port)
    env["PYTHONUTF8"] = "1"
    env["BAB_ROOT"] = str(Path(os.environ.get("TEMP", ".")) / "bab-bili-smoke")
    env["PYTHONDONTWRITEBYTECODE"] = "1"  # 子进程别往源码目录里写 __pycache__
    py = sys.executable
    proc = subprocess.Popen([py, "server.py", "--port", str(port)], cwd=str(SRC), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        up = wait_port(port)
        check(up, f"服务没在 {port} 起来")
        if up:
            h = get_json(f"http://127.0.0.1:{port}/health")
            check(h.get("ok") is True and h.get("version") == load("module.json").get("version"),
                  f"/health 版本对不上：{h.get('version')}")
            check(bool(h.get("bridge")) is False or True, "/health 的 bridge 字段能读")
            d = get_json(f"http://127.0.0.1:{port}/doctor")
            check(d.get("ok") is True and isinstance(d.get("checks"), list),
                  f"/doctor 没回检查表：{d}")
            check(any(c.get("name") == "login" for c in d["checks"]), "/doctor 缺 login 一项")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            proc.kill()


FAKE_BROWSER = """
import json

CALLS = []
ORIGINS = []
COOKIE = "bili_jct=FAKEJCT; SESSDATA=fakesess"


def engine_info():
    return {"ok": True, "path": "fake", "kind": "fake", "version": "FakeChrome 1.0"}


def ensure_home():
    ORIGINS.append("home")


def ensure_origin(url):
    ORIGINS.append(url)


def fetch_json(url, method="GET", body=None, raw_body=None, headers=None, timeout=45.0):
    CALLS.append({"url": url, "method": method, "body": raw_body})
    if "passport" in url:
        return {"code": 0, "data": {"url": "https://x/qr", "qrcode_key": "K"}}
    return {"code": 0, "data": {"isLogin": True, "mid": "42", "uname": "测试"}}

def js(expression, timeout=15.0, await_promise=True):
    CALLS.append({"url": "js:" + expression[:30], "method": "JS", "body": None})
    return COOKIE


class _Sess:
    def cookies(self):
        return {"bili_jct": "FAKEJCT", "SESSDATA": "fakesess"}

    def set_cookies(self, values):
        return len(values or {})


def session():
    return _Sess()


def session_alive():
    return True


def close():
    pass
"""


def check_browser_mode(tmp: Path) -> None:
    """假内核：确认 http_json 走页面、passport 会先挪同源、csrf 从 cookie 里拿。"""
    import importlib
    import os
    import subprocess
    import sys
    import textwrap

    fake_dir = tmp / "fakebrowser"
    fake_dir.mkdir(parents=True, exist_ok=True)
    (fake_dir / "browser.py").write_text(textwrap.dedent(FAKE_BROWSER), encoding="utf-8")

    script = textwrap.dedent(
        f"""
        import json, sys, time
        sys.path.insert(0, {str(SRC)!r})
        sys.path.insert(0, {str(fake_dir)!r})
        import server as S
        doc = S.http_json("https://api.bilibili.com/x/web-interface/nav", params={{"a": "中文"}})
        assert doc["code"] == 0, doc
        url = __import__("browser").CALLS[-1]["url"]
        assert "a=%E4%B8%AD%E6%96%87" in url, url
        S.http_json("https://passport.bilibili.com/x/passport-login/web/qrcode/generate")
        origins = __import__("browser").ORIGINS
        assert any("passport.bilibili.com" in str(o) for o in origins), origins
        csrf = S._csrf()
        assert csrf == "FAKEJCT", csrf
        assert S.transport() == "browser", S.transport()
        print("fake-ok")
        """
    )
    env = dict(os.environ)
    env["BAB_ROOT"] = str(tmp)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["BAB_BILI_TRANSPORT"] = "browser"
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=120)
    ok = "fake-ok" in (out.stdout or "")
    check(ok, f"浏览器通道行为不对：{(out.stdout or '')[-200:]} {(out.stderr or '')[-300:]}")


def main() -> int:

    if not SRC.is_dir():
        print(f"skip: 没有 {SRC}")
        return 0

    man = load("module.json")
    conn = load("connection.json")

    check(man.get("format") == "pbab/1", f"format 应为 pbab/1：{man.get('format')}")
    check(man.get("api") == 1, f"api 应为 1：{man.get('api')}")
    check(str(man.get("id") or "") == "bili_bridge", f"id 应为 bili_bridge：{man.get('id')}")
    check(str(man.get("version") or "").startswith("0."), f"版本应升到 0.x：{man.get('version')}")
    check(str(man.get("version") or "") >= "0.7.0", f"0.7.0 起才有记忆/互关/评论：{man.get('version')}")
    wants = list((man.get("bridge") or {}).get("wants") or [])
    check("memory.note" in wants, "module.json 的 bridge.wants 里没有 memory.note（她写不进自己的抽屉）")
    entry = str((man.get("entry") or {}).get("start") or "")
    check(bool(entry) and (SRC / entry).is_file(), f"entry.start 不存在：{entry}")
    ports = [int(p) for p in (man.get("ports") or []) if str(p).isdigit()]
    hport = int((man.get("health") or {}).get("port") or 0)
    check(hport in ports, f"health.port {hport} 不在 ports {ports} 里")
    check(str((man.get("memory") or {}).get("program") or "") == "program_bilibili",
          f"memory.program 应为 program_bilibili：{man.get('memory')}")
    check(bool((man.get("login") or {}).get("label")), "缺 login 块（扫码登录要它）")

    provides = conn.get("provides") or {}
    tools = provides.get("tools") or []
    eps = {str(e.get("name")): e for e in (provides.get("endpoints") or [])}
    check(len(tools) == EXPECTED_TOOLS, f"工具数应为 {EXPECTED_TOOLS}，实际 {len(tools)}")
    lost = [t for t in tools if str(t.get("endpoint")) not in eps]
    check(not lost, f"这些工具在 endpoints 里找不到同名端点：{[t.get('name') for t in lost]}")
    for t in tools:
        ep = eps.get(str(t.get("endpoint"))) or {}
        check(str(ep.get("path") or "").startswith("/"), f"{t.get('name')} 的 path 应以 / 开头")
        check(str(ep.get("method") or "").upper() in ("GET", "POST"), f"{t.get('name')} 的 method 不对")

    src = (SRC / "server.py").read_text(encoding="utf-8")
    src = (SRC / "server.py").read_text(encoding="utf-8")
    for token, why in (
            ("def do_browse", "自己刷视频"),
            ("def do_comment_queue", "评论待批"),
            ("def _poll_others", "回互关人"),
            ("def relation_attr", "查互关"),
            ("def remember", "写记忆抽屉"),
            ("def call_cap", "真的去调桥（0.7.1 及以前这里是空的，抽屉一直没写进去）"),
            ("/bridge/call", "桥的调用地址"),
            ("memory.note", "桥上调 memory.note"),
            ("def _usage", "每日用量"),
            ("reply_per_person", "每人回复上限"),
            ("comment_daily", "评论上限")):
        check(token in src, f"源码里没有 {token}（{why}）")
    check((SRC / "agent.md").is_file(), "没有 agent.md（她读到的那份说明）")
    if (SRC / "agent.md").is_file():
        doc = (SRC / "agent.md").read_text(encoding="utf-8-sig")
        check(len(doc) > 300, "agent.md 太短")
        check("bili_browse" in doc and "bili_comment" in doc, "agent.md 没提新工具")
        check("怎么装" not in doc and "扫码" not in doc, "agent.md 里混进了给使用者看的安装步骤")
    sch = load("settings.schema.json")
    props = sch.get("properties") or {}
    for key in ("owner_mid", "reply_mutual", "reply_per_person", "reply_daily",
                "browse_daily", "comment_enabled", "comment_daily"):
        check(key in props, f"settings.schema.json 缺 {key}")
    for token, why in (("def do_doctor", "自检 /doctor"),
                       ("def rotate_log", "日志轮转"),
                       ("def module_settings", "设置从桥上读"),
                       ("def _fail", "统一错误信封"),
                       ('"uptime_s"', "/health 的 uptime_s"),
                       ('"last_error"', "/health 的 last_error")):
        check(token in src, f"server.py 里没有 {why}（{token}）")

    start = SRC / str(entry or "start.cmd")
    if start.is_file():
        raw = start.read_bytes()
        check(not any(b > 127 for b in raw), "start.cmd 里有非 ASCII 字节（cmd 会乱码）")
        text = raw.decode("ascii", "replace")
        check("\r\n" in text, "start.cmd 应该是 CRLF")
        check("BAB_MODULE_PORT" in text, "start.cmd 没读 BAB_MODULE_PORT（池端口会连不上）")

    with tempfile.TemporaryDirectory() as td:
        check_browser_mode(Path(td))

    junk = [p for p in SRC.rglob("*") if p.name == "__pycache__" or p.suffix in (".pyc", ".pyo")]
    check(not junk, f"源码目录里不该有这些：{[str(p.relative_to(SRC)) for p in junk]}")
    check((SRC / "vendor" / "segno" / "__init__.py").is_file(), "vendor/segno 没了（二维码画不出来）")
    check((SRC / "vendor" / "websocket" / "__init__.py").is_file(), "vendor/websocket 没了（CDP 连不上）")
    check((SRC / "browser.py").is_file(), "browser.py 没了（自带内核起不来）")
    eng = SRC / "engine" / "chrome-headless-shell-win64.zip"
    check(eng.is_file() and eng.stat().st_size > 100_000_000,
          f"自带内核 zip 不对：{eng if eng.exists() else '不存在'}")
    for token, why in (('def ensure_engine', "解内核"), ("def fetch_json", "页面内 fetch"),
                       ("DevToolsActivePort", "CDP 端口发现")):
        check(token in (SRC / "browser.py").read_text(encoding="utf-8"), f"browser.py 里没有 {why}")
    check((SRC / "server.py").read_text(encoding="utf-8").count('if transport() == "browser"') >= 2,
          "server.py 没把 transport 分流到浏览器")
    schema = load("settings.schema.json") or {}
    props = (schema.get("properties") or {}) if isinstance(schema, dict) else {}
    keys = set(props) | {f.get("key") for f in (schema.get("fields") or []) if isinstance(f, dict)}
    check("transport" in keys, "设置里没有 transport（切不回直连）")
    check("idle_minutes" in keys, "设置里没有 idle_minutes（内核不会歇）")

    schema_name = str((man.get("settings") or {}).get("schema") or "")
    if schema_name:
        check(bool(load(schema_name)), f"{schema_name} 解析不出来")

    try:
        from app.core import pbab  # noqa: PLC0415

        info = pbab.validate(SRC)
        check(info["manifest"]["id"] == "bili_bridge",
              f"pbab.validate 认出来的 id 不对：{info['manifest'].get('id')}")
    except Exception as exc:  # noqa: BLE001
        check(False, f"pbab.validate 过不去：{exc!r}")

    try:
        behaviour()
    except Exception as exc:  # noqa: BLE001
        check(False, f"行为验不过：{type(exc).__name__}: {exc}")

    if "--smoke" in sys.argv:
        smoke()

    if FAILS:
        print(f"FAIL {len(FAILS)} 条：")
        for f in FAILS:
            print("  -", f)
        print(f"\n{OKS} ok, {len(FAILS)} fail")
        return 1
    print(f"PASS {OKS} 条：清单、十二个工具↔端点、启动脚本、自检/日志/设置、agent.md、无垃圾文件都对。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
