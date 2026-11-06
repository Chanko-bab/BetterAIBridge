# -*- coding: utf-8 -*-
r"""05：依赖下载的进度、取消、半成品清理，以及启用失败自动开依赖框。

先写红：这些断言在实现前应当失败。
    .venv\Scripts\python.exe tools\test_download_progress.py
"""
from __future__ import annotations

import http.server
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QLabel, QProgressBar, QPushButton,
)

from app.core import pbab, config  # noqa: E402
from app.ui.dialogs.module_requires import RequiresDialog  # noqa: E402
from app.ui.pages import mods as mods_page  # noqa: E402

FAILS: list[str] = []
OKS = 0

PAYLOAD = b"z" * (256 * 1024)


def check(ok: bool, msg: str) -> None:
    global OKS
    if ok:
        OKS += 1
    else:
        FAILS.append(msg)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/big":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.end_headers()
        for i in range(0, len(PAYLOAD), 32 * 1024):
            self.wfile.write(PAYLOAD[i:i + 32 * 1024])
            self.wfile.flush()

    def log_message(self, *args: object) -> None:
        pass


def _server() -> http.server.ThreadingHTTPServer:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_download_progress() -> None:
    srv = _server()
    tmp = Path(tempfile.mkdtemp())
    try:
        url = f"http://127.0.0.1:{srv.server_port}/big"
        dest = tmp / "a.bin"
        seen: list[tuple[int, int]] = []
        try:
            pbab._download(url, dest, progress=lambda d, t: seen.append((d, t)))
        except TypeError as exc:
            check(False, f"_download 应接受 progress（实际 {exc}）")
        check(dest.is_file() and dest.read_bytes() == PAYLOAD, "下载完整后应落位")
        check(bool(seen), "应收到进度回调")
        if seen:
            check(seen[-1][0] == len(PAYLOAD), "进度应报到总字节数")
            check(seen[-1][1] == len(PAYLOAD), "进度总长应来自 Content-Length")

        dest2 = tmp / "b.bin"
        state = {"n": 0}

        def tick(_d: int, _t: int) -> None:
            state["n"] += 1

        try:
            pbab._download(url, dest2, progress=tick, cancel=lambda: state["n"] >= 1)
            check(False, "取消时应抛 PbabCancelled")
        except Exception as exc:  # noqa: BLE001
            cls = getattr(pbab, "PbabCancelled", None)
            check(cls is not None and isinstance(exc, cls),
                  f"取消应抛 PbabCancelled（实际 {type(exc).__name__}: {exc}）")
        check(not dest2.exists(), "取消后成品文件不应存在")
        check(not list(tmp.glob("*.part")), "取消后 .part 半成品应删掉")
    finally:
        srv.shutdown()
        srv.server_close()


def test_download_require_cancel() -> None:
    cancelled_cls = getattr(pbab, "PbabCancelled", None)
    if cancelled_cls is None:
        check(False, "pbab 应有 PbabCancelled")
        return

    tmp = Path(tempfile.mkdtemp())
    orig_doc, orig_root, orig_dl = pbab._requires_doc, pbab._require_root, pbab._download
    orig_modules = config._cfg.get("modules_dir")  # type: ignore[attr-defined]
    calls: list[tuple[str, object, object]] = []
    flag = {"cancel": False}

    pbab._requires_doc = lambda _mid: [{
        "id": "r", "install": "download", "target": "r",
        "source": ["http://a/x.zip", "http://b/x.zip"], "sha256": "0" * 64,
    }]
    pbab._require_root = lambda _mid: tmp / "root"
    config._cfg["modules_dir"] = str(tmp / "cache")  # type: ignore[attr-defined]

    def fake(url: str, dest: Path, progress=None, cancel=None) -> None:
        calls.append((url, progress, cancel))
        flag["cancel"] = True
        raise cancelled_cls("下载已取消")

    pbab._download = fake
    try:
        try:
            pbab.download_require("m", "r", progress=lambda _d, _t: None,
                                  cancel=lambda: flag["cancel"])
            check(False, "取消应抛 PbabCancelled")
        except cancelled_cls:
            pass
        check(len(calls) == 1, f"取消后不应再试下一个源（实际试了 {len(calls)} 个）")
        check(bool(calls) and calls[0][1] is not None and calls[0][2] is not None,
              "download_require 应把 progress/cancel 传给 _download")
    finally:
        pbab._requires_doc, pbab._require_root, pbab._download = orig_doc, orig_root, orig_dl
        if orig_modules is None:
            config._cfg.pop("modules_dir", None)  # type: ignore[attr-defined]
        else:
            config._cfg["modules_dir"] = orig_modules  # type: ignore[attr-defined]


