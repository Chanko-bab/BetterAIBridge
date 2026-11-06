# -*- coding: utf-8 -*-
"""存档 / 导入 / 卸载计划 的回归测试（非 pytest，退出码 0/1）。"""
from __future__ import annotations

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


def make_entity(base: Path) -> Path:
    ent = base / "WiseEntity" / "entity"
    (ent / "persona").mkdir(parents=True)
    (ent / "persona" / "persona.md").write_text("# 人格\n她叫小琛。\n", encoding="utf-8")
    (ent / "config").mkdir(parents=True)
    (ent / "config" / "llm.json").write_text('{"api_key": "sk-x"}', encoding="utf-8")
    (ent / "config" / "llm.placeholder.json").write_text("{}", encoding="utf-8")
    mem = ent / "memory"
    (mem / "internal" / "web_owner").mkdir(parents=True)
    (mem / "internal" / "web_owner" / "2026.10.31.txt").write_text(
        "2026.10.31\n\n上午(06:00-11:00)\n- 08:12 主人说早上好\n", encoding="utf-8")
    # 一个"没装的模组"的抽屉：强写必须把它也带上
    (mem / "external" / "program_ghost" / "提醒").mkdir(parents=True)
    (mem / "external" / "program_ghost" / "提醒" / "2026.10.31.txt").write_text(
        "2026.10.31\n\n下午(13:00-18:00)\n- 15:00 该喝水了\n", encoding="utf-8")
    (ent / "state").mkdir(parents=True)
    (ent / "state" / "sessions.json").write_text('{"turns": 3}', encoding="utf-8")
    (ent / "state" / "instance.json").write_text('{"pid": 1}', encoding="utf-8")
    return ent


def main() -> int:
    name = portable.archive_name("小琛")
    check(name.endswith(portable.ARCHIVE_EXT), f"存档后缀应是 {portable.ARCHIVE_EXT}（实际 {name}）")
    check("小琛" in name, "存档名里应带显示名")
    check("/" not in name and ":" not in name, "存档名里不能有路径分隔符/冒号")
    check(portable.archive_name('a/b:c*?"<>|').count("/") == 0, "非法字符要被剔掉")

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        ent = make_entity(base)
        target = base / "out.babpak"
        res = portable.write_archive(ent, "小琛", target=target)
        check(res.get("ok"), f"存档应成功（实际 {res}）")
        check(Path(res.get("path", "")).is_file(), "存档文件应真的写出来")
        check(res.get("memory") == 2, f"两个记忆文件都要进存档（实际 {res.get('memory')}）")
        with zipfile.ZipFile(target) as zf:
            names = zf.namelist()
            man = zf.read("manifest.json").decode("utf-8")
        check("manifest.json" in names, "存档里应有 manifest.json")
        check("entity/persona/persona.md" in names, "应带上人格")
        check("entity/config/llm.json" in names, "应带上模型配置")
        check("entity/config/llm.placeholder.json" not in names, "占位配置不该进存档")
        check("entity/state/instance.json" not in names, "运行期状态不该进存档")
        check("bab-archive/1" in man, f"清单里应有版本号（实际 {man[:60]}）")

        info = portable.read_archive(target)
        check(info.get("ok") and info.get("persona") and info.get("memory"), f"读取存档应认出人格与记忆（实际 {info}）")

        bad = base / "bad.babpak"
        bad.write_bytes(b"not a zip")
        check(not portable.read_archive(bad).get("ok"), "坏文件要被判成无效存档")

        no_man = base / "noman.babpak"
        with zipfile.ZipFile(no_man, "w") as zf:
            zf.writestr("hello.txt", "hi")
        check(not portable.read_archive(no_man).get("ok"), "没有清单的 zip 要被拒")

        # 导入到一台全新的安装里：记忆强写，不看模组装没装
        fresh = base / "Fresh" / "WiseEntity" / "entity"
        fresh.mkdir(parents=True)
        r = portable.restore_archive(target, fresh)
        check(r.get("ok"), f"导入应成功（实际 {r}）")
        got = (fresh / "memory" / "external" / "program_ghost" / "提醒" / "2026.10.31.txt")
        check(got.is_file() and "该喝水了" in got.read_text(encoding="utf-8"),
              "没装过的模组抽屉也要强写进去")
        check((fresh / "persona" / "persona.md").is_file(), "人格要写到新安装里")
        check((fresh / "state" / "sessions.json").is_file(), "聊天记录应一起恢复")

        # 卸载计划：只认程序目录
        app = base / "App"
        (app / "WiseEntity").mkdir(parents=True)
        (app / "main.py").write_text("print('hi')", encoding="utf-8")
        plan = portable.uninstall_script(app)
        check(plan.get("ok"), f"正规程序目录应能生成卸载脚本（实际 {plan}）")
        check(str(app) in plan.get("ps1", ""), "ps1 里应写死这个程序目录")
        ps1 = plan.get("ps1", "")
        check("Remove-Item" in ps1 and "-Recurse" in ps1, "脚本应真的删目录")
        check("Stop-Process" in ps1, "脚本应杀占用进程")
        check("for ($i" in ps1, "脚本应重试删除")
        check("CreateShortcut" in ps1 and "TargetPath" in ps1, "脚本应只删指向本程序的快捷方式")
        check("System.Windows.Forms" in ps1 and "ProgressBar" in ps1,
              "卸载要有一块自己的画面（WinForms + 进度条），不再只有黑窗口")
        check("$form.Show()" in ps1 and "DoEvents" in ps1, "画面要真的显示并刷新进度")
        check("卸载完成" in ps1, "成功时给一句「卸载完成」")
        check("backup entity" in ps1 and "uninstalled-entity-" in ps1,
              "旧安装的 entity 要先备份再删")
        check("renamed empty dir" in ps1, "文件删净、只剩空目录时要当成功处理")
        check("记忆和人格会先备份" in ps1, "卸载窗口要说明数据会先备份")
        check(plan.get("cmd", "").isascii(), "cmd 壳必须是纯 ASCII")
        check(portable.archive_dir().is_dir(), "存档目录要能自动创建")
        check(str(Path.home()).lower()[:3] in str(portable.archive_dir()).lower(),
              f"存档默认落在用户目录（实际 {portable.archive_dir()}）")

        no_main = base / "NoMain"
        (no_main / "WiseEntity").mkdir(parents=True)
        check(not portable.uninstall_script(no_main).get("ok"), "没有 main.py 的目录要拒绝")

        check(not portable.uninstall_script(Path("C:\\")).get("ok"), "盘根要拒绝")
        shallow = base / "x"
        shallow.mkdir()
        check(not portable.uninstall_script(shallow).get("ok"), "太浅的目录要拒绝")

    if FAILS:
        print(f"FAIL {len(FAILS)} 条：")
        for f in FAILS:
            print("  -", f)
        print(f"\n{OKS} ok, {len(FAILS)} fail")
        return 1
    print(f"PASS {OKS} 条：存档打包/读取/导入（记忆强写）、卸载计划的路径护栏都对。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
