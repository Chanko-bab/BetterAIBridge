# -*- coding: utf-8 -*-
import os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("BAB_NO_AUTORESTART", None)
os.environ.pop("XIAOCHEN_SMOKE", None)
from unittest.mock import patch
from app.ui import main_window as mw
from app.services import runtime

class Log:
    def warning(self, *a, **k): pass

class Label:
    def setText(self, *a, **k): pass

class Fake:
    _core_down = 0
    _last_core_restart = 0.0
    _core_proc = None
    log = Log()
    foot_label = Label()
    def _core_proc_done(self, *a): pass

checks = 0
def ok(cond, msg):
    global checks
    assert cond, msg
    checks += 1

runtime.STATE.update(state="starting", at=time.time(), detail="正在确认内核…")
f = Fake()
with patch.object(mw.config, "get", lambda key, default=None: default if default is not None else True):
    for _ in range(3):
        mw.MainWindow._watch_core(f, False)
ok(f._core_down == 0, "starting 时不应累计失败")
ok(f._core_proc is None, "starting 时不应启动第二份内核")

runtime.STATE.update(state="starting", at=time.time() - 120, detail="stale")
f2 = Fake()
with patch.object(mw.config, "get", lambda key, default=None: default if default is not None else True):
    mw.MainWindow._watch_core(f2, False)
ok(f2._core_down == 1, "starting 超过 90 秒后应恢复计数")

f3 = Fake(); f3._core_down = 2
mw.MainWindow._watch_core(f3, True)
ok(f3._core_down == 0, "up 时应清零")

print(f"core_watch: {checks} checks PASS")
