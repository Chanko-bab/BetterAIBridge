"""页面接线与播放器契约的离屏检查（0.3.5 的三处回归各有一条断言）。

不依赖内核、不弹窗，随时可跑：

    .venv\\Scripts\\python.exe tools\\test_pages.py

退出码 0 = 全过；1 = 有断言失败（会逐条打印 FAIL）。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 卸载测试绝不能真删开发树（2026-10-31 事故）
os.environ["BAB_NO_UNINSTALL"] = "1"
os.environ["BAB_NO_AUTORESTART"] = "1"   # 页面测试别真去拉起内核（0.4.4 的看门狗会）
os.environ["BAB_NO_PERSIST"] = "1"       # 别把测试窗口大小写进用户配置
os.environ["BAB_NO_ANIM"] = "1"          # 切页淡入不参与断言
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from app.core import config as _cfg  # noqa: E402
from app.services import audio  # noqa: E402
from app.services import core_client as _core_client  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

# 机器上可能真跑着一份程序（40720 有人应答）：页面一 show 就会去读真实配置，
# 默认值断言会被带跑偏，还可能顺手改到真配置。整套测试把内核地址指到没人听的端口。
_orig_client_init = _core_client.CoreClient.__init__


def _dead_client_init(self, base=None, timeout=8.0):
    _orig_client_init(self, "http://127.0.0.1:1", timeout)


_core_client.CoreClient.__init__ = _dead_client_init

NAV_PAGES = ("chat", "mods", "services", "logs", "settings", "details")
MIN_NAV_HEIGHT = 34  # 13px 字 + 上下各 9px padding，低于这个数就会裁字

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def find_mp3() -> Path | None:
    """找一段真的能播的 mp3 当正样本；找不到就跳过这条。"""
    cands = []
    cache = ROOT / "WiseEntity" / "entity" / "state" / "tts_cache"
    if cache.is_dir():
        cands += sorted(cache.glob("*.mp3"), key=lambda p: p.stat().st_size)
    tmp = Path(os.environ.get("TEMP", "")) / "bab-tts"
    if tmp.is_dir():
        cands += sorted(tmp.glob("*.mp3"), key=lambda p: p.stat().st_size)
    for p in cands:
        if p.stat().st_size > 0:
            return p
    return None


def load_theme(app: QApplication) -> None:
    """和 main.py:75-80 一样把 QSS 挂上去——不挂的话量出来的按钮高度不是真实高度。"""
    qss = ROOT / "app" / "ui" / "theme" / "style.qss"
    try:
        app.setStyleSheet(qss.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"warn 读不到 style.qss：{exc}")


def main() -> int:
    app = QApplication(sys.argv[:1])
    load_theme(app)
    win = MainWindow()
    win.show()
    app.processEvents()

    # --- 1. 每个页面都必须真的进了 QStackedWidget，否则 show_page 是空操作
    check(win.titlebar.title_label.text() == "Better AI Bridge Launcher",
          f"标题栏固定写 Better AI Bridge Launcher（实际 {win.titlebar.title_label.text()!r}）")
    from app.services import update as _update  # noqa: PLC0415
    check(getattr(win, "version_label", None) is not None, "侧栏底部有版本号")
    if getattr(win, "version_label", None) is not None:
        want_ver = _update.version() or "版本未知"
        check(win.version_label.text() == want_ver,
              f"版本号显示正确（实际 {win.version_label.text()!r}，应为 {want_ver!r}）")
    check(getattr(win, "avatar_card", None) is not None, "侧栏有方形头像卡")
    for key in NAV_PAGES:
        win.show_page(key)
        app.processEvents()
        page = win.pages.get(key)
        idx = win.stack.indexOf(page) if page is not None else -1
        check(page is not None and idx >= 0, f"pages[{key}] 在 QStackedWidget 里（index={idx}）")

    # 外观页不在主导航里，但测试要用到；懒加载后得先让它建出来
    win.show_page("appearance")
    app.processEvents()

    # --- 2. 点页面必须真的切过去（日志页「点不开」就是这条）
    for key in NAV_PAGES:
        if key not in win.pages:
            continue
        win.show_page(key)
        app.processEvents()
        cur = win.stack.currentWidget()
        got = "None" if cur is None else type(cur).__name__
        check(cur is win.pages[key], f"show_page({key}) 后当前页是 {got}")

    # --- 3. 导航按钮高度容得下字（底部「日志」被压就是这条）
    for key, btn in win.buttons.items():
        check(btn.height() >= MIN_NAV_HEIGHT,
              f"nav[{key}] 高度 {btn.height()} ≥ {MIN_NAV_HEIGHT}（不被裁字）")

    # --- 4. 日志页自己的最小高度还在（0.3.4 的修复别被改回去）
    win.show_page("logs")
    app.processEvents()
    logs = win.pages.get("logs")
    view = getattr(logs, "view", None)
    check(view is not None and view.minimumHeight() >= 260,
          f"logs.view 最小高度 {getattr(view, 'minimumHeight', lambda: -1)()} ≥ 260")

    # --- 5. 播放器必须说真话：放不出来要返回 False，而不是静默 None
    check(audio.player.play(Path("C:/definitely/not/here-0.3.5.mp3")) is False,
          "play(不存在的文件) 返回 False")

    sample = find_mp3()
    if sample is None:
        print("skip play(真 mp3) —— 本机没有可用的 mp3 样本")
    else:
        ok = audio.player.play(sample)
        check(ok is True, f"play({sample.name}) 返回 True（会真的响一声）")
        check(getattr(audio.player, "last_error", "?") == "",
              f"播放成功后 last_error 为空（现在是 {getattr(audio.player, 'last_error', '?')!r}）")
        audio.player.stop()

        # 5b. 真的播了多久：play_wait 阻塞到播完，没播的话会立刻返回
        t0 = time.time()
        waited = audio.player.play_wait(sample)
        spent = time.time() - t0
        check(waited is True and spent >= 1.0,
              f"play_wait 真的等了 {spent:.2f}s（没播会瞬间返回）")

    # --- 6. 试音那行字必须说实话（放不出声就不能写「试听放出来了」）
    try:
        from app.ui.pages.settings import preview_done_text  # noqa: PLC0415
    except ImportError:
        check(False, "settings.preview_done_text 存在（试音提示要能区分合成了/放没放出来）")
    else:
        said = preview_done_text(24576, True)
        lied = preview_done_text(24576, False)
        check("正在播放" in said and "24 KB" in said, f"试音成功文案：{said!r}")
        check("正在播放" not in lied and ("没出声" in lied or "放不" in lied),
              f"试音失败文案：{lied!r}")

    # --- 7. 页面销毁后后台线程回来，不能再炸（退出时不打 traceback）
    settings_page = win.pages.get("settings")
    if settings_page is not None:
        # 回调自己炸了，处理异常的那段代码不能跟着炸（0.3.4 里 self.log 不存在）
        try:
            settings_page._run_task_cb((None, None))
            check(True, "回调抛异常时 _run_task_cb 自己不再炸")
        except Exception as exc:  # noqa: BLE001
            check(False, f"回调异常处理炸了：{type(exc).__name__}: {exc}")

        settings_page.deleteLater()
        app.processEvents()
        try:
            settings_page._emit((None, None))
            check(True, "页面销毁后 _emit 不抛异常")
        except Exception as exc:  # noqa: BLE001
            check(False, f"页面销毁后 _emit 炸了：{type(exc).__name__}: {exc}")

    # --- 8. 模组页要能发现 program_cache 里还没装的包（安装包会带两个）
    mods_page = win.pages.get("mods")
    if mods_page is not None:
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory(prefix="bab_pk_") as td:
            root = Path(td)
            sample = ROOT / "program_cache" / "program_web_bridge.pbab"
            if not sample.exists():
                print("skip 本地模组包发现 —— 没有 program_web_bridge.pbab 样本")
            else:
                shutil.copy2(sample, root / sample.name)
                try:
                    found = mods_page._local_packages(root)
                except Exception as exc:  # noqa: BLE001
                    check(False, f"模组页 _local_packages 不存在或炸了：{type(exc).__name__}: {exc}")
                    found = []
                check(len(found) == 1 and str(found[0][1].get("id")) == "web_bridge",
                      f"发现本地模组包（{[str(p.name) for p, _ in found]}）")
                (root / "坏包.pbab").write_bytes(b"not a zip at all")
                try:
                    again = mods_page._local_packages(root)
                    check(len(again) == 1, "坏包被跳过，不抛异常")
                except Exception as exc:  # noqa: BLE001
                    check(False, f"遇到坏包就炸了：{type(exc).__name__}: {exc}")

    # --- 9. 托盘菜单：只留「强制在线」，别让人猜「我现在忙」是什么意思
    tray_menu = win.tray.contextMenu()
    tray_texts = [a.text() for a in tray_menu.actions() if a.text()]
    check(any("强制在线" in t for t in tray_texts), f"托盘菜单里有「强制在线」（实际 {tray_texts}）")
    check(not any("我现在忙" in t for t in tray_texts), "托盘菜单里去掉了「我现在忙」")
    forced: dict[str, str] = {}
    orig_set_presence = win._set_presence
    win._set_presence = lambda state: forced.setdefault("state", state)
    try:
        for act in tray_menu.actions():
            if "强制在线" in act.text():
                act.trigger()
    finally:
        win._set_presence = orig_set_presence
    check(forced.get("state") == "online", f"点「强制在线」把状态改成 online（实际 {forced}）")

    # --- 10. 状态按钮：在线 / 忙碌，字数对称
    chat_page = win.pages.get("chat")
    if chat_page is not None:
        check(chat_page.btn_busy.text() == "忙碌",
              f"忙碌按钮写「忙碌」（实际 {chat_page.btn_busy.text()!r}）")
        check(chat_page.btn_online.text() == "在线",
              f"在线按钮写「在线」（实际 {chat_page.btn_online.text()!r}）")
        try:
            busy_text = chat_page._presence_text("busy")
            online_text = chat_page._presence_text("online")
        except Exception as exc:  # noqa: BLE001
            check(False, f"_presence_text 不存在或炸了：{type(exc).__name__}: {exc}")
            busy_text, online_text = "", ""
        check(busy_text == "● 忙碌", f"状态点是「● 忙碌」（实际 {busy_text!r}）")
        check(online_text == "● 在线", f"状态点是「● 在线」（实际 {online_text!r}）")

        # --- 10a. AI 生成标识：常驻在输入框下方
        check(getattr(chat_page, "ai_label", None) is not None, "聊天页有 AI 生成标识")
        if getattr(chat_page, "ai_label", None) is not None:
            check(chat_page.ai_label.text().startswith("对话内容由 AI 生成"),
                  f"AI 标识文案（实际 {chat_page.ai_label.text()!r}）")

        # --- 10c. 教程改成六页向导
        from app.ui.dialogs.tutorial import PAGES, TutorialWelcome

        tut = TutorialWelcome()
        try:
            check(len(PAGES) == 6, f"教程页数（实际 {len(PAGES)}）")
            check(tut.stack.count() == 6, f"教程 QStackedWidget 页数（实际 {tut.stack.count()}）")
            check(tut.btn_next.text() == "下一页", "第一页的按钮是「下一页」")
            for _ in range(5):
                tut._next()
            check(tut.btn_next.text() == "完成", "最后一页的按钮是「完成」")
            _all = " ".join(str(x[1]) for x in PAGES)
            check("在线" in _all and "忙碌" in _all, "教程里讲了「在线 / 忙碌」状态")
        finally:
            tut.deleteLater()

        # --- 10b. 输入框：Enter 发送、Shift+Enter 换行（内测反馈）
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtTest import QTest

        from app.ui.pages.chat import ChatInput

        ci = ChatInput()
        ci.show()
        try:
            QTest.keyClicks(ci, "line one")
            QTest.keyClick(ci, _Qt.Key_Return, _Qt.ShiftModifier)
            QTest.keyClicks(ci, "line two")
            check("\n" in ci.text() and "line two" in ci.text(),
                  f"Shift+Enter 应换行（实际 {ci.text()!r}）")
            sent_input: list[str] = []
            ci.submitted.connect(lambda: sent_input.append(ci.text()))
            QTest.keyClick(ci, _Qt.Key_Return)
            check(len(sent_input) == 1, f"Enter 只发一次（实际 {len(sent_input)} 次）")
            max_h = ci._one_line_h() + (ChatInput.MAX_LINES - 1) * ci._line_h()
            check(ci.height() <= max_h, f"输入框高度不超过 8 行（实际上限 {max_h}px）")
            check(ChatInput.MAX_LINES == 8, "输入框最多 8 行")
        finally:
            ci.close()

        # --- 11. 说好几句时被打断：后面没出口的几句收回，只记一次情绪，不接着放
        import threading

        from app.ui.pages import chat as chat_mod

        def pump(ms: int) -> None:
            end = time.time() + ms / 1000.0
            while time.time() < end:
                app.processEvents()
                time.sleep(0.01)

        stops: list[int] = []
        emotions: list[tuple] = []
        pushed: list[str] = []
        said: list[str] = []
        audio.player.stop = lambda: stops.append(1)
        gate = threading.Event()
        started: list[str] = []

        def fake_play_wait(path):
            started.append(Path(path).name)
            gate.wait(3.0)
            return True

        class FakeClient:
            """不让测试真去连内核：合成返回字节，情绪只记在本地。"""

            def __init__(self, *a, **kw):
                pass

            def tts_say(self, text, voice=None, rate=None):
                said.append(text)
                return b"ID3fake"

            def emotion_stimulus(self, kind, intensity=1.0):
                emotions.append((kind, intensity))
                return {"ok": True}

            def feed(self, session=None, after=0):
                return {"messages": [], "total": 0}

            def presence(self):
                return {"state": "busy"}

            def set_presence(self, state):
                return {"ok": True, "state": state}

            def tts_voices(self):
                return {"ok": True, "voices": [], "config": {"rate": "-30%"}}

            def notice_push(self, text, session=None, kind=None):
                pushed.append(text)
                return {"ok": True}

            def notices(self, session=None, after=0):
                return [{"ts": 1700000000.0, "text": "对方主动找您"}]

            def tutorial_get(self):
                return {"mode": "deferred", "seen": False, "pending_since": 0}

            def tutorial_update(self, *a, **kw):
                return {"ok": True, "mode": "done", "pending_since": 0}

            def mood(self, *a, **kw):
                return {"mood": "平平的"}

            def memory_stats(self):
                return {"total": 0}

            def chat(self, *a, **kw):
                return {"ok": True, "reply": "", "messages": []}

        orig_play_wait = audio.player.play_wait
        orig_save = audio.save_audio
        orig_client = chat_mod.CoreClient
        audio.player.play_wait = fake_play_wait
        audio.save_audio = lambda data: Path("r:\\tts\\fake.mp3")
        chat_mod.CoreClient = FakeClient
        chat_page.speak.setChecked(True)
        try:
            # 一次三句：第一句在念，后两句只在她嘴上
            before = chat_page.msg_lay.count()
            chat_page._deliver(["第一句，说慢一点", "第二句，还没出口", "第三句，也没出口"], 0, 3, 0)
            pump(1800)
            check(bool(started), f"第一句开始念了（started={started}）")
            check(chat_page.msg_lay.count() == before + 1,
                  "第二句还没冒泡（念完第一句才轮到它）")
            check(chat_page._pending_parts() == 2,
                  f"后两句算「没出口」（实际 {chat_page._pending_parts()} 句）")
            check("正在输入" in chat_page.typing.text(),
                  f"等的时候仍显示「正在输入」（实际 {chat_page.typing.text()!r}）")

            swallowed = chat_page._interrupt_speech()
            check(swallowed == 2, f"被打断：收回 2 句（实际 {swallowed}）")
            check(chat_page._pending_parts() == 0, "收回后不再排队")
            check(bool(stops), "把正在念的那句掐掉了")
            check(chat_page.msg_lay.count() == before + 1,
                  "聊天里不再插「对方被打断」（它去了右边那栏）")
            check(any("对方被打断" in t for t in chat_page.nanny.texts()),
                  f"保姆栏里有这条（实际 {chat_page.nanny.texts()}）")
            pump(300)
            check(any("对方被打断" in t for t in pushed),
                  f"「对方被打断」落盘了（实际 {pushed}）")
            pump(500)  # 情绪走的是后台线程，等它落账
            check(emotions == [("cut_off", 1.0)],
                  f"情绪只登记一次（实际 {emotions}）")

            gate.set()
            pump(1200)
            check(chat_page.msg_lay.count() == before + 1,
                  "被打断后，后面那两句不会自己冒出来")

            # 只说一句：你打字不受影响，不掐声、不提示
            gate.clear()
            started.clear()
            before2 = chat_page.msg_lay.count()
            stops.clear()
            chat_page._deliver(["就只有这一句而已"], 0, 1, 0)
            pump(1500)
            check(bool(started), "单句开始念了")
            none_swallowed = chat_page._interrupt_speech()
            check(none_swallowed == 0, f"单句不算被打断（实际 {none_swallowed}）")
            check(not stops, "单句不掐声")
            check(chat_page.msg_lay.count() == before2 + 1,
                  "单句不补「对方被打断」")
            gate.set()
            pump(400)

            # --- 12. 关掉朗读：没有声音，但「她话没说完」这件事还在（按语速估算）
            chat_page.speak.setChecked(False)
            gate.set()
            pump(300)
            chat_page._refresh_tts_rate()
            pump(300)
            check(chat_page._tts_rate == "-30%",
                  f"语速从内核读回来了（实际 {chat_page._tts_rate!r}）")

            emotions.clear()
            stops.clear()
            started.clear()
            quiet = chat_page.msg_lay.count()
            chat_page._deliver(["第一句，先说这个", "第二句，等她说完", "第三句，还有"],
                               0, 3, 0)
            pump(700)  # 文字模式：冒泡前的准备最多 500 ms
            check(chat_page.msg_lay.count() == quiet + 1,
                  "第一句冒出来了，后两句还没")
            check(chat_page._pending_parts() == 2,
                  f"后两句算没出口（实际 {chat_page._pending_parts()} 句）")
            check("正在输入" in chat_page.typing.text(),
                  f"没开朗读也显示「正在输入」（实际 {chat_page.typing.text()!r}）")

            swallowed2 = chat_page._interrupt_speech()
            check(swallowed2 == 2, f"没开朗读同样收回 2 句（实际 {swallowed2}）")
            check(chat_page.msg_lay.count() == quiet + 1, "聊天里同样不插提示")
            check(any("对方被打断" in t for t in chat_page.nanny.texts()),
                  "没开朗读也进保姆栏")
            check(not stops, "没开朗读，没有声音可掐")
            pump(600)
            check(emotions == [("cut_off", 0.6)],
                  f"听不见嘴，打断轻一点，记 0.6（实际 {emotions}）")
            pump(2500)
            check(chat_page.msg_lay.count() == quiet + 1,
                  "收回的两句不会自己冒出来")
            check(not started, "关掉朗读后一句都没合成")
            chat_page._tts_rate = "+0%"

            # --- 13. 保姆栏：提醒不插聊天、带时间、可收起、可清空、不重复记
            import re

            chat_page.nanny.clear()
            pump(50)
            check(chat_page.nanny.count() == 0, "清空后一栏为空")
            quiet2 = chat_page.msg_lay.count()
            chat_page._poll_notices()
            pump(400)
            check(chat_page.msg_lay.count() == quiet2, "内核的保姆播报不进聊天")
            check(any("对方主动找您" in t for t in chat_page.nanny.texts()),
                  f"播报进了保姆栏（实际 {chat_page.nanny.texts()}）")
            stamps = chat_page.nanny.times()
            check(bool(stamps) and all(re.fullmatch(r"\d{2}:\d{2}:\d{2}", t) for t in stamps),
                  f"每条都带 HH:MM:SS 时间（实际 {stamps}）")
            n_before = chat_page.nanny.count()
            chat_page._poll_notices()
            pump(300)
            check(chat_page.nanny.count() == n_before, "同一条不重复记")

            chat_page.nanny.set_collapsed(True)
            check(chat_page.nanny.width() <= 40,
                  f"收起后只剩一条窄边（实际 {chat_page.nanny.width()}）")
            chat_page._nanny_push("模组「web_bridge」没响应了")
            check(chat_page.nanny.btn_open.text().startswith("保") and
                  len(chat_page.nanny.btn_open.text()) > 1,
                  f"收起时显示未读数（实际 {chat_page.nanny.btn_open.text()!r}）")
            chat_page.nanny.set_collapsed(False)
            check(chat_page.nanny.width() > 200, "展开后恢复宽度")
            check(chat_page.nanny.btn_open.text() == "保", "展开后未读清零")
            check(any("模组" in t for t in chat_page.nanny.texts()),
                  "模组掉线告警也进这一栏")
            check(hasattr(chat_page.nanny, "opened"), "保姆栏有 opened 信号（小屋入口）")
            check("记录" in chat_page.nanny.title.toolTip(), "保姆标题提示能看记录")
            check(chat_page.nanny.title.cursor().shape() == Qt.PointingHandCursor,
                  "保姆标题是手型")

            # --- 15. 一段话放完，「正在输入」就得消掉（0.3.7：一直挂着）
            gate.set()
            chat_page.speak.setChecked(True)
            chat_page._deliver(["第一句，短。", "第二句，也短。"], 0, 2, 0)
            pump(5000)
            check(chat_page.typing.text() == "",
                  f"放完了打字提示要清掉（实际 {chat_page.typing.text()!r}）")
            check(not chat_page._dot.isActive(), "那个小点也停了")
            check(chat_page._deliver_state is None, "逐句链已经收尾")

            # --- 16. 保姆教程：进右边那栏，别再插进聊天
            chat_page.nanny.clear()
            chat_page._tut_mode = "deferred"
            chat_page._tut_since = 0
            chat_page._tut_proactive = False
            quiet3 = chat_page.msg_lay.count()
            chat_page._tutorial_maybe_fire(99)
            pump(800)
            check(chat_page.msg_lay.count() == quiet3,
                  f"教程不再插进聊天（多了 {chat_page.msg_lay.count() - quiet3} 条）")
            tut = [t for t in chat_page.nanny.texts()
                   if ("在线" in t or "关闭此窗口" in t or "聊两句" in t
                       or "补几句" in t or "是个 AI" in t)]
            check(len(tut) >= 3, f"教程进了保姆栏（实际 {chat_page.nanny.texts()}）")

            quiet4 = chat_page.msg_lay.count()
            chat_page._tut_wait_online = True
            chat_page.set_presence("online")
            pump(600)
            check(chat_page.msg_lay.count() == quiet4, "「选在线」那句也不插聊天")
            check(any("先随便聊两句" in t for t in chat_page.nanny.texts()),
                  "「选在线」那句进了保姆栏")

            src = (ROOT / "app" / "ui" / "pages" / "chat.py").read_text(encoding="utf-8-sig")
            check('bubble("system", "保姆程序' not in src,
                  "源码里不再有「保姆程序：…」走聊天气泡")

            # --- 18. 动作：只认 〖〗，气泡里缩小变灰，念的时候整段跳过
            from app.ui import action_text as act_txt

            check(act_txt.spoken("〖抬了下眼皮〗您问这个干什么") == "您问这个干什么",
                  f"念之前把动作删掉（实际 {act_txt.spoken('〖抬了下眼皮〗您问这个干什么')!r}）")
            check(act_txt.spoken("（顿了顿）往下说") == "（顿了顿）往下说",
                  "（）不再当动作（那是正常插入语，照念）")
            segs = act_txt.segments("〖顿了一下〗说吧。")
            check(len(segs) == 2 and segs[0][1] is True and segs[1][1] is False,
                  f"切片把动作单独标出来（实际 {segs}）")
            check("font-size:11px" in act_txt.to_html("〖顿了一下〗说吧。"),
                  "气泡里的动作缩小了")
            check(act_txt.is_action_only("〖顿了一下〗") and
                  not act_txt.is_action_only("〖顿了一下〗说吧"), "只有动作的句子认得出来")

            said.clear()
            chat_page.speak.setChecked(True)
            gate.set()
            before5 = chat_page.msg_lay.count()
            chat_page._deliver(["〖抬了下眼皮〗您问这个干什么。"], 0, 1, 0)
            pump(2500)
            check(bool(said), "开口了才会合成")
            check(all("〖" not in s and "抬了下眼皮" not in s for s in said),
                  f"合成用的文本里没有动作（实际 {said}）")
            check("您问这个干什么" in (said[0] if said else ""),
                  f"说的话原样念（实际 {said}）")
            labels = [lb for lb in chat_page.findChildren(QLabel) if lb.objectName() == "BubbleText"]
            text_lbl = labels[-1] if labels else None
            check(text_lbl is not None and "11px" in (text_lbl.text() or ""),
                  f"气泡里用的是缩小样式（实际 {(text_lbl.text() if text_lbl else None)!r}）")

            said.clear()
            before6 = chat_page.msg_lay.count()
            chat_page._deliver(["〖只是吸了口气〗"], 0, 1, 0)
            pump(1200)
            check(chat_page.msg_lay.count() == before6 + 1, "只有动作也冒泡")
            check(not said, f"只有动作就不合成（实际 {said}）")
            check(chat_page.typing.text() == "", "只有动作也不留「正在输入」")

            # --- 17. 刚画完的那一轮，别被 5 秒一次的 poll 重画一遍
            class FeedEcho(FakeClient):
                def feed(self, session=None, after=0):
                    if after:
                        return {"turns": [], "total": 2}
                    return {"turns": [{"role": "user", "text": "你话很少"},
                                      {"role": "assistant", "text": "饿着呢，能有多少话。"}],
                            "total": 2}

            chat_mod.CoreClient = FeedEcho
            chat_page._pending = False
            chat_page._resyncing = False
            before3 = chat_page.msg_lay.count()
            chat_page._on_ok({"ok": True, "reply": "饿着呢，能有多少话。",
                              "messages": ["饿着呢，能有多少话。"], "mood": ""})
            chat_page.poll(force=True)  # 就在这一瞬间，游标还没对齐
            pump(1500)
            check(chat_page.msg_lay.count() == before3 + 1,
                  f"同一轮只画一次（实际多画了 {chat_page.msg_lay.count() - before3 - 1} 条）")

            # --- 17b. 她主动说的话也要朗读（feed 里冒出来的那句以前被静音）
            said.clear()

            class FeedPro(FakeClient):
                def feed(self, session=None, after=0):
                    if after:
                        return {"turns": [{"role": "assistant", "text": "我在这儿。",
                                           "proactive": True}], "total": 3}
                    return {"turns": [], "total": 2}

            chat_mod.CoreClient = FeedPro
            chat_page._cursor = 2
            chat_page._pending = False
            chat_page._resyncing = False
            chat_page.speak.setChecked(True)
            chat_page.poll(force=True)
            pump(2000)
            check(any("我在这儿" in t for t in said),
                  f"主动说的话要被朗读（实际 {said}）")
            # 聊天界面只放对话本身：主动话不挂「她/对方…」标签
            row = chat_page.msg_lay.itemAt(chat_page.msg_lay.count() - 2)
            frame = row.layout().itemAt(0).widget() if row and row.layout() else None
            tags = frame.findChildren(QLabel, "BubbleTag") if frame is not None else []
            check(not tags, "主动说话不挂标签（聊天里不该多出这种东西）")
        finally:
            gate.set()
            audio.player.play_wait = orig_play_wait
            audio.save_audio = orig_save
            chat_mod.CoreClient = orig_client
            chat_page.speak.setChecked(False)

        # --- 14. 设置页的「肚子」两个分界：能填、能存、坏组合不存
        from app.services import core_client as cc

        sp = win.pages["settings"]
        check(abs(sp.sb_full.value() - 10.0) < 1e-6 and abs(sp.sb_hungry.value() - 3.0) < 1e-6,
              f"默认分界是 10 / 3（实际 {sp.sb_full.value()} / {sp.sb_hungry.value()}）")
        sent: list[tuple[float, float]] = []
        orig_set = cc.CoreClient.stomach_set
        cc.CoreClient.stomach_set = lambda self, f, h: sent.append((f, h)) or {"ok": True}
        try:
            sp.sb_full.setValue(12.0)
            sp.sb_hungry.setValue(4.0)
            sp.save_stomach()
            pump(600)
            check(sent == [(12.0, 4.0)], f"改完会写回内核（实际 {sent}）")
            check("已保存" in sp.lbl_stomach.text(),
                  f"保存后有回话（实际 {sp.lbl_stomach.text()!r}）")
            sent.clear()
            sp.sb_full.setValue(2.0)
            sp.sb_hungry.setValue(4.0)
            sp.save_stomach()
            pump(300)
            check(not sent and "没保存" in sp.lbl_stomach.text(),
                  "饱线小于饿线时拦住不写（并说明原因）")
        finally:
            cc.CoreClient.stomach_set = orig_set

        # --- 15. 设置页的「记忆库」：读数、保存、坏组合不存
        check(abs(sp.sb_mem_max.value() - 2.0) < 1e-6
              and abs(sp.sb_mem_zip.value() - 0.5) < 1e-6
              and sp.sb_mem_days.value() == 60,
              f"默认是 2.0 G / 0.5 G / 60 天（实际 {sp.sb_mem_max.value()} / "
              f"{sp.sb_mem_zip.value()} / {sp.sb_mem_days.value()}）")
        orig_stats = cc.CoreClient.memory_stats
        orig_save_mem = cc.CoreClient.memory_save
        cc.CoreClient.memory_stats = lambda self: {
            "ok": True,
            "stats": {"used_mb": 12.5, "files": 34, "keep_days": 60},
            "config": {"max_gb": 3.0, "compress_gb": 1.0, "keep_days": 45},
        }
        mem_sent: list[tuple[float, float, int]] = []
        cc.CoreClient.memory_save = lambda self, a, b, c: mem_sent.append((a, b, c)) or {"ok": True}
        try:
            sp.refresh_memory()
            pump(600)
            check("12.5 MB" in sp.lbl_memory.text(),
                  f"刷新后显示占用（实际 {sp.lbl_memory.text()!r}）")
            check(abs(sp.sb_mem_max.value() - 3.0) < 1e-6 and sp.sb_mem_days.value() == 45,
                  f"刷新会把配置填回来（实际 {sp.sb_mem_max.value()} / {sp.sb_mem_days.value()}）")
            sp.sb_mem_max.setValue(5.0)
            sp.sb_mem_zip.setValue(1.5)
            sp.sb_mem_days.setValue(90)
            sp.save_memory()
            pump(600)
            check(mem_sent == [(5.0, 1.5, 90)], f"改完会写回内核（实际 {mem_sent}）")
            check("已保存" in sp.lbl_memory.text(),
                  f"保存后有回话（实际 {sp.lbl_memory.text()!r}）")
            mem_sent.clear()
            sp.sb_mem_max.setValue(1.0)
            sp.sb_mem_zip.setValue(9.0)
            sp.save_memory()
            pump(300)
            check(not mem_sent and "没保存" in sp.lbl_memory.text(),
                  "压缩阈值大于上限时拦住不写（并说明原因）")
        finally:
            cc.CoreClient.memory_stats = orig_stats
            cc.CoreClient.memory_save = orig_save_mem

    # 16. 建档向导的「脾气」页：16 套人设、分三组、默认落在第一套
    from app.core import framework_setup  # noqa: E402
    from app.ui.dialogs.onboarding import OnboardingWizard  # noqa: E402
    check(len(framework_setup.STYLES) == 16,
          f"应有 16 套人设（实际 {len(framework_setup.STYLES)}）")
    group_members = [n for _g, _d, ms in framework_setup.STYLE_GROUPS for n in ms]
    check(sorted(group_members) == sorted(framework_setup.STYLES),
          "分组成员应正好等于 16 套人设")
    check("〖" in framework_setup.TEMPLATE and "（抬了下眼皮）" not in framework_setup.TEMPLATE,
          "人格模板里的动作说明应已改成 〖〗")
    wiz = OnboardingWizard(win)
    try:
        wiz.stack.setCurrentIndex(3)
        pump(200)
        items = [wiz.cb_style.itemText(i) for i in range(wiz.cb_style.count())
                 if wiz.cb_style.itemData(i)]
        check(len(items) == 17, f"下拉里应有 16 套 + 自定义（实际 {len(items)}）")
        check(wiz.cb_style.count() == 20, f"应有 17 项 + 3 条分组分隔（实际 {wiz.cb_style.count()}）")
        check(wiz._style_key() == "傲娇", f"默认应选中第一套（实际 {wiz._style_key()}）")
        idx = next(i for i in range(wiz.cb_style.count())
                   if wiz.cb_style.itemData(i) == "病娇")
        wiz.cb_style.setCurrentIndex(idx)
        pump(200)
        check(wiz._style_key() == "病娇", "切到病娇后应读得到")
        check("慎用" in wiz.lbl_style_hint.text() or "剧情向" in wiz.lbl_style_hint.text(),
              f"病娇应提示慎用（实际 {wiz.lbl_style_hint.text()!r}）")
        idx = next(i for i in range(wiz.cb_style.count())
                   if wiz.cb_style.itemData(i) == "__custom__")
        wiz.cb_style.setCurrentIndex(idx)
        pump(200)
        check(wiz._style_key() == "__custom__", "应能切到自定义")
        check("至少写 30 字" in wiz.lbl_style_hint.text(),
              f"自定义应提示字数（实际 {wiz.lbl_style_hint.text()!r}）")
        check("至少 30 字" in wiz.ed_custom.placeholderText(), "自定义输入框应提示写完整")
        check("字数太少" in wiz._custom_problem("太短了"), "字数太少应被拦住")
        check("无效" in wiz._custom_problem(
            "今天天气不错，我们出去走走，看看外面的树和云，然后回来吃饭。"),
            "没有性格信息应判无效")
        check(wiz._custom_problem(
            "她嘴硬心软，被夸的时候会先嘴硬，被冷落时会沉默，不许敷衍，也不许真的冷着她。") == "",
            "写清脾气和反应应通过")
        # 最后一页：没点「让保姆整理」之前，「完成」必须置灰
        wiz.stack.setCurrentIndex(3)
        wiz.preview.setPlainText("")
        wiz._persona_ready = False
        wiz._busy = False
        wiz._sync()
        check(wiz.btn_next.text() == "完成", "最后一页按钮应写「完成」")
        check(not wiz.btn_next.isEnabled(), "没整理前「完成」应置灰")
        wiz.preview.setPlainText("手打的一版")
        wiz._sync()
        check(not wiz.btn_next.isEnabled(), "手打草稿不算整理过，「完成」仍应置灰")
        wiz._persona_ready = True
        wiz._sync()
        check(wiz.btn_next.isEnabled(), "整理出草稿后「完成」应可点")
        wiz._busy = True
        wiz._sync()
        check(not wiz.btn_next.isEnabled(), "保姆整理中「完成」应置灰")
        wiz._busy = False
        wiz._sync()
        check(wiz.btn_next.isEnabled(), "整理结束后「完成」恢复可点")
    finally:
        wiz.close()
        wiz.deleteLater()

    # 17. 模组卡片：看日志、重启（坏了得能自己看，不用等人翻文件夹）
    from app.ui import pages as pages_pkg  # noqa: E402
    mods_mod = pages_pkg.mods
    if mods_page is not None:
        with tempfile.TemporaryDirectory(prefix="bab_log_") as td:
            mdir = Path(td) / "program_demo.pbab"
            (mdir / "logs").mkdir(parents=True)
            (mdir / "logs" / "server.log").write_text(
                "[demo] starting with python on port 40725\n[demo] boom: something failed\n",
                encoding="utf-8",
            )
            mod = {"id": "demo", "name": "演示", "state": "broken", "version": "0.1.0",
                   "dir": str(mdir), "folder": "program_demo.pbab", "pid": None}
            try:
                text = mods_mod.module_log_text(mod)
            except Exception as exc:  # noqa: BLE001
                text = ""
                check(False, f"module_log_text 不存在或炸了：{type(exc).__name__}: {exc}")
            check("something failed" in text, "日志里应能看到模组自己的 server.log")
            check("演示" in text or "demo" in text, f"日志头部应标明是哪个模组（实际 {text[:80]!r}）")
            empty = mods_mod.module_log_text({"id": "nope", "name": "空", "dir": str(Path(td) / "none")})
            check("还没有日志" in empty or "没有日志" in empty or "没找到" in empty,
                  f"没有日志时给出人话（实际 {empty[:60]!r}）")

        card = mods_mod.ModuleCard(mods_page, mod)
        texts = [b.text() for b in card.findChildren(pages_pkg.mods.QPushButton)]
        check(any("看日志" in t for t in texts), f"卡片上有「看日志」（实际 {texts}）")
        check(any("重启" in t for t in texts), f"卡片上有「重启」（实际 {texts}）")
        calls: list[str] = []

        def fake_call(fn, mid, ok_text, after=None):
            calls.append(getattr(fn, "__name__", "?"))
            if after is not None:
                after(None)

        orig_call = mods_page.call
        mods_page.call = fake_call
        try:
            card.on_restart()
            pump(200)
        finally:
            mods_page.call = orig_call
        check(calls == ["disable", "enable"], f"重启应是「先停后启」（实际 {calls}）")
        card.deleteLater()

    # --- 18. 模组页的「模组市场」：打开 GitHub Pages 模组页
    market_btn = None
    for b in mods_page.findChildren(pages_pkg.mods.QPushButton):
        if b.text() == "模组市场":
            market_btn = b
            break
    check(market_btn is not None, "模组页标题栏应有「模组市场」按钮")

    opened: list[str] = []
    keep_open = mods_mod.QDesktopServices.openUrl

    def fake_open(url):
        opened.append(url.toString())
        return True

    mods_mod.QDesktopServices.openUrl = fake_open
    try:
        if market_btn is not None:
            market_btn.click()
        pump(120)
    finally:
        mods_mod.QDesktopServices.openUrl = keep_open

    check(opened and opened[0] == mods_mod.MARKET_URL,
          f"点「模组市场」应打开 Pages 模组页（实际 {opened}）")
    check(mods_mod.MARKET_URL == "https://chanko-bab.github.io/BetterAIBridge/modules.html",
          "市场链接应是 Pages 模组页")

    # --- 19. 设置页：存档 / 卸载程序
    sett = win.pages["settings"]
    sett_btns = [b.text() for b in sett.findChildren(pages_pkg.mods.QPushButton)]
    check(any(x.startswith("存档") for x in sett_btns), f"设置页应有「存档…」按钮（实际 {sett_btns}）")
    check("卸载程序" in sett_btns, f"设置页应有「卸载程序」按钮（实际 {sett_btns}）")
    check("重置启动器" in sett_btns, f"设置页应有「重置启动器」按钮（实际 {sett_btns}）")
    check(getattr(sett, "_wheel_guard", None) is not None, "设置页装了滚轮保护")

    from app.services import avatar as _avatar  # noqa: PLC0415
    if not _avatar.info().get("custom"):
        from app.ui.dialogs.avatar_dialog import AvatarDialog  # noqa: PLC0415
        ad = AvatarDialog(win)
        check(ad.lb_avatar.text() == "默认的灰发头像",
              f"默认头像文案应写灰发（实际 {ad.lb_avatar.text()!r}）")
        ad.deleteLater()

    import tempfile as _tf
    import zipfile as _zip
    from app.ui.pages import settings as sett_mod

    keep_entity = sett_mod.portable.entity_dir
    keep_adir = sett_mod.portable.archive_dir
    try:
        with _tf.TemporaryDirectory() as td:
            tdp = Path(td)
            ent = tdp / "WiseEntity" / "entity"
            (ent / "persona").mkdir(parents=True)
            (ent / "persona" / "persona.md").write_text("# 人格\n她叫小琛。\n", encoding="utf-8")
            (ent / "memory" / "internal" / "web_owner").mkdir(parents=True)
            (ent / "memory" / "internal" / "web_owner" / "2026.10.31.txt").write_text(
                "2026.10.31\n\n上午(06:00-11:00)\n- 08:00 我醒了\n", encoding="utf-8")
            sett_mod.portable.entity_dir = lambda *a, **k: ent
            sett_mod.portable.archive_dir = lambda: tdp / "archives"

            sett.save_archive(notify=False)
            made = list((tdp / "archives").glob("*.babpak"))
            check(len(made) == 1, f"点存档应产出一个 .babpak（实际 {made}）")
            if made:
                with _zip.ZipFile(made[0]) as zf:
                    names = zf.namelist()
                check("entity/persona/persona.md" in names, "存档里应有人格")
                check(any(n.startswith("entity/memory/") for n in names), "存档里应有记忆")
            check("已存档" in sett.lbl_archive.text(), f"界面上要说出存档结果（实际 {sett.lbl_archive.text()[:40]!r}）")
            check("不在程序目录里" in sett.lbl_archive.text(),
                  f"存档后要说明它不在程序目录里（实际 {sett.lbl_archive.text()[-40:]!r}）")
            check(str(sett_mod.portable.archive_dir()) in sett.lbl_archive.text(),
                  "存档标签里要写清楚存在哪")

            from PySide6.QtWidgets import QHBoxLayout as _QHB
            row_lay = None
            for _lay in sett.findChildren(_QHB):
                if _lay.indexOf(sett.btn_archive) >= 0 and _lay.indexOf(sett.btn_uninstall) >= 0:
                    row_lay = _lay
                    break
            check(row_lay is not None, "找不到同时装着「存档」「卸载程序」的那一行")
            if row_lay is not None:
                check(row_lay.indexOf(sett.btn_archive) == 0,
                      f"这一行第一个应是「存档」（实际 {row_lay.indexOf(sett.btn_archive)}）")
                check(row_lay.itemAt(row_lay.count() - 1).spacerItem() is not None,
                      "这一行末尾要有弹簧，把按钮顶在左边")

            keep_spawn = sett_mod.portable.spawn_uninstall
            keep_finish = sett._finish_uninstall
            spawned: list[dict] = []
            finished: list[bool] = []
            sett_mod.portable.spawn_uninstall = lambda plan: (spawned.append(plan), {"ok": True, "script": "x"})[1]
            sett._finish_uninstall = lambda *a, **k: finished.append(True)
            sett.uninstall(confirm=False)
            check(spawned and spawned[0].get("ok"), f"卸载应生成有效计划（实际 {spawned}）")
            check(bool(finished), "卸载后应调用退出收尾")

            spawned.clear()
            finished.clear()
            # 存档默认位置必须在程序目录外面，否则卸载会连它一起删
            arch = sett_mod.portable.archive_dir()
            check(str(arch).lower().startswith(str(Path.home()).lower()[:3]),
                  f"存档目录应在本地磁盘的用户目录下（实际 {arch}）")
            check(str(Path(sett_mod.config.APP_DIR)).lower() not in str(arch).lower(),
                  f"存档目录不能在程序目录里面（实际 {arch}）")

            # 卸载脚本得杀进程、删快捷方式、重试
            plan_live = sett_mod.portable.uninstall_script(sett_mod.config.APP_DIR)
            ps1 = plan_live.get("ps1", "")
            cmd = plan_live.get("cmd", "")
            check(plan_live.get("ok") is True, "开发树应能生成卸载计划")
            check("Stop-Process" in ps1, "卸载脚本应先杀占用进程")
            check("ExecutablePath" in ps1, "卸载脚本要按 ExecutablePath 杀占用进程")
            check("Name -match" in ps1 and "python|pythonw|node|electron" in ps1,
                  "命令行兜底只针对 python/node/electron，不能误杀 powershell 自己")
            check("CreateShortcut" in ps1 and "TargetPath" in ps1,
                  "快捷方式按目标路径删，不能按文件名通配（会删掉别的安装）")
            check("Remove-Item" in ps1 and "-Recurse" in ps1, "卸载脚本应递归删目录")
            check("for ($i" in ps1, "卸载脚本应重试删除（文件被占用时）")
            check("bab-uninstall.log" in (plan_live.get("log") or ""), "卸载要留日志")
            check(cmd.isascii(), "cmd 壳必须是纯 ASCII（cmd 按 ANSI 解析，中文会乱码）")
            check("powershell" in cmd.lower() and "-File" in cmd, "cmd 壳应调用 ps1")

            # 点按钮必须真的走"带提示/带确认"的分支：clicked 会带 checked=False，
            # 直接 connect(save_archive) 会把它当成 notify=False（0.3.14 就是这么坏的）。
            clicked_archive: list[bool] = []
            keep_export = sett.export_archive
            sett.export_archive = lambda: clicked_archive.append(True)
            sett.btn_archive.click()
            sett.export_archive = keep_export
            check(clicked_archive == [True],
                  f"点「存档」应走 export_archive（实际 {clicked_archive}）")

            clicked_uninstall: list[bool] = []
            keep_uninst = sett.uninstall
            sett.uninstall = lambda confirm=True: clicked_uninstall.append(bool(confirm))
            sett.btn_uninstall.click()
            sett.uninstall = keep_uninst
            check(clicked_uninstall == [True],
                  f"点「卸载程序」应按 confirm=True 走（实际 {clicked_uninstall}）")

            keep_ask = sett._ask_uninstall
            keep_save = sett.save_archive
            saved: list[bool] = []
            sett._ask_uninstall = lambda plan: "archive"
            sett.save_archive = lambda notify=True: saved.append(True)
            sett.uninstall(confirm=True)
            check(saved == [True], f"选「先去存档」应先存档（实际 {saved}）")
            check(not spawned and not finished, f"选「先去存档」不能顺手把程序删了（实际 {spawned}）")
            sett._ask_uninstall = lambda plan: "remove"
            sett.uninstall(confirm=True)
            check(bool(spawned) and bool(finished), "选「完全卸载」才会真删")
            sett._ask_uninstall = keep_ask
            sett.save_archive = keep_save
            sett_mod.portable.spawn_uninstall = keep_spawn
            sett._finish_uninstall = keep_finish
    finally:
        sett_mod.portable.entity_dir = keep_entity
        sett_mod.portable.archive_dir = keep_adir

    # --- 19b. 人格草稿必须能改、字数不限
    wiz.preview.setPlainText("")
    check(wiz.preview.isReadOnly() is False, "人格草稿要可以编辑（保姆写完能改）")
    check(wiz.preview.minimumHeight() >= 200, f"草稿要给够高度（实际 {wiz.preview.minimumHeight()}）")
    long_text = "我只是想试试能写多长。" * 400
    wiz.preview.setPlainText(long_text)
    check(wiz.preview.toPlainText() == long_text, "草稿不该截断字数")
    wiz.preview.setPlainText("")

    # --- 20. 建档向导里的「导入智能体」：选存档 -> 人格和记忆回来（强写）
    from app.ui.dialogs.onboarding import OnboardingWizard
    from app.core import portable as portable_mod

    wiz = OnboardingWizard(win)
    imp_btn = getattr(wiz, "btn_import", None)
    check(imp_btn is not None and imp_btn.text() == "导入智能体",
          "建档向导第一页应有「导入智能体」按钮")

    keep_entity = portable_mod.entity_dir
    keep_get = wiz.__class__.__mro__  # 占位，下面用模块级补丁
    import app.ui.dialogs.onboarding as onboarding_mod

    keep_open = onboarding_mod.QFileDialog.getOpenFileName
    keep_info = onboarding_mod.QMessageBox.information
    import app.ui.dialogs.archive_key as archive_key_mod
    keep_ask_key = archive_key_mod.ask_missing_key
    try:
        archive_key_mod.ask_missing_key = lambda *a, **k: (True, "")
        with _tf.TemporaryDirectory() as td2:
            tdp2 = Path(td2)
            src = tdp2 / "src" / "WiseEntity" / "entity"
            (src / "persona").mkdir(parents=True)
            (src / "persona" / "persona.md").write_text("# 人格\n她叫小琛。\n", encoding="utf-8")
            (src / "memory" / "external" / "program_ghost" / "提醒").mkdir(parents=True)
            (src / "memory" / "external" / "program_ghost" / "提醒" / "2026.10.31.txt").write_text(
                "2026.10.31\n\n下午(13:00-18:00)\n- 15:00 该喝水了\n", encoding="utf-8")
            pkg = tdp2 / "one.babpak"
            wr = portable_mod.write_archive(src, "小琛", target=pkg, include_key=True)
            check(wr.get("ok"), f"测试存档应能写出来（实际 {wr}）")

            fresh = tdp2 / "fresh" / "WiseEntity" / "entity"
            fresh.mkdir(parents=True)
            portable_mod.entity_dir = lambda *a, **k: fresh
            onboarding_mod.QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(pkg), ""))
            onboarding_mod.QMessageBox.information = staticmethod(lambda *a, **k: 0)

            wiz._import_agent()
            check(bool(getattr(wiz, "saved", False)), "导入成功后应把 saved 置真（程序才会继续启动）")
            check((fresh / "persona" / "persona.md").is_file(), "导入应把人格写进新安装")
            ghost = fresh / "memory" / "external" / "program_ghost" / "提醒" / "2026.10.31.txt"
            check(ghost.is_file() and "该喝水了" in ghost.read_text(encoding="utf-8"),
                  "没装过的模组抽屉也要强写进去")
    finally:
        portable_mod.entity_dir = keep_entity
        onboarding_mod.QFileDialog.getOpenFileName = keep_open
        onboarding_mod.QMessageBox.information = keep_info
        archive_key_mod.ask_missing_key = keep_ask_key
        wiz.deleteLater()

    # 18. 设置页：声音引擎（edge / BreezeBlue）与「她主动说话」
    from app.services import core_client as cc  # noqa: PLC0415

    sp2 = win.pages.get("settings")
    if sp2 is not None:
        check(sp2.cb_engine.count() == 3 and sp2.cb_engine.itemData(0) == "edge"
              and sp2.cb_engine.itemData(1) == "breezeblue"
              and sp2.cb_engine.itemData(2) == "local",
              "朗读引擎下拉应有 edge / BreezeBlue / 本地三项")
        check(sp2.cb_prev_engine.count() == 3
              and sp2.cb_prev_engine.itemData(0) == "edge"
              and sp2.cb_prev_engine.itemData(1) == "breezeblue"
              and sp2.cb_prev_engine.itemData(2) == "local",
              "试听引擎下拉应有 edge / BreezeBlue / 本地三项")
        check(hasattr(sp2, "btn_local_install") and hasattr(sp2, "lbl_local"),
              "设置页应有本地语音包的下载按钮与状态")
        check(sp2.slider_follow.minimum() == 0 and sp2.slider_follow.maximum() == 3,
              "主动程度应是 0-3 四档")
        check(sp2.btn_say_now.text() == "让智能体现在说一句", "应有「让智能体现在说一句」按钮")
        check(hasattr(sp2, "btn_update") and sp2.btn_update.text() == "检查更新"
              and "GitHub" in sp2.btn_update.toolTip(),
              "设置页应有「检查更新」按钮（检查 GitHub 新版本）")
        ap = win.pages.get("appearance")
        check(ap is not None and hasattr(ap, "cb_font_family")
              and hasattr(ap, "cb_font_size") and hasattr(ap, "lbl_font_preview"),
              "外观页应有字体卡：字体/字号/预览")
        check(ap is not None and ap.cb_font_size.minimum() == 12
              and ap.cb_font_size.maximum() == 18,
              "外观页字号范围应是 12–18")
        check(ap is not None and ap.cb_bg_effect.count() == 3
              and ap.cb_bg_follow.count() == 4 and hasattr(ap, "preview"),
              "外观页应有背景卡：三种背景 + 四种跟随 + 预览")
        check(ap is not None and ap.cb_bg_source.count() == 3
              and hasattr(ap, "btn_bg_media"),
              "外观页应有底图：动态效果/图片/视频")
        check(hasattr(win, "backdrop") and win.backdrop is not None
              and hasattr(win, "main_stage"),
              "主窗口应把背景铺在所有页面下面")
        check(win.stack.testAttribute(Qt.WA_TranslucentBackground),
              "页面栈应透明，背景才透得出来")
        _saved = {}
        _orig_set = _cfg.set_value
        try:
            os.environ.pop("BAB_NO_PERSIST", None)
            _cfg.set_value = lambda k, v: _saved.__setitem__(k, v)
            win.resize(1234, 777)
            win._save_window_size()
        finally:
            _cfg.set_value = _orig_set
            os.environ["BAB_NO_PERSIST"] = "1"
        check(_saved.get("ui.window_size") == [1234, 777],
              "退出时应把窗口大小写进 ui.window_size")
        from PySide6.QtWidgets import QPushButton as _QPB
        _btns = [b.text() for b in sp2.findChildren(_QPB)]
        check("打开日志目录" in _btns and "再看教程" in _btns,
              "设置页应有「打开日志目录」「再看教程」")
        check(hasattr(sp2, "btn_import") and sp2.btn_import.text() == "导入存档",
              "设置页应有「导入存档」")
        check(hasattr(sp2, "cb_eyes") and hasattr(sp2, "cb_ears")
              and hasattr(sp2, "cb_cam") and hasattr(sp2, "cb_mic")
              and hasattr(sp2, "lbl_sense"),
              "设置页应有耳目卡：两个开关 + 摄像头/麦克风下拉")
        check(hasattr(sp2, "sp_watch_sec") and hasattr(sp2, "sp_listen_sec")
              and hasattr(sp2, "sp_listen_len")
              and sp2.sp_watch_sec.minimum() == 30
              and sp2.sp_listen_sec.minimum() == 60,
              "耳目卡应有可改的看/听间隔与听时长")

        sent_voice: list[dict] = []
        orig_tts_cfg = cc.CoreClient.tts_config
        cc.CoreClient.tts_config = lambda self, **kw: sent_voice.append(kw) or {"ok": True}
        try:
            sp2._loading_voice = True
            sp2.cb_engine.setCurrentIndex(0)   # 先回到 edge，保证下面这次真的会变化
            sp2._loading_voice = False
            sent_voice.clear()
            sp2.cb_engine.setCurrentIndex(1)
            pump(400)
            check(bool(sent_voice) and sent_voice[-1].get("engine") == "breezeblue",
                  f"换引擎会写回内核（实际 {sent_voice[-1:]!r}）")
            sp2._loading_voice = True
            sp2.cb_prev_engine.setCurrentIndex(0)
            sp2._loading_voice = False
            sent_voice.clear()
            sp2.cb_prev_engine.setCurrentIndex(1)
            pump(400)
            check(bool(sent_voice) and sent_voice[-1].get("preview_engine") == "breezeblue",
                  f"换试听引擎也会写回 preview_engine（实际 {sent_voice[-1:]!r}）")
            sp2.ed_bb_base.setText("https://example.test/v1")
            sp2.ed_bb_voice.setText("my-voice")
            sp2.ed_bb_model.setText("m1")
            sp2.save_voice()
            pump(400)
            check(sent_voice[-1].get("bb_voice") == "my-voice"
                  and sent_voice[-1].get("bb_base") == "https://example.test/v1"
                  and sent_voice[-1].get("bb_model") == "m1",
                  f"BreezeBlue 的地址/音色/模型一起存（实际 {sent_voice[-1]!r}）")
        finally:
            cc.CoreClient.tts_config = orig_tts_cfg
            sp2._loading_voice = True
            sp2.cb_engine.setCurrentIndex(0)
            sp2.cb_prev_engine.setCurrentIndex(0)
            sp2._loading_voice = False

        sent_follow: list[int] = []
        orig_fget = cc.CoreClient.followup_get
        orig_fset = cc.CoreClient.followup_set
        cc.CoreClient.followup_get = lambda self: {
            "ok": True, "config": {"level": 1},
            "levels": [{"level": 0, "name": "关", "label": "不补话"},
                       {"level": 1, "name": "克制", "label": "少补"},
                       {"level": 2, "name": "正常", "label": "补一句"},
                       {"level": 3, "name": "黏人", "label": "补两句"}]}
        cc.CoreClient.followup_set = lambda self, lv: sent_follow.append(lv) or {"ok": True}
        try:
            sp2.refresh_followup()
            pump(500)
            check(sp2.slider_follow.value() == 1 and "克制" in sp2.lbl_follow.text(),
                  f"刷新会读回档位（实际 {sp2.slider_follow.value()} / "
                  f"{sp2.lbl_follow.text()!r}）")
            sp2.slider_follow.setValue(3)
            pump(500)
            check(sent_follow == [3], f"拖滑条会写回内核（实际 {sent_follow}）")
            check("黏人" in sp2.lbl_follow.text(),
                  f"滑条下有档位说明（实际 {sp2.lbl_follow.text()!r}）")
        finally:
            cc.CoreClient.followup_get = orig_fget
            cc.CoreClient.followup_set = orig_fset

        said_now: list[bool] = []
        orig_pro = cc.CoreClient.proactive_send
        cc.CoreClient.proactive_send = lambda self, force=True: (
            said_now.append(force) or {"sent": True, "text": "在呢。"})
        try:
            sp2.say_now()
            pump(500)
            check(said_now == [True] and "在呢。" in sp2.lbl_follow.text(),
                  f"「现在说一句」会让她开口（实际 {said_now} / {sp2.lbl_follow.text()!r}）")
            check(sp2.btn_say_now.isEnabled(), "说完按钮恢复可点")
        finally:
            cc.CoreClient.proactive_send = orig_pro

    win.hide()
    app.quit()

    # ---- 模组的「给智能体看的说明」独立成 agent.md（0.3.18）----
    mb_src = (ROOT / "WiseEntity" / "entity" / "core" / "modules_box.py").read_text(encoding="utf-8")
    check("def agent_doc(" in mb_src, "modules_box 没有 agent_doc()：模组没法单独写给智能体看的说明")
    body = mb_src.split("def persona_text(", 1)[-1]
    check("agent_doc(" in body, "persona_text 没读 agent.md")
    check("这份东西是干什么的" not in body, "persona_text 还把 introduce.md 塞进提示词（会让她读安装说明）")

    print(f"\n{len(fails)} 条失败" if fails else "\nPASS")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
