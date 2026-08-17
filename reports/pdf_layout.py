"""
Page composition for participant PDF reports.

This module takes the matplotlib figures produced by
:mod:`reports.report_builder` and arranges them onto portrait US-Letter
(8.5 x 11) pages, four visualizations per page in a 2×2 grid, each with
a raw-value caption line printed underneath.  It also builds the
first-page letterhead banner using the two institutional PNG assets in
``SNBR_TMS_App/icons``.

Public API
----------
ReportItem                            -- figure + caption + section key
compose_four_per_page(items)          -> list[Figure]
build_letterhead_banner_page(summary) -> Figure
"""

from __future__ import annotations

import io
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Page constants and asset paths
# ---------------------------------------------------------------------------

PAGE_SIZE = (8.5, 11.0)          # portrait US Letter, inches
PAGE_MARGIN = 0.4                 # uniform inch margin on all sides
LETTERHEAD_HEIGHT = 2.1           # inches reserved for letterhead banner on page 1

# Footer stamped on every page (see :func:`stamp_page_footer`).
_FOOTER_Y_INCHES = 0.22           # baseline height above the page bottom edge
_FOOTER_FONTSIZE = 8.0
_FOOTER_COLOR = "#5A6B7C"


def generation_date_string(when: datetime | None = None) -> str:
    """Return the report generation date as ``dd/mm/YYYY`` (today by default)."""
    return (when or datetime.now()).strftime("%d/%m/%Y")


def stamp_page_footer(
    page_fig,
    page_number: int,
    total_pages: int,
    date_generated: str,
):
    """Stamp a page's footer: date generated (left) + page N of M (right).

    Text is drawn in figure coordinates inside the bottom margin so it never
    overlaps the composed content above. Applied to *every* page, including the
    letterhead cover page.
    """
    y = _FOOTER_Y_INCHES / PAGE_SIZE[1]
    left_x = PAGE_MARGIN / PAGE_SIZE[0]
    right_x = 1.0 - (PAGE_MARGIN / PAGE_SIZE[0])

    page_fig.text(
        left_x, y, f"Date generated: {date_generated}",
        ha="left", va="center",
        fontsize=_FOOTER_FONTSIZE, color=_FOOTER_COLOR,
    )
    page_fig.text(
        right_x, y, f"Page {page_number} of {total_pages}",
        ha="right", va="center",
        fontsize=_FOOTER_FONTSIZE, color=_FOOTER_COLOR,
    )
    return page_fig


