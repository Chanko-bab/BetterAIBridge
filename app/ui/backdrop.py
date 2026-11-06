"""聊天列动态背景。

灵感来自 `D:\\动态鼠标跟随背景`（pygame 两层：背景 + 鼠标跟随），这里用 Qt 重画：
- 背景层：呼吸渐变 / 漂浮光斑 / 点阵
- 跟随层：柔光 / 拖尾 / 粒子
- 点击：在鼠标按下的位置扩散一圈
铺满整列聊天区（标题、消息、输入），左侧操作台和右侧保姆栏不铺；关掉时保持原来的浅灰底。
"""
from __future__ import annotations

import logging
import math
import random
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, QUrl
log = logging.getLogger("xiaochen.backdrop")

from PySide6.QtGui import (QColor, QCursor, QImage, QLinearGradient, QPainter, QPainterPath,
                          QPen, QPixmap, QRadialGradient)
from PySide6.QtWidgets import QApplication, QWidget

from ..core import config

try:  # 视频是可选能力：机器上没有 QtMultimedia 时退回动态效果
    from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
except Exception:  # noqa: BLE001
    QMediaPlayer = None  # type: ignore
    QVideoSink = None  # type: ignore

EFFECTS = ("gradient", "blobs", "dots")
FOLLOWERS = ("off", "glow", "trail", "particles")
SOURCES = ("effects", "image", "video")
CLICK_STYLES = ("ripple", "double", "spark", "bubble")
PALETTES = ("light",)

PALETTE = {
    "light": {
        "base": "#f4f6fa",
        "top": "#dde8ff",
        "bottom": "#f4f6fa",
        "blobs": ("#8fb8ff", "#b9a3ff", "#8fe3e8"),
        "glow": "#7fa8f5",
        "dots": "#c8d2e4",
    },
}

DEFAULTS = {
    "enabled": True,
    "effect": "blobs",
    "follower": "glow",
    "palette": "light",
    "click": True,
    "click_style": "ripple",
    "source": "image",
    "media": "",
    "speed": 1.0,
    "opacity": 1.0,
}


def default_media() -> Path:
    """内置默认背景（白底同心圆），放在安装目录 assets 下。"""
    return Path(config.APP_DIR) / "assets" / "bab-bg.jpg"


_TICK_MS = 33


def _f(value, lo: float, hi: float, fallback: float) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return fallback


def cfg() -> dict:
    raw = config.get("ui.background")
    out = dict(DEFAULTS)
    if isinstance(raw, dict):
        out.update({k: v for k, v in raw.items() if k in DEFAULTS})
    out["effect"] = out["effect"] if out["effect"] in EFFECTS else "blobs"
    out["follower"] = out["follower"] if out["follower"] in FOLLOWERS else "glow"
    out["source"] = out["source"] if out["source"] in SOURCES else "effects"
    out["media"] = str(out.get("media") or "").strip()
    out["palette"] = "light"
    out["click"] = bool(out.get("click", True))
    out["click_style"] = (out["click_style"] if out.get("click_style") in CLICK_STYLES
                          else "ripple")
    out["speed"] = _f(out["speed"], 0.2, 3.0, 1.0)
    out["opacity"] = _f(out["opacity"], 0.0, 1.0, 1.0)
    out["enabled"] = bool(out["enabled"])
    return out


def save(patch: dict) -> dict:
    cur = cfg()
    cur.update({k: v for k, v in patch.items() if k in DEFAULTS})
    config.set_value("ui.background", cur)
    return cfg()


