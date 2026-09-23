"""Render the SNBR Report Dispatch mark to PNG and ICO.

Standalone developer utility -- not imported by the application. Sibling of
``scripts/generate_logo.py``: same 64x64 user units (y increasing downward),
same palette, same round caps and joins, same matplotlib rasteriser, so the
two apps read as one family in a taskbar.

The shapes differ completely, which is what has to survive at 16px: the
analysis app is a figure-8 TMS coil with an MEP trace running through it;
the dispatch app is an envelope -- reports going out -- whose flap is that
same MEP trace, spiking where the flap point would be.

    .venv312/Scripts/python.exe scripts/generate_dispatch_logo.py
    .venv312/Scripts/python.exe scripts/generate_dispatch_logo.py --preview

Writing to icons/logo_dispatch/ keeps it clear of the analysis app's
icons/logo/; the PyInstaller specs bundle the whole icons/ tree, so both ride
along without a spec change.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image

OUT_DIR = Path(__file__).resolve().parent.parent / "icons" / "logo_dispatch"

VIEWBOX = 64.0
PNG_SIZES = (16, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

# Below this the flap's MEP articulation falls under a pixel and turns to
# mush, so the plain-V cut is used instead. Same cutoff as the parent mark.
SMALL_SIZE_CUTOFF = 32

# Identical to scripts/generate_logo.py -- the family is the palette.
LIGHT = {"ink": "#0F2E52", "accent": "#12A594"}
DARK = {"ink": "#E8EEF6", "accent": "#2DD4BF"}

# Envelope body. Drawn as a closed polyline so the round joins give the
# corners their radius, exactly as the parent's arcs get theirs from caps.
BODY = [(8, 18), (56, 18), (56, 48), (8, 48), (8, 18)]

# Primary cut: the flap is the MEP trace -- long straight runs from the top
# corners, a small negative deflection, then the peak at the flap point. The
# peak stops well clear of the body's bottom edge; running the two strokes
# together closes the envelope's mouth and it stops reading as a flap.
FULL = {
    "stroke": 3.4,
    "body": BODY,
    "flap": [(8, 18), (24, 30), (28, 25), (32, 41), (36, 27), (40, 32), (56, 18)],
}
# Small cut: plain flap, heavier stroke, so 16px stays a clean envelope.
SMALL = {
    "stroke": 5.0,
    "body": [(9, 19), (55, 19), (55, 47), (9, 47), (9, 19)],
    "flap": [(9, 19), (32, 37), (55, 19)],
}


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
    ax.plot(*zip(*cut["body"]), color=palette["ink"], **line)
    ax.plot(*zip(*cut["flap"]), color=palette["accent"], **line)

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


def preview(path: Path) -> Path:
    """A contact sheet of the real sizes on light and dark, for eyeballing."""
    sizes = (16, 24, 32, 48, 64, 128)
    pad, gap = 24, 20
    width = pad * 2 + sum(sizes) + gap * (len(sizes) - 1)
    row = max(sizes)
    sheet = Image.new("RGBA", (width, pad * 3 + row * 2), (255, 255, 255, 255))
    dark_band = Image.new("RGBA", (width, row + pad), (24, 28, 34, 255))
    sheet.paste(dark_band, (0, pad * 2 + row))
    for band, palette in ((0, LIGHT), (1, DARK)):
        x = pad
        for size in sizes:
            img = render_at(size, palette)
            y = pad + band * (row + pad) + (row - size)
            sheet.paste(img, (x, y), img)
            x += size + gap
    sheet.save(path)
    return path


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if "--preview" in sys.argv:
        # Into the temp dir, not OUT_DIR: the specs bundle icons/ wholesale, so
        # anything left there ships inside the executable. OUT_DIR holds only
        # assets that are meant to be shipped.
        import tempfile

        target = Path(tempfile.gettempdir()) / "snbr_dispatch_mark_preview.png"
        print(f"wrote {preview(target)}")
        return 0

    for name, palette in (("dispatch", LIGHT), ("dispatch-dark", DARK)):
        for size in PNG_SIZES:
            render_at(size, palette).save(OUT_DIR / f"{name}-{size}.png")
            print(f"wrote {name}-{size}.png")

    # Windows .ico: each frame rendered with the cut appropriate to its size,
    # rather than downsampling one master (which loses the small sizes).
    frames = [render_at(s, LIGHT) for s in ICO_SIZES]
    frames[-1].save(
        OUT_DIR / "dispatch.ico",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=frames[:-1],
    )
    print("wrote dispatch.ico")
    return 0


if __name__ == "__main__":
    sys.exit(main())
