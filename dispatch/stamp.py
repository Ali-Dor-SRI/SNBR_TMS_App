"""Stamp patient identity onto the cover page of an exported report.

The exported PDF is never modified: a one-page overlay is drawn with
matplotlib, and pypdf merges it onto a *copy* of page 1.

Where the box goes is decided per report, not fixed. The analysis app's cover
is a letterhead plus one rasterized summary figure whose height varies
(4.0", 5.2" or 7.8" depending on the path and the data), and older reports
also carried a visit table and timeline there. So :func:`plan_box` reads
page 1's content stream, tracks the graphics state to find where every image
and text run actually puts ink -- an image counts only where its pixels are
non-white -- and places the box in the lowest ink-free band that fits. A
full box is preferred; a compact two-line box is the fallback; if neither
fits, the box goes at the bottom and the report is flagged as overlapped so
the batch can warn.

Three variants, deliberately unmistakable from each other:

* **identified** -- a blue-bordered "PATIENT IDENTIFICATION" box with the
  name, MRN, study ID and visit date.
* **incomplete** -- an amber "PATIENT IDENTIFICATION (INCOMPLETE)" box when
  the enrolment log gives one of the name and the MRN but not the other. The
  field it has is printed; the blank one reads "not recorded in the enrolment
  log". Withholding the name because the MRN is blank would throw away the
  one thing the clinician needs to file the report.
* **unresolved** -- an amber box headed "IDENTITY NOT RESOLVED" when there is
  no roster row at all, or one with neither field. The lab chose to send such
  reports de-identified rather than hold them back; the box exists so a
  recipient can never mistake a missing name for an omitted one.

pypdf and matplotlib are imported inside the functions so the package
imports on a machine without them (the import smoke test pins this policy).
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dispatch.identity import Identity, ParticipantKey

PAGE_SIZE = (8.5, 11.0)   # portrait US Letter, inches -- must match pdf_layout
_PT = 72.0

_BOX_MARGIN_X_IN = 0.4
_BOX_MIN_BOTTOM_IN = 0.45      # clears the analysis app's 0.22" footer
_BAND_MARGIN_IN = 0.08         # breathing room above and below the box
_HEADING_IN = 0.26
_LINE_IN = 0.21
_PAD_IN = 0.12
_INK_THRESHOLD = 240           # 8-bit grey below this counts as ink

# Printed in place of a field the enrolment log left blank. Says where the
# gap is, so a missing MRN cannot read as an MRN nobody bothered to type.
_ABSENT = "not recorded in the enrolment log"

_IDENT_EDGE = "#1F6AA5"
_IDENT_FILL = "#EEF4FA"
_WARN_EDGE = "#B7791F"
_WARN_FILL = "#FFF6E5"
_TEXT = "#1F2A36"


# -- what to write -----------------------------------------------------------

def _fmt_visit(visit: date | None) -> str:
    return visit.strftime("%d/%m/%Y") if visit else "unknown"


def _box_text(
    key: ParticipantKey, visit_date: date | None, identity: Identity | None,
    unresolved_reason: str, compact: bool,
) -> tuple[str, list[tuple[str, str]], bool]:
    """Return ``(heading, [(label, value), ...], warn)`` for one variant.

    Three variants, not two. A roster row giving only one of the name and the
    MRN still identifies the patient, so it is stamped with what it has and
    the blank field says so; only a report with neither goes out with no
    identity at all.
    """
    visit = _fmt_visit(visit_date)
    if identity is not None and identity.identifying:
        partial = identity.partial
        name = identity.name.strip() or _ABSENT
        mrn = identity.mrn.strip() or _ABSENT
        if compact:
            lines = [
                ("Patient", f"{name}     MRN: {mrn}"),
                ("Study ID", f"{key.label()}     Visit date: {visit}"),
            ]
        else:
            lines = [
                ("Patient name", name),
                ("MRN", mrn),
                ("Study ID", key.label()),
                ("Visit date", visit),
            ]
        heading = (
            "PATIENT IDENTIFICATION (INCOMPLETE)" if partial else "PATIENT IDENTIFICATION"
        )
        return heading, lines, partial

    reason = unresolved_reason or (
        f"roster row lacks {' and '.join(identity.missing_fields())}"
        if identity is not None else "not in the enrolment roster"
    )
    note = "This report is de-identified. Identity must be confirmed by other means."
    if compact:
        lines = [
            ("Study ID", f"{key.label()}     Visit date: {visit}     Reason: {reason}"),
            ("Note", note),
        ]
    else:
        lines = [
            ("Study ID", key.label()),
            ("Visit date", visit),
            ("Reason", reason),
            ("Note", note),
        ]
    return "IDENTITY NOT RESOLVED", lines, True


def _box_height_in(line_count: int) -> float:
    return _HEADING_IN + line_count * _LINE_IN + _PAD_IN


# -- where to put it -----------------------------------------------------------

@dataclass(frozen=True)
class BoxPlan:
    bottom_in: float
    height_in: float
    compact: bool
    overlaps: bool          # no ink-free band fit even the compact box


def _mat_mul(a, b):
    """PDF matrix product a x b (both 6-tuples, row-vector convention)."""
    a0, a1, a2, a3, a4, a5 = a
    b0, b1, b2, b3, b4, b5 = b
    return (
        a0 * b0 + a1 * b2, a0 * b1 + a1 * b3,
        a2 * b0 + a3 * b2, a2 * b1 + a3 * b3,
        a4 * b0 + a5 * b2 + b4, a4 * b1 + a5 * b3 + b5,
    )


def _apply(m, x, y):
    return m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]


def _image_ink_runs(pil_image) -> list[tuple[float, float]]:
    """``[(top_frac, bottom_frac), ...]`` for each run of consecutive rows
    holding ink, in image units where 0 is the top row.

    Runs, not the overall extent: the analysis app's summary raster is one
    tall image with white space *inside* it (between the demographics and a
    caption near its foot, say), and that space is where the box belongs.
    """
    import numpy as np

    grey = np.asarray(pil_image.convert("L"))
    if grey.ndim != 2 or grey.size == 0:
        return []
    inked = grey.min(axis=1) < _INK_THRESHOLD
    height = grey.shape[0]
    runs = []
    start = None
    for row, has_ink in enumerate(inked):
        if has_ink and start is None:
            start = row
        elif not has_ink and start is not None:
            runs.append((start / height, row / height))
            start = None
    if start is not None:
        runs.append((start / height, 1.0))
    return runs


def ink_intervals(page) -> list[tuple[float, float]]:
    """Vertical page intervals (points, from the bottom) that carry ink.

    Walks the content stream with a q/Q stack, tracking the CTM, the text
    matrix and the font size. Images contribute the page extent of each run
    of non-white rows; every text run contributes its line box. Anything the
    walker does not understand is ignored, so an exotic PDF degrades to
    "no ink known" rather than failing the stamp.
    """
    from pypdf.generic import ContentStream

    images = {}
    try:
        for img in page.images:
            images[Path(img.name).stem] = img.image
    except Exception:   # a broken image stream must not stop the stamp
        images = {}

    content = page.get_contents()
    if content is None:
        return []
    stream = ContentStream(content, page.pdf)

    intervals: list[tuple[float, float]] = []
    ctm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    stack: list[tuple] = []
    font_size = 0.0
    tm = tlm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    def add(y0, y1):
        lo, hi = (y0, y1) if y0 <= y1 else (y1, y0)
        intervals.append((lo, hi))

    for operands, operator in stream.operations:
        op = operator.decode("latin-1") if isinstance(operator, bytes) else str(operator)
        try:
            if op == "q":
                stack.append((ctm, font_size))
            elif op == "Q":
                if stack:
                    ctm, font_size = stack.pop()
            elif op == "cm":
                ctm = _mat_mul(tuple(float(v) for v in operands), ctm)
            elif op == "Tf":
                font_size = float(operands[1])
            elif op == "BT":
                tm = tlm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
            elif op == "Tm":
                tm = tlm = tuple(float(v) for v in operands)
            elif op in ("Td", "TD"):
                tlm = _mat_mul((1.0, 0.0, 0.0, 1.0, float(operands[0]), float(operands[1])), tlm)
                tm = tlm
            elif op in ("Tj", "TJ", "'", '"'):
                full = _mat_mul(tm, ctm)
                _, base = _apply(full, 0.0, 0.0)
                _, top = _apply(full, 0.0, font_size)
                add(base, top)
            elif op == "Do":
                name = str(operands[0]).lstrip("/")
                pil = images.get(name)
                if pil is None:
                    continue
                for top_frac, bottom_frac in _image_ink_runs(pil):
                    # PDF images map their top row to unit-square y = 1.
                    _, y_top = _apply(ctm, 0.0, 1.0 - top_frac)
                    _, y_bottom = _apply(ctm, 0.0, 1.0 - bottom_frac)
                    add(y_bottom, y_top)
        except (ValueError, TypeError, IndexError):
            continue
    return intervals


def _free_bands(intervals: list[tuple[float, float]], page_height: float) -> list[tuple[float, float]]:
    """Ink-free vertical bands, lowest first, from merged *intervals*."""
    merged: list[list[float]] = []
    for lo, hi in sorted(intervals):
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    bands = []
    cursor = 0.0
    for lo, hi in merged:
        if lo > cursor:
            bands.append((cursor, lo))
        cursor = max(cursor, hi)
    if cursor < page_height:
        bands.append((cursor, page_height))
    return bands


def plan_box(page, full_lines: int, compact_lines: int) -> BoxPlan:
    """Choose the box's vertical placement on *page* (a pypdf page)."""
    page_height = float(page.mediabox.height)
    try:
        bands = _free_bands(ink_intervals(page), page_height)
    except Exception:   # unreadable content: fall back to the default spot
        bands = []

    min_bottom = _BOX_MIN_BOTTOM_IN * _PT
    margin = _BAND_MARGIN_IN * _PT
    for compact, lines in ((False, full_lines), (True, compact_lines)):
        height = _box_height_in(lines) * _PT
        for band_lo, band_hi in bands:
            bottom = max(band_lo + margin, min_bottom)
            if bottom + height + margin <= band_hi:
                return BoxPlan(bottom / _PT, height / _PT, compact, overlaps=False)
    return BoxPlan(_BOX_MIN_BOTTOM_IN, _box_height_in(compact_lines), True, overlaps=True)


