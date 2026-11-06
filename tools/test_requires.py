# -*- coding: utf-8 -*-
r"""外置依赖（requires）的契约自检。

重资产不随包发：模组只写 `requires`，壳负责「检测 → 告知 → 取得 → 回填」。
这一套不联网，用临时目录和假的下载器把四条线钉住：

1. 清单校验：缺 license_url / download 缺 sha256 / target 越界 / id 重复都要拒；
2. 检测：env 与 paths 能认出已装的第三方软件；
3. 状态：没装就是 missing，登记路径后变 ok，环境变量能注入；
4. 下载：sha256 对不上要删掉并报错，对得上才落位，且不碰用户自己的目录。

    .venv\Scripts\python.exe tools\test_requires.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import zipfile
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


def write_module(base: Path, mid: str, extra: dict | None = None) -> Path:
    d = base / f"program_{mid}.pbab"
    d.mkdir(parents=True)
    man = {"format": "pbab/1", "api": 1, "id": mid, "name": "依赖测试", "version": "0.1.0"}
    man.update(extra or {})
    (d / "module.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    (d / "introduce.md").write_text("# 依赖测试\n", encoding="utf-8")
    (d / "connection.json").write_text(json.dumps({"version": 1, "provides": {"tools": []}}),
                                      encoding="utf-8")
    return d


def expect_fail(base: Path, extra: dict, word: str, label: str) -> None:
    d = write_module(base, "bad_" + str(abs(hash(label)) % 100000), extra)
    try:
        pbab.validate(d)
        check(False, f"{label} 应该被拒")
    except pbab.PbabError as exc:
        check(word in str(exc), f"{label} 的报错要提到「{word}」（实际 {exc}）")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="bab-requires-"))
    bundle = tmp / "bundle"
    bundle.mkdir()
    keep_bd, keep_modules_dir = pbab.bundle_dir, pbab.config.get("modules_dir")
    pbab.bundle_dir = lambda: bundle

    good_req = [
        {"id": "qq-client", "name": "QQ（官方客户端）", "kind": "app", "install": "guided",
         "source": ["https://im.qq.com/pcqq"], "license_url": "https://im.qq.com/license",
         "detect": {"env": ["BAB_TEST_QQ"], "paths": ["%BAB_TEST_QQ%"]}},
        {"id": "runtime", "name": "运行时", "kind": "runtime", "install": "download",
         "source": ["https://example.com/rt.zip"], "sha256": "a" * 64, "size": 3,
         "target": "runtime/rt", "license_url": "https://example.com/license"},
        {"id": "model", "name": "模型素材", "kind": "asset", "install": "manual",
         "source": ["https://example.com/model"], "license_url": "https://example.com/model-license"},
    ]
    try:
        # --- 1. 清单校验
        d = write_module(bundle, "req_ok", {"requires": good_req})
        info = pbab.validate(d)
        check(info["manifest"]["id"] == "req_ok", "带 requires 的正常清单应能过校验")

        expect_fail(bundle, {"requires": [dict(good_req[0], license_url="")]},
                    "license_url", "缺 license_url")
        bad = dict(good_req[1])
        bad.pop("sha256")
        expect_fail(bundle, {"requires": [bad]}, "sha256", "download 缺 sha256")
        expect_fail(bundle, {"requires": [dict(good_req[1], target="../escape")]},
                    "相对路径", "download 的 target 越界")
        expect_fail(bundle, {"requires": [good_req[0], dict(good_req[0])]},
                    "重复", "requires 里 id 重复")
        expect_fail(bundle, {"requires": [dict(good_req[0], source=["file:///etc/passwd"])]},
                    "http", "source 不是 http(s)")

        # --- 2. 检测
        qq_dir = tmp / "qq-installed"
        qq_dir.mkdir()
        os.environ["BAB_TEST_QQ"] = str(qq_dir)
        found = pbab.detect_require({"detect": {"env": ["BAB_TEST_QQ"]}})
        check(Path(found) == qq_dir, f"env 检测应认出已装目录（实际 {found!r}）")
        found2 = pbab.detect_require({"detect": {"paths": ["%BAB_TEST_QQ%"]}})
        check(Path(found2) == qq_dir, f"paths 检测应展开环境变量（实际 {found2!r}）")
        check(pbab.detect_require({"detect": {"env": ["BAB_NOT_SET_XYZ"]}}) == "",
              "找不到时应回空串，而不是瞎猜")

        # --- 3. 状态 / 环境变量
        st = {r["id"]: r for r in pbab.require_status("req_ok")}
        check(st["qq-client"]["ok"] and Path(st["qq-client"]["path"]) == qq_dir,
              f"QQ 已装应判 ok（实际 {st['qq-client']}）")
        check(not st["runtime"]["ok"], "运行时没下过，应判 missing")
        check(not st["model"]["ok"], "模型没登记，应判 missing")
        try:
            pbab.ensure_requires("req_ok")
            check(False, "缺依赖时启用应被拦住")
        except pbab.PbabError as exc:
            check("还缺依赖" in str(exc) and "运行时" in str(exc),
                  f"缺依赖的报错要点名（实际 {exc}）")

        env = pbab.require_env("req_ok")
        check(env.get("BAB_REQ_QQ_CLIENT") == str(qq_dir),
              f"已装依赖要注入环境变量（实际 {env}）")

        model_dir = tmp / "my-model"
        model_dir.mkdir()
        pbab.set_require_path("req_ok", "model", str(model_dir))
        st = {r["id"]: r for r in pbab.require_status("req_ok")}
        check(st["model"]["ok"] and Path(st["model"]["path"]) == model_dir,
              "用户登记路径后应判 ok")
        try:
            pbab.set_require_path("req_ok", "model", str(tmp / "not-there"))
            check(False, "路径不存在时应被拒")
        except pbab.PbabError as exc:
            check("路径不存在" in str(exc), f"路径不存在的报错要清楚（实际 {exc}）")

        # --- 4. 下载 + 校验（假下载器，不联网）
        pbab.config._cfg["modules_dir"] = str(tmp / "cache")  # type: ignore[attr-defined]
        orig_dl = pbab._download
        good_zip = tmp / "rt.zip"
        with zipfile.ZipFile(good_zip, "w") as zf:
            zf.writestr("app.txt", "hi")
        import hashlib

        good_sha = hashlib.sha256(good_zip.read_bytes()).hexdigest()

        def fake_download_ok(url: str, dest: Path, progress=None, cancel=None,
                             timeout: float = 120.0) -> None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(good_zip.read_bytes())

        # 先把清单里的 sha256 换成真的（重新写 module.json）
        d = bundle / "program_req_ok.pbab"
        man = json.loads((d / "module.json").read_text(encoding="utf-8"))
        man["requires"][1]["sha256"] = good_sha
        (d / "module.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")

        def fake_download_bad(url: str, dest: Path, progress=None, cancel=None,
                              timeout: float = 120.0) -> None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"tampered")

        pbab._download = fake_download_bad
        try:
            pbab.download_require("req_ok", "runtime")
            check(False, "sha256 对不上时应报错")
        except pbab.PbabError as exc:
            check("sha256" in str(exc), f"校验失败要说 sha256（实际 {exc}）")
        check(not (bundle / "program_req_ok.pbab" / "runtime" / "rt").exists(),
              "校验失败的东西不能落位")

        pbab._download = fake_download_ok
        try:
            got = pbab.download_require("req_ok", "runtime")
            check(bool(got.get("ok")) and Path(got["path"]).is_dir(),
                  f"下载应解压到 target（实际 {got}）")
            check((Path(got["path"]) / "app.txt").is_file(), "解压内容应完整")
            st = {r["id"]: r for r in pbab.require_status("req_ok")}
            check(st["runtime"]["ok"], "下载完后运行时应判 ok")
        finally:
            pbab._download = orig_dl

        # 目标已存在时不要重复下载
        pbab._download = lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该再下载"))
        try:
            again = pbab.download_require("req_ok", "runtime")
            check(again.get("cached") is True, "已就位时应直接回 cached")
        finally:
            pbab._download = orig_dl
    finally:
        pbab.bundle_dir = keep_bd
        pbab.config._cfg["modules_dir"] = keep_modules_dir  # type: ignore[attr-defined]
        os.environ.pop("BAB_TEST_QQ", None)
        import shutil

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
