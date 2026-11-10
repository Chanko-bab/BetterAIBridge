"""配置可移植性：换了盘/复制了目录之后，配置里指着的旧目录必须被点名。

背景（0.6.5 自查）：
    把整个项目目录复制到 E 盘之后，config/app.yaml（随目录一起被复制、
    又在 .gitignore 里）还写着 D 盘的老路径。老目录当时还在，于是所有
    "路径不存在就回退" 的判断都不触发，启动器一声不响地去跑 D 盘那份内核。
    这类事故的共同点是：错得很安静。

这里锁住三件事：
    1. 指向安装目录内的配置：不告警，原样保留
    2. 指向目录外（且真实存在）：必须告警，但不擅自改写用户配置
    3. 指向不存在：回退到安装目录推导值（原有行为，不许回归）
另外把"同盘兄弟目录不算内部"这条也锁住——桥的路径守卫踩的是同一类坑。
"""
from __future__ import annotations

import logging
import sys
import tempfile
from pathlib import Path

ROOT = Path(sys.argv[0]).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import config  # noqa: E402

FAILED = []
PASSED = 0


def check(ok: bool, label: str) -> None:
    global PASSED
    if ok:
        PASSED += 1
        print(f"  PASS {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL {label}")


class Capture(logging.Handler):
    """抓住 xiaochen 日志，验证告警真的写了。"""

    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def _sanitize_with_log(cfg):
    cap = Capture()
    log = logging.getLogger("xiaochen")
    log.addHandler(cap)
    old_level = log.level
    log.setLevel(logging.WARNING)
    try:
        out = config._sanitize(cfg)
    finally:
        log.removeHandler(cap)
        log.setLevel(old_level)
    return out, cap.lines


def main() -> int:
    app_dir = Path(config.APP_DIR)

    # 1. 安装目录内：不告警、不改值
    cfg = dict(config.DEFAULTS)
    out, lines = _sanitize_with_log(cfg)
    check(
        not [x for x in lines if "安装目录之外" in x],
        "配置在安装目录内时不会误报",
    )
    check(
        Path(out["project_root"]) == Path(config.DEFAULTS["project_root"]),
        "配置在安装目录内时原样保留",
    )

    # 2. 目录外且存在：必须告警，但不擅自改写
    with tempfile.TemporaryDirectory() as tmp:
        outside = Path(tmp) / "entity"
        outside.mkdir(parents=True, exist_ok=True)
        (outside / "dummy.txt").write_text("x", encoding="utf-8")
        cfg = dict(config.DEFAULTS)
        cfg["project_root"] = str(outside)
        out, lines = _sanitize_with_log(cfg)
        check(
            any("安装目录之外" in x and "project_root" in x for x in lines),
            "配置指向目录外时告警并点名是哪个键",
        )
        check(
            out["project_root"] == str(outside),
            "配置指向目录外时不擅自改写（用户可能是有意的）",
        )

    # 3. 不存在：回退到安装目录推导值
    cfg = dict(config.DEFAULTS)
    cfg["project_root"] = str(Path(tempfile.gettempdir()) / "bab-not-exist-0.6.5")
    out, lines = _sanitize_with_log(cfg)
    check(
        out["project_root"] == config.DEFAULTS["project_root"],
        "路径不存在时回退到安装目录推导值（旧行为不回归）",
    )
    check(
        any("不存在" in x for x in lines),
        "回退时写日志说明原因",
    )

    # 4. 同盘兄弟目录不算内部（桥的守卫踩的是同一类坑）
    sibling = app_dir.parent / (app_dir.name + "-old")
    check(
        not config._inside_install(sibling),
        f"同盘兄弟目录 {sibling.name} 不被判成安装目录内部",
    )
    check(config._inside_install(app_dir), "安装目录自身判为内部")
    check(
        config._inside_install(Path(app_dir) / "WiseEntity"),
        "安装目录的子路径判为内部",
    )

    if FAILED:
        print("\n失败：")
        for label in FAILED:
            print(" -", label)
        return 1
    print(f"\n全部 {PASSED} 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
