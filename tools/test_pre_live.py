# -*- coding: utf-8 -*-
"""前置模组真跑一遍：先建目录/写代码，普通模组随后能读到。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import pbab  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def write_module(base: Path, folder: str, manifest: dict, files: dict[str, str]) -> Path:
    d = base / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / "module.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    for rel, text in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return d


tmp = Path(tempfile.mkdtemp(prefix="bab-pre-live-"))
old_app = pbab.config.APP_DIR
old_bundle = pbab.config.bundle_dir
pbab.config.APP_DIR = tmp
pbab.config.bundle_dir = lambda: tmp / "program_bundle"
py = sys.executable

try:
    src = tmp / "src"
    pre = write_module(src, "pre-program_pre_live.pbab", {
        "format": "pbab/1", "id": "pre_live", "kind": "pre",
        "name": "前置实跑", "version": "0.1.0", "api": 1,
        "entry": {"start": "start.cmd"},
        "bridge": {"wants": ["project.apply"]},
    }, {
        "start.cmd": f'@echo off\r\n"{py}" "%~dp0make.py"\r\n',
        "introduce.md": "# 前置实跑\n\n测试用前置模组。\n",
        "connection.json": '{"provides": {}}\n',
        "make.py": (
            "import os\nfrom pathlib import Path\n"
            "root = Path(os.environ['BAB_ROOT'])\n"
            "(root / 'entity/state/pre_live').mkdir(parents=True, exist_ok=True)\n"
            "(root / 'entity/state/pre_live/ready.txt').write_text('ready', encoding='utf-8')\n"
            "(root / 'demo_added').mkdir(parents=True, exist_ok=True)\n"
            "(root / 'demo_added/hello.py').write_text('X = 1\\n', encoding='utf-8')\n"
        ),
    })
    norm = write_module(src, "program_norm_live.pbab", {
        "format": "pbab/1", "id": "norm_live", "kind": "bridge",
        "name": "普通实跑", "version": "0.1.0", "api": 1,
        "entry": {"start": "start.cmd"},
    }, {
        "start.cmd": f'@echo off\r\n"{py}" "%~dp0use.py"\r\n',
        "introduce.md": "# 普通实跑\n\n测试用普通模组。\n",
        "connection.json": '{"provides": {}}\n',
        "use.py": (
            "import os, sys, time\nfrom pathlib import Path\n"
            "root = Path(os.environ['BAB_ROOT'])\n"
            "ready = root / 'entity/state/pre_live/ready.txt'\n"
            "if not ready.exists():\n"
            "    sys.exit(2)\n"
            "(root / 'entity/state/pre_live/normal_seen.txt').write_text(ready.read_text(encoding='utf-8'), encoding='utf-8')\n"
            "time.sleep(2.2)\n"
        ),
    })

    pbab.install(str(pre))
    pbab.install(str(norm))
    pbab.registry.patch("pre_live", state="enabled")
    pbab.registry.patch("norm_live", state="enabled")

    got = pbab.start_enabled()
    ids = [str(x.get("id") or "") for x in got]
    check(ids[:2] == ["pre_live", "norm_live"], "启动顺序：前置先、普通后")
    check((tmp / "entity" / "state" / "pre_live" / "ready.txt").read_text(encoding="utf-8") == "ready",
          "前置建了目录并写了标记")
    check((tmp / "demo_added" / "hello.py").exists(), "前置新增了代码文件")
    check(pbab.registry.get("pre_live").get("state") == "enabled", "一次性前置跑完算 enabled")
    check((tmp / "entity" / "state" / "pre_live" / "normal_seen.txt").read_text(encoding="utf-8") == "ready",
          "普通模组读到了前置准备的内容")
    check(pbab.registry.get("norm_live").get("state") == "enabled", "普通模组正常启用")

    # --- B：前置模组预写 enabled，401 窗口不该再出现 -------------------
    def watch(mid: str, call, wait_s: float = 5.0):
        seen: list[bool] = []
        box: dict[str, object] = {}

        def worker() -> None:
            try:
                box["res"] = call()
            except Exception as exc:  # noqa: BLE001
                box["err"] = exc

        th = threading.Thread(target=worker, daemon=True)
        th.start()
        deadline = time.time() + wait_s
        while th.is_alive() and time.time() < deadline:
            if (pbab.registry.get(mid) or {}).get("state") == "enabled":
                seen.append(True)
                break
            time.sleep(0.02)
        th.join(35)
        check(not th.is_alive(), f"{mid} 的启用动作在 35 秒内结束")
        return seen, box

    slow = write_module(src, "pre-program_pre_slow.pbab", {
        "format": "pbab/1", "id": "pre_slow", "kind": "pre",
        "name": "慢前置", "version": "0.1.0", "api": 1,
        "entry": {"start": "start.cmd"},
        "bridge": {"wants": ["project.apply"]},
    }, {
        "start.cmd": f'@echo off\r\n"{py}" "%~dp0slow.py"\r\n',
        "introduce.md": "# 慢前置\n\n测试用。\n",
        "connection.json": '{"provides": {}}\n',
        "slow.py": (
            "import os, time\nfrom pathlib import Path\n"
            "time.sleep(2.0)\n"
            "root = Path(os.environ['BAB_ROOT'])\n"
            "(root / 'entity/state/pre_slow').mkdir(parents=True, exist_ok=True)\n"
            "(root / 'entity/state/pre_slow/done.txt').write_text('done', encoding='utf-8')\n"
        ),
    })
    pbab.install(str(slow))
    seen, box = watch("pre_slow", lambda: pbab.enable("pre_slow"))
    check(bool(seen), "慢前置运行期间 registry 已是 enabled（B 生效）")
    check("err" not in box, f"慢前置退出 0 不抛错：{box.get('err')!r}")
    check((box.get("res") or {}).get("state") == "enabled", "慢前置跑完仍是 enabled")

    bad = write_module(src, "pre-program_pre_bad.pbab", {
        "format": "pbab/1", "id": "pre_bad", "kind": "pre",
        "name": "失败前置", "version": "0.1.0", "api": 1,
        "entry": {"start": "start.cmd"},
        "bridge": {"wants": ["project.apply"]},
    }, {
        "start.cmd": f'@echo off\r\n"{py}" "%~dp0bad.py"\r\n',
        "introduce.md": "# 失败前置\n\n测试用。\n",
        "connection.json": '{"provides": {}}\n',
        "bad.py": "import sys, time\ntime.sleep(1.0)\nsys.exit(2)\n",
    })
    pbab.install(str(bad))
    seen2, box2 = watch("pre_bad", lambda: pbab.enable("pre_bad"))
    check(bool(seen2), "失败前置运行期间也先预写 enabled")
    check(isinstance(box2.get("err"), pbab.PbabError), f"退出 2 抛 PbabError：{box2.get('err')!r}")
    check(pbab.registry.get("pre_bad").get("state") == "broken", "退出 2 最终标记 broken")

    # 等普通模组自己退出，清理测试进程
    time.sleep(2.5)
    for mid in ("pre_live", "norm_live"):
        pid = pbab.registry.get(mid).get("pid")
        if pid:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
finally:
    pbab.config.APP_DIR = old_app
    pbab.config.bundle_dir = old_bundle
    shutil.rmtree(tmp, ignore_errors=True)

print()
if fails:
    print(f"FAILED {len(fails)}")
    sys.exit(1)
print("PASS 前置实跑")
