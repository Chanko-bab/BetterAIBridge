"""耳目一直看着/听着：定时采样写进最近感知，并进聊天提示词。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from WiseEntity.entity.core import presence, sense  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="bab_obs_"))
    orig = (sense.OBS_PATH, sense._cfg, sense.eyes, sense.look, presence.is_online)
    try:
        sense.OBS_PATH = tmp / "sense_observations.json"
        sense._cfg = lambda: {"eyes": True, "ears": True, "watch": True,
                              "listen_always": False, "watch_sec": 45,
                              "listen_sec": 90, "listen_len": 7}
        sense.eyes = lambda: True
        presence.is_online = lambda: True
        sense.look = lambda q="", quiet=False: {"ok": True, "text": "用户从门口回来了。"}
        out = sense.auto_observe()
        check(len(out) == 1 and out[0]["kind"] == "看到", f"一直看着采到一条（{out}）")
        check("门口回来" in sense.recent_line(), "最近感知里能读到")
        frag = sense.fragment()
        check("你最近看到的 / 听到的" in frag, "聊天提示词带上最近感知")
        check("用户从门口回来了" in frag, "提示词里有原话")
        second = sense.auto_observe()
        check(second == [], "自定义间隔内不重复采（节流生效）")
        check(sense.watch_sec() == 45.0, "看到间隔可配置")
        check(sense.listen_sec() == 90.0, "听间隔可配置")
        check(sense.listen_len() == 7.0, "每次听几秒可配置")
        sense._cfg = lambda: {"eyes": True, "ears": True, "watch": True,
                              "listen_always": False, "watch_sec": 1,
                              "listen_sec": 99999, "listen_len": 99}
        check(sense.watch_sec() == 30.0, "看间隔下限 30 秒")
        check(sense.listen_sec() == 3600.0, "听间隔上限 60 分钟")
        check(sense.listen_len() == 15.0, "听时长上限 15 秒")
        sense.remember("听到", "他说「我回来了」。")
        check("我回来了" in sense.recent_line(), "听到的也会记下来")
    finally:
        (sense.OBS_PATH, sense._cfg, sense.eyes, sense.look,
         presence.is_online) = orig
    print("\nPASS" if not fails else f"\n{len(fails)} 条失败")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