def test_stage_order() -> None:
    tmp = Path(tempfile.mkdtemp())
    orig = (pbab._requires_doc, pbab._require_root, pbab._download,
            pbab._sha256_file, pbab._safe_extract_zip,
            pbab.read_requires_state, pbab._write_requires_state)
    orig_modules = config._cfg.get("modules_dir")  # type: ignore[attr-defined]
    stages: list[str] = []

    pbab._requires_doc = lambda _mid: [{
        "id": "r", "install": "download", "target": "r",
        "source": ["http://a/x.zip"], "sha256": "0" * 64,
    }]
    pbab._require_root = lambda _mid: tmp / "root"
    config._cfg["modules_dir"] = str(tmp / "cache")  # type: ignore[attr-defined]

    def fake_dl(_url: str, dest: Path, progress=None, cancel=None) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x")

    pbab._download = fake_dl
    pbab._sha256_file = lambda _p: "0" * 64
    pbab._safe_extract_zip = lambda _z, _t: None
    pbab.read_requires_state = lambda _mid: {"items": {}}
    pbab._write_requires_state = lambda _mid, _doc: None
    try:
        pbab.download_require("m", "r", stage=stages.append)
        check(stages == ["verify", "extract", "done"],
              f"阶段顺序应是 verify/extract/done（实际 {stages}）")
    finally:
        (pbab._requires_doc, pbab._require_root, pbab._download,
         pbab._sha256_file, pbab._safe_extract_zip,
         pbab.read_requires_state, pbab._write_requires_state) = orig
        if orig_modules is None:
            config._cfg.pop("modules_dir", None)  # type: ignore[attr-defined]
        else:
            config._cfg["modules_dir"] = orig_modules  # type: ignore[attr-defined]


