"""Render the SNBR TMS mark to PNG and ICO.

Standalone developer utility -- not imported by the application. The geometry
here mirrors icons/logo/logo.svg exactly (64x64 user units, y increasing
downward). matplotlib does the rasterising because it honours the round caps
and joins the SVG asks for and is already a project dependency; cairosvg is
not required.

    .venv312/Scripts/python.exe scripts/generate_logo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

OUT_DIR = Path(__file__).resolve().parent.parent / "icons" / "logo"

VIEWBOX = 64.0
PNG_SIZES = (16, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

# Below this pixel size the 3.4-unit stroke and the 14-degree ring gaps fall
# under a pixel and turn to mush, so the simplified cut is used instead.
SMALL_SIZE_CUTOFF = 32

LIGHT = {"ink": "#0F2E52", "accent": "#12A594"}
DARK = {"ink": "#E8EEF6", "accent": "#2DD4BF"}

RING_RADIUS = 11.0
RING_CENTRES = ((21.0, 32.0), (43.0, 32.0))  # tangent at (32, 32): the coil junction

# Primary cut: rings opened by a 14-degree gap where the trace crosses them.
FULL = {
    "stroke": 3.4,
    "gap": 14.0,
    "trace": [(3, 32), (26.5, 32), (28.5, 34.5), (31, 18), (36, 46), (38.5, 32), (61, 32)],
}
# Small cut: unbroken rings, heavier stroke, shallower deflection.
SMALL = {
    "stroke": 5.0,
    "gap": 0.0,
    "trace": [(4, 32), (28, 32), (31, 20), (36, 44), (39, 32), (60, 32)],
}


def _arc(cx: float, cy: float, start_deg: float, end_deg: float):
    t = np.radians(np.linspace(start_deg, end_deg, 600))
    return cx + RING_RADIUS * np.cos(t), cy + RING_RADIUS * np.sin(t)


def _ring_arcs(gap: float):
    """The two windings, each opened by ``gap`` degrees at its outer pole."""
    if not gap:
        return [_arc(cx, cy, 0.0, 360.0) for cx, cy in RING_CENTRES]
    (lx, ly), (rx, ry) = RING_CENTRES
    return [
        _arc(lx, ly, 180.0 + gap, 180.0 - gap + 360.0),
        _arc(rx, ry, gap, 360.0 - gap),
    ]


def render(size: int, cut: dict, palette: dict[str, str], dpi: int = 100) -> Image.Image:
    """Return an RGBA image of the mark at ``size`` x ``size`` pixels."""
    fig = plt.figure(figsize=(size / dpi, size / dpi), dpi=dpi)
    fig.patch.set_alpha(0.0)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, VIEWBOX)
    ax.set_ylim(VIEWBOX, 0)  # SVG orientation: y grows downward
    ax.set_axis_off()
    ax.patch.set_alpha(0.0)

    line = dict(
        solid_capstyle="round",
        solid_joinstyle="round",
        linewidth=cut["stroke"] * (size / VIEWBOX) * 72.0 / dpi,
    )
    for xs, ys in _ring_arcs(cut["gap"]):
        ax.plot(xs, ys, color=palette["ink"], **line)
    ax.plot(*zip(*cut["trace"]), color=palette["accent"], **line)

    scratch = OUT_DIR / f"._render_{size}.png"
    fig.savefig(scratch, dpi=dpi, transparent=True)
    plt.close(fig)
    img = Image.open(scratch).convert("RGBA")
    img.load()
    scratch.unlink()
    return img


def render_at(size: int, palette: dict[str, str]) -> Image.Image:
    """Render at ``size``, picking the cut and supersampling the small sizes."""
    cut = SMALL if size <= SMALL_SIZE_CUTOFF else FULL
    scale = 8 if size <= 64 else 1
    img = render(size * scale, cut, palette)
    return img.resize((size, size), Image.LANCZOS) if scale > 1 else img


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for name, palette in (("logo", LIGHT), ("logo-dark", DARK)):
        for size in PNG_SIZES:
            render_at(size, palette).save(OUT_DIR / f"{name}-{size}.png")
            print(f"wrote {name}-{size}.png")

    # Windows .ico: each frame rendered with the cut appropriate to its size,
    # rather than downsampling one master (which loses the small sizes).
    frames = [render_at(s, LIGHT) for s in ICO_SIZES]
    frames[-1].save(
        OUT_DIR / "logo.ico",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=frames[:-1],
    )
    print("wrote logo.ico")
    return 0


if __name__ == "__main__":
    sys.exit(main())