def _resolve_icons_dir() -> Path:
    """Return the icons directory for both source and PyInstaller runs.

    In a PyInstaller bundle, ``sys._MEIPASS`` points to the extracted
    data root where the spec's ``('icons', 'icons')`` entry lands.
    Otherwise, resolve relative to the source tree.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "icons"
    return Path(__file__).resolve().parent.parent / "icons"


ICONS_DIR = _resolve_icons_dir()
LAB_LETTERHEAD_PATH = ICONS_DIR / "Lab_letter_head.png"
SUNNYBROOK_LOGO_PATH = ICONS_DIR / "Sunnybrook_Harquail.png"


# ---------------------------------------------------------------------------
# Report item
# ---------------------------------------------------------------------------

@dataclass
class ReportItem:
    """One visualization destined for the PDF report.

    ``figure`` is the matplotlib figure as originally produced by the
    plotting layer.  ``caption`` is the raw-value line printed beneath
    the rasterized image (``None`` = no caption text).  ``section_key``
    is retained so the renderer can locate the summary item.
    """

    figure: object                    # matplotlib.figure.Figure
    caption: str | None = None
    section_key: str | None = None


# ---------------------------------------------------------------------------
# Rasterization helper
# ---------------------------------------------------------------------------

def _rasterize_figure(fig, dpi: int = 200) -> np.ndarray:
    """Render a matplotlib figure to an RGBA numpy image array."""
    import matplotlib.image as mpimg

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=dpi, bbox_inches="tight")
    buffer.seek(0)
    image = mpimg.imread(buffer)
    buffer.close()
    return image


def _place_image_axis(page_fig, image: np.ndarray, rect: tuple[float, float, float, float]):
    """Place a rasterized image in a figure-fraction rectangle (l, b, w, h)."""
    ax = page_fig.add_axes(rect)
    ax.imshow(image, interpolation="none")
    ax.set_axis_off()
    return ax


def _place_caption_axis(
    page_fig,
    caption: str,
    rect: tuple[float, float, float, float],
    fontsize: float = 10.0,
):
    """Place a centred caption text block in a figure-fraction rectangle."""
    ax = page_fig.add_axes(rect)
    ax.set_axis_off()
    ax.text(
        0.5, 0.5, caption,
        ha="center", va="center",
        fontsize=fontsize, color="#1F2A36",
        transform=ax.transAxes, wrap=True,
    )
    return ax


# ---------------------------------------------------------------------------
# Four-per-page composition (2×2 grid)
# ---------------------------------------------------------------------------

# Slot layout on each body page:
#   0 = top-left,    1 = top-right
#   2 = bottom-left, 3 = bottom-right
ITEMS_PER_PAGE = 4
_GRID_COLS = 2
_GRID_ROWS = 2


def _slot_rects(slot_index: int) -> tuple[
    tuple[float, float, float, float],
    tuple[float, float, float, float],
]:
    """Return (image_rect, caption_rect) in figure fractions for one of the
    four slots in the 2×2 grid.

    Slot indices are laid out left-to-right, top-to-bottom (0=TL, 1=TR,
    2=BL, 3=BR). Each cell is divided vertically into an image band and
    a thin caption band beneath it.
    """
    margin_x = PAGE_MARGIN / PAGE_SIZE[0]
    margin_y = PAGE_MARGIN / PAGE_SIZE[1]

    inner_gap_x = 0.02
    inner_gap_y = 0.025

    content_width = 1.0 - 2.0 * margin_x
    content_height = 1.0 - 2.0 * margin_y

    cell_width = (content_width - inner_gap_x) / _GRID_COLS
    cell_height = (content_height - inner_gap_y) / _GRID_ROWS

    col = slot_index % _GRID_COLS
    row = slot_index // _GRID_COLS  # 0 = top row, 1 = bottom row

    cell_left = margin_x + col * (cell_width + inner_gap_x)
    # Top row sits higher on the page → larger 'bottom' fraction
    if row == 0:
        cell_bottom = margin_y + cell_height + inner_gap_y
    else:
        cell_bottom = margin_y

    # Caption takes the bottom ~0.4" of each cell, image takes the rest.
    caption_height = 0.4 / PAGE_SIZE[1]
    image_bottom = cell_bottom + caption_height
    image_height = cell_height - caption_height

    image_rect = (cell_left, image_bottom, cell_width, image_height)
    caption_rect = (cell_left, cell_bottom, cell_width, caption_height)
    return image_rect, caption_rect


def _new_page_figure():
    import matplotlib.pyplot as plt

    return plt.figure(figsize=PAGE_SIZE)


def compose_four_per_page(items: list[ReportItem]) -> list:
    """Compose a sequence of ``ReportItem`` s into portrait Letter pages.

    Every page hosts up to four items in a 2×2 grid (top-left, top-right,
    bottom-left, bottom-right). Trailing slots on the final page are left
    blank when the item count isn't divisible by four.

    Returns a list of matplotlib figures in page order. The caller is
    responsible for saving these via ``PdfPages`` and closing them.
    """
    pages = []
    i = 0
    while i < len(items):
        page_fig = _new_page_figure()
        for slot in range(ITEMS_PER_PAGE):
            if i >= len(items):
                break
            item = items[i]
            image = _rasterize_figure(item.figure)
            image_rect, caption_rect = _slot_rects(slot)
            _place_image_axis(page_fig, image, image_rect)
            if item.caption:
                _place_caption_axis(
                    page_fig, item.caption, caption_rect, fontsize=8.5,
                )
            i += 1
        pages.append(page_fig)
    return pages


# Backwards-compatibility alias — older imports / external scripts still
# reach for ``compose_two_per_page``. Treat it as 4-per-page going forward.
compose_two_per_page = compose_four_per_page


# ---------------------------------------------------------------------------
# Letterhead banner page
# ---------------------------------------------------------------------------

def _load_icon(path: Path) -> np.ndarray | None:
    import matplotlib.image as mpimg

    if not path.is_file():
        return None
    return mpimg.imread(str(path))


def build_letterhead_banner_page(summary_fig=None):
    """Build page 1: letterhead banner on top, optional summary below.

    The two institutional PNGs are placed side-by-side across the top of
    the page, preserving each image's aspect ratio.  When *summary_fig*
    is provided, its content is rasterized and pasted into the body
    region below the banner.

    Returns a matplotlib figure sized to portrait Letter.
    """
    page_fig = _new_page_figure()

    margin_x = PAGE_MARGIN / PAGE_SIZE[0]
    margin_y = PAGE_MARGIN / PAGE_SIZE[1]
    banner_height_frac = LETTERHEAD_HEIGHT / PAGE_SIZE[1]

    # --- Banner region: two icons side by side ---
    banner_bottom = 1.0 - margin_y - banner_height_frac
    banner_left = margin_x
    banner_width = 1.0 - 2.0 * margin_x

    lab_img = _load_icon(LAB_LETTERHEAD_PATH)
    logo_img = _load_icon(SUNNYBROOK_LOGO_PATH)

    if lab_img is not None and logo_img is not None:
        # Split the banner area so each image keeps its native aspect ratio
        # and occupies as much vertical space as it can within the band.
        lab_h, lab_w = lab_img.shape[0], lab_img.shape[1]
        logo_h, logo_w = logo_img.shape[0], logo_img.shape[1]
        lab_ratio = lab_w / lab_h
        logo_ratio = logo_w / logo_h

        gap = 0.02
        available_w = banner_width - gap

        # Apportion horizontal space by native aspect ratio, then shrink
        # vertically so each image fits the banner height.
        total_ratio = lab_ratio + logo_ratio
        lab_slot_w = available_w * (lab_ratio / total_ratio)
        logo_slot_w = available_w * (logo_ratio / total_ratio)

        # Compute per-image height that preserves aspect ratio within its slot.
        lab_img_h_frac = (lab_slot_w * PAGE_SIZE[0]) / lab_ratio / PAGE_SIZE[1]
        logo_img_h_frac = (logo_slot_w * PAGE_SIZE[0]) / logo_ratio / PAGE_SIZE[1]

        # Clamp each image to the banner height.
        if lab_img_h_frac > banner_height_frac:
            lab_img_h_frac = banner_height_frac
            lab_slot_w = (lab_img_h_frac * PAGE_SIZE[1] * lab_ratio) / PAGE_SIZE[0]
        if logo_img_h_frac > banner_height_frac:
            logo_img_h_frac = banner_height_frac
            logo_slot_w = (logo_img_h_frac * PAGE_SIZE[1] * logo_ratio) / PAGE_SIZE[0]

        # Vertically centre each image within the banner band.
        lab_bottom = banner_bottom + (banner_height_frac - lab_img_h_frac) / 2.0
        logo_bottom = banner_bottom + (banner_height_frac - logo_img_h_frac) / 2.0

        lab_left = banner_left
        logo_left = banner_left + lab_slot_w + gap

        ax_lab = page_fig.add_axes((lab_left, lab_bottom, lab_slot_w, lab_img_h_frac))
        ax_lab.imshow(lab_img, interpolation="none")
        ax_lab.set_axis_off()

        ax_logo = page_fig.add_axes((logo_left, logo_bottom, logo_slot_w, logo_img_h_frac))
        ax_logo.imshow(logo_img, interpolation="none")
        ax_logo.set_axis_off()

    # --- Body region: embed the patient-info block beneath the banner ---
    #
    # The summary figure for page 1 now holds participant demographics
    # only, so it is much shorter than the available body area.  We
    # preserve its native aspect ratio and anchor it flush to the top of
    # the body region instead of stretching it vertically.
    if summary_fig is not None:
        body_top = banner_bottom - 0.02
        body_bottom = margin_y
        body_left = margin_x
        body_width = 1.0 - 2.0 * margin_x

        summary_image = _rasterize_figure(summary_fig)
        img_h_px, img_w_px = summary_image.shape[0], summary_image.shape[1]
        img_ratio = img_w_px / img_h_px
        body_height_by_width = (body_width * PAGE_SIZE[0]) / img_ratio / PAGE_SIZE[1]
        body_height_available = body_top - body_bottom
        body_height = min(body_height_by_width, body_height_available)
        width_by_height = (body_height * PAGE_SIZE[1] * img_ratio) / PAGE_SIZE[0]
        if width_by_height < body_width:
            body_width = width_by_height
            body_left = (1.0 - body_width) / 2.0

        ax_body = page_fig.add_axes(
            (body_left, body_top - body_height, body_width, body_height)
        )
        ax_body.imshow(summary_image, interpolation="none")
        ax_body.set_axis_off()

    return page_fig