class Backdrop(QWidget):
    """聊天消息区的背景画布；关掉时只铺一层浅灰。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Backdrop")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        self._cfg = cfg()
        self._phase = 0.0
        self._w = 1
        self._h = 1
        self._blobs: list[dict] = []
        self._blob_pix: list[QPixmap] = []
        self._glow_pix: QPixmap | None = None
        self._dots_pix: QPixmap | None = None
        self._fx = 0.5
        self._fy = 0.5
        self._fade = 1.0
        self._was_inside = False
        self._trail: list[QPointF] = []
        self._particles: list[dict] = []
        self._clicks: list[dict] = []
        self._spawn = 0.0
        self._filtering = False
        self._rnd = random.Random()
        self._image: QImage | None = None
        self._frame: QImage | None = None
        self._media_error = ""
        self._player = None
        self._sink = None
        self._media_key: tuple[str, str] | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._reset_blobs()
        self._rebuild()

    # ---------------------------------------------------------------- 外部接口
    def set_config(self, conf: dict | None = None) -> None:
        self._cfg = cfg() if conf is None else dict(conf)
        self._cfg["effect"] = self._cfg.get("effect") if self._cfg.get("effect") in EFFECTS else "blobs"
        self._cfg["follower"] = self._cfg.get("follower") if self._cfg.get("follower") in FOLLOWERS else "glow"
        self._cfg["source"] = self._cfg.get("source") if self._cfg.get("source") in SOURCES else "effects"
        self._cfg["media"] = str(self._cfg.get("media") or "").strip()
        self._cfg["palette"] = "light"
        self._cfg["click"] = bool(self._cfg.get("click", True))
        self._cfg["click_style"] = (self._cfg["click_style"]
                                    if self._cfg.get("click_style") in CLICK_STYLES
                                    else "ripple")
        self._phase = 0.0
        self._trail.clear()
        self._particles.clear()
        self._reset_blobs()
        self._rebuild()
        if self._cfg.get("enabled"):
            self._apply_media()
        else:
            self._stop_media()
            self._media_key = None
            self._image = None
            self._frame = None
        if self._cfg.get("enabled") and self.isVisible():
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def enabled(self) -> bool:
        return bool(self._cfg.get("enabled"))

    # ---------------------------------------------------------------- 图片 / 视频
    def _apply_media(self) -> None:
        src = str(self._cfg.get("source") or "effects")
        media = str(self._cfg.get("media") or "").strip()
        if src == "image" and not media:
            media = str(default_media())
        key = (src, media)
        if key == self._media_key:
            return
        self._media_key = key
        self._stop_media()
        self._image = None
        self._frame = None
        self._media_error = ""
        if src not in ("image", "video") or not media:
            return
        path = Path(media)
        if not path.is_absolute():
            path = Path(config.APP_DIR) / path
        if not path.is_file():
            self._media_error = "找不到这个文件"
            return
        if src == "image":
            img = QImage(str(path))
            if img.isNull():
                self._media_error = "这张图片读不出来"
            else:
                self._image = img
            return
        if QMediaPlayer is None:
            self._media_error = "这台机器没有 QtMultimedia，放不了视频"
            return
        self._player = QMediaPlayer(self)
        self._sink = QVideoSink(self)
        self._player.setVideoSink(self._sink)
        self._sink.videoFrameChanged.connect(self._on_frame)
        self._player.errorOccurred.connect(self._on_media_error)  # type: ignore[attr-defined]
        self._player.setLoops(QMediaPlayer.Infinite)  # type: ignore[attr-defined]
        self._player.setSource(QUrl.fromLocalFile(str(path)))  # type: ignore[attr-defined]
        self._player.play()  # type: ignore[attr-defined]

    def _stop_media(self) -> None:
        if self._player is not None:
            try:
                self._player.stop()  # type: ignore[attr-defined]
                self._player.setSource(QUrl())  # type: ignore[attr-defined]
                self._player.deleteLater()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                log.debug("清理背景播放器失败", exc_info=True)
            self._player = None
            self._sink = None

    def _on_frame(self, frame) -> None:
        img = frame.toImage()
        if not img.isNull():
            self._frame = img
            self.update()

    def _on_media_error(self, *_args) -> None:
        self._media_error = "视频放不出来（格式或解码器不支持）"
        self.update()

    def media_error(self) -> str:
        return self._media_error

    # ---------------------------------------------------------------- 生命周期
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        inst = QApplication.instance()
        if inst is not None and not self._filtering:
            inst.installEventFilter(self)
            self._filtering = True
        if self._cfg.get("enabled"):
            self._timer.start()
            if self._player is not None:
                self._player.play()  # type: ignore[attr-defined]

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        if self._player is not None:
            self._player.pause()  # type: ignore[attr-defined]
        inst = QApplication.instance()
        if inst is not None and self._filtering:
            inst.removeEventFilter(self)
            self._filtering = False
        super().hideEvent(event)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        """窗口里任何位置按下鼠标，只要落在背景上就扩散一圈。"""
        if (event.type() == QEvent.MouseButtonPress and self.isVisible()
                and self._cfg.get("enabled") and self._cfg.get("click", True)):
            local = self.mapFromGlobal(QCursor.pos())
            if self.rect().contains(local):
                self._clicks.append({"x": float(local.x()), "y": float(local.y()), "t": 0.0})
                if len(self._clicks) > 8:
                    self._clicks = self._clicks[-8:]
                self._timer.start()
                self.update()
        return False

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._w = max(1, self.width())
        self._h = max(1, self.height())
        self._rebuild()
        self.update()

    # ---------------------------------------------------------------- 几何缓存
    def _pal(self) -> dict:
        return PALETTE.get(str(self._cfg.get("palette")), PALETTE["light"])

    def _reset_blobs(self) -> None:
        rnd = random.Random(20261103)
        count = 5
        self._blobs = []
        for i in range(count):
            angle = rnd.uniform(0, math.tau)
            speed = rnd.uniform(0.006, 0.016)
            self._blobs.append({
                "x": rnd.uniform(0.1, 0.9),
                "y": rnd.uniform(0.1, 0.9),
                "vx": math.cos(angle) * speed,
                "vy": math.sin(angle) * speed,
                "color": i % count,
            })

    def _rebuild(self) -> None:
        pal = self._pal()
        radius = max(80, int(min(self._w, self._h) * 0.34))
        self._blob_pix = []
        for color in pal["blobs"]:
            self._blob_pix.append(self._radial(radius, color, 0.45))
        self._glow_pix = self._radial(max(60, int(min(self._w, self._h) * 0.18)), pal["glow"], 0.55)
        dots = QPixmap(self._w, self._h)
        dots.fill(Qt.transparent)
        p = QPainter(dots)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(pal["dots"]))
        step = 42
        for y in range(step // 2, self._h, step):
            for x in range(step // 2, self._w, step):
                p.drawEllipse(QPointF(x, y), 1.5, 1.5)
        p.end()
        self._dots_pix = dots
        self._fx = min(1.0, max(0.0, self._fx))
        self._fy = min(1.0, max(0.0, self._fy))

    @staticmethod
    def _radial(radius: int, color: str, alpha: float) -> QPixmap:
        size = max(2, radius * 2)
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing, True)
        g = QRadialGradient(QPointF(radius, radius), radius)
        c = QColor(color)
        c.setAlphaF(max(0.0, min(1.0, alpha)))
        g.setColorAt(0.0, c)
        mid = QColor(color)
        mid.setAlphaF(max(0.0, min(1.0, alpha * 0.45)))
        g.setColorAt(0.55, mid)
        edge = QColor(color)
        edge.setAlphaF(0.0)
        g.setColorAt(1.0, edge)
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(QRectF(0, 0, size, size))
        p.end()
        return pix

    # ---------------------------------------------------------------- 帧
    def _tick(self) -> None:
        if not self._cfg.get("enabled"):
            self._timer.stop()
            return
        speed = float(self._cfg.get("speed") or 1.0)
        dt = _TICK_MS / 1000.0 * speed
        self._phase += dt
        self._step_blobs(dt)
        self._step_follower(dt)
        for c in self._clicks:
            c["t"] += dt
        self._clicks = [c for c in self._clicks if c["t"] < 0.8]
        self.update()

    def _step_blobs(self, dt: float) -> None:
        for b in self._blobs:
            b["x"] += b["vx"] * dt
            b["y"] += b["vy"] * dt
            if b["x"] < -0.2 or b["x"] > 1.2:
                b["vx"] *= -1
                b["x"] = min(1.2, max(-0.2, b["x"]))
            if b["y"] < -0.2 or b["y"] > 1.2:
                b["vy"] *= -1
                b["y"] = min(1.2, max(-0.2, b["y"]))

    def _cursor(self) -> tuple[float, float] | None:
        local = self.mapFromGlobal(QCursor.pos())
        if 0 <= local.x() <= self._w and 0 <= local.y() <= self._h:
            return local.x() / self._w, local.y() / self._h
        return None

    def _step_follower(self, dt: float) -> None:
        kind = str(self._cfg.get("follower"))
        if kind == "off":
            return
        target = self._cursor()
        if target is None:
            # 移出窗口：不沿边界拖出去，150ms 内淡掉并清空轨迹/粒子
            if self._was_inside:
                self._was_inside = False
            self._fade = max(0.0, self._fade - dt / 0.15)
            if self._fade <= 0.0:
                self._trail.clear()
                self._particles.clear()
            return
        self._was_inside = True
        self._fade = min(1.0, self._fade + dt / 0.12)
        # 光斑中心夹在窗口内，靠近边缘留出半径；拖尾/粒子允许贴边
        margin = 0.10 if kind == "glow" else 0.02
        tx = min(1.0 - margin, max(margin, target[0]))
        ty = min(1.0 - margin, max(margin, target[1]))
        # 指数缓动：顺滑的惯性跟随
        k = 0.12 if kind == "glow" else (0.22 if kind == "trail" else 0.15)
        self._fx += (tx - self._fx) * k
        self._fy += (ty - self._fy) * k
        if kind == "trail":
            self._trail.append(QPointF(self._fx * self._w, self._fy * self._h))
            while len(self._trail) > 18:
                self._trail.pop(0)
        elif kind == "particles":
            self._spawn += dt
            while self._spawn >= 0.02:
                self._spawn -= 0.02
                if len(self._particles) < 120:
                    angle = self._rnd.uniform(0, math.tau)
                    sp = self._rnd.uniform(15, 70)
                    life = self._rnd.uniform(0.6, 1.2)
                    self._particles.append({
                        "x": self._fx * self._w, "y": self._fy * self._h,
                        "vx": math.cos(angle) * sp, "vy": math.sin(angle) * sp,
                        "life": life, "max": life,
                    })
            alive = []
            for pt in self._particles:
                pt["life"] -= dt
                if pt["life"] > 0:
                    pt["x"] += pt["vx"] * dt
                    pt["y"] += pt["vy"] * dt
                    pt["vx"] *= 0.96
                    pt["vy"] *= 0.96
                    if -8 <= pt["x"] <= self._w + 8 and -8 <= pt["y"] <= self._h + 8:
                        alive.append(pt)
            self._particles = alive

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        pal = self._pal()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 14.0, 14.0)
        p.setClipPath(clip)
        p.fillRect(self.rect(), QColor(pal["base"]))
        if not self._cfg.get("enabled"):
            p.end()
            return
        opacity = float(self._cfg.get("opacity") or 1.0)
        source = str(self._cfg.get("source") or "effects")
        drew = False
        if source == "image" and self._image is not None:
            self._paint_media(p, self._image, opacity)
            drew = True
        elif source == "video" and self._frame is not None:
            self._paint_media(p, self._frame, opacity)
            drew = True
        if not drew:
            effect = str(self._cfg.get("effect"))
            if effect == "gradient":
                self._paint_gradient(p, pal, opacity)
            elif effect == "blobs":
                self._paint_blobs(p, opacity)
            else:
                self._paint_dots(p, opacity)
        if not drew:
            self._paint_follower(p, opacity)
        self._paint_clicks(p, opacity)
        p.end()

    def _paint_media(self, p: QPainter, img: QImage, opacity: float) -> None:
        iw, ih = img.width(), img.height()
        if iw <= 0 or ih <= 0:
            return
        scale = max(self._w / iw, self._h / ih)
        w, h = iw * scale, ih * scale
        target = QRectF((self._w - w) / 2.0, (self._h - h) / 2.0, w, h)
        p.setOpacity(max(0.0, min(1.0, opacity)))
        p.drawImage(target, img)
        p.setOpacity(1.0)

    def _paint_gradient(self, p: QPainter, pal: dict, opacity: float) -> None:
        k = (math.sin(self._phase / 9.0 * math.tau) + 1.0) / 2.0
        top = QColor(pal["top"])
        bottom = QColor(pal["bottom"])
        top.setAlphaF(0.55 + 0.25 * k)
        bottom.setAlphaF(0.10 * k)
        g = QLinearGradient(0, 0, 0, self._h)
        g.setColorAt(0.0, top)
        g.setColorAt(1.0, bottom)
        p.setOpacity(max(0.0, min(1.0, opacity)))
        p.fillRect(self.rect(), g)
        p.setOpacity(1.0)

    def _paint_blobs(self, p: QPainter, opacity: float) -> None:
        p.setOpacity(max(0.0, min(1.0, opacity)))
        for b in self._blobs:
            pix = self._blob_pix[b["color"] % len(self._blob_pix)]
            x = b["x"] * self._w - pix.width() / 2
            y = b["y"] * self._h - pix.height() / 2
            p.drawPixmap(int(x), int(y), pix)
        p.setOpacity(1.0)

    def _paint_dots(self, p: QPainter, opacity: float) -> None:
        if self._dots_pix is not None:
            p.setOpacity(max(0.0, min(1.0, opacity)))
            p.drawPixmap(0, 0, self._dots_pix)
            p.setOpacity(1.0)

    def _paint_clicks(self, p: QPainter, opacity: float) -> None:
        if not self._clicks:
            return
        style = str(self._cfg.get("click_style") or "ripple")
        accent = QColor(self._pal()["glow"])
        base = max(0.0, min(1.0, opacity))
        for c in self._clicks:
            k = max(0.0, min(1.0, c["t"] / 0.8))
            fade = (1.0 - k) * base
            x, y = float(c["x"]), float(c["y"])
            p.setBrush(Qt.NoBrush)
            if style == "double":
                for width, span, alph in ((2.0, 54.0, 0.50), (1.4, 34.0, 0.32)):
                    ring = QColor(accent)
                    ring.setAlphaF(alph * fade)
                    pen = QPen(ring)
                    pen.setWidthF(width)
                    p.setPen(pen)
                    r = 8.0 + span * k
                    p.drawEllipse(QPointF(x, y), r, r)
                continue
            if style == "spark":
                for i in range(8):
                    ang = i * math.pi / 4 + 0.35
                    rr = 10.0 + 44.0 * k
                    dot = QColor(accent)
                    dot.setAlphaF(0.55 * fade)
                    p.setPen(Qt.NoPen)
                    p.setBrush(dot)
                    size = max(1.2, 3.4 * (1.0 - k))
                    p.drawEllipse(QPointF(x + math.cos(ang) * rr,
                                          y + math.sin(ang) * rr), size, size)
                continue
            if style == "bubble":
                for i, off in enumerate((-10.0, 2.0, 13.0)):
                    rise = 10.0 + 46.0 * k + abs(off) * 0.6
                    rr = max(1.0, (4.0 + i) * (1.0 - k * 0.7))
                    bub = QColor(accent)
                    bub.setAlphaF(0.34 * fade)
                    p.setPen(Qt.NoPen)
                    p.setBrush(bub)
                    p.drawEllipse(QPointF(x + off, y - rise), rr, rr)
                continue
            # ripple
            ring = QColor(accent)
            ring.setAlphaF(0.55 * fade)
            pen = QPen(ring)
            pen.setWidthF(2.0)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(x, y), 8.0 + 54.0 * k, 8.0 + 54.0 * k)
            dot = QColor(accent)
            dot.setAlphaF(0.45 * fade)
            p.setPen(Qt.NoPen)
            p.setBrush(dot)
            p.drawEllipse(QPointF(x, y), 3.0 * (1.0 - k) + 1.0,
                          3.0 * (1.0 - k) + 1.0)

    def _paint_follower(self, p: QPainter, opacity: float) -> None:
        kind = str(self._cfg.get("follower"))
        if kind == "off":
            return
        p.setOpacity(max(0.0, min(1.0, opacity * self._fade)))
        if kind == "glow" and self._glow_pix is not None:
            pix = self._glow_pix
            p.drawPixmap(int(self._fx * self._w - pix.width() / 2),
                         int(self._fy * self._h - pix.height() / 2), pix)
        elif kind == "trail":
            n = len(self._trail)
            for i, pt in enumerate(self._trail):
                k = (i + 1) / max(1, n)
                color = QColor(self._pal()["glow"])
                color.setAlphaF(0.06 + 0.30 * k)
                p.setPen(Qt.NoPen)
                p.setBrush(color)
                p.drawEllipse(pt, max(2.0, 9.0 * k), max(2.0, 9.0 * k))
        elif kind == "particles":
            for pt in self._particles:
                k = max(0.0, min(1.0, pt["life"] / pt["max"]))
                color = QColor(self._pal()["glow"])
                color.setAlphaF(0.15 + 0.55 * k)
                p.setPen(Qt.NoPen)
                p.setBrush(color)
                p.drawEllipse(QPointF(pt["x"], pt["y"]), 2.0 + 3.0 * k, 2.0 + 3.0 * k)
        p.setOpacity(1.0)
