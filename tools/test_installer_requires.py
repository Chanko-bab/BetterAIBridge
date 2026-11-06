# -*- coding: utf-8 -*-
r"""通用「官方安装包」依赖（install:"installer"）的契约自检。

全部用虚构的 Acme.App；不联网、不碰真实产品。
    .venv\Scripts\python.exe tools\test_installer_requires.py
"""
from __future__ import annotations

import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from app.core import pbab  # noqa: E402

FAILS: list[str] = []
OKS = 0


def check(ok: bool, msg: str) -> None:
    global OKS
    if ok:
        OKS += 1
    else:
        FAILS.append(msg)


def good_req(**kw) -> dict:
    req = {
        "id": "acme_app",
        "name": "Acme.App（官方，不随包）",
        "kind": "app",
        "install": "installer",
        "source": ["https://vendor.example/download"],
        "resolve": {
            "type": "json",
            "url": "https://vendor.example/releases.json",
            "keys": ["windows.x64.url"],
            "cache_seconds": 600,
        },
        "verify": {"type": "authenticode", "signer_contains": "Acme"},
        "run": {"mode": "interactive", "elevate": True, "args": []},
        "detect": {"paths": ["%BAB_TEST_ACME%\\acme.exe"], "executable": "acme.exe"},
        "homepage": "https://vendor.example/",
        "license_url": "https://vendor.example/eula",
    }
    req.update(kw)
    return req


def expect_bad(req: dict, word: str, label: str) -> None:
    try:
        pbab._check_requires({"requires": [req]})
        check(False, f"{label} 应被拒绝")
    except pbab.PbabError as exc:
        check(word in str(exc), f"{label} 报错应提到「{word}」（实际 {exc}）")