def test_requires_dialog_progress() -> None:
    app = QApplication.instance() or QApplication([])
    orig_status, orig_dl = pbab.require_status, pbab.download_require
    pbab.require_status = lambda _mid: [{
        "id": "runtime", "name": "运行时", "kind": "runtime", "ok": False,
        "install": "download", "source": ["http://example.invalid/x"],
        "size": 128, "target": "runtime", "sha256": "0" * 64,
    }, {
        "id": "guide", "name": "官方客户端", "kind": "runtime", "ok": False,
        "install": "guided", "source": ["http://example.invalid/g"],
        "size": 0, "target": "guide", "sha256": "0" * 64,
    }]
    started = threading.Event()
    release = threading.Event()

    def fake_dl(mid: str, rid: str, progress=None, cancel=None, stage=None):
        started.set()
        if progress:
            progress(10 * 1024 * 1024, 100 * 1024 * 1024)
        while not release.is_set():
            if cancel and cancel():
                raise getattr(pbab, "PbabCancelled", RuntimeError)("下载已取消")
            time.sleep(0.02)
        return {"ok": True, "id": rid, "path": "x"}

    pbab.download_require = fake_dl
    dlg = RequiresDialog(None, "demo", "演示")
    dlg.show()
    QTest.qWait(50)
    dlg2 = None
    try:
        bars = dlg.findChildren(QProgressBar)
        check(len(bars) >= 1, "下载行应有进度条")
        cancels = [b for b in dlg.findChildren(QPushButton) if b.text() == "取消"]
        check(len(cancels) >= 1, "下载行应有取消按钮")
        labels = [x.text() for x in dlg.findChildren(QLabel)]
        check(any("打开下载地址" in b.text() for b in dlg.findChildren(QPushButton)),
              "下载类依赖应叫「打开下载地址」")
        check(any("打开官方页面" in b.text() for b in dlg.findChildren(QPushButton)),
              "引导类依赖应叫「打开官方页面」")
        if bars:
            check(not bars[0].isVisible(), "未下载时进度条应隐藏")
            check(bars[0].format() == "%p%", f"进度条应显示百分比（实际 {bars[0].format()}）")
        dl = next((b for b in dlg.findChildren(QPushButton)
                   if b.text() == "下载并校验"), None)
        check(dl is not None, "应有下载按钮")
        if dl is not None and bars:
            dl.click()
            QTest.qWait(250)
            check(started.is_set(), "点下载应真的开始")
            check(bars[0].isVisible(), "下载时进度条应显示")
            check(bars[0].value() == 10, f"进度条应是 10%（实际 {bars[0].value()}）")
            labels_now = [x.text() for x in dlg.findChildren(QLabel)]
            check(any("10.0 MB / 100.0 MB" in x for x in labels_now),
                  f"应显示 MB 进度（实际 {labels_now}）")
            check("下载源" in dlg.hint.text(), f"提示应说 download 源（实际 {dlg.hint.text()}）")
            check(not dl.isEnabled(), "下载中应禁用下载按钮")
            check(cancels and cancels[0].isVisible(), "下载中应显示取消按钮")

            # 关掉再开：同一份下载进度应还在
            dlg2 = RequiresDialog(None, "demo", "演示")
            dlg2.show()
            QTest.qWait(100)
            bars2 = dlg2.findChildren(QProgressBar)
            check(bool(bars2) and bars2[0].isVisible(), "重开依赖框应看到进行中的进度")
            if bars2:
                check(bars2[0].value() == 10, "重开后进度值应保留")

            if cancels:
                cancels[0].click()
                QTest.qWait(300)
                check("取消" in dlg.hint.text(), f"取消后应提示已取消（实际 {dlg.hint.text()}）")
    finally:
        release.set()
        QTest.qWait(150)
        if dlg2 is not None:
            dlg2.close()
            dlg2.deleteLater()
        dlg.close()
        dlg.deleteLater()
        QTest.qWait(80)
        pbab.require_status, pbab.download_require = orig_status, orig_dl


def test_requires_dialog_reopen_done() -> None:
    app = QApplication.instance() or QApplication([])
    orig_status, orig_dl = pbab.require_status, pbab.download_require
    state = {"ok": False}
    started = threading.Event()
    release = threading.Event()

    def status(_mid: str) -> list[dict]:
        return [{
            "id": "runtime", "name": "运行时", "kind": "runtime", "ok": state["ok"],
            "install": "download", "source": ["http://example.invalid/x"],
            "size": 128, "target": "runtime", "sha256": "0" * 64,
        }]

    def fake_dl(mid: str, rid: str, progress=None, cancel=None, stage=None):
        started.set()
        if progress:
            progress(60, 100)
        release.wait(3)
        state["ok"] = True
        return {"ok": True, "id": rid, "path": "x"}

    pbab.require_status, pbab.download_require = status, fake_dl
    dlg = RequiresDialog(None, "demo", "演示")
    dlg.show()
    QTest.qWait(50)
    dlg2 = None
    try:
        dl = next((b for b in dlg.findChildren(QPushButton)
                   if b.text() == "下载并校验"), None)
        check(dl is not None, "应有下载按钮")
        if dl is not None:
            dl.click()
            QTest.qWait(150)
            check(started.is_set(), "后台下载应已开始")
            dlg.close()
            release.set()
            QTest.qWait(500)
            dlg2 = RequiresDialog(None, "demo", "演示")
            dlg2.show()
            QTest.qWait(100)
            check("1/1 就绪" in dlg2.hint.text(),
                  f"下载完重开应显示已就绪（实际 {dlg2.hint.text()}）")
            check(not any(b.text() == "下载并校验" for b in dlg2.findChildren(QPushButton)),
                  "已就绪的行不该再有下载按钮")
    finally:
        release.set()
        QTest.qWait(150)
        if dlg2 is not None:
            dlg2.close()
            dlg2.deleteLater()
        dlg.close()
        dlg.deleteLater()
        QTest.qWait(80)
        pbab.require_status, pbab.download_require = orig_status, orig_dl


