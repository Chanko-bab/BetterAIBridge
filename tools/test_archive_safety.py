# -*- coding: utf-8 -*-
"""存档导入的安全回归：白名单、路径越界、整包拒绝、原子性。

非 pytest，退出码 0/1。
"""
from __future__ import annotations

import json
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import portable  # noqa: E402

FAILS: list[str] = []
OKS = 0


def check(ok: bool, msg: str) -> None:
    global OKS
    if ok:
        OKS += 1
    else:
        FAILS.append(msg)


def make_zip(path: Path, members: dict[str, bytes], manifest: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        if manifest:
            zf.writestr("manifest.json", json.dumps(
                {"format": portable.ARCHIVE_FORMAT, "name": "测试"}, ensure_ascii=False))
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def fresh_entity(base: Path) -> Path:
    ent = base / "WiseEntity" / "entity"
    for sub in ("persona", "config", "memory", "state", "core"):
        (ent / sub).mkdir(parents=True, exist_ok=True)
    (ent / "core" / "app.py").write_text("ORIGINAL", encoding="utf-8")
    return ent


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        ent = fresh_entity(base)

        # 1. 正常存档：人格、配置、记忆、状态都进得去
        good = make_zip(base / "good.babpak", {
            "entity/persona/persona.md": "# 小琛\n".encode("utf-8"),
            "entity/config/llm.json": b'{"api_key":"sk-test"}',
            "entity/state/sessions.json": b'{"turns":1}',
            "entity/memory/internal/web_owner/2026.11.03.txt": b"hello",
            str(Path("entity") / "self" / "self.md"): b"# \xe6\x88\x91\xe6\x98\xaf\xe8\xb0\x81\n",
            str(Path("entity") / "self" / "evidence.jsonl"): b'{"ability":"avatar_see","ok":true}\n',
        })
        r = portable.restore_archive(good, ent)
        check(r.get("ok") is True, f"正常存档应通过：{r}")
        check((ent / "persona" / "persona.md").is_file(), "人格应写入")
        check((ent / "memory" / "internal" / "web_owner" / "2026.11.03.txt").is_file(), "记忆应写入")
        check((ent / "self" / "self.md").is_file(), "自我档案应写入")
        check((ent / "self" / "evidence.jsonl").is_file(), "能力证据应写入")
        check(not (ent / "config" / "llm.placeholder.json").exists(), "占位配置不该被导入")

        # 2. `..` 越界：整包拒绝，外面不能出现文件
        bad1 = make_zip(base / "bad1.babpak", {
            "entity/persona/persona.md": b"# ok\n",
            "entity" + "/" + ".." + "/" + "evil.txt": b"evil",
        })
        r = portable.restore_archive(bad1, ent)
        check(r.get("ok") is False, "`..` 应被拒绝")
        check(not (base / "evil.txt").exists(), "`..` 不能写出 entity")

        # 3. 盘符绝对路径：拒绝
        bad2 = make_zip(base / "bad2.babpak", {
            "entity/persona/persona.md": b"# ok\n",
            "entity" + "/" + "C:" + "/Windows/evil.txt": b"evil",
        })
        r = portable.restore_archive(bad2, ent)
        check(r.get("ok") is False, "盘符路径应被拒绝")
        check(not Path("C:/Windows/evil.txt").exists(), "盘符路径不能落地")

        # 4. 覆盖程序代码：拒绝，原文件不变
        bad3 = make_zip(base / "bad3.babpak", {
            "entity/persona/persona.md": b"# ok\n",
            "entity/core/app.py": b"PWNED",
        })
        r = portable.restore_archive(bad3, ent)
        check(r.get("ok") is False, "程序代码路径应被拒绝")
        check((ent / "core" / "app.py").read_text(encoding="utf-8") == "ORIGINAL",
              "程序代码不能被改写")

        # 5. 反斜杠：拒绝
        bad4 = make_zip(base / "bad4.babpak", {
            "entity/persona/persona.md": b"# ok\n",
            "entity" + chr(92) + ".." + chr(92) + "evil2.txt": b"evil",
        })
        r = portable.restore_archive(bad4, ent)
        check(r.get("ok") is False, "反斜杠路径应被拒绝")

        # 6. 整包拒绝时一个字节都不写（人格也不能先落盘）
        before = (ent / "persona" / "persona.md").read_bytes()
        bad5 = make_zip(base / "bad5.babpak", {
            "entity/persona/persona.md": b"# NEW\n",
            "entity/memory/../../outside.txt": b"evil",
        })
        r = portable.restore_archive(bad5, ent)
        check(r.get("ok") is False, "坏包应整体拒绝")
        check((ent / "persona" / "persona.md").read_bytes() == before, "坏包不能先写人格")

        # 7. 只有 persona 的旧存档仍能导入
        small = make_zip(base / "small.babpak", {"entity/persona/persona.md": b"# small\n"})
        r = portable.restore_archive(small, ent)
        check(r.get("ok") is True and r.get("files") == 1, f"小存档应通过：{r}")

        # 8. 白名单外的普通文件也拒绝（不是只拦越界）
        bad6 = make_zip(base / "bad6.babpak", {
            "entity/persona/persona.md": b"# ok\n",
            "entity/" + "app" + ".yaml": b"x",
        })
        r = portable.restore_archive(bad6, ent)
        check(r.get("ok") is False, "白名单外文件应被拒绝")

    print(f"{OKS} ok, {len(FAILS)} fail")
    for f in FAILS:
        print("FAIL:", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
