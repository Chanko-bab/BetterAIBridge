# -*- coding: utf-8 -*-
"""把出包 staging 目录（packaging\\payload）打成绿色/便携 zip。

用法（在仓库根）：
    .venv\\Scripts\\python.exe packaging\\make-portable.py
    .venv\\Scripts\\python.exe packaging\\make-portable.py --out D:\\BAB-release

生成的 zip 解压后是一个自带说明的目录：先双击 setup.cmd 装依赖（只装一次），
之后双击 start.cmd。数据留在目录里，不写注册表、不加卸载项。
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

README = """BetterAIBridge {version} 便携版（绿色，免安装）
=================================================

这是一个解压就能用的版本：不写注册表、不装卸载项、不开机自启。
所有东西——程序、人格、记忆、日志——都在这一个文件夹里，整个文件夹挪走或删掉就行。

第一次使用
----------
1. 双击 setup.cmd（或右键 setup.ps1 → 使用 PowerShell 运行）。
   它会建三个 Python 环境并联网装依赖，通常 5-15 分钟，请不要中途关窗口。
   机器上没有 Python 3.10+ 时，它会自己下载并装一个 3.12（只装给当前用户，不需要管理员）。
2. 装完后双击 start.cmd 启动，跟着向导填称呼和 API Key。
3. 之后再启动都只需要 start.cmd。

数据在哪
--------
    WiseEntity\\entity\\        她的人格、记忆、情绪、自我
    WiseEntity\\runtime\\logs\\ 内核日志
    logs\\                      启动器日志
    config\\app.yaml            端口和路径（第一次启动自动生成）

卸载就是把整个文件夹删掉。删之前建议在「设置 → 存档 → 导出」存一个 .babpak。

和安装版的区别
--------------
- 不写系统卸载信息，不出现在「应用和功能」里；没有桌面/开始菜单快捷方式。
- 不参与自动更新：升级请下载新的便携 zip，解压到新文件夹，
  把旧的 config\\ 和 WiseEntity\\entity\\ 拷过去（或者用新版本的迁移命令）。
- 同一台机器上可以和安装版并存；但请不要让两个版本指向同一个数据目录，也不要同时开两个。

关于下一个大版本
----------------
0.6.5 是 Python 版的最后一个版本。0.7.0 会改用 Go + Wails 重写，届时会提供数据迁移命令，
把人格、记忆、情绪、自我、模组配置和存档搬到新版本；模组接口保持兼容。
0.6.5 装好可以一直用，不需要为了 0.7.0 提前做什么。
"""


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(HERE / "payload"), help="staging 目录")
    ap.add_argument("--out", default=str(REPO.parent / "dist"), help="输出目录")
    ap.add_argument("--version", default="", help="默认读仓库根 VERSION.txt")
    args = ap.parse_args(argv)

    src = Path(args.src)
    if not (src / "main.py").is_file():
        print(f"[-] 找不到 payload：{src}\\main.py（先跑 build.ps1 生成 staging）", file=sys.stderr)
        return 2

    version = args.version.strip()
    if not version:
        txt = (REPO / "VERSION.txt").read_text(encoding="utf-8-sig").strip()
        version = txt.split()[-1] if txt else ""
    if not version:
        print("[-] 读不到版本号", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    name = f"BetterAIBridge-{version}-portable"
    target = out / f"{name}.zip"

    files = sorted(p for p in src.rglob("*") if p.is_file())
    print(f"[*] staging {src} -> {target}（{len(files)} 个文件）")

    tmp = target.with_suffix(".zip.tmp")
    if tmp.exists():
        tmp.unlink()
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        readme = README.format(version=version).replace("\n", "\r\n")
        info = zipfile.ZipInfo(f"{name}/README-PORTABLE.txt", date_time=(2026, 11, 20, 12, 0, 0))
        info.external_attr = 0o644 << 16
        z.writestr(info, ("\ufeff" + readme).encode("utf-8"))
        for f in files:
            rel = f.relative_to(src).as_posix()
            z.write(f, f"{name}/{rel}")

    tmp.replace(target)
    data = target.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    print(f"[+] {target.name}")
    print(f"    {len(data):,} B  sha256 {sha}")
    print(f"    {len(files) + 1} 个文件（含 README-PORTABLE.txt）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
