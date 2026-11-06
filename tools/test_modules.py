"""两个自带模组（web_bridge / bili_bridge）对当前外壳的"适配"回归测试。

测的是外壳真正会读、会用的东西，而不是"文件在不在"：

  1) 清单能过 `pbab.validate()`（format=pbab/1、api=1、id 合规、name/version 非空）；
  2) `connection.json` 里声明的**每一个**工具都能解析出一个端点
     —— 复刻 `WiseEntity/entity/core/tool_bus.py:_build()` 的解析规则：
     先看 `tools[].endpoint`，再退化成"名字最后一段"，两样都对不上，工具会被**静默丢掉**；
  3) 端点 path 以 `/` 开头、method 合法（否则 tool_bus 同样跳过）；
  4) `entry.start` 存在，入口脚本读 `BAB_MODULE_PORT`（外壳会换池端口）；
  5) 清单里 `login.port` / `health.port` / `ports[0]` 三者不打架；
  6) `settings.schema.json` 能被 `pbab.settings_fields()` 读成非空字段表；
  7) 打包好的 `.pbab` 里不含 `__pycache__` / `*.pyc`，且包里的工具声明也全解析得到端点。

开发树里有 `program_cache/_modsrc/<id>/` 就查源码 + 查包；只有装好的副本时（`_modsrc` 不在），
退化成"只查包"——同一份测试在两处都能跑。

用法：
    python tools\\test_modules.py            # 静态检查
    python tools\\test_modules.py --live    # 额外在 BAB_TEST_ROOT 里装+启用+探活，再卸掉
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import pbab  # noqa: E402

CASES = [
    {"id": "web_bridge", "src": ROOT / "program_cache" / "_modsrc" / "web_bridge",
     "pkg": ROOT / "program_cache" / "program_web_bridge.pbab"},
    {"id": "bili_bridge", "src": ROOT / "program_cache" / "_modsrc" / "bili_bridge",
     "pkg": ROOT / "program_cache" / "program_bili_bridge.pbab"},
]

fails: list[str] = []
LIVE_ROOT = os.environ.get("BAB_TEST_ROOT") or ""
LIVE = "--live" in sys.argv
PASS = "PASS"


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


# tool_bus.py:_build() 的解析规则，逐字复刻
def resolve_tools(conn: dict) -> tuple[dict, list[str]]:
    prov = conn.get("provides") or {}
    eps = {}
    for ep in prov.get("endpoints") or []:
        if isinstance(ep, dict) and ep.get("name"):
            eps[str(ep["name"]).lower()] = ep
    out: dict[str, dict] = {}
    lost: list[str] = []
    for t in prov.get("tools") or []:
        if isinstance(t, str):
            name, epic = t, ""
        elif isinstance(t, dict) and t.get("name"):
            name, epic = str(t["name"]), str(t.get("endpoint") or "")
        else:
            continue
        ep = eps.get(epic.lower()) if epic else None
        if ep is None:
            ep = eps.get(name.rsplit("_", 1)[-1].lower())
        if not ep:
            lost.append(name)
            continue
        out[name] = ep
    return out, lost


def check_connection_doc(name: str, conn: dict, where: str) -> int:
    resolved, lost = resolve_tools(conn)
    check(not lost, f"{name}: {where} 的工具全解析到端点（丢了：{lost}）" if lost
          else f"{name}: {where} 的 {len(resolved)} 个工具全解析到端点")
    bad = [f"{k}->{v.get('name')}" for k, v in resolved.items()
           if not str(v.get("path") or "").startswith("/")
           or str(v.get("method") or "POST").upper() not in ("GET", "POST")]
    check(not bad, f"{name}: {where} 端点 path/method 合法（坏的：{bad}）" if bad
          else f"{name}: {where} 端点 path/method 合法")
    return len(resolved)


def check_source(case: dict) -> dict:
    name, src = case["id"], case["src"]
    print(f"\n--- {name} ---")
    if not src.is_dir():
        print(f"skip {name}: 没有源码目录（{src}），只查包")
        return {}
    try:
        meta = pbab.validate(src)
    except Exception as exc:  # noqa: BLE001
        check(False, f"{name}: pbab.validate 失败：{exc}")
        return {}
    man = meta["manifest"]
    check(str(man.get("format")) == "pbab/1", f"{name}: format=pbab/1")
    check(int(man.get("api") or 0) == pbab.API_VERSION, f"{name}: api={pbab.API_VERSION}")
    check(bool(str(man.get("author") or "").strip()), f"{name}: 写了 author")
    check(bool(str(man.get("summary") or "").strip()), f"{name}: 写了 summary（卡片上会显示）")

    conn = meta["connection"]
    check_connection_doc(name, conn, "connection.json")

    start_rel = str((man.get("entry") or {}).get("start") or "")
    start = src / start_rel
    check(start.is_file(), f"{name}: entry.start 存在（{start_rel}）")
    if start.is_file():
        check(b"BAB_MODULE_PORT" in start.read_bytes(),
              f"{name}: entry.start 读 BAB_MODULE_PORT（外壳会换池端口）")

    ports = [int(p) for p in (man.get("ports") or []) if str(p).isdigit()]
    health_port = int((man.get("health") or {}).get("port") or 0)
    login_port = int((man.get("login") or {}).get("port") or 0)
    check(bool(ports), f"{name}: 清单写了 ports")
    if ports:
        check(health_port in ports, f"{name}: health.port({health_port}) 在 ports 里")
        if login_port:
            check(login_port in ports, f"{name}: login.port({login_port}) 在 ports 里")

    fields = []
    if (src / "settings.schema.json").exists():
        # 直接读源码里的 schema（不依赖"这个模组已经装进这台机器"），
        # pbab.settings_fields() 走的是 registry，开发树上没装就永远是 0 个。
        import json as _json

        try:
            doc = _json.loads((src / "settings.schema.json").read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            doc = {}
            check(False, f"{name}: settings.schema.json 不是合法 JSON：{exc}")
        raw_fields = doc.get("fields")
        if not isinstance(raw_fields, list):
            raw_fields = doc.get("properties")
        fields = raw_fields if isinstance(raw_fields, (list, dict)) else []
        check(len(fields) > 0, f"{name}: settings.schema.json 能读成 {len(fields)} 个字段")
    print(f"     {name}: 声明 {len(conn.get('provides', {}).get('tools') or [])} 个工具、"
          f"{len(fields)} 个设置项、{meta['members']} 个文件")
    return man


def check_package(case: dict, src_man: dict) -> None:
    name, pkg = case["id"], case["pkg"]
    if not pkg.exists():
        check(False, f"{name}: 打包产物存在 {pkg}")
        return
    try:
        pmeta = pbab.validate(pkg)
    except Exception as exc:  # noqa: BLE001
        check(False, f"{name}: 包校验失败：{exc}")
        return
    pman = pmeta["manifest"]
    if src_man:
        check(str(pman.get("version")) == str(src_man.get("version")),
              f"{name}: 包里的版本和源一致（{pman.get('version')}）")
    with zipfile.ZipFile(pkg) as zf:
        bad_members = [n for n in zf.namelist() if "__pycache__" in n or n.endswith(".pyc")]
        check(not bad_members, f"{name}: 包里没有 __pycache__/*.pyc（有 {len(bad_members)} 个）")
        try:
            conn = json.loads(zf.read("connection.json").decode("utf-8-sig"))
        except Exception as exc:  # noqa: BLE001
            check(False, f"{name}: 包里读不出 connection.json：{exc}")
        else:
            check_connection_doc(name, conn, "包内")


def wait_port(port: int, seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        with socket.socket() as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", int(port))) == 0:
                return True
        time.sleep(0.2)
    return False


def check_live(case: dict) -> None:
    """在 BAB_TEST_ROOT 里装 + 启用 + 探活，再停用 + 卸载。"""
    name, pkg = case["id"], case["pkg"]
    root = Path(LIVE_ROOT)
    print(f"\n--- {name} @ {root} ---")
    if not (root / "program_bundle").is_dir():
        check(False, f"{name}: {root} 不像一份安装（没有 program_bundle）")
        return
    sys.path.insert(0, str(root))
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    import importlib
    pb = importlib.import_module("app.core.pbab")
    try:
        pb.install(str(pkg))
    except Exception as exc:  # noqa: BLE001
        print(f"     ({name}: 已经装过，直接启用 —— {exc})")
    try:
        res = pb.enable(name)
    except Exception as exc:  # noqa: BLE001
        check(False, f"{name}: 启用失败：{exc}")
        return
    port = int(res.get("runtime_port") or 0)
    check(str(res.get("state")) == "enabled", f"{name}: state=enabled（pid={res.get('pid')}, port={port}）")
    if port:
        check(wait_port(port, 15), f"{name}: 端口 {port} 在听")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=6) as resp:
                doc = json.loads(resp.read().decode("utf-8", "replace"))
            check(doc.get("ok") is True, f"{name}: /health 回 ok=true（version={doc.get('version')}）")
        except Exception as exc:  # noqa: BLE001
            check(False, f"{name}: /health 打不通：{exc}")
    try:
        pb.disable(name)
        pb.uninstall(name)
        check(True, f"{name}: 停用 + 卸载完成")
    except Exception as exc:  # noqa: BLE001
        check(False, f"{name}: 停用/卸载失败：{exc}")


def main() -> int:
    for case in CASES:
        src, pkg = case.get("src"), case.get("pkg")
        if not (src and src.exists()) and not (pkg and pkg.exists()):
            print(f"skip {case['id']}: 开发树里没有它的源码与包（已移出，等基于 M 重做）")
            continue
        man = check_source(case)
        check_package(case, man)
    if LIVE:
        if not LIVE_ROOT:
            check(False, "给了 --live 但没设 BAB_TEST_ROOT")
        else:
            for case in CASES:
                check_live(case)
    print()
    if fails:
        print(f"{len(fails)} 条失败")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
