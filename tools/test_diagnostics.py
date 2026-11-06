# -*- coding: utf-8 -*-
"""诊断包：脱敏、日志覆盖、同名不覆盖（非 pytest，退出码 0/1）。"""
from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import diagnostics as D  # noqa: E402

FAILS: list[str] = []
OKS = 0


def check(ok: bool, msg: str) -> None:
    global OKS
    if ok:
        OKS += 1
    else:
        FAILS.append(msg)


def main() -> int:
    # 1. 脱敏：各家 key、Bearer、桥令牌、查询参数
    raw = "\n".join([
        "key=sk-abcdef1234567890",
        "breeze=brz_abcdef1234567890",
        "bridge=0123456789abcdef0123456789abcdef",
        "Authorization: Bearer abcdefghijklmnop",
        "x-bridge-token: s3cr3t-token-value",
        "X-Sense-Token: another-secret",
        "xi-api-key: breezesecret",
        "http://127.0.0.1:1/x?token=verysecret&a=1",
    ])
    clean = D._scrub(raw)
    for secret in ("sk-abcdef1234567890", "brz_abcdef1234567890",
                   "0123456789abcdef0123456789abcdef", "abcdefghijklmnop",
                   "s3cr3t-token-value", "another-secret", "breezesecret",
                   "verysecret"):
        check(secret not in clean, f"脱敏漏了：{secret}")
    check("token=***" in clean, f"查询参数也要遮（实际 {clean}）")
    check("a=1" in clean, "查询参数里的普通字段不要误伤")

    # 2. 同名不覆盖
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        p = base / "x.zip"
        p.write_bytes(b"old")
        p2 = D._unique(p)
        check(p2 != p and p2.name.startswith("x-"), f"同名应加后缀（实际 {p2.name}）")

    # 3. 日志覆盖：core-boot / asr-boot / launcher-boot + entity_core
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        logs = base / "logs"
        runtime = base / "runtime"
        bundle = base / "bundle"
        logs.mkdir()
        runtime.mkdir()
        bundle.mkdir()
        for name in ("core-boot.log", "asr-boot.log", "launcher-boot.log", "app.log"):
            (logs / name).write_text(f"{name} line\n", encoding="utf-8")
        (runtime / "entity_core.log").write_text("entity line\n", encoding="utf-8")
        old = (D.LOGS, D.RUNTIME_LOGS, D.BUNDLE)
        D.LOGS, D.RUNTIME_LOGS, D.BUNDLE = logs, runtime, bundle
        try:
            files: dict[str, str] = {}
            D._collect(files)
        finally:
            D.LOGS, D.RUNTIME_LOGS, D.BUNDLE = old
        for name in ("core-boot.log", "asr-boot.log", "launcher-boot.log"):
            check(f"日志/{name}" in files, f"诊断包应带上 {name}")
        check("日志/entity_core.log" in files, "内核日志仍要带")
        check("日志/app.log" in files, "应用日志仍要带")

    # 4. 两次导出不覆盖
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        a = D.export_zip(base)
        b = D.export_zip(base)
        check(a != b and a.is_file() and b.is_file(),
              f"同秒导出两次应得到两个文件（{a.name} / {b.name}）")
        with zipfile.ZipFile(b) as zf:
            names = zf.namelist()
        check("系统信息.txt" in names, "诊断包应带系统信息")

    if FAILS:
        print(f"FAIL {len(FAILS)} 条：")
        for f in FAILS:
            print("  -", f)
        print(f"\n{OKS} ok, {len(FAILS)} fail")
        return 1
    print(f"PASS {OKS} 条：脱敏、日志覆盖、诊断包不覆盖。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
