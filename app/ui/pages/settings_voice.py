"""设置页的语音块：引擎、音色、BreezeBlue、本地 MOSS、试听。

拆出来是为了让 settings.py 只留接线；这些方法依赖 SettingsPage 的控件属性。
"""
from __future__ import annotations

from PySide6.QtWidgets import QFileDialog

from ...core import local_tts


class VoiceActionsMixin:
    def _voice_payload(self) -> dict:
        port = local_tts.saved_port()
        return {
            "voice": str(self.cb_voice.currentData() or ""),
            "rate": self.cb_rate.currentText(),
            "engine": str(self.cb_engine.currentData() or "edge"),
            "preview_engine": str(self.cb_prev_engine.currentData() or "edge"),
            "bb_base": self.ed_bb_base.text().strip(),
            "bb_key": self.ed_bb_key.text().strip(),
            "bb_voice": self.ed_bb_voice.text().strip(),
            "bb_model": self.ed_bb_model.text().strip(),
            "local_url": f"http://127.0.0.1:{port or 18084}",
            "local_voice": str(self.cb_local_voice.currentData() or "Junhao"),
            "local_ref": self.ed_local_ref.text().strip(),
        }

    def _apply_engine_visibility(self) -> None:
        """两个引擎（朗读/试听）各自选：edge 的行、BreezeBlue 的行按需显示。"""
        chat = str(self.cb_engine.currentData() or "edge")
        prev = str(self.cb_prev_engine.currentData() or "edge")
        bb = "breezeblue" in (chat, prev)
        local = "local" in (chat, prev)
        self.row_edge.setVisible("edge" in (chat, prev))
        self.box_bb.setVisible(bb)
        self.box_local.setVisible(local)
        self.lbl_engine_hint.setVisible(bb)
        if local:
            self.refresh_local_tts()

    def on_engine_changed(self) -> None:
        """换引擎：只显示用得上的那几行；本地没装好先要求下载，取消就退回 edge。"""
        self._apply_engine_visibility()
        if getattr(self, "_loading_voice", False):
            return
        if ("local" in (self.cb_engine.currentData(), self.cb_prev_engine.currentData())
                and not local_tts.is_ready()):
            if not self.install_local_tts():
                self._loading_voice = True
                try:
                    if self.cb_engine.currentData() == "local":
                        self.cb_engine.setCurrentIndex(self.cb_engine.findData("edge"))
                    if self.cb_prev_engine.currentData() == "local":
                        self.cb_prev_engine.setCurrentIndex(self.cb_prev_engine.findData("edge"))
                finally:
                    self._loading_voice = False
                self._apply_engine_visibility()
                self.lbl_voice.setText("本地语音包还没装，先退回 edge；想用再点「本地 MOSS」。")
                return
        self.save_voice()

    def refresh_local_tts(self) -> None:
        try:
            ready = local_tts.is_ready()
        except Exception as exc:  # noqa: BLE001
            self.lbl_local.setText(f"（读不到本地语音状态：{exc}）")
            return
        if ready:
            self.lbl_local.setText("已装好。第一次合成会加载模型，可能要几十秒。")
            self.btn_local_install.setText("重装 / 修复")
        else:
            self.lbl_local.setText("还没装。约 760MB 模型 + 依赖，装好才能保存这个声音。")
            self.btn_local_install.setText("下载本地语音包")

    def install_local_tts(self) -> bool:
        if local_tts.is_ready():
            self.refresh_local_tts()
            return True
        from ..dialogs.local_tts_install import LocalTtsInstallDialog

        dlg = LocalTtsInstallDialog(self)
        dlg.exec()
        self.refresh_local_tts()
        return bool(dlg.ok)

    def pick_local_ref(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选一段参考音频（3–10 秒，越干净越好）", "",
            "音频 (*.wav *.mp3 *.flac *.m4a *.ogg);;所有文件 (*)")
        if path:
            self.ed_local_ref.setText(path)
            self.save_voice()

    def clear_local_ref(self) -> None:
        self.ed_local_ref.setText("")
        self.save_voice()

    def refresh_voice(self) -> None:
        def work():
            from ...services.core_client import CoreClient

            return CoreClient(timeout=8).tts_voices()

        def ok(res):
            try:
                cfg = (res or {}).get("config") or {}
                vs = (res or {}).get("voices") or []
                self._loading_voice = True
                eng = str(cfg.get("engine") or "edge")
                i = self.cb_engine.findData(eng)
                self.cb_engine.setCurrentIndex(i if i >= 0 else 0)
                peng = str(cfg.get("preview_engine") or "edge")
                pi = self.cb_prev_engine.findData(peng)
                self.cb_prev_engine.setCurrentIndex(pi if pi >= 0 else 0)
                if vs:
                    self.cb_voice.clear()
                    for v in vs:
                        self.cb_voice.addItem(str(v.get("label") or v.get("id")), str(v.get("id") or ""))
                cur = str(cfg.get("voice") or "")
                if cur:
                    j = self.cb_voice.findData(cur)
                    if j < 0:  # 用户手填的音色不在常用表里，也留住
                        self.cb_voice.addItem(cur, cur)
                        j = self.cb_voice.count() - 1
                    self.cb_voice.setCurrentIndex(j)
                rate = str(cfg.get("rate") or "+0%")
                k = self.cb_rate.findText(rate)
                if k < 0:
                    self.cb_rate.addItem(rate)
                    k = self.cb_rate.count() - 1
                self.cb_rate.setCurrentIndex(k)
                self.ed_bb_base.setText(str(cfg.get("bb_base") or ""))
                self.ed_bb_key.setText(str(cfg.get("bb_key") or ""))
                self.ed_bb_voice.setText(str(cfg.get("bb_voice") or ""))
                self.ed_bb_model.setText(str(cfg.get("bb_model") or ""))
                lv = str(cfg.get("local_voice") or "Junhao")
                li = self.cb_local_voice.findData(lv)
                self.cb_local_voice.setCurrentIndex(li if li >= 0 else 0)
                self.ed_local_ref.setText(str(cfg.get("local_ref") or ""))
                self.lbl_voice.setText("")
            except Exception as e:  # noqa: BLE001
                self.lbl_voice.setText(f"（读不到音色：{e}）")
            finally:
                self._loading_voice = False
                self._apply_engine_visibility()

        self._spawn(work, ok, lambda e: self.lbl_voice.setText(f"（内核没连上：{e}）"))

    def save_voice(self) -> None:
        if getattr(self, "_loading_voice", False):
            return
        p = self._voice_payload()
        if "local" in (p["engine"], p["preview_engine"]) and not local_tts.is_ready():
            self.lbl_voice.setText("本地语音包还没装好，先点「下载本地语音包」。")
            return
        if p["engine"] == "edge" and not p["voice"]:
            return

        def work():
            from ...services.core_client import CoreClient

            return CoreClient(timeout=8).tts_config(**p)

        def ok(_r):
            self.lbl_voice.setText("已保存")

        self._spawn(work, ok, lambda e: self.lbl_voice.setText(f"（保存失败：{e}）"))

    def preview_voice(self) -> None:
        p = self._voice_payload()
        # 走「试听引擎」：BreezeBlue 的音色在内核的 bb_voice 里，别拿 edge 的音色名去顶
        is_edge = p["preview_engine"] == "edge"
        voice = p["voice"] if is_edge else ""
        rate = p["rate"] if is_edge else ""
        local = p["preview_engine"] == "local"
        if local and not local_tts.is_ready():
            self.lbl_voice.setText("本地语音包还没装好，先点「下载本地语音包」。")
            return
        self.lbl_voice.setText("正在加载本地模型，第一次会慢一些…" if local else "正在合成…")

        def work():
            from ...services.core_client import CoreClient

            if local:
                local_tts.start()
            data = CoreClient(timeout=300 if local else 180).tts_say(
                "你好呀，我是这台机器里住着的那个人。", voice, rate,
                use="preview", timeout=300.0 if local else 180.0)
            from ...services import audio
            path = audio.save_audio(data)
            return path, audio.player.play(path)

        def done(res) -> None:
            from .settings import preview_done_text

            path, played = res
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            self.lbl_voice.setText(preview_done_text(size, played))

        self._spawn(work, done, lambda e: self.lbl_voice.setText(f"（试听失败：{e}）"))
