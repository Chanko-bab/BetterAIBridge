"""语音消息 UI：麦克风按钮、录音条、音频气泡（不碰真麦克风）。"""
from __future__ import annotations

import os
import sys
import tempfile
import wave
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["BAB_NO_UNINSTALL"] = "1"
os.environ["BAB_NO_AUTORESTART"] = "1"
os.environ["BAB_NO_PERSIST"] = "1"
os.environ["BAB_NO_ANIM"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.services import audio  # noqa: E402
from app.ui.pages.chat import ChatPage  # noqa: E402
from app.ui.widgets.voice_bubble import VoiceBubble  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


class FakeWin:
    def __init__(self) -> None:
        self.pages: dict = {}

    def show_page(self, *_a, **_k) -> None:
        pass


def make_wav(path: Path, seconds: float = 6.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 16000
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


def main() -> int:
    QApplication.instance() or QApplication([])

    page = ChatPage(FakeWin())
    check(hasattr(page, "btn_mic"), "聊天输入行有麦克风按钮")
    check(page.btn_mic.text() == "🎤", "麦克风默认显示图标")
    check(page.rec_bar.isHidden(), "录音条默认收起")
    check(hasattr(page, "_voice_start") and hasattr(page, "_voice_send")
          and hasattr(page, "_voice_cancel"), "开始/发送/取消三个入口都在")
    check(hasattr(page, "rec_send") and page.rec_send.text() == "发送", "录音条有发送按钮")
    check(not page.rec_send.isEnabled(), "打开麦克风前发送按钮禁用")
    check(hasattr(audio.player, "playing_path"), "播放器能报当前播放的文件")

    tmp = Path(tempfile.mkdtemp(prefix="bab_voice_ui_"))

    class _FakeRec:
        def __init__(self, ms):
            self.ms = ms
            self.active = True
            self.stopped = False

        def elapsed_ms(self):
            return self.ms

        def stop(self):
            self.active = False
            self.stopped = True
            return {"path": str(tmp / "fake.wav"), "ms": self.ms, "bytes": 0}

        def cancel(self):
            self.active = False

    page.rec_bar.show()
    page._rec = _FakeRec(3000)
    page._voice_tick()
    check(not page.rec_send.isEnabled(), "不足 5 秒时发送按钮仍禁用")
    check("还差" in page.rec_hint.text(), "不足 5 秒提示还差几秒")

    page._rec = _FakeRec(90000)
    page._voice_tick()
    check(page._rec_ready and not page._rec_timer.isActive(), "到 90 秒停录、进入待发送")
    check(page.rec_send.isEnabled(), "待发送时发送按钮可用")
    check("90 秒" in page.rec_hint.text(), "到 90 秒提示等发送")
    page._voice_cancel()
    check(not page._rec_ready and page.rec_bar.isHidden(), "取消后回到空闲")

    wav = make_wav(tmp / "6s.wav")
    vb = VoiceBubble({"id": "v1", "path": str(wav), "ms": 6000}, "这是一段转写", "me")
    check(vb.objectName() == "VoiceBubbleMe", "自己的语音用 Me 样式")
    check(vb.time.text() == "0:06", "时长显示成 0:06")
    check(vb.tr_btn.isVisible() or vb.tr_btn.text() == "转写", "有转写时出现「转写」按钮")
    check(vb.tr.isHidden(), "转写默认收起")
    vb.tr_btn.setChecked(True)
    check(not vb.tr.isHidden(), "点一下展开转写")

    gone = VoiceBubble({"id": "v2", "path": str(tmp / "nope.wav"), "ms": 6000})
    check(gone.time.text() == "已清除", "文件没了显示「已清除」")
    check(not gone.btn.isEnabled(), "已清除的语音不能播放")

    her = VoiceBubble({"id": "v3", "path": str(wav), "ms": 3000}, "", "her")
    check(her.objectName() == "VoiceBubbleHer", "她的语音用 Her 样式")

    print("\nPASS" if not fails else f"\n{len(fails)} 条失败")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
