"""启动器耳目：配置、设备、频率，以及那个只开在本机的小门。

不碰真实 config/sense.json，也不真开摄像头/麦克风：把 CFG_PATH 指到临时目录，
把 senses / CoreClient 换成假的。
    D:\\BetterAIBridge\\.venv\\Scripts\\python.exe tools\\test_sense.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def main() -> int:
    import httpx

    from app.services import sense, sense_server

    tmp = Path(tempfile.mkdtemp(prefix="bab-sense-"))
    sense.CFG_PATH = tmp / "sense.json"

    c = sense.cfg()
    check(c["eyes"] is False and c["ears"] is False, "默认两只眼耳都关着")
    check(c["announce"] is True, "默认看/听前会说一声")
    check(c["port"] == 0 and c["token"] == "", "端口/令牌默认空")

    sense.save({"eyes": True, "nonsense": 1})
    c = sense.cfg()
    check(c["eyes"] is True, "保存 eyes=True 读得回来")
    check("nonsense" not in c, "不认识的键不落盘")
    check(bool(c["updated_at"]), "写了 updated_at")
    check(json.loads(sense.CFG_PATH.read_text(encoding="utf-8"))["eyes"] is True,
          "文件里确实是 JSON 且 eyes=true")

    check(sense.next_gap(0) == 0.0, "主动程度 0：不看/听")
    g2 = sense.next_gap(2)
    check(16 * 60 <= g2 <= 26 * 60, f"主动程度 2 的间隔在 16-26 分钟（{g2:.0f}s）")
    g3 = sense.next_gap(3)
    check(7 * 60 <= g3 <= 12 * 60, f"主动程度 3 的间隔在 7-12 分钟（{g3:.0f}s）")

    check(sense.camera_index("") == -1, "没选摄像头 -> -1（走屏幕）")
    check(sense.camera_index("0") == 0, "选 0 号 -> 0")

    real_list = sense.senses.camera_list
    real_mics = sense.senses.list_mics
    sense.senses.camera_list = lambda timeout=8.0: ["Integrated Camera"]  # type: ignore[assignment]
    sense.senses.list_mics = lambda: [{"index": 0, "name": "Mic A", "channels": 2}]  # type: ignore[assignment]
    try:
        d = sense.devices()
        check(d["cameras"] == ["Integrated Camera"], "devices 带上摄像头")
        check(d["mics"][0]["name"] == "Mic A", "devices 带上麦克风")
        sense._cams_cache.update({"at": 0.0, "list": []})
        check(sense.first_camera() == "Integrated Camera",
              "自动模式：没选摄像头时取第一台")
        check(d["camera"] == "" and d["mic"] == "", "devices 回当前选择")
    finally:
        sense.senses.camera_list = real_list  # type: ignore[assignment]
        sense.senses.list_mics = real_mics  # type: ignore[assignment]

    # ---- 小门：该拒的拒、该回的会 ----
    seen: dict = {}

    def fake_look(question: str = "") -> dict:
        seen["look_q"] = question
        return {"ok": True, "text": "看到一张测试图", "source": "screen"}

    def fake_listen(seconds: float = 6.0) -> dict:
        seen["listen_s"] = seconds
        return {"ok": True, "text": "听到一句测试话", "seconds": 3.0}

    sense.look = fake_look  # type: ignore[assignment]
    sense.listen = fake_listen  # type: ignore[assignment]
    info = sense_server.start()
    check(info["ok"] and info["port"] > 0, f"小门起来了（端口 {info['port']}）")
    port = info["port"]
    token = sense.cfg()["token"]
    check(bool(token), "令牌写进了 sense.json")
    check(sense.cfg()["port"] == port, "端口写进了 sense.json")
    base = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(timeout=10) as cli:
            check(cli.get(base + "/health").json().get("ok") is True, "/health 不用令牌")
            check(cli.post(base + "/look", json={}).status_code == 403, "没令牌 -> 403")
            r = cli.post(base + "/look", json={"question": "这是什么"},
                         headers={"X-Sense-Token": token})
            check(r.status_code == 200 and r.json()["text"] == "看到一张测试图", "/look 回描述")
            check(seen.get("look_q") == "这是什么", "/look 把问题带过去")
            r = cli.post(base + "/listen", json={"seconds": 4.5},
                         headers={"X-Sense-Token": token})
            check(r.status_code == 200 and r.json()["text"] == "听到一句测试话", "/listen 回文字")
            check(abs(float(seen.get("listen_s", 0)) - 4.5) < 0.01, "/listen 把秒数带过去")
            check(cli.post(base + "/nope", json={},
                           headers={"X-Sense-Token": token}).status_code == 404, "没这个路口 -> 404")

            # 界面桥：背景读/改、鼠标、mkdiy、只许 ui.* 的配置写入
            from app.core import config as cfgmod

            real_set, real_get = cfgmod.set_value, cfgmod.get
            store = {"ui.background": {"enabled": True, "effect": "blobs",
                                       "follower": "glow", "click": True,
                                       "click_style": "ripple", "opacity": 0.8,
                                       "speed": 1.0}}
            cfgmod.set_value = lambda k, v: store.__setitem__(k, v)  # type: ignore[assignment]
            cfgmod.get = lambda k, d=None: store.get(k, d)  # type: ignore[assignment]
            try:
                r = cli.get(base + "/ui/background", headers={"X-Sense-Token": token})
                check(r.status_code == 200 and r.json()["config"]["effect"] == "blobs",
                      "/ui/background 读得到背景设置")
                r = cli.post(base + "/ui/background", json={"effect": "dots", "opacity": 0.5},
                             headers={"X-Sense-Token": token})
                check(r.status_code == 200 and r.json()["config"]["effect"] == "dots"
                      and abs(float(r.json()["config"]["opacity"]) - 0.5) < 0.01,
                      "/ui/background 改得动观感")
                check(cli.post(base + "/ui/background", json={"media": "C:/x.png"},
                               headers={"X-Sense-Token": token}).status_code == 500,
                      "/ui/background 拒绝 media")
                check(store["ui.background"].get("media") in (None, ""),
                      "media 没被模组塞进去")

                sense_server.set_mouse(12.5, 34.5, True)
                r = cli.get(base + "/ui/mouse", headers={"X-Sense-Token": token})
                check(r.status_code == 200 and r.json()["inside"] is True
                      and abs(float(r.json()["x"]) - 12.5) < 0.1,
                      "/ui/mouse 读得到鼠标位置")

                made = Path(cfgmod.APP_DIR) / f"bridge-mkdir-test-{tmp.name[-6:]}"
                r = cli.post(base + "/fs/mkdir", json={"path": str(made)},
                             headers={"X-Sense-Token": token})
                check(r.status_code == 200 and made.is_dir(), "/fs/mkdir 能建目录")
                made.rmdir()
                r = cli.post(base + "/fs/mkdir", json={"path": "C:/Windows/evil-bab-test"},
                             headers={"X-Sense-Token": token})
                check(r.status_code == 500, "/fs/mkdir 不许出安装目录")

                r = cli.post(base + "/config/set", json={"key": "ui.window_size",
                                                        "value": [1200, 800]},
                             headers={"X-Sense-Token": token})
                check(r.status_code == 200 and store.get("ui.window_size") == [1200, 800],
                      "/config/set 写得进 ui.*")
                r = cli.post(base + "/config/set", json={"key": "core.auto_restart",
                                                        "value": False},
                             headers={"X-Sense-Token": token})
                check(r.status_code == 500, "/config/set 拒绝非 ui.*")
            finally:
                cfgmod.set_value, cfgmod.get = real_set, real_get  # type: ignore[assignment]
    finally:
        sense_server.stop()
    check(not sense_server.info()["ok"], "stop 之后小门关着")
    check(sense.cfg()["port"] == 0, "stop 之后端口清 0")

    # 旧版写在安装目录 config/sense.json，默认路径下要自动搬进 entity/config
    _old = tmp / "old-root" / "sense.json"
    _old.parent.mkdir(parents=True)
    _old.write_text(json.dumps({"eyes": True, "ears": False, "announce": True,
                                "camera": "", "mic": "", "port": 0, "token": ""}),
                    encoding="utf-8")
    sense._OLD_CFG = _old
    sense.CFG_PATH = tmp / "new" / "config" / "sense.json"
    sense._DEFAULT_CFG = sense.CFG_PATH
    sense._migrated_old = False
    sense.cfg()
    check(sense.CFG_PATH.exists()
          and json.loads(sense.CFG_PATH.read_text(encoding="utf-8"))["eyes"] is True,
          "旧安装目录的 sense.json 会搬进 entity/config")

    print()
    if fails:
        print(f"FAILED {len(fails)}")
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
