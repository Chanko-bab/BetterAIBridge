# -*- coding: utf-8 -*-
r"""抖音桥（douyin_bridge）契约与 P1 行为自检（非 pytest，退出码 0/1）。

    D:\BetterAIBridge\.venv\Scripts\python.exe tools\test_module_douyin.py
    ... --smoke   真起一次服务打 /health

源码目录可用 BAB_DOUYIN_SRC 覆盖；默认 D:\Program for BAB\program_douyin_bridge.pbab。
"""
from __future__ import annotations

import importlib
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
SRC = Path(os.environ.get("BAB_DOUYIN_SRC") or r"D:\Program for BAB\program_douyin_bridge.pbab")
EXPECTED_TOOLS = 22

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
    p = s.getsockname()[1]
    s.close()
    return p


def contract() -> None:
    mod = load("module.json")
    conn = load("connection.json")
    schema = load("settings.schema.json")
    tools = (conn.get("provides") or {}).get("tools") or []
    eps = (conn.get("provides") or {}).get("endpoints") or []
    check(mod.get("id") == "douyin_bridge", "id 不是 douyin_bridge")
    check(str(mod.get("version")) == "0.6.5", f"版本不是 0.6.5：{mod.get('version')}")
    check(len(tools) == EXPECTED_TOOLS, f"工具数 {len(tools)} != {EXPECTED_TOOLS}")
    check(len(eps) == EXPECTED_TOOLS, f"端点数 {len(eps)} != {EXPECTED_TOOLS}")
    for t in tools:
        if t.get("endpoint") not in {e.get("name") for e in eps}:
            check(False, f"工具 {t.get('name')} 的端点 {t.get('endpoint')} 不存在")
    names = {t.get("name") for t in tools}
    for want in ("douyin_comments", "douyin_save_image", "douyin_dm_read",
                 "douyin_dm_send", "douyin_spark_keep", "douyin_group_read"):
        check(want in names, f"缺工具 {want}")
    wants = set((mod.get("bridge") or {}).get("wants") or [])
    for cap in ("warehouse.put", "chat.say", "notice.push"):
        check(cap in wants, f"wants 缺 {cap}")
    libs = (mod.get("warehouse") or {}).get("libraries") or []
    check(any(x.get("id") == "media" for x in libs), "缺 warehouse media 库")
    keys = {f.get("key") for f in schema.get("fields") or []}
    for k in ("owner_name", "owner_uid", "enable_dm", "spark_enabled", "group_read_only"):
        check(k in keys, f"settings 缺 {k}")
    script = (SRC / "start.cmd").read_bytes()
    check(not script.startswith(b"\xef\xbb\xbf"), "start.cmd 带 BOM")
    check(b"\r\n" in script and b"\n" not in script.replace(b"\r\n", b""), "start.cmd 不是 CRLF")
    check(b"BAB_MODULE_PORT" in script, "start.cmd 没读 BAB_MODULE_PORT")
    # __pycache__ 是本地跑测试产生的；pack_pbab 会跳过，这里不当作包内容。


