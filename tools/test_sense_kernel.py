"""内核侧的耳目：能力清单、转发到启动器的小门、/vision 与 /asr 两个路口。

不联网、不抓图：httpx.post 打桩，只验 URL/头/请求体和边界。
    WiseEntity\\entity\\.venv\\Scripts\\python.exe tools\\test_sense_kernel.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "WiseEntity"))

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


class _Resp:
    def __init__(self, doc: dict, code: int = 200) -> None:
        self.status_code = code
        self._doc = doc
        self.text = json.dumps(doc, ensure_ascii=False)

    def json(self) -> dict:
        return self._doc


def main() -> int:
    from fastapi import HTTPException

    from entity.core import app as core_app
    from entity.core import bridge

    for cap in ("sense.look", "sense.listen", "sense.devices"):
        one = bridge.CAPS.get(cap) or {}
        check(bool(one.get("desc")) and callable(one.get("fn")), f"能力清单里有 {cap}")
    check("question" in (bridge.CAPS["sense.look"]["args"] or {}), "sense.look 带 question 参数")
    check("seconds" in (bridge.CAPS["sense.listen"]["args"] or {}), "sense.listen 带 seconds 参数")

    for cap in ("ui.background.get", "ui.background.set", "ui.mouse.get",
                "fs.mkdir", "config.write"):
        one = bridge.CAPS.get(cap) or {}
        check(bool(one.get("desc")) and callable(one.get("fn")), f"能力清单里有 {cap}")
    check("effect" in (bridge.CAPS["ui.background.set"]["args"] or {}),
          "ui.background.set 带 effect 参数")

    paths = {getattr(r, "path", "") for r in core_app.app.routes}
    check("/vision" in paths, "内核有 POST /vision")
    check("/asr" in paths, "内核有 POST /asr")

    tmp = Path(tempfile.mkdtemp(prefix="bab-sense-k-"))
    old_cfg = bridge._SENSE_CFG
    bridge._SENSE_CFG = tmp / "sense.json"

    # 界面桥：没开启动器时先给中文 503
    try:
        bridge._sense_get("/ui/background")
        check(False, "没开启动器时界面桥应 503")
    except HTTPException as e:
        check(e.status_code == 503, "没开启动器时界面桥 503")

    bridge._SENSE_CFG.write_text(json.dumps({"port": 43210, "token": "tk",
                                             "eyes": True, "ears": True}),
                                 encoding="utf-8")
    import httpx as _hx

    real_post, real_get = _hx.post, _hx.get
    hits: list[dict] = []

    def fake_post(url, json=None, headers=None, timeout=None):
        hits.append({"method": "POST", "url": url, "json": json, "headers": headers})
        return _Resp({"ok": True, "config": {"effect": "dots"}, "path": "x"})

    def fake_get(url, headers=None, timeout=None):
        hits.append({"method": "GET", "url": url, "headers": headers})
        return _Resp({"ok": True, "inside": True, "x": 1.0, "y": 2.0})

    _hx.post, _hx.get = fake_post, fake_get
    try:
        doc = bridge._ui_background_get("m")
        check(doc.get("ok") is True and hits[-1]["url"].endswith("/ui/background")
              and hits[-1]["method"] == "GET", "ui.background.get 走 GET /ui/background")
        bridge._ui_background_set("m", effect="dots", opacity=0.6)
        check(hits[-1]["method"] == "POST"
              and hits[-1]["json"] == {"effect": "dots", "opacity": 0.6},
              "ui.background.set 只把允许的项发过去")
        try:
            bridge._ui_background_set("m", media="C:/x.png")
            check(False, "ui.background.set 应拒绝 media")
        except HTTPException as e:
            check(e.status_code == 400, "ui.background.set 拒绝 media")
        doc = bridge._ui_mouse_get("m")
        check(hits[-1]["url"].endswith("/ui/mouse") and doc.get("inside") is True,
              "ui.mouse.get 走 GET /ui/mouse")
        bridge._fs_mkdir("m", path="sub/dir")
        check(hits[-1]["url"].endswith("/fs/mkdir")
              and hits[-1]["json"] == {"path": "sub/dir"}, "fs.mkdir 把 path 带过去")
        bridge._config_set("m", key="ui.background.opacity", value=0.5)
        check(hits[-1]["url"].endswith("/config/set")
              and hits[-1]["json"]["key"] == "ui.background.opacity",
              "config.write 写 ui.*")
        try:
            bridge._config_set("m", key="core.auto_restart", value=False)
            check(False, "config.write 应拒绝非 ui.*")
        except HTTPException as e:
            check(e.status_code == 400, "config.write 拒绝非 ui.*")
    finally:
        _hx.post, _hx.get = real_post, real_get
    try:
        try:
            bridge._sense_post("/look", {})
            check(False, "没开耳目时应抛 503")
        except HTTPException as e:
            check(e.status_code == 503, "没开耳目时 503 并给中文说明")

        bridge._SENSE_CFG.write_text(json.dumps({"port": 45678, "token": "tok-1"}),
                                     encoding="utf-8")
        got: dict = {}

        def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
            got.update({"url": url, "json": json, "headers": headers, "timeout": timeout})
            return _Resp({"ok": True, "text": "看到一只猫"})

        old_post = bridge.httpx.post
        bridge.httpx.post = fake_post  # type: ignore[assignment]
        try:
            res = bridge._sense_look("m1", question="画面里有什么")
            check(res.get("text") == "看到一只猫", "sense.look 把启动器的回答带回来")
            check(got["url"] == "http://127.0.0.1:45678/look", "请求打到 127.0.0.1 的小门")
            check(got["headers"].get("X-Sense-Token") == "tok-1", "带上令牌")
            check(got["json"].get("question") == "画面里有什么", "问题带过去")

            bridge._sense_listen("m1", seconds=999)
            check(abs(float(got["json"].get("seconds")) - 20.0) < 0.01, "listen 秒数上限 20")
            bridge._sense_listen("m1", seconds=0)
            check(abs(float(got["json"].get("seconds")) - 1.0) < 0.01, "listen 秒数下限 1")

            bridge._sense_devices("m1")
            check(got["url"].endswith("/devices"), "devices 也走小门")
        finally:
            bridge.httpx.post = old_post  # type: ignore[assignment]
    finally:
        bridge._SENSE_CFG = old_cfg

    old_asr = bridge._voice_asr
    bridge._voice_asr = lambda mid, **kw: {"text": "你好", "chars": 2}  # type: ignore[assignment]
    try:
        out = core_app.asr_hear(core_app.AsrIn(path="x.wav"))
        check(out.get("text") == "你好", "/asr 复用语音服务")
    finally:
        bridge._voice_asr = old_asr  # type: ignore[assignment]

    # --- 她知道不知道自己有眼睛耳朵 -------------------------------------
    import asyncio

    from entity.core import llm_box, sense, tool_bus

    tmp2 = Path(tempfile.mkdtemp(prefix="bab-sense-p-"))
    old_scfg = sense.CFG_PATH
    sense.CFG_PATH = tmp2 / "sense.json"
    try:
        sense.CFG_PATH.write_text(json.dumps({"eyes": False, "ears": False}),
                                  encoding="utf-8")
        frag = sense.fragment()
        check("关着" in frag, "没开耳目：提示词直说看不见听不见")
        tool_bus._cache["at"] = 0.0
        names = tool_bus.tools()
        check("look_around" not in names and "listen_now" not in names,
              "没开耳目：工具列表里不出现看/听")

        sense.CFG_PATH.write_text(json.dumps({
            "eyes": True, "ears": True, "camera": "Integrated Camera",
            "mic": "1", "port": 45678, "token": "tok-2",
        }), encoding="utf-8")
        frag = sense.fragment()
        check("Integrated Camera" in frag and "look_around" in frag,
              "开了眼睛：提示词写上摄像头名与 look_around")
        check("麦克风" in frag and "listen_now" in frag,
              "开了耳朵：提示词写上麦克风与 listen_now")
        tool_bus._cache["at"] = 0.0
        names = tool_bus.tools()
        check("look_around" in names and "listen_now" in names,
              "开了耳目：工具列表里出现 look_around / listen_now")

        try:
            sys_txt = llm_box.build_system("web:owner", "")
            check("你的眼睛和耳朵" in sys_txt, "系统提示词里带上耳目那段")
        except Exception as e:  # noqa: BLE001
            check(False, f"拼系统提示词失败：{type(e).__name__}: {e}")

        old_look, old_listen = sense.look, sense.listen
        sense.look = lambda q="": {"ok": True, "source": "camera", "text": f"看到猫（{q}）"}
        sense.listen = lambda s=6.0: {"ok": True, "text": f"听到一句话（{s}秒）"}
        try:
            r = asyncio.run(tool_bus.call("look_around", {"question": "猫"}))
            res = r.get("result") or {}
            check(r.get("ok") is True and "看到猫" in str(res.get("text")),
                  f"look_around 把画面描述带回来（{r}）")
            r = asyncio.run(tool_bus.call("listen_now", {"seconds": 3}))
            res = r.get("result") or {}
            check(r.get("ok") is True and "3" in str(res.get("text")),
                  f"listen_now 把转写带回来（{r}）")

            def boom(q=""):
                raise RuntimeError("耳目没开：主人还没允许你看/听")

            sense.look = boom
            r = asyncio.run(tool_bus.call("look_around", {}))
            check(r.get("ok") is False and "耳目没开" in str(r.get("error")),
                  f"看不了时把原因说给她（{r}）")
        finally:
            sense.look, sense.listen = old_look, old_listen
    finally:
        sense.CFG_PATH = old_scfg
        tool_bus._cache["at"] = 0.0
        import shutil

        shutil.rmtree(tmp2, ignore_errors=True)

    print()
    if fails:
        print(f"FAILED {len(fails)}")
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
