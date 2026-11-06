"""外观：字体/字号设置 + 聊天消息区的动态背景。

    .venv\\Scripts\\python.exe tools\\test_appearance.py
退出码 0 = 全过；1 = 有断言失败。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtWidgets import QApplication  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def main() -> int:
    app = QApplication(sys.argv[:1])
    assert app is not None

    from app.core import config
    from app.ui import backdrop
    from app.ui.backdrop import Backdrop
    from app.ui.pages.appearance import AppearancePage

    d = backdrop.DEFAULTS
    check(d["enabled"] is True and d["source"] == "image"
          and d["effect"] == "blobs" and d["follower"] == "glow",
          "背景默认开启、内置白底图、漂浮光斑、柔光跟随")
    check(set(backdrop.EFFECTS) == {"gradient", "blobs", "dots"}, "三种背景")
    check(set(backdrop.FOLLOWERS) == {"off", "glow", "trail", "particles"}, "四种跟随")

    tpl = (ROOT / "config" / "app.yaml.template").read_text(encoding="utf-8")
    check("background:" in tpl and "enabled: true" in tpl and "source: image" in tpl,
          "app.yaml 模板默认开背景、用内置图")

    orig = config.get("ui.background")
    try:
        config.set_value("ui.background", {"enabled": True, "source": "effects",
                                          "media": "", "effect": "blobs",
                                          "follower": "glow", "palette": "light",
                                          "speed": 1.0, "opacity": 1.0})
        cfg = backdrop.cfg()
        check(cfg["enabled"] is True and cfg["effect"] == "blobs", "配置能读回")

        b = Backdrop()
        b.resize(420, 300)
        b.show()
        app.processEvents()
        img = b.grab().toImage()
        check(img.width() == 420 and img.height() == 300, "背景按控件尺寸出图")
        center = img.pixelColor(210, 150)
        corner = img.pixelColor(2, 2)
        check(center.name() != corner.name() or center.name() != "#f4f6fa",
              "浅色漂浮光斑在底色上能看见")

        b.set_config({"enabled": False})
        app.processEvents()
        flat = b.grab().toImage().pixelColor(210, 150)
        check(flat.name() == "#f4f6fa", "关掉背景只剩浅灰底")

        seen = set()
        for eff in backdrop.EFFECTS:
            b.set_config({"enabled": True, "effect": eff, "palette": "light"})
            app.processEvents()
            seen.add(b.grab().toImage().pixelColor(210, 150).name())
        check(len(seen) >= 2, "三种背景画出来不一样")

        b.set_config({"enabled": True, "effect": "gradient", "palette": "dark"})
        app.processEvents()
        dark = b.grab().toImage().pixelColor(210, 150)
        check(dark.lightness() > 200, "深色配置也会回落到浅色（不再有黑底）")

        b.set_config({"enabled": True, "effect": "dots", "follower": "trail"})
        b._fx = 0.0
        b._cursor = lambda: (0.9, 0.1)  # type: ignore[method-assign]
        b._step_follower(0.2)
        check(b._fx > 0.0, "跟随点会朝光标移动")

        b.set_config({"enabled": True, "effect": "dots", "follower": "off", "click": True})
        b._clicks = []
        app.processEvents()
        no_click = b.grab().toImage()
        b._clicks = [{"x": 210.0, "y": 150.0, "t": 0.5}]
        app.processEvents()
        with_click = b.grab().toImage()
        diff = 0
        for yy in range(110, 190):
            for xx in range(160, 260):
                if no_click.pixelColor(xx, yy).name() != with_click.pixelColor(xx, yy).name():
                    diff += 1
        check(diff > 20, "点击会在背景上画扩散圈")

        page = AppearancePage(None)
        check(hasattr(page, "cb_font_family") and hasattr(page, "cb_font_size")
              and hasattr(page, "lbl_font_preview"), "外观页有字体卡")
        check(page.cb_font_size.minimum() == 12 and page.cb_font_size.maximum() == 18,
              "字号范围 12–18")
        check(page.cb_bg_source.count() == 3, "底图有动态效果/图片/视频三档")
        check(page.cb_bg_effect.count() == 3 and page.cb_bg_follow.count() == 4,
              "外观页有 3 种背景、4 种跟随")
        check(page.cb_bg_click.count() == 5, "外观页有五种点击效果（含关）")
        check(page.sl_bg_opacity.minimum() == 40 and page.sl_bg_opacity.maximum() == 100,
              "浓淡滑条 40–100")
        check(page.sl_bg_speed.minimum() == 50 and page.sl_bg_speed.maximum() == 200,
              "速度滑条 50–200")

        page.cb_bg_on.setChecked(True)
        page.cb_bg_effect.setCurrentIndex(2)   # 点阵
        page.sl_bg_opacity.setValue(80)
        page._save_bg()
        saved = backdrop.cfg()
        check(saved["enabled"] and saved["effect"] == "dots",
              "外观页改动能写回配置")
        check(saved.get("palette") == "light" and saved.get("click") is True
              and saved.get("click_style") == "ripple",
              "配置里色调固定浅色、点击动画默认开")
        check(abs(float(saved["opacity"]) - 0.8) < 0.01, "浓淡按百分比保存")
        page.cb_bg_click.setCurrentIndex(page.cb_bg_click.findData("off"))    # 关掉点击
        page._save_bg()
        check(backdrop.cfg().get("click") is False, "点击动画能关掉")

        # 图片/视频底图：路径能存，缺文件时退回动态效果且不崩
        missing = str(ROOT / "no-such-media.png")
        config.set_value("ui.background", {
            "enabled": True, "source": "image", "media": missing,
            "effect": "blobs", "follower": "off", "opacity": 1.0,
            "speed": 1.0, "click": False,
        })
        b2 = Backdrop()
        b2.set_config()
        b2.resize(420, 300)
        b2.show()
        app.processEvents()
        b2.grab()
        check(bool(b2.media_error()), "图片不存在时会给出说明并退回动态效果")
        config.set_value("ui.background", {
            "enabled": True, "source": "video", "media": missing,
            "effect": "blobs", "follower": "off", "opacity": 1.0,
            "speed": 1.0, "click": False,
        })
        b3 = Backdrop()
        b3.set_config()
        b3.resize(420, 300)
        b3.show()
        app.processEvents()
        b3.grab()
        check(bool(b3.media_error()), "视频不存在时会给出说明并退回动态效果")

        config.set_value("ui.background", {
            "enabled": True, "source": "image", "media": "",
            "effect": "blobs", "follower": "off", "opacity": 1.0,
            "speed": 1.0, "click": False,
        })
        b4 = Backdrop()
        b4.set_config()
        b4.resize(420, 300)
        b4.show()
        app.processEvents()
        b4.grab()
        check(b4._image is not None and not b4.media_error(),
              "media 留空时自动用内置白底图")
    finally:
        config.set_value("ui.background", orig)

    qss = (ROOT / "app" / "ui" / "theme" / "style.qss").read_text(encoding="utf-8")
    check("QScrollArea#ChatScroll" in qss and "QWidget#Backdrop" in qss,
          "聊天滚动区/背景控件透明")

    print("PASS" if not fails else "FAIL")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
