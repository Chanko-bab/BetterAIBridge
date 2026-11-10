"""时间感：4h30 没说话、40min 关闭门槛、心跳兜底。"""
from __future__ import annotations

import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "WiseEntity"))

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def _ts(seconds_ago: float) -> str:
    return datetime.fromtimestamp(time.time() - seconds_ago).strftime("%Y-%m-%dT%H:%M:%S")


def main() -> int:
    from entity.core import time_sense as T

    tmp = Path(tempfile.mkdtemp(prefix="bab-time-"))
    old_state, old_sessions = T.STATE_PATH, T.S.SESSIONS_PATH
    T.STATE_PATH = tmp / "time_sense.json"
    T.S.SESSIONS_PATH = tmp / "sessions.json"

    try:
        text = T.fragment()
        check("# 时间" in text and "现在是" in text, "每轮都有当前时间")
        check("距离" not in text, "第一次启动不提距离")

        T.S.write_json(T.S.SESSIONS_PATH, {
            "web:owner": [{"role": "user", "content": "在吗", "ts": _ts(4 * 3600 + 29 * 60)}]
        })
        check("距离上一次说话" not in T.fragment(), "4 小时 29 分还不提")

        T.S.write_json(T.S.SESSIONS_PATH, {
            "web:owner": [{"role": "user", "content": "在吗", "ts": _ts(4 * 3600 + 31 * 60)}]
        })
        text = T.fragment()
        check("距离上一次说话" in text and "4 小时 31 分钟" in text,
              "4 小时 31 分提上一次说话")

        now = time.time()
        T.S.write_json(T.STATE_PATH, {"last_shutdown_at": now - 39 * 60,
                                      "last_alive_at": now - 39 * 60})
        got = T.boot()
        check(got["show"] is False, "关闭 39 分钟不当成长时间")
        check("上一次关闭" not in T.fragment(), "关闭 39 分钟不提关闭句")

        now = time.time()
        T.S.write_json(T.STATE_PATH, {"last_shutdown_at": now - 41 * 60,
                                      "last_alive_at": now - 41 * 60})
        got = T.boot()
        check(got["show"] is True, "关闭 41 分钟算长")
        text = T.fragment()
        check("上一次关闭" in text and "第一句话" in text, "关闭 41 分钟提一次")
        T.consume_boot()
        check("上一次关闭" not in T.fragment(), "提过之后不再重复")

        # 关掉 41 分钟，但上一次说话已经 5 小时：先提关闭，不重复提没说话。
        T.S.write_json(T.S.SESSIONS_PATH, {
            "web:owner": [{"role": "user", "content": "在吗", "ts": _ts(5 * 3600)}]
        })
        now = time.time()
        T.S.write_json(T.STATE_PATH, {"last_shutdown_at": now - 41 * 60,
                                      "last_alive_at": now - 41 * 60})
        T.boot()
        text = T.fragment()
        check("上一次关闭" in text and "距离上一次说话" not in text,
              "关闭句优先，不叠两条")

        # 没有正常退出，只剩心跳：也能估出关闭时长。
        now = time.time()
        T.S.write_json(T.STATE_PATH, {"last_alive_at": now - 2 * 3600})
        got = T.boot()
        check(got["show"] is True and 7000 < got["gap_s"] < 8000,
              "心跳兜底：两小时前还活着")

        # 时钟回拨 / 未来时间不出现负数。
        T.S.write_json(T.S.SESSIONS_PATH, {
            "web:owner": [{"role": "user", "content": "在吗", "ts": _ts(-3600)}]
        })
        T.S.write_json(T.STATE_PATH, {})
        check("距离上一次说话" not in T.fragment(), "未来时间不报负数")
    finally:
        T.STATE_PATH, T.S.SESSIONS_PATH = old_state, old_sessions
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if fails:
        print(f"失败 {len(fails)} 条：")
        for f in fails:
            print(" - " + f)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
