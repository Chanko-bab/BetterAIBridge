"""Authenticode 签名校验：命令构造、状态映射、真实签名文件。"""
from __future__ import annotations

import base64
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core import pbab  # noqa: E402

_ok = 0
_bad = 0


def check(cond, label):
    global _ok, _bad
    if cond:
        _ok += 1
        print("  ok  " + label)
    else:
        _bad += 1
        print("  FAIL " + label)


def _run_script(cmd):
    check(isinstance(cmd, list) and "-EncodedCommand" in cmd,
          "使用 -EncodedCommand，不靠 -Command 追加参数")
    encoded = cmd[cmd.index("-EncodedCommand") + 1]
    return base64.b64decode(encoded).decode("utf-16-le")


def test_command_construction():
    print("== 命令构造 ==")
    seen = {}

    class R:
        stdout = b'{"Status":"Valid","Subject":"CN=Acme"}'
        returncode = 0
        stderr = b""

    def fake(cmd, **kwargs):
        seen["cmd"] = cmd
        return R()

    tricky = Path(r"C:\tmp\a'b.exe")
    with mock.patch.object(pbab.subprocess, "run", side_effect=fake):
        out = pbab._powershell_signature(tricky)
    script = _run_script(seen["cmd"])
    check("Get-AuthenticodeSignature" in script, "调用 Get-AuthenticodeSignature")
    check("a''b.exe" in script, "路径里的单引号被转义")
    check(out["Status"] == "Valid", "解析字符串 Status")
    check(out["Subject"] == "CN=Acme", "解析 Subject")


def test_numeric_status():
    print("== 状态映射 ==")

    class R:
        stdout = b'{"Status":0,"Subject":"CN=Acme"}'
        returncode = 0
        stderr = b""

    with mock.patch.object(pbab.subprocess, "run", return_value=R()):
        out = pbab._powershell_signature(Path("C:/dummy.exe"))
    check(out["Status"] == "Valid", "数值 0 映射为 Valid（不能当成空字符串）")


def test_real_signature():
    print("== 真实文件 ==")
    ps = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    if not ps.is_file():
        print("  skip 没有 powershell.exe")
        return
    sig = pbab._powershell_signature(ps)
    check(sig["Status"] == "Valid", "powershell.exe 是 Valid")
    check("Microsoft" in sig["Subject"], "签名者包含 Microsoft")
    good, state, subject = pbab.verify_installer(
        ps, {"type": "authenticode", "signer_contains": "Microsoft"})
    check(good and state == "valid", "verify_installer 放行 Microsoft")
    bad, state2, _ = pbab.verify_installer(
        ps, {"type": "authenticode", "signer_contains": "NotThisSigner"})
    check((not bad) and state2 == "invalid", "签名者不匹配时拒绝")

    tmp = Path(tempfile.gettempdir()) / "bab-signature-unsigned.exe"
    tmp.write_bytes(b"MZ" + b"\0" * 64)
    try:
        bad, state3, _ = pbab.verify_installer(
            tmp, {"type": "authenticode", "signer_contains": "Microsoft"})
        check(not bad and state3 in ("invalid", "unknown"),
              "未签名文件不放行（invalid/unknown）")
    finally:
        tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    test_command_construction()
    test_numeric_status()
    test_real_signature()
    print(f"\n{_ok} 项通过，{_bad} 项失败")
    sys.exit(0 if _bad == 0 else 1)