def test_call_on_err() -> None:
    class FakeHint:
        def setText(self, _text: str) -> None:
            pass

    class FakePage:
        hint = FakeHint()

        def reload(self) -> None:
            pass

    page = FakePage()
    seen: list[BaseException] = []
    popped: list[tuple] = []
    orig_run, orig_box = mods_page.run_async, mods_page.QMessageBox

    def fake_run(fn, on_ok, on_err=None, on_err_obj=None):
        on_err_obj(pbab.PbabMissingRequires(
            "还缺依赖：运行时。先在模组页点「依赖」把它们装好，再启用。"))

    class FakeBox:
        @staticmethod
        def warning(*args):
            popped.append(args)

    mods_page.run_async = fake_run
    mods_page.QMessageBox = FakeBox
    try:
        try:
            mods_page.ModsPage.call(page, lambda mid: None, "m", "好了",
                                    on_err=lambda exc: seen.append(exc) or True)
        except TypeError as exc:
            check(False, f"ModsPage.call 应接受 on_err（实际 {exc}）")
    finally:
        mods_page.run_async, mods_page.QMessageBox = orig_run, orig_box
    check(bool(seen), "call 应把异常对象交给 on_err")
    check(bool(seen) and isinstance(seen[0], pbab.PbabMissingRequires),
          "on_err 收到的应是 PbabMissingRequires 异常对象")
    check(not popped, "on_err 处理了就不该再弹默认错误框")


def test_toggle_opens_requires() -> None:
    class FakeHint:
        def setText(self, _text: str) -> None:
            pass

    class FakePage:
        def __init__(self) -> None:
            self.hint = FakeHint()
            self.calls: list[dict] = []

        def reload(self) -> None:
            pass

        def call(self, fn, mid, ok_text, after=None, on_err=None) -> None:
            self.calls.append({"fn": fn, "mid": mid, "on_err": on_err})
            if on_err is not None:
                on_err(pbab.PbabMissingRequires(
                    "还缺依赖：运行时。先在模组页点「依赖」把它们装好，再启用。"))

    card = type("Card", (), {})()
    card.mod = {"id": "m", "name": "演示", "state": "disabled"}
    card.page = FakePage()
    card.opened = False
    card.on_requires = lambda: setattr(card, "opened", True)
    try:
        mods_page.ModuleCard.on_toggle(card)
    except TypeError as exc:
        check(False, f"on_toggle 应传 on_err 给 page.call（实际 {exc}）")
    QTest.qWait(50)
    check(card.opened, "启用失败且抛 PbabMissingRequires 时应自动打开依赖框")


def test_missing_requires_type() -> None:
    orig = pbab.require_status
    pbab.require_status = lambda _mid: [{"id": "r", "name": "运行时", "ok": False}]
    try:
        try:
            pbab.ensure_requires("demo")
        except pbab.PbabMissingRequires as exc:
            check("还缺依赖" in str(exc), "缺依赖应抛 PbabMissingRequires")
        else:
            check(False, "缺依赖时 ensure_requires 应抛异常")
    finally:
        pbab.require_status = orig


def main() -> int:
    test_download_progress()
    test_download_require_cancel()
    test_requires_dialog_progress()
    test_requires_dialog_reopen_done()
    test_call_on_err()
    test_toggle_opens_requires()
    test_missing_requires_type()
    # 等后台线程收尾，否则 Qt 在解释器退出时可能带着未结束的 QThread 崩溃。
    try:
        from app.services import worker as _worker
        if _worker._POOL is not None:
            _worker._POOL.waitForDone(5000)
    except Exception:  # noqa: BLE001
        pass
    app = QApplication.instance()
    if app is not None:
        app.processEvents()
    print("")
    if FAILS:
        print(f"失败 {len(FAILS)} 条：")
        for f in FAILS:
            print("  -", f)
        sys.stdout.flush()
        os._exit(1)
    print(f"PASS {OKS} 条")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