# -- drawing -------------------------------------------------------------------

def _overlay_pdf_bytes(
    heading: str, lines: list[tuple[str, str]], warn: bool, bottom_in: float, height_in: float,
) -> bytes:
    """Render the identity box on an otherwise blank Letter page, as PDF."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    # TrueType (42) rather than matplotlib's default Type 3 glyph outlines, so
    # the name and MRN are real text: searchable in the recipient's viewer,
    # and extractable by the tests that check the stamp landed.
    plt.rcParams["pdf.fonttype"] = 42

    # The overlay must paint NOTHING but the box. A default figure starts its
    # content stream with a full-page white fill, and the merge appends the
    # overlay's ops after the cover's, so that fill would wipe the letterhead
    # and demographics before the box is drawn -- which is exactly what
    # happened on the first real report. Text extraction cannot see a white
    # rectangle, so keep the transparency and the test that checks for it.
    fig = plt.figure(figsize=PAGE_SIZE, facecolor="none")
    fig.patch.set_alpha(0.0)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, PAGE_SIZE[0])
    ax.set_ylim(0, PAGE_SIZE[1])
    ax.set_axis_off()
    ax.patch.set_visible(False)

    left = _BOX_MARGIN_X_IN
    width = PAGE_SIZE[0] - 2 * _BOX_MARGIN_X_IN
    edge, fill = (_WARN_EDGE, _WARN_FILL) if warn else (_IDENT_EDGE, _IDENT_FILL)
    ax.add_patch(FancyBboxPatch(
        (left, bottom_in), width, height_in,
        boxstyle="round,pad=0,rounding_size=0.08",
        linewidth=1.6, edgecolor=edge, facecolor=fill,
    ))

    pad_x = 0.18
    top = bottom_in + height_in - 0.12
    ax.text(left + pad_x, top, heading, fontsize=11.5, fontweight="bold",
            color=edge, ha="left", va="top")
    y = top - _HEADING_IN
    label_x = left + pad_x
    value_x = left + pad_x + 1.3
    for label, value in lines:
        ax.text(label_x, y, f"{label}:", fontsize=10.5, fontweight="bold",
                color=_TEXT, ha="left", va="top")
        ax.text(value_x, y, value, fontsize=10.5, color=_TEXT, ha="left", va="top")
        y -= _LINE_IN

    buf = io.BytesIO()
    fig.savefig(buf, format="pdf", transparent=True)
    plt.close(fig)
    return buf.getvalue()


def content_paints_the_page(data: bytes) -> bool:
    """True if *data* (a PDF content stream) fills the whole page area.

    A renderer-free check for the regression described in
    :func:`_overlay_pdf_bytes`: a page-sized path (``612 792`` is the Letter
    corner in points) followed by a fill operator. A transparent figure still
    emits the path, but ends it with ``n`` (no-op) rather than ``f``.
    """
    width_pt, height_pt = (round(v * _PT) for v in PAGE_SIZE)
    corner = f"{width_pt} {height_pt} l".encode()
    start = 0
    while True:
        index = data.find(corner, start)
        if index < 0:
            return False
        after = data[index:index + 40]
        if b"\nf" in after or b" f\n" in after or b"\nB" in after:
            return True
        start = index + len(corner)


def overlay_paints_the_page(overlay_pdf: bytes) -> bool:
    """:func:`content_paints_the_page` applied to an overlay PDF's first page."""
    from pypdf import PdfReader

    page = PdfReader(io.BytesIO(overlay_pdf)).pages[0]
    content = page.get_contents()
    return content_paints_the_page(content.get_data() if content is not None else b"")


