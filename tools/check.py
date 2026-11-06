"""一条命令跑完所有自检；红了就别打包。

用法：
    python tools\\check.py              # 全跑
    python tools\\check.py --only pages,memory
    python tools\\check.py --list       # 看有哪些
    python tools\\check.py --no-fallback  # 不许换解释器重试

退出码：0 = 全绿；1 = 有红的；2 = 环境不对（找不到测试脚本）。

为什么要有这个文件：12 套测试分散在两个解释器上跑来跑去，靠人记很容易漏。
打包脚本会在 staging 之前调它一次，红了就不出包——历史上两次事故
（install.ps1 丢 BOM、edge-tts 漏装）都是"打完包才发现"。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 300

# name, script, interpreter ("gui" / "kernel" / "any"), 说明
SUITES = [
    ("pages", "tools/test_pages.py", "gui", "页面接线 / 气泡 / 朗读 / 保姆栏 / 设置页"),
    ("smoke", "tools/smoke.py", "gui", "整窗冒烟：六个页面都在、向导四页"),
    ("stomach", "tools/test_stomach.py", "gui", "肚子：读数、分界、喊饿"),
    ("modules", "tools/test_modules.py", "gui", "模组包：校验、工具与端点对齐、无 pyc"),
    ("requires", "tools/test_requires.py", "gui",
     "外置依赖：清单校验、检测、下载校验、环境变量"),
    ("download_progress", "tools/test_download_progress.py", "gui",
     "依赖下载：进度、取消、半成品清理、重开可见、启用失败自动开依赖框"),
    ("installer_requires", "tools/test_installer_requires.py", "gui",
     "官方安装包依赖：清单、解析、签名、状态机、启动与完成"),
    ("signature", "tools/test_signature.py", "gui",
     "Authenticode：命令构造、状态映射、真实签名文件"),
    ("exception_policy", "tools/test_exception_policy.py", "any",
     "异常策略：宽泛捕获不回流、入口/核心路径无静默 pass"),
    ("module_settings", "tools/test_module_settings.py", "gui",
     "模组设置：number 保留小数、integer 仍走整数"),
    ("reinstall", "tools/test_reinstall.py", "gui",
     "原地重装：覆盖文件、保留设置、缺原包就拒绝"),
    ("ports", "tools/test_ports.py", "gui",
     "端口诊断：谁占着端口、结束进程的安全边界"),
    ("startup", "tools/test_startup.py", "gui",
     "开机自启命令、core.auto_restart 配置读写"),
    ("module_port", "tools/test_module_port.py", "any", "模组端口：真起一次服务、/health"),
    ("nanny", "tools/test_nanny.py", "kernel", "保姆：探 runtime_port、degraded 判定"),
    ("nanny_log", "tools/test_nanny_log.py", "kernel", "保姆日志：落盘、截尾、坏行跳过、面板"),
    ("nanny_window", "tools/test_nanny_window.py", "gui", "保姆小屋：统计、日志行、刷新"),
    ("nanny_scan", "tools/test_nanny_scan.py", "kernel", "保姆按需扫描：列目录、读文本、找关键词、只读边界"),
    ("notices", "tools/test_notices.py", "kernel", "提醒：落盘、读回、动作符与分条"),
    ("proactive", "tools/test_proactive.py", "kernel",
     "主动发言：在线/不在线两套门槛、在线久了搭话、切回在线搭话"),
    ("followup", "tools/test_followup.py", "kernel", "插话：主动程度、计时、补话"),
    ("tool_rounds", "tools/test_tool_rounds.py", "kernel", "工具轮数：协议行不漏进正文"),
    ("reply_split", "tools/test_reply_split.py", "kernel", "长回复分条：换行不断句、不硬劈半句"),
    ("tool_desc", "tools/test_tool_desc.py", "kernel", "工具说明：结构化参数中文化，不露 dict repr"),
    ("tts_timing", "tools/test_tts_timing.py", "gui", "朗读计时：语速、句子窗口"),
    ("tts_http", "tools/test_tts_http.py", "kernel", "BreezeBlue 语音：路径/头/请求体、错误说明"),
    ("avatar", "tools/test_avatar.py", "gui", "头像：默认图、裁剪成 256、元信息、坏图拒绝"),
    ("avatar_kernel", "tools/test_avatar_kernel.py", "kernel", "头像进提示词、桥 avatar.get、工具 avatar_see"),
    ("sense", "tools/test_sense.py", "gui", "耳目：配置、设备、间隔、本机小门"),
    ("sense_kernel", "tools/test_sense_kernel.py", "kernel",
     "耳目内核桥：sense.look/listen、/vision、/asr"),
    ("sense_observe", "tools/test_sense_observe.py", "kernel",
     "耳目一直看着/听着：定时采样、最近感知进提示词"),
    ("self_model", "tools/test_self_model.py", "kernel",
     "自我认知：第一人称、随耳目/模组/工具变化、边界不吹牛"),
    ("self_system", "tools/test_self_system.py", "kernel",
     "自我系统：证据、self.md、经历、账本、校准、反思调度"),
    ("self_reflect", "tools/test_self_reflect.py", "kernel",
     "自我反思：JSON 校验、只写合法档案、工具证据回写"),
    ("self_trials", "tools/test_self_trials.py", "kernel",
     "自我尝试：L0/L1/L2 权限、同意、每小时去重"),
    ("style_kernel", "tools/test_style_kernel.py", "kernel",
     "自定义性格：本地兜底、脸谱规格、应用/恢复、桥"),
    ("memory", "tools/test_memory.py", "kernel", "记忆：一天一本、分桶、压缩、迁移"),
    ("caps", "tools/test_caps.py", "kernel",
     "记忆 A（owner 归一）+ 三个能力（voice.tts / voice.asr / vision.describe）+ 语音服务骨架"),
    ("styles", "tools/test_styles.py", "kernel", "人设：16 套底表与开局取值"),
    ("emotion_bridge", "tools/test_emotion_bridge.py", "kernel", "情绪接线：6 调质 → 13 维、量程、推力上限"),
    ("local_tts", "tools/test_local_tts.py", "any",
     "本地语音包：端口/清单/假 sidecar 合成 WAV/缓存/格式识别"),
    ("refs", "tools/lint_refs.py", "any", "死链：代码里写死的路径还存不存在"),
    ("module_m", "tools/test_module_m.py", "gui", "模组框架 M：清单、二十三个工具、开发说明、旧 id 迁移（没源码就跳过）"),
    ("module_pre", "tools/test_module_pre.py", "any",
     "前置模板 pre：命名/entry/一次性/文档/包校验"),
        ("module_routine", "tools/test_module_routine.py", "gui", "日常事务：清单、十三个工具、时间解析、免打扰、调度（没源码就跳过）"),
        ("module_bili", "tools/test_module_bili.py", "gui",
         "B 站桥：清单、十二个工具、agent.md、自检/日志/设置回读"),
        ("module_qq", "tools/test_module_qq.py", "gui",
         "QQ 桥：清单、十四个工具、自带引擎与登录、看图/听声/引用/撤回/群管待批（没源码就跳过）"),
        ("module_live2d", "tools/test_module_live2d.py", "gui",
         "立绘：清单、四工具、设置、16 动作、情绪映射、口型包络、VTS 追踪参数白名单"),
        ("module_auth", "tools/test_module_auth.py", "any",
         "模组鉴权：直接调 /chat 的模组带本机 token，包能过校验"),
        ("portable", "tools/test_portable.py", "gui", "存档 / 导入 / 卸载计划（路径护栏）"),
        ("pre_bridge", "tools/test_pre_bridge.py", "any",
         "前置模组：pre 命名、受控改文件、备份、存档 Key 开关"),
        ("pre_live", "tools/test_pre_live.py", "any",
         "前置实跑：先建目录写代码，普通模组随后读到，一次性前置退出 0 算启用"),
        ("archive_safety", "tools/test_archive_safety.py", "any",
         "存档导入：白名单、路径越界、整包拒绝、原子性"),
        ("reset", "tools/test_reset.py", "any",
         "重置启动器：清用户数据/模组，留程序、内核代码和安装信息"),
        ("data_dir", "tools/test_data_dir.py", "any",
         "数据目录：0.4.19 起回安装目录、忽略 data_dir、内核同源"),
        ("core_auth", "tools/test_core_auth.py", "gui",
         "内核鉴权：token 落盘、header/cookie、/health 公开、启动器带 token"),
        ("core_http", "tools/test_core_http.py", "kernel",
         "内核鉴权集成：/health 公开、/state 401、带 token 200、/ 拦、/bridge 自己判"),
        ("diagnostics", "tools/test_diagnostics.py", "gui",
         "诊断包：脱敏、引导日志覆盖、同秒导出不覆盖"),
        ("update", "tools/test_update.py", "gui",
         "检查更新：版本号、下载页地址、空地址时只提示不打开"),
        ("ui_font", "tools/test_ui_font.py", "gui",
         "界面字体：字体族替换、字号缩放、边界与日志例外"),
        ("appearance", "tools/test_appearance.py", "gui",
         "外观：字体卡、聊天背景参数、三种背景/四种跟随渲染"),
    ("dialog_bg", "tools/test_dialog_bg.py", "gui",
     "弹窗背景：内置白底图、QDialog/QMessageBox 自动铺"),
        ("wheel_guard", "tools/test_wheel_guard.py", "gui",
         "滚轮防误触：设置数值不被滚轮改，页面仍能滚"),
        ("launcher_idle", "tools/test_launcher_idle.py", "gui",
         "启动器空闲：隐藏/切页停轮询，回来恢复，日志页不空转"),
        ("launcher_p1", "tools/test_launcher_p1.py", "gui",
         "启动器 P1：连接复用、线程池上限、气泡上限、任务去重"),
        ("window_state", "tools/test_window_state.py", "gui",
         "窗口位置：坏坐标夹回可见区，正常位置/大小保存"),
        ("perf", "tools/test_perf.py", "any",
         "启动埋点：节点/毫秒/summary；字号缩放下布局宽度"),
        ("startup_budget", "tools/test_startup_budget.py", "gui",
         "启动预算：只建聊天页、控件 <200、埋点齐全"),
        ("a11y", "tools/test_a11y.py", "gui",
         "可访问性：图标按钮有名字，可点击标题能键盘触发"),
]


def interpreters() -> dict[str, Path | None]:
    gui = ROOT / ".venv" / "Scripts" / "python.exe"
    kernel = ROOT / "WiseEntity" / "entity" / ".venv" / "Scripts" / "python.exe"
    return {
        "gui": gui if gui.exists() else None,
        "kernel": kernel if kernel.exists() else None,
        "any": Path(sys.executable),
    }


def pick(interp: dict[str, Path | None], kind: str) -> Path:
    if kind == "any":
        return Path(sys.executable)
    found = interp.get(kind)
    if found:
        return found
    return Path(sys.executable)


def other_kind(kind: str) -> str:
    return "kernel" if kind == "gui" else "gui"


def run_one(py: Path, script: Path) -> tuple[int, str, float]:
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    t0 = time.time()
    try:
        proc = subprocess.run(
            [str(py), str(script)],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
        )
        out = proc.stdout or ""
        code = proc.returncode
    except subprocess.TimeoutExpired:
        out = f"超时（>{TIMEOUT}s）"
        code = 124
    return code, out, time.time() - t0


def last_line(text: str) -> str:
    for line in reversed([ln.rstrip() for ln in text.splitlines()]):
        if line:
            return line if len(line) <= 90 else line[:87] + "..."
    return ""


def looks_like_missing_module(text: str) -> bool:
    return "ModuleNotFoundError" in text or "ImportError" in text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="跑完 BetterAIBridge 的所有自检")
    ap.add_argument("--only", default="", help="只跑这几套，逗号分隔")
    ap.add_argument("--list", action="store_true", help="列出所有测试")
    ap.add_argument("--no-fallback", action="store_true", help="不许换解释器重试")
    args = ap.parse_args(argv)

    if args.list:
        for name, script, kind, desc in SUITES:
            print(f"{name:12} {kind:7} {desc}")
        return 0

    wanted = {s.strip() for s in args.only.split(",") if s.strip()}
    suites = [s for s in SUITES if not wanted or s[0] in wanted]
    if wanted:
        unknown = wanted - {s[0] for s in SUITES}
        if unknown:
            print(f"[check] 不认识的测试：{', '.join(sorted(unknown))}")
            return 2

    missing = [s[1] for s in suites if not (ROOT / s[1]).exists()]
    if missing:
        print("[check] 找不到这些测试脚本：")
        for m in missing:
            print(f"  - {m}")
        return 2

    interp = interpreters()
    print(f"[check] 根目录 {ROOT}")
    for kind in ("gui", "kernel"):
        py = interp.get(kind)
        print(f"[check] {kind:6} {py if py else '（没有这个 venv，用当前解释器）'}")
    print("")

    header = f"{'suite':12} {'结果':4} {'耗时':>6}  说明"
    print(header)
    print("-" * 78)
    failures: list[str] = []
    t_all = time.time()
    for name, rel, kind, desc in suites:
        script = ROOT / rel
        py = pick(interp, kind)
        code, out, secs = run_one(py, script)
        note = last_line(out)
        if code != 0 and not args.no_fallback and looks_like_missing_module(out):
            alt_kind = other_kind(kind) if kind != "any" else "kernel"
            alt = pick(interp, alt_kind)
            if alt != py:
                code2, out2, secs2 = run_one(alt, script)
                if code2 == 0:
                    code, out, secs, note = code2, out2, secs + secs2, "换 " + alt_kind + " 后通过"
                else:
                    code, out, note = code2, out2, last_line(out2)
        ok = code == 0
        if not ok:
            failures.append(name)
        print(f"{name:12} {'PASS' if ok else 'FAIL':4} {secs:5.1f}s  {desc}")
        if not ok:
            for line in (note or "（没有输出）").splitlines()[-1:]:
                print(f"{'':12}       │ {line}")
    print("-" * 78)
    print(f"[check] {time.time() - t_all:.1f}s · {len(suites) - len(failures)} 通过 · {len(failures)} 失败")
    if failures:
        print(f"[check] 红的是：{', '.join(failures)}")
        print("[check] 完整输出用单套跑：python tools\\check.py --only " + failures[0])
        return 1
    print("[check] 全绿")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
