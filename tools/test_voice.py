"""语音消息：中性提示词、录音存档/清理、时长与保留策略。"""
from __future__ import annotations

import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from WiseEntity.entity.core import voice_prompt, voice_store  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def make_wav(path: Path, seconds: float, rate: int = 16000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = int(rate * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * frames)
    return path


def main() -> int:
    # ---- 提示词：只说「对方」，不许写死关系 ----
    txt = voice_prompt.build("今天有点累，想早点睡。", 12300)
    check("【语音消息】" in txt and "对方发来一条" in txt, "提示词开头是中性语音消息")
    check("12" in txt and "秒" in txt, "带上时长")
    check("今天有点累" in txt, "带上转写原文")
    check("不要逐字复述" in txt, "提醒按意思理解")
    bad = [w for w in voice_prompt.RELATION_WORDS if w in txt]
    check(not bad, f"模板里没有关系词（发现：{bad}）")
    check(voice_prompt.has_relation_word("我男朋友来了"), "能识别关系词")
    check(not voice_prompt.has_relation_word("今天天气不错"), "普通句子不误判")

    # 说话人自己提到关系词，是内容，不是模板，不能删
    own = voice_prompt.build("我老公刚回来。", 5000)
    check("我老公" in own, "转写里的关系词原样保留，不做审查")

    fail_txt = voice_prompt.build("", 6000, failed=True)
    check("没成功" in fail_txt and "不要猜" in fail_txt, "转写失败时明说，不许猜")

    # ---- 存档：保留 / 临时 / 清理 ----
    root = Path(tempfile.mkdtemp(prefix="bab_voice_"))
    src = make_wav(root / "src.wav", 6.0)
    row = voice_store.save(root, src, source="owner", kept=True, transcript="你好")
    check(row["kept"] is True and row["dur_ms"] >= 5900, "保留：时长从 wav 算出来")
    check(Path(row["path"]).is_file(), "保留：文件落在 voice 目录")
    check(row["path"].endswith(".wav") and "state" in row["path"].replace("\\", "/"),
          "保留：路径在 entity/state 下")
    check(len(voice_store.rows(root)) == 1, "索引里有一条")

    tmp_row = voice_store.save(root, src, source="owner", kept=False, into_temp=True,
                               transcript="临时")
    check(tmp_row["kept"] is False and "Temp" in tmp_row["path"], "不保留：落到临时目录")
    check(voice_store.total_bytes(root) > 0, "总大小非零")

    voice_store.update(root, row["id"], transcript="改过的转写")
    got = voice_store.get(root, row["id"]) or {}
    check(got.get("transcript") == "改过的转写", "转写可回写")

    res = voice_store.clear_all(root)
    check(res["files"] >= 2, f"清除所有音频删了 {res['files']} 个")
    check(not Path(row["path"]).is_file(), "持久文件被删")
    after = voice_store.get(root, row["id"]) or {}
    check(after.get("deleted") is True and after.get("transcript") == "改过的转写",
          "清除后行保留、转写保留")
    check(voice_store.total_bytes(root) == 0, "清除后总大小为 0")

    # 30 天清理：老行删文件、标 deleted
    old = voice_store.save(root, make_wav(root / "old.wav", 5.0), source="owner",
                           kept=True, transcript="旧")
    p = Path(old["path"])
    import time
    voice_store.update(root, old["id"], ts=time.time() - 40 * 86400)
    voice_store.janitor(root, days=30)
    check((voice_store.get(root, old["id"]) or {}).get("deleted") is True, "超期录音被清")
    check(not p.is_file(), "超期文件真的删了")

    # ---- 启动器侧入口必须真的把函数导出（0.6.5 回归：
    # `from WiseEntity.entity.core import voice_store` 只会绑一个局部名字，
    # app.services.voice_store.save 会 AttributeError）----
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "launcher_voice_store", ROOT / "app" / "services" / "voice_store.py"
    )
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    for name in ("save", "rows", "get", "update", "clear_all",
                 "purge_temp", "janitor", "total_bytes"):
        check(callable(getattr(wrapper, name, None)), f"启动器入口导出 {name}()")

    print("\nPASS" if not fails else f"\n{len(fails)} 条失败")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
