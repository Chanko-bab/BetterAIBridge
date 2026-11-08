"""模组看门狗：模组偷偷死掉时，把它拉起来，并只在保姆栏说一声。

为什么要有它：
- 启动器原来只在开机时 `pbab.start_enabled()` 一次，之后模组崩了没人管；
- 模组卡上的「运行中」只代表进程还在，不代表它真的还能干活。

边界：
- 只巡 `state == "enabled"` 的普通模组；前置模组（kind=pre）跑完就退出，不巡。
- 用户手动停用、正在重启、正在装依赖时不动它。
- 通知只走 `CoreClient.notice_push(..., kind="nanny")`，不往聊天里塞话。
- 重启次数有上限；反复掉线就停手，把原因写进注册表和模组卡。
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Dict, Deque

from app.core import pbab, registry

log = logging.getLogger(__name__)

INTERVAL_S = 20.0
FIRST_DELAY_S = 45.0
FAILS_TO_RESTART = 3
MAX_RESTARTS_PER_HOUR = 5
BACKOFF_S = (15.0, 60.0, 300.0)
# 停手标记：进程重启/启动器重启后，看门狗靠它记住“这个模组已经放弃过了”。
GIVEUP_TAG = "[看门狗停手]"


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


class ModuleSupervisor:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._mem: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    # --- 生命周期 ---------------------------------------------------
    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="bab-mod-watch", daemon=True)
            self._thread.start()
            log.info("模组看门狗已启动（每 %.0f 秒巡一次）", INTERVAL_S)

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # 给开机启动留出时间：刚起来的模组别一上来就被判死。
        if self._stop.wait(FIRST_DELAY_S):
            return
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.warning("模组看门狗巡检出错", exc_info=True)
            self._stop.wait(INTERVAL_S)

    # --- 巡检 -------------------------------------------------------
    def tick(self) -> None:
        now = time.time()
        for mod in registry.modules():
            mid = str(mod.get("id") or "")
            if not mid:
                continue
            state = str(mod.get("state") or "")
            if state == "broken":
                if mid not in self._mem:
                    err = str(mod.get("last_error") or "")
                    if err.startswith(GIVEUP_TAG):
                        try:
                            old_pid = int(mod.get("pid") or 0)
                        except (TypeError, ValueError):
                            old_pid = 0
                        self._mem[mid] = {
                            "pid": old_pid, "fails": 0, "next": 0.0, "gave_up": True,
                            "restarts": deque(), "last_error": err, "last_ok": 0.0,
                        }
                    else:
                        # 开机就 broken 的（缺依赖等）不反复试。
                        continue
            elif state != "enabled":
                continue
            if str(mod.get("kind") or "") == pbab.KIND_PRE:
                continue
            mem = self._mem.setdefault(mid, {
                "pid": 0, "fails": 0, "next": 0.0, "gave_up": False,
                "restarts": deque(), "last_error": "", "last_ok": 0.0,
            })
            try:
                pid = int(mod.get("pid") or 0)
            except (TypeError, ValueError):
                pid = 0
            if mem["pid"] != pid:
                # 用户手动启停/重启或进程自己换了 pid：把旧账清零。
                mem.update(pid=pid, fails=0, next=0.0, gave_up=False, last_error="")
            if mem["gave_up"]:
                continue
            if now < float(mem["next"] or 0):
                continue

            ok, why = pbab.health_ok(mod)
            if ok:
                mem["fails"] = 0
                mem["last_ok"] = now
                mem["last_error"] = ""
                if str(mod.get("last_health") or "") != "ok":
                    registry.patch(mid, last_health="ok", last_ok=_iso(now), last_error="")
                continue

            mem["fails"] = int(mem["fails"]) + 1
            mem["last_error"] = why
            if mem["fails"] == 1 or str(mod.get("last_health") or "") != "fail":
                registry.patch(mid, last_health="fail", last_error=str(why)[:300],
                               last_fail=_iso(now))
            if mem["fails"] < FAILS_TO_RESTART:
                continue
            self._restart(mid, mod, mem, why)

    def _restart(self, mid: str, mod: Dict[str, Any], mem: Dict[str, Any], why: str) -> None:
        now = time.time()
        restarts: Deque[float] = mem["restarts"]
        while restarts and now - restarts[0] > 3600:
            restarts.popleft()
        name = str(mod.get("name") or mid)
        if len(restarts) >= MAX_RESTARTS_PER_HOUR:
            mem["gave_up"] = True
            registry.patch(mid, state="broken", last_health="fail",
                           last_error=(f"{GIVEUP_TAG} 一小时内已重启 {len(restarts)} 次，"
                                       f"先停手：{why}")[:300])
            self._note(mid, "broken")
            self._notice(f"「{name}」反复掉线，我先不试了。原因：{why}；日志在模组卡的「看日志」里。")
            log.warning("模组 %s 一小时内重启 %s 次，停止自动拉起", mid, len(restarts))
            return

        attempt = len(restarts) + 1
        self._notice(f"「{name}」好像掉线了（{why}），我在重新拉起（第 {attempt} 次）。")
        log.warning("模组 %s 健康检查失败 %s 次，尝试第 %s 次重启：%s",
                    mid, mem["fails"], attempt, why)
        ok = False
        reason = ""
        try:
            got = pbab.restart(mid)
            ok, reason = pbab.health_ok(got or registry.get(mid) or mod)
        except (pbab.PbabError, OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
            reason = str(exc)
            log.warning("模组 %s 重启失败：%s", mid, exc)
        restarts.append(now)
        mem["fails"] = 0
        mem["next"] = now + BACKOFF_S[min(attempt - 1, len(BACKOFF_S) - 1)]
        try:
            mem["pid"] = int((registry.get(mid) or {}).get("pid") or 0)
        except (TypeError, ValueError):
            mem["pid"] = 0
        if ok:
            mem["last_ok"] = time.time()
            mem["last_error"] = ""
            registry.patch(mid, state="enabled", last_health="ok",
                           last_ok=_iso(time.time()), last_error="")
            self._note(mid, "enabled")
            self._notice(f"「{name}」回来了。")
        else:
            mem["last_error"] = reason
            registry.patch(mid, state="broken", last_health="fail",
                           last_error=f"自动重启没成功：{reason}"[:300])
            self._note(mid, "broken")
            self._notice(f"「{name}」没拉起来：{reason}。我隔一会儿再试。")

    def _note(self, mid: str, state: str) -> None:
        """记进模组流水，让她在提示词里知道“刚刚变了”。"""
        try:
            pbab._note_event(registry.get(mid) or {"id": mid}, state)  # noqa: SLF001
        except (OSError, ValueError, TypeError, KeyError):
            log.debug("记录模组事件失败：%s", mid, exc_info=True)

    def _notice(self, text: str) -> None:
        """只进保姆栏；内核对不在时安静失败（下次巡检还会继续）。"""
        log.info("看门狗提示：%s", text)
        try:
            from app.services.core_client import CoreClient

            CoreClient(timeout=4).notice_push(text, kind="nanny")
        except (OSError, RuntimeError, ValueError, TypeError):
            log.debug("看门狗提示没送到内核：%s", text, exc_info=True)


supervisor = ModuleSupervisor()