def behaviour() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="douyin_test_"))
    os.environ["BAB_ROOT"] = str(tmp)
    sys.path.insert(0, str(SRC))
    for name in ("server", "browser", "scrape"):
        sys.modules.pop(name, None)
    srv = importlib.import_module("server")
    real_im_read = srv.scrape.im_read

    srv.settings = lambda: {
        "owner_name": "小王", "owner_uid": "u1", "enable_dm": True,
        "dm_max_per_day": 1, "spark_enabled": True,
        "spark_window_start": 0, "spark_window_end": 24,
        "spark_max_per_day": 1, "group_read_only": True,
    }
    srv._need_login = lambda: None
    srv.browser.session = lambda: object()
    srv.remember = lambda *a, **k: None
    srv.scrape.comments = lambda sess, url, n: {
        "ok": True,
        "items": [{"text": "好可爱", "images": [
            {"url": "https://p3-sign.douyinpic.com/a.jpg", "width": 10, "height": 20}]}],
    }
    srv.scrape.im_conversations = lambda sess: {"ok": True, "items": [
        {"name": "群A", "group": True, "last": "x"},
        {"name": "小王", "group": False, "last": "y"},
    ]}
    srv.scrape.im_read = lambda sess, target, limit: {"ok": True, "target": target, "items": [
        {"text": "hi", "images": [{"url": "https://p3-sign.douyinpic.com/b.jpg",
                                   "width": 1, "height": 2}]}]}
    srv.scrape.im_send = lambda sess, target, text: {"ok": True, "target": target,
                                                     "verified": True, "text": text}
    srv.scrape.im_spark = lambda sess, target: {"ok": True, "days": 5}

    sent: list[tuple] = []
    srv.call_cap = lambda cap, args=None, timeout=8.0: (sent.append((cap, args)), {"ok": True, "id": "w1"})[1]

    # refs
    ref = srv._image_ref("https://p3-sign.douyinpic.com/a.jpg", "comments")
    check(bool(ref) and srv._image_url(ref) == "https://p3-sign.douyinpic.com/a.jpg", "图片 ref 往返失败")
    check(srv._image_ref("https://evil.example/x.jpg") == "", "非抖音图床也给了 ref")
    check(srv._image_url("dy_nope") == "", "不存在的 ref 给出了 URL")

    out = srv.do_comments({"url": "https://www.douyin.com/video/1"})
    imgs = out["items"][0].get("images") or []
    check(len(imgs) == 1 and "url" not in imgs[0] and imgs[0].get("ref"), "评论图片没换成 ref")

    srv._download_image = lambda url: (b"\x89PNG\r\n\x1a\nxx", "png")
    saved = srv.do_save_image({"ref": imgs[0]["ref"], "name": "a.png"})
    cap, args = sent[-1]
    check(saved.get("ok") and cap == "warehouse.put", "存图没走 warehouse.put")
    check(args.get("kind") == "image" and args.get("library") == "media", "存图参数不对")
    check(args.get("base64"), "存图没带 base64")
    try:
        srv.do_save_image({"ref": "dy_nope"})
        check(False, "过期 ref 也存了")
    except RuntimeError:
        check(True, "")

    # DM：只发给小王，限额 1
    res = srv.do_dm_send({"target": "小王", "text": "你好"})
    check(res.get("ok") and res.get("verified"), "私聊没发出去")
    try:
        srv.do_dm_send({"target": "小王", "text": "再来"})
        check(False, "私聊超了日限额还发")
    except RuntimeError as exc:
        check("额度" in str(exc), f"超限报错不对：{exc}")
    try:
        srv.do_dm_send({"target": "别人", "text": "hi"})
        check(False, "私聊发给了非绑定号")
    except RuntimeError as exc:
        check("不是设置里的你" in str(exc), f"非绑定号报错不对：{exc}")

    out = srv.do_dm_read({"target": "小王"})
    check(out["items"][0]["images"][0].get("ref"), "私信图片没换成 ref")

    # im_read 之前只在“当前页恰好是消息页”时才找会话，从首页读私聊会
    # 报“没找到会话”。这里锁住“先打开消息页”的行为。
    nav: list[str] = []
    old_goto = srv.scrape._im_goto
    srv.scrape._im_goto = lambda sess: (nav.append("goto"), "https://www.douyin.com/messages")[1]

    class _Sess:
        def js(self, script, timeout=0):
            if "const target" in script:
                return {"ok": True, "name": "小王"}
            return []

    try:
        real_im_read(_Sess(), "小王", 5)
    finally:
        srv.scrape._im_goto = old_goto
    check(bool(nav), "im_read 没有先打开消息页（会误报找不到会话）")

    # 火花：今天一次
    srv.call_cap = lambda cap, args=None, timeout=8.0: {"ok": True, "text": "今天也想你"}
    srv._spark_text = lambda: "今天也想你"
    r1 = srv.do_spark_keep({})
    r2 = srv.do_spark_keep({})
    check(r1.get("sent") is True, "火花第一次没发")
    check(r2.get("already") is True, "火花第二次没判 already")
    check("今天也想你" in (r1.get("text") or ""), "火花文本不对")

    g = srv.do_groups()
    check(g.get("count") == 1 and g["items"][0]["name"] == "群A", "群聊没过滤出群")
    gr = srv.do_group_read({"group": "群A"})
    check(gr["items"][0]["images"][0].get("ref"), "群聊图片没换成 ref")
    print("behaviour ok", tmp)


def smoke() -> None:
    port = free_port()
    py = sys.executable
    p = subprocess.Popen([py, "-X", "utf8", str(SRC / "server.py"), "--port", str(port)],
                         cwd=str(SRC), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        end = time.time() + 20
        data = None
        while time.time() < end:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                    data = json.loads(r.read().decode("utf-8", "ignore"))
                break
            except OSError:
                time.sleep(0.3)
        check(bool(data) and data.get("ok"), "服务没起来")
        check(len(data.get("tools") or []) == EXPECTED_TOOLS, "health 工具数不对")
        check(data.get("version") == "0.6.5", "health 版本不对")
    finally:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()


def main() -> int:
    contract()
    behaviour()
    if "--smoke" in sys.argv:
        smoke()
    print(f"PASS {OKS} / FAIL {len(FAILS)}")
    for f in FAILS:
        print(" -", f)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    raise SystemExit(main())
