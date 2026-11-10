"""版本号单一真源：VERSION.txt 说了算，别的地方只能跟它一致。

为什么要有这个文件：
    0.6.5 之前，版本号散在 VERSION.txt、packaging/version.txt、README 的
    "当前版本" 一行、四个 docs/*.html 的导航/首屏/安装说明里。发版时靠人记，
    结果就是"仓库写 0.6.5、站点写 0.6.4、线上还是 0.5.9"这种自相矛盾。
    这个工具把"谁说了算"钉死成 VERSION.txt，其余位置只做跟随。

站点页与代码不同步，是发版时才允许的事：
    本地开发时，代码可能已经是 0.6.5，但线上 Release 还是 0.6.4。
    默认检查只把 README/打包位点当硬错误；docs/*.html 的旧版本会打 WARN，
    不拦自检。发版前用 `--site` 或 `--strict-docs` 再查一次，才会真正失败。

用法：
    python tools\\version.py                 # 检查代码/打包位点，站点只告警
    python tools\\version.py --site          # 连站点页一起检查（发版前用）
    python tools\\version.py --sync          # 同步代码/打包位点
    python tools\\version.py --sync-site     # 同步站点页（发版时用）

退出码：0 一致（或站点仅告警）；1 硬位点不一致；2 读不到 VERSION.txt。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION.txt"
VER_RE = r"(\d+\.\d+\.\d+)"

# 发布位点：只认"这一版叫什么"，不碰 changelog 里的历史版本号。
# 每个元组 = (文件, 正则, 说明)。正则里必须恰好有一个版本号捕获组。
RELEASE_PATTERNS: List[Tuple[str, str, str]] = [
    ("packaging/version.txt", r"^\s*" + VER_RE + r"\s*$", "出包脚本读的版本"),
    ("README.md", r"\*\*当前版本：" + VER_RE, "README 首屏的当前版本"),
    ("README.md", r"有安装包：`BetterAIBridge-Setup-" + VER_RE, "README 里的安装包名"),
]

SITE_PATTERNS: List[Tuple[str, str, str]] = [
    ("docs/index.html", r"下载 " + VER_RE, "首页导航/首屏下载按钮"),
    ("docs/index.html", VER_RE + r" 公开测试版", "首页状态与页脚"),
    ("docs/docs.html", r"BetterAIBridge " + VER_RE + r" 文档", "文档页 meta 描述"),
    ("docs/docs.html", r"下载 " + VER_RE, "文档页导航"),
    ("docs/docs.html", VER_RE + r" · 公开测试版文档", "文档页首屏"),
    ("docs/docs.html", VER_RE + r" 是 Windows 10/11 64 位的公开测试包", "文档页正文"),
    ("docs/docs.html", r"BetterAIBridge " + VER_RE + r"</code>", "文档页默认安装目录"),
    ("docs/docs.html", r"BetterAIBridge-Setup-" + VER_RE + r"\.exe", "文档页安装包名"),
    ("docs/docs.html", r"再装 " + VER_RE, "文档页升级说明"),
    ("docs/docs.html", r"装好 " + VER_RE, "文档页升级说明"),
    ("docs/docs.html", r"手动装 " + VER_RE, "文档页升级说明"),
    ("docs/docs.html", VER_RE + r" 没有", "文档页正文（没有跳过）"),
    ("docs/docs.html", VER_RE + r" 安装完", "文档页正文（安装完没有模组）"),
    ("docs/docs.html", VER_RE + r" 不捆绑模组", "文档页页脚"),
    ("docs/index.html", VER_RE + r" 是启动器/内核的基线版", "首页正文"),
    ("docs/docs.html", r"请手动装 " + VER_RE, "文档页升级说明"),
    ("docs/docs.html", VER_RE + r" 公开测试版 · 下载与 Release 已上线", "文档页页脚"),
    ("docs/developers.html", r"下载 " + VER_RE, "参与页导航"),
    ("docs/modules.html", r"下载 " + VER_RE, "模组页导航"),
    ("docs/modules.html", VER_RE + r" 不捆绑模组", "模组页首屏"),
    ("docs/modules.html", VER_RE + r" 公开测试版", "模组页页脚"),
]


def current() -> str:
    raw = VERSION_FILE.read_text(encoding="utf-8").strip()
    m = re.search(VER_RE, raw)
    if not m:
        print("VERSION.txt 里没有 x.y.z 形式的版本号", file=sys.stderr)
        raise SystemExit(2)
    return m.group(1)


def _scan(ver: str, patterns: List[Tuple[str, str, str]]) -> Tuple[List[str], List[str]]:
    """返回（不一致项、缺失位点）。"""
    bad: List[str] = []
    missing: List[str] = []
    for rel, pattern, label in patterns:
        p = ROOT / rel
        if not p.is_file():
            missing.append(f"{rel}（{label}）")
            continue
        text = p.read_text(encoding="utf-8-sig")
        hits = list(re.finditer(pattern, text, flags=re.MULTILINE))
        if not hits:
            missing.append(f"{rel}（{label}）")
            continue
        for m in hits:
            found = m.group(1)
            if found != ver:
                bad.append(f"{rel}（{label}）：写的是 {found}，应为 {ver}")
    return bad, missing


def sync(ver: str, patterns: List[Tuple[str, str, str]]) -> int:
    changed = 0
    for rel, pattern, _label in patterns:
        p = ROOT / rel
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8-sig")
        new = re.sub(pattern, lambda m: m.group(0).replace(m.group(1), ver, 1),
                     text, flags=re.MULTILINE)
        if new != text:
            p.write_text(new, encoding="utf-8")
            changed += 1
            print(f"  已写 {rel}")
    print(f"同步完成：{changed} 个文件按 {ver} 对齐")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="版本号单一真源检查/同步")
    ap.add_argument("--check", action="store_true", help="只检查（默认）")
    ap.add_argument("--site", action="store_true", help="连站点页一起检查（发版前用）")
    ap.add_argument("--strict-docs", action="store_true", help="站点页不一致即失败（同 --site）")
    ap.add_argument("--sync", action="store_true", help="按 VERSION.txt 同步代码/打包位点")
    ap.add_argument("--sync-site", action="store_true", help="按 VERSION.txt 同步站点页")
    args = ap.parse_args()

    ver = current()
    print(f"  真源 VERSION.txt = {ver}")
    if args.sync:
        return sync(ver, RELEASE_PATTERNS)
    if args.sync_site:
        return sync(ver, SITE_PATTERNS)

    bad, missing = _scan(ver, RELEASE_PATTERNS)
    for m in missing:
        print(f"  MISS {m}")
    for b in bad:
        print(f"  FAIL {b}")

    site_bad, site_missing = _scan(ver, SITE_PATTERNS)
    strict_docs = bool(args.site or args.strict_docs)
    for m in site_missing:
        print(("  MISS " if strict_docs else "  WARN 找不到 ") + m)
    for b in site_bad:
        print(("  FAIL " if strict_docs else "  WARN ") + b)

    if bad or missing:
        print(f"\n失败：{len(bad)} 处不一致、{len(missing)} 处找不到版本位点。")
        print("修法：python tools\\version.py --sync（历史版本号不受影响）")
        return 1
    if strict_docs and (site_bad or site_missing):
        print(f"\n失败：站点页 {len(site_bad)} 处不一致、{len(site_missing)} 处找不到位点。")
        print("修法：python tools\\version.py --sync-site（发版时再跑）")
        return 1
    if site_bad or site_missing:
        print("\n提示：站点页仍是旧版本（本地开发阶段允许）。发版前请再跑 --site。")
    print(f"  PASS {len(RELEASE_PATTERNS)} 个代码/打包位点等于 {ver}"
          + (f"；站点 {len(SITE_PATTERNS)} 个位点也一致" if strict_docs else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
