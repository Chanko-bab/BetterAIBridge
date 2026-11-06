"""Regenerate assets icons (round style) from the 512 px masters.

Masters live in assets/_src/ (not shipped: build.ps1 skips _src).
Outputs: bab.ico / bab-setup.ico (16/32/48/256) + bab-64.png + bab-40.png.

    python tools/make_icons.py
"""
from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw, ImageFilter

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
SIZES = [(16, 16), (32, 32), (48, 48), (256, 256)]
SS = 4  # supersampling factor for the round mask


def master(name: str) -> Image.Image:
    path = os.path.join(ASSETS, "_src", name)
    if not os.path.exists(path):
        raise SystemExit(f"missing master: {path}")
    im = Image.open(path).convert("RGB")
    if im.size != (512, 512):
        im = im.resize((512, 512), Image.LANCZOS)
    return im.resize((256, 256), Image.LANCZOS).filter(
        ImageFilter.UnsharpMask(radius=1.2, percent=110, threshold=2)
    )


def round_mask(size: int, inset: int = 2) -> Image.Image:
    """Anti-aliased circle mask, transparent corners."""
    big = (size * SS, size * SS)
    mask = Image.new("L", big, 0)
    d = ImageDraw.Draw(mask)
    pad = inset * SS
    d.ellipse((pad, pad, big[0] - 1 - pad, big[1] - 1 - pad), fill=255)
    return mask.resize((size, size), Image.LANCZOS)


def rounded(im: Image.Image) -> Image.Image:
    out = im.convert("RGBA")
    out.putalpha(round_mask(out.size[0]))
    return out


def build() -> None:
    app = rounded(master("app-512.png"))
    app.save(os.path.join(ASSETS, "bab.ico"), sizes=SIZES)
    app.resize((64, 64), Image.LANCZOS).save(os.path.join(ASSETS, "bab-64.png"), "PNG")
    app.resize((40, 40), Image.LANCZOS).save(os.path.join(ASSETS, "bab-40.png"), "PNG")

    setup = rounded(master("setup-512.png"))
    setup.save(os.path.join(ASSETS, "bab-setup.ico"), sizes=SIZES)

    for name in ("bab.ico", "bab-setup.ico", "bab-64.png", "bab-40.png"):
        path = os.path.join(ASSETS, name)
        print(f"{name:16s} {os.path.getsize(path):>8,} bytes")


if __name__ == "__main__":
    try:
        build()
    except ImportError:
        sys.exit("needs Pillow: pip install pillow")
