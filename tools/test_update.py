"""检查更新：版本比较、Release 解析、下载校验、安全解压、helper 脚本。"""
from __future__ import annotations

import hashlib
import io
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import update as U  # noqa: E402

FAILED = []


def check(ok: bool, msg: str) -> None:
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        FAILED.append(msg)


def test_version() -> None:
    check(U.parse_version("v0.6.0") == (0, 6, 0), "解析 v0.6.0")
    check(U.parse_version("0.5.9") == (0, 5, 9), "解析 0.5.9")
    check(U.is_newer("0.6.0", "0.5.9"), "0.6.0 比 0.5.9 新")
    check(not U.is_newer("0.5.9", "0.5.9"), "同版本不算新")
    check(not U.is_newer("0.5.8", "0.5.9"), "旧版本不算新")


def _payload(version="0.6.0", with_zip=True) -> dict:
    assets = [
        {"name": "update.json", "browser_download_url": "https://example/update.json"},
        {"name": f"BetterAIBridge-Setup-{version}.exe", "browser_download_url": "https://example/setup.exe"},
    ]
    if with_zip:
        assets.append(
            {
                "name": f"BetterAIBridge-{version}-update.zip",
                "browser_download_url": "https://example/update.zip",
                "size": 123,
            }
        )
    return {"tag_name": "v" + version, "body": "notes", "assets": assets}


def _fetch(payload, manifest=None):
    def fetch(url: str):
        if url == U.API_LATEST:
            return payload
        if url.endswith("update.json"):
            return manifest
        raise AssertionError(url)

    return fetch


def test_release() -> None:
    version = "0.6.0"
    manifest = {
        "version": version,
        "file": f"BetterAIBridge-{version}-update.zip",
        "sha256": "a" * 64,
        "size": 123,
    }
    info = U.latest_info(fetch=_fetch(_payload(version), manifest))
    check(info.version == version, "release 版本")
    check(info.notes == "notes", "release 说明")
    check(info.sha256 == "a" * 64, "manifest sha256")
    check(info.size == 123, "manifest size")
    check(info.update_url.endswith("update.zip"), "zip 下载地址")
    check(info.setup_url.endswith("setup.exe"), "Setup 下载地址")

    try:
        U.latest_info(fetch=_fetch(_payload(version, with_zip=False), manifest))
    except U.UpdateError as e:
        check("更新包" in str(e), "缺 zip 资产要拒绝")
    else:
        check(False, "缺 zip 资产要拒绝")

    check(U.check("0.5.9", _fetch(_payload(version), manifest)) is not None, "有新版返回 info")
    check(U.check("0.6.0", _fetch(_payload(version), manifest)) is None, "同版本返回 None")


def test_download() -> None:
    data = b"hello update"
    digest = hashlib.sha256(data).hexdigest()

    class Resp:
        def __init__(self):
            self.buf = io.BytesIO(data)

        def read(self, n=-1):
            return self.buf.read(n)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    old = U._open_url
    U._open_url = lambda url: Resp()
    try:
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "u.zip"
            seen = []
            U.download("https://example/u.zip", dest, digest, len(data), progress=lambda n, t: seen.append((n, t)))
            check(dest.read_bytes() == data, "下载内容")
            check(seen and seen[-1][0] == len(data), "下载进度")
            try:
                U.download("https://example/u.zip", dest, "0" * 64, len(data))
            except U.UpdateError as e:
                check("校验" in str(e), "坏哈希要拒绝")
            else:
                check(False, "坏哈希要拒绝")
    finally:
        U._open_url = old


def test_extract() -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        good = td / "good.zip"
        with zipfile.ZipFile(good, "w") as z:
            z.writestr("/".join(("app","x.py")), "x")
            z.writestr("/".join(("WiseEntity","entity","brain","state.py")), "x")
            z.writestr("VERSION.txt", "BetterAIBridge 0.6.0\n")
        out = td / "out"
        U.safe_extract(good, out)
        check((out / "app" / "x.py").read_text() == "x", "解压 app")
        check((out / "WiseEntity" / "entity" / "brain" / "state.py").exists(), "解压 brain py")

        for name in ("/".join(("WiseEntity","entity","memory","x.json")), "/".join(("WiseEntity","entity","config","llm.json"))):
            bad = td / "bad.zip"
            with zipfile.ZipFile(bad, "w") as z:
                z.writestr(name, "{}")
                z.writestr("VERSION.txt", "x")
            try:
                U.safe_extract(bad, td / "badout")
            except U.UpdateError:
                check(True, f"拒绝 {name}")
            else:
                check(False, f"拒绝 {name}")

        bad = td / "evil.zip"
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr(str(Path("..") / "evil.txt"), "x")
        try:
            U.safe_extract(bad, td / "evilout")
        except U.UpdateError:
            check(True, "拒绝路径穿越")
        else:
            check(False, "拒绝路径穿越")


def test_helper() -> None:
    text = U.helper_script(Path(r"D:\BAB"), Path(r"C:\u.zip"), "0.6.0", 1234)
    for needle in ("Wait-Process", "stop-all.ps1", "Expand-Archive", "launch.vbs", "0.6.0", "1234"):
        check(needle in text, f"helper 含 {needle}")
    check("entity\\memory" not in text and "entity/memory" not in text, "helper 不备份个人数据")


def test_market() -> None:
    check(U.market_url() == U.MARKET_PAGE, "市场默认 Pages 模组页")


def main() -> int:
    test_version()
    test_release()
    test_download()
    test_extract()
    test_helper()
    test_market()
    if FAILED:
        print(f"\n{len(FAILED)} 项失败")
        return 1
    print("\n更新逻辑全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