def write_module(base: Path, mid: str, req: dict) -> Path:
    d = base / f"program_{mid}.pbab"
    d.mkdir(parents=True)
    man = {"format": "pbab/1", "api": 1, "id": mid, "name": "Acme 测试", "version": "0.1.0",
           "requires": [req]}
    (d / "module.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    return d


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="bab-installer-"))
    bundle = tmp / "bundle"
    bundle.mkdir()
    keep_bd = pbab.bundle_dir
    keep_modules = pbab.config.get("modules_dir")
    pbab.bundle_dir = lambda: bundle
    pbab.config._cfg["modules_dir"] = str(tmp / "cache")  # type: ignore[attr-defined]
    pbab._RESOLVE_CACHE.clear()
    pbab._SIG_CACHE.clear()
    keep_verify = pbab.verify_installer
    os.environ["BAB_TEST_ACME"] = str(tmp / "acme")
    (tmp / "acme").mkdir()
    try:
        # --- 1. 清单校验
        pbab._check_requires({"requires": [good_req()]})
        expect_bad(good_req(kind="runtime"), "kind", "installer 只允许 app")
        expect_bad(good_req(detect={}), "detect", "缺 detect")
        expect_bad(good_req(verify={"type": "none"}), "verify", "不允许 verify none")
        expect_bad(good_req(verify={"type": "authenticode"}), "signer_contains",
                   "authenticode 缺 signer")
        expect_bad(good_req(verify={"type": "sha256", "sha256": "abc"}), "sha256",
                   "sha256 位数不对")
        expect_bad(good_req(run={"mode": "silent", "args": []}), "interactive",
                   "只允许 interactive")
        expect_bad(good_req(run={"mode": "interactive", "args": ["/S"]}), "args",
                   "args 必须为空")
        expect_bad(good_req(resolve={"type": "json", "url": "http://x/y",
                                     "keys": ["a"]}), "https", "resolve 必须 https")
        expect_bad(good_req(resolve={"type": "json", "url": "https://x/y",
                                     "keys": []}), "keys", "keys 不能为空")
        expect_bad(good_req(resolve={"type": "json", "url": "https://x/y",
                                     "keys": ["a"], "cache_seconds": 9999}),
                   "cache_seconds", "cache_seconds 上限")

        # --- 2. detect 与登记
        exe = tmp / "acme" / "acme.exe"
        exe.write_bytes(b"MZ")
        check(Path(pbab.detect_require(good_req())).name == "acme.exe",
              "paths + 环境变量应能检测")
        write_module(bundle, "acme_det", good_req())
        pbab.set_require_path("acme_det", "acme_app", str(tmp / "acme"))
        rec = pbab._state_item("acme_det", "acme_app")
        check(Path(rec.get("path", "")).name == "acme.exe",
              "选目录时按 detect.executable 拼 exe")
        pbab.set_require_path("acme_det", "acme_app", str(exe))
        check(pbab._state_item("acme_det", "acme_app").get("path") == str(exe),
              "选文件时原样登记")
        env = pbab.require_env("acme_det")
        check(env.get("BAB_REQ_ACME_APP") == str(exe), "require_env 注入登记路径")

        # --- 3. 状态机
        st = pbab.require_status("acme_det")[0]
        check(st["state"] == "installed" and st["ok"], "检测到程序应 installed")

        write_module(bundle, "acme_state",
                     good_req(detect={"paths": ["%BAB_TEST_ACME%\\nope.exe"]}))
        st = pbab.require_status("acme_state")[0]
        check(st["state"] == "missing" and not st["ok"], "没装应 missing")
        inst = tmp / "cache" / "installer" / "acme-setup.exe"
        inst.parent.mkdir(parents=True, exist_ok=True)
        inst.write_bytes(b"MZ")
        doc = pbab.read_requires_state("acme_state")
        doc["items"] = {"acme_app": {"installer": str(inst)}}
        pbab._write_requires_state("acme_state", doc)
        pbab.verify_installer = lambda p, spec: (True, "valid", "CN=Acme App")
        st = pbab.require_status("acme_state")[0]
        check(st["state"] == "ready" and st["installer_ready"] and not st["ok"],
              "安装包有效应 ready 但 ok=False")
        check(st["installer_path"] == str(inst), "ready 带 installer_path")
        pbab.verify_installer = lambda p, spec: (False, "invalid", "CN=Other")
        st = pbab.require_status("acme_state")[0]
        check(st["state"] == "invalid" and not st["ok"], "签名无效应 invalid")
        pbab.verify_installer = lambda p, spec: (True, "valid", "CN=Acme App")
        pbab._INSTALLING[("acme_state", "acme_app")] = {"started": time.time()}
        st = pbab.require_status("acme_state")[0]
        check(st["state"] == "installing", "安装中应 installing")
        pbab._INSTALLING.clear()
        doc["items"]["acme_app"]["install_started_at"] = time.time()
        pbab._write_requires_state("acme_state", doc)
        st = pbab.require_status("acme_state")[0]
        check(st["state"] == "ready", "只有安装记录、安装包还在时应 ready")

        # --- 4. resolver
        pbab._fetch_text = lambda url: json.dumps(
            {"windows": {"x64": {"url": "https://cdn.example/acme-setup.exe"}}})
        url, note = pbab._resolve_installer_url(good_req())
        check(url == "https://cdn.example/acme-setup.exe", f"json 嵌套键（实际 {url}）")
        pbab._fetch_text = lambda url: (
            'var params = {"a": {"download": "https://cdn.example/js-setup.exe"}};')
        url, note = pbab._resolve_installer_url(
            good_req(resolve={"type": "js-var", "url": "https://x/cfg.js",
                              "keys": ["a.download"]}))
        check(url == "https://cdn.example/js-setup.exe", f"js-var 提取（实际 {url}）")
        pbab._fetch_text = lambda url: (_ for _ in ()).throw(RuntimeError("offline"))
        req_direct = good_req(source=["https://cdn.example/direct.exe"],
                              resolve={"type": "json", "url": "https://x/y",
                                       "keys": ["a"]})
        url, note = pbab._resolve_installer_url(req_direct)
        check(url == "https://cdn.example/direct.exe", "解析失败应回退直链")
        pbab._RESOLVE_CACHE.clear()
        try:
            pbab._resolve_installer_url(good_req(source=["https://x/page"]))
            check(False, "没有直链应抛错")
        except pbab.PbabError:
            check(True, "没有直链应抛错")

        # --- 5. 下载
        write_module(bundle, "acme_dl",
                     good_req(source=["https://cdn.example/Acme Setup.exe"]))
        pbab._fetch_text = lambda url: json.dumps({"url": "https://cdn.example/a.exe"})
        pbab._RESOLVE_CACHE.clear()
        sig_ok = lambda p, spec: (True, "valid", "CN=Acme App")
        pbab.verify_installer = sig_ok
        stages: list[str] = []
        calls = {}

        def fake_dl(url, dest, progress=None, cancel=None, headers=None, max_bytes=None):
            calls["url"] = url
            calls["headers"] = headers or {}
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"MZ-fake")
            if progress:
                progress(10, 10)

        pbab._download = fake_dl
        got = pbab.download_installer("acme_dl", "acme_app", stage=stages.append)
        check(got.get("ok") and Path(got["installer"]).is_file(), "下载安装包应落位")
        check("BetterAIBridge" in calls["headers"].get("User-Agent", ""), "UA 用启动器名")
        check(stages[0] == "resolve" and "signature" in stages and stages[-1] == "done",
              f"阶段顺序不对：{stages}")
        check(Path(got["installer"]).name.startswith("acme_app-"), "文件名带 rid")
        check(pbab._state_item("acme_dl", "acme_app").get("signature") == "valid",
              "下载后记签名状态")

        pbab.verify_installer = lambda p, spec: (False, "invalid", "CN=Other")
        pbab._RESOLVE_CACHE.clear()
        try:
            pbab.download_installer("acme_dl", "acme_app")
            check(False, "签名失败应抛错")
        except pbab.PbabError:
            check(True, "签名失败应抛错")
        check(not Path(pbab._state_item("acme_dl", "acme_app").get("installer", "")).exists(),
              "签名失败应删安装包")

        # --- 6. 签名（sha256）
        pbab.verify_installer = keep_verify
        f = tmp / "signed.bin"
        f.write_bytes(b"abc")
        sha = pbab._sha256_file(f)
        ok, state, _ = pbab.verify_installer(f, {"type": "sha256", "sha256": sha})
        check(ok and state == "valid", "sha256 正确应 valid")
        ok, state, _ = pbab.verify_installer(f, {"type": "sha256", "sha256": "0" * 64})
        check(not ok and state == "invalid", "sha256 不对应 invalid")

        # --- 7. 启动安装器
        write_module(bundle, "acme_run",
                     good_req(detect={"paths": ["%BAB_TEST_ACME%\\nope.exe"]}))
        inst2 = tmp / "cache" / "run" / "acme-setup.exe"
        inst2.parent.mkdir(parents=True, exist_ok=True)
        inst2.write_bytes(b"MZ")
        doc = pbab.read_requires_state("acme_run")
        doc["items"] = {"acme_app": {"installer": str(inst2)}}
        pbab._write_requires_state("acme_run", doc)
        pbab.verify_installer = sig_ok
        pbab._shell_execute = lambda p, args, cwd: 42
        got = pbab.start_installer("acme_run", "acme_app")
        check(got.get("ok") and got.get("started"), "启动安装器应成功")
        check(("acme_run", "acme_app") in pbab._INSTALLING, "启动后要登记安装中")
        pbab._shell_execute = lambda p, args, cwd: 1223
        got = pbab.start_installer("acme_run", "acme_app")
        check(got.get("cancelled") and not got.get("ok"), "UAC 1223 应 cancelled")
        pbab._INSTALLING.clear()

        # --- 8. 完成安装
        pbab._INSTALLING[("acme_run", "acme_app")] = {"started": time.time(),
                                                     "installer": str(inst2)}
        pbab.complete_install("acme_run", "acme_app", str(exe))
        st = pbab.require_status("acme_run")[0]
        check(st["ok"] and st["state"] == "installed", "complete 后 installed")
        check(not inst2.exists(), "完成后删安装包")
        check(("acme_run", "acme_app") not in pbab._INSTALLING, "完成后清安装中")

        # --- 9. UI：状态 chip、按钮、安装确认
        from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton
        app = QApplication.instance() or QApplication([])
        from app.ui.dialogs.module_requires import RequiresDialog

        write_module(bundle, "acme_ui",
                     good_req(detect={"paths": ["%BAB_TEST_ACME%\\nope.exe"]}))
        inst3 = tmp / "cache" / "ui" / "acme-setup.exe"
        inst3.parent.mkdir(parents=True, exist_ok=True)
        inst3.write_bytes(b"MZ")
        doc = pbab.read_requires_state("acme_ui")
        doc["items"] = {"acme_app": {"installer": str(inst3)}}
        pbab._write_requires_state("acme_ui", doc)
        pbab.verify_installer = lambda p, spec: (True, "valid", "CN=Acme App")
        dlg = RequiresDialog(None, "acme_ui")
        labels = [w.text() for w in dlg.findChildren(QLabel)]
        buttons = [w.text() for w in dlg.findChildren(QPushButton)]
        check("待安装" in labels, "ready 应显示待安装")
        check("安装" in buttons, "ready 应有安装按钮")
        check("重新下载" in buttons, "ready 应有重新下载")

        started = {}
        keep_start = pbab.start_installer
        keep_q = QMessageBox.question
        pbab.start_installer = lambda mid, rid: started.update(mid=mid, rid=rid) or {
            "ok": True, "started": True}
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        btn = next(w for w in dlg.findChildren(QPushButton) if w.text() == "安装")
        btn.click()
        check(started.get("rid") == "acme_app", "点安装应调用 start_installer")
        check("安装程序已打开" in dlg.hint.text(), "安装后应提示等待")
        QMessageBox.question = keep_q
        pbab.start_installer = keep_start
        dlg.close()

        # missing 状态
        doc = pbab.read_requires_state("acme_ui")
        doc["items"] = {}
        pbab._write_requires_state("acme_ui", doc)
        dlg = RequiresDialog(None, "acme_ui")
        labels = [w.text() for w in dlg.findChildren(QLabel)]
        buttons = [w.text() for w in dlg.findChildren(QPushButton)]
        check("缺" in labels, "missing 应显示缺")
        check("下载官方安装包" in buttons, "missing 应有下载官方安装包")
        dlg.close()

        # installed 状态
        pbab.set_require_path("acme_ui", "acme_app", str(exe))
        dlg = RequiresDialog(None, "acme_ui")
        labels = [w.text() for w in dlg.findChildren(QLabel)]
        check("✓ 已就绪" in labels, "installed 应显示已就绪")
        dlg.close()
    finally:
        pbab.bundle_dir = keep_bd
        pbab.config._cfg["modules_dir"] = keep_modules  # type: ignore[attr-defined]
        os.environ.pop("BAB_TEST_ACME", None)
        shutil.rmtree(tmp, ignore_errors=True)

    print("")
    if FAILS:
        print(f"失败 {len(FAILS)} 条：")
        for f in FAILS:
            print("  - " + f)
        return 1
    print(f"全过（{OKS} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