def build_overlay(
    key: ParticipantKey,
    visit_date: date | None,
    identity: Identity | None,
    unresolved_reason: str = "",
    plan: BoxPlan | None = None,
) -> bytes:
    """The overlay page as PDF bytes; identified when *identity* has either field.

    Without a *plan* the full box is drawn at the default bottom position.
    """
    compact = plan.compact if plan is not None else False
    heading, lines, warn = _box_text(key, visit_date, identity, unresolved_reason, compact)
    if plan is None:
        plan = BoxPlan(_BOX_MIN_BOTTOM_IN, _box_height_in(len(lines)), False, False)
    return _overlay_pdf_bytes(heading, lines, warn, plan.bottom_in, plan.height_in)


@dataclass(frozen=True)
class Stamped:
    path: Path
    plan: BoxPlan

    @property
    def overlaps(self) -> bool:
        return self.plan.overlaps


def stamp_report(
    source_pdf: str | Path,
    output_pdf: str | Path,
    key: ParticipantKey,
    visit_date: date | None,
    identity: Identity | None,
    unresolved_reason: str = "",
) -> Stamped:
    """Write *output_pdf*: a copy of *source_pdf* with the identity box on page 1.

    The source file is opened read-only and is never altered.
    """
    from pypdf import PdfReader, PdfWriter

    source_pdf = Path(source_pdf)
    output_pdf = Path(output_pdf)
    if not source_pdf.is_file():
        raise FileNotFoundError(f"Report not found: {source_pdf}")

    # Clone into the writer first and merge on the writer's own page: merging
    # on a reader's page is the path pypdf deprecated as unreliable.
    writer = PdfWriter(clone_from=str(source_pdf))
    cover = writer.pages[0]

    _, full_lines, _ = _box_text(key, visit_date, identity, unresolved_reason, compact=False)
    _, compact_lines, _ = _box_text(key, visit_date, identity, unresolved_reason, compact=True)
    plan = plan_box(cover, len(full_lines), len(compact_lines))

    overlay = PdfReader(io.BytesIO(build_overlay(key, visit_date, identity, unresolved_reason, plan)))
    cover.merge_page(overlay.pages[0])

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with open(output_pdf, "wb") as fh:
        writer.write(fh)
    return Stamped(path=output_pdf, plan=plan)
