"""模组看门狗：连续失败才重启、失败退避、每小时上限、停手后记住、HTTP 健康。

这些测试不碰真进程：registry 与 pbab 都换成内存假货，
只验“什么时候该拉、什么时候不该拉、拉完怎么说”。
"""
from __future__ import annotations

import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import pbab_process  # noqa: E402
from app.services import supervisor as sv  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


class FakeRegistry:
    def __init__(self, mods) -> None:
        rows = list(mods.values()) if isinstance(mods, dict) else list(mods)
        self.mods = {m["id"]: dict(m) for m in rows}

    def modules(self):
        return [dict(m) for m in self.mods.values()]

    def get(self, mid):
        m = self.mods.get(mid)
        return dict(m) if m else None

    def patch(self, mid, **kw):
        if mid in self.mods:
            self.mods[mid].update(kw)


class FakePbab:
    KIND_PRE = "pre"

    def __init__(self, registry: FakeRegistry) -> None:
        self.registry = registry
        self.ok = False
        self.restarts: list[str] = []
        self.notes: list[tuple[str, str]] = []
        self.health_calls = 0
        self.restart_raises = False

    def health_ok(self, mod):
        self.health_calls += 1
        return (True, "") if self.ok else (False, "端口 40733 连不上")

    def restart(self, mid):
        if self.restart_raises:
            raise OSError("起不来")
        self.restarts.append(mid)
        m = self.registry.mods[mid]
        m["pid"] = int(m.get("pid") or 0) + 1000
        m["state"] = "enabled"
        self.ok = True
        return dict(m)

    def _note_event(self, mod, state):
        self.notes.append((str(mod.get("id") or ""), state))


class Sup(sv.ModuleSupervisor):
    def __init__(self) -> None:
        super().__init__()
        self.notices: list[str] = []

    def _notice(self, text: str) -> None:
        self.notices.append(text)


def mod(mid="m1", state="enabled", pid=100, kind="module"):
    return {"id": mid, "name": "测试模组", "state": state, "pid": pid,
            "kind": kind, "ports": [40733], "runtime_port": 40733}


def install(monkeypatch_mods: dict) -> tuple[Sup, FakePbab, FakeRegistry]:
    reg = FakeRegistry(monkeypatch_mods)
    fake = FakePbab(reg)
    sv.registry = reg  # type: ignore[assignment]
    sv.pbab = fake  # type: ignore[assignment]
    return Sup(), fake, reg


def test_three_fails_then_restart() -> None:
    sup, fake, reg = install({"m1": mod()})
    fake.ok = False
    sup.tick()
    sup.tick()
    check(not fake.restarts, "失败 1–2 次不重启")
    sup.tick()
    check(fake.restarts == ["m1"], "连续 3 次失败才重启")
    check(reg.mods["m1"]["state"] == "enabled", "重启成功后回到 enabled")
    check(reg.mods["m1"].get("last_health") == "ok", "重启成功后记健康")
    check(any("回来了" in n for n in sup.notices), "恢复时只发一句回来了")
    check(all("nanny" not in n for n in sup.notices), "提示文案里不混 kind（kind 在调用处）")


def test_backoff_and_manual_stop() -> None:
    sup, fake, reg = install({"m1": mod(), "m2": mod("m2", state="disabled")})
    fake.ok = False
    for _ in range(3):
        sup.tick()
    check(len(fake.restarts) == 1, "第一次重启")
    calls = fake.health_calls
    sup.tick()
    check(fake.health_calls == calls, "重启后 15 秒退避期内不再探")
    reg.mods["m1"]["state"] = "disabled"
    reg.mods["m1"]["pid"] = 999
    sup.tick()
    check(fake.health_calls == calls, "用户手动停用后不再探")


def test_give_up_and_remember() -> None:
    sup, fake, reg = install({"m1": mod()})
    fake.ok = False
    # 每轮：3 次失败 + 1 次重启；共 5 次，第 6 轮触发停手。
    sup.tick()  # 3 次失败 → 第 1 次重启
    for _ in range(5):
        # 只把失败数推进到“差一次”，保留 restarts 计数；next 清掉以跳过退避。
        sup._mem["m1"]["fails"] = 2
        sup._mem["m1"]["next"] = 0.0
        fake.ok = False
        sup.tick()
    check(len(fake.restarts) == 5, f"一小时最多重启 5 次（实际 {len(fake.restarts)}）")
    sup._mem["m1"]["next"] = 0.0
    sup._mem["m1"]["fails"] = 2
    fake.ok = False
    sup.tick()
    check(reg.mods["m1"]["state"] == "broken", "超过上限后标 broken")
    check(str(reg.mods["m1"].get("last_error") or "").startswith(sv.GIVEUP_TAG),
          "停手原因带可识别标记")
    check(any("我先不试了" in n for n in sup.notices), "停手时在保姆栏说清楚")
    # 模拟启动器重启：新的看门狗读到 broken + 标记，不再拉。
    sup2, fake2, _ = install({"m1": dict(reg.mods["m1"])})
    before = fake2.health_calls
    sup2.tick()
    check(fake2.health_calls == before and not fake2.restarts, "重启启动器后仍记得停手")


def test_recovery_clears_fails() -> None:
    sup, fake, reg = install({"m1": mod()})
    fake.ok = False
    sup.tick()
    sup.tick()
    fake.ok = True
    sup.tick()
    check(sup._mem["m1"]["fails"] == 0, "恢复一次就清零失败计数")
    check(reg.mods["m1"].get("last_health") == "ok", "恢复后写健康")


def test_pre_module_skipped() -> None:
    sup, fake, _ = install({"pre1": mod("pre1", kind="pre")})
    fake.ok = False
    sup.tick()
    check(fake.health_calls == 0, "前置模组跑完就退出，不巡")


class _H(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        code = 200 if self.path == "/health" else 404
        self.send_response(code)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        return


def test_http_health() -> None:
    srv = HTTPServer(("127.0.0.1", 0), _H)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        check(pbab_process._http_ok(port, {"path": "/health"}), "HTTP /health 200 算健康")
        check(not pbab_process._http_ok(port, {"path": "/nope"}), "HTTP 404 不算健康")
        ok, why = pbab_process.check_health(
            {"runtime_port": port, "pip": 0}, {"type": "http", "path": "/health"})
        check(ok, "check_health 走 http 分支")
        ok2, why2 = pbab_process.check_health(
            {"runtime_port": port}, {"type": "http", "path": "/nope"})
        check(not ok2 and "HTTP" in why2, "HTTP 失败给中文原因")
    finally:
        srv.shutdown()


def test_dead_pid() -> None:
    ok, why = pbab_process.check_health(
        {"runtime_port": 1, "pid": 999_999_999}, {"type": "port"})
    check(not ok and "已经不在" in why, "进程没了先报进程，不甩端口")


def main() -> int:
    test_three_fails_then_restart()
    test_backoff_and_manual_stop()
    test_give_up_and_remember()
    test_recovery_clears_fails()
    test_pre_module_skipped()
    test_http_health()
    test_dead_pid()
    if fails:
        print("FAIL %d" % len(fails))
        for f in fails:
            print("  - " + f)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
