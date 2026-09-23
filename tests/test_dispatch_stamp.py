"""dispatch/stamp.py -- the identity box lands on page 1 and nowhere else.

The source PDF is a synthetic two-page report drawn with matplotlib in
``tmp_path`` (never a real report). Skips when pypdf is absent, the same
policy test_cmap_parser applies to pdfplumber.
"""

from __future__ import annotations

import io
from datetime import date

import pytest

pypdf = pytest.importorskip("pypdf")

from dispatch.identity import Identity, ParticipantKey
from dispatch.stamp import (
    build_overlay, content_paints_the_page, overlay_paints_the_page, stamp_report,
)

KEY = ParticipantKey("SNBR", 80)
VISIT = date(2026, 8, 18)


@pytest.fixture
def source_pdf(tmp_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    path = tmp_path / "report_SNBR_080_20260818.pdf"
    with PdfPages(path) as pdf:
        for label in ("COVER", "BODY"):
            fig = plt.figure(figsize=(8.5, 11))
            fig.text(0.1, 0.9, label, fontsize=20)
            pdf.savefig(fig)
            plt.close(fig)
    return path


def _texts(path):
    reader = pypdf.PdfReader(str(path))
    return [page.extract_text() for page in reader.pages]


def test_identified_stamp_on_cover_only(source_pdf, tmp_path):
    out = tmp_path / "John_Smith_1234567_20260818.pdf"
    ident = Identity(KEY, "AA-SNBR-080", "John Smith", "1234567")
    stamp_report(source_pdf, out, KEY, VISIT, ident)

    texts = _texts(out)
    assert len(texts) == 2
    cover, body = texts
    assert "PATIENT IDENTIFICATION" in cover
    assert "John Smith" in cover and "1234567" in cover
    assert "SNBR-080" in cover and "18/08/2026" in cover
    assert "COVER" in cover
    assert "John Smith" not in body and "BODY" in body


def test_unresolved_stamp_is_the_amber_variant_and_names_the_reason(source_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    stamp_report(source_pdf, out, KEY, VISIT, None, "not in the enrolment roster")
    cover = _texts(out)[0]
    assert "IDENTITY NOT RESOLVED" in cover
    assert "not in the enrolment roster" in cover
    assert "PATIENT IDENTIFICATION" not in cover
    assert "de-identified" in cover


def test_a_blank_mrn_does_not_discard_the_name(source_pdf, tmp_path):
    """The reported bug: one empty cell made the whole report anonymous."""
    out = tmp_path / "out.pdf"
    stamp_report(source_pdf, out, KEY, VISIT, Identity(KEY, "AA-SNBR-080", "John Smith", ""))
    cover = _texts(out)[0]
    assert "John Smith" in cover, "the name the log *did* have must be stamped"
    assert "PATIENT IDENTIFICATION (INCOMPLETE)" in cover
    assert "IDENTITY NOT RESOLVED" not in cover
    assert "not recorded in the enrolment log" in cover
    assert "SNBR-080" in cover and "18/08/2026" in cover


def test_a_blank_name_does_not_discard_the_mrn(source_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    stamp_report(source_pdf, out, KEY, VISIT, Identity(KEY, "AA-SNBR-080", "  ", "1234567"))
    cover = _texts(out)[0]
    assert "1234567" in cover
    assert "PATIENT IDENTIFICATION (INCOMPLETE)" in cover
    assert "IDENTITY NOT RESOLVED" not in cover
    assert "not recorded in the enrolment log" in cover


def test_a_row_with_neither_field_is_still_unresolved(source_pdf, tmp_path):
    """The de-identified path survives -- it just no longer swallows partials."""
    out = tmp_path / "out.pdf"
    stamp_report(source_pdf, out, KEY, VISIT, Identity(KEY, "AA-SNBR-080", "", ""))
    cover = _texts(out)[0]
    assert "IDENTITY NOT RESOLVED" in cover
    assert "lacks name and MRN" in cover
    assert "de-identified" in cover


def test_the_incomplete_box_is_the_amber_variant(source_pdf, tmp_path):
    """Complete is blue, incomplete is amber -- the caveat has to be visible.

    Checked on the drawn colours rather than the text, since both variants
    share the same heading prefix.
    """
    import re

    from dispatch.stamp import _IDENT_EDGE, _WARN_EDGE, build_overlay

    def hex_rgb(value):
        return tuple(int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))

    def stroke_colours(pdf_bytes):
        """Every ``r g b RG`` in the page, parsed as floats.

        Parsed rather than string-matched: matplotlib writes ten decimal
        places, and pinning that formatting would make this test fail on a
        matplotlib upgrade that changes nothing visible.
        """
        data = pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages[0].get_contents().get_data()
        return {
            tuple(round(float(c), 6) for c in match)
            for match in re.findall(rb"([\d.]+) ([\d.]+) ([\d.]+) RG", data)
        }

    def near(colours, target):
        return any(all(abs(c - t) < 1e-4 for c, t in zip(found, target)) for found in colours)

    partial = stroke_colours(build_overlay(KEY, VISIT, Identity(KEY, "x", "John Smith", "")))
    complete = stroke_colours(build_overlay(KEY, VISIT, Identity(KEY, "x", "John Smith", "1234567")))

    assert near(partial, hex_rgb(_WARN_EDGE)) and not near(partial, hex_rgb(_IDENT_EDGE))
    assert near(complete, hex_rgb(_IDENT_EDGE)) and not near(complete, hex_rgb(_WARN_EDGE))


def test_overlay_paints_only_the_box_never_the_page():
    """Demonstrated on the first real report: a default matplotlib figure
    opens its content stream with a full-page white fill, and since the merge
    appends the overlay's ops after the cover's, that fill erased the
    letterhead and demographics before the box was drawn. Text extraction
    cannot see a white rectangle, so this checks the operators directly.
    """
    ident = Identity(KEY, "AA-SNBR-080", "John Smith", "1234567")
    assert not overlay_paints_the_page(build_overlay(KEY, VISIT, ident))
    assert not overlay_paints_the_page(build_overlay(KEY, VISIT, None, "not in roster"))


def test_the_detector_would_catch_an_opaque_overlay():
    """The check above is only worth having if it fails for the bad case."""
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(8.5, 11))   # default: opaque white background
    buf = io.BytesIO()
    fig.savefig(buf, format="pdf")
    plt.close(fig)
    assert overlay_paints_the_page(buf.getvalue())


def test_cover_content_survives_the_merge(source_pdf, tmp_path):
    """The stamped page must still contain every drawing op of the original."""
    original = pypdf.PdfReader(str(source_pdf)).pages[0].get_contents().get_data()
    out = tmp_path / "out.pdf"
    stamp_report(source_pdf, out, KEY, VISIT, Identity(KEY, "x", "A B", "1"))
    stamped = pypdf.PdfReader(str(out)).pages[0].get_contents().get_data()
    # pypdf wraps the original in q/Q; the original ops must appear verbatim
    # and precede the overlay's, and nothing after them may fill the page.
    assert original.strip() in stamped
    tail = stamped[stamped.index(original.strip()) + len(original.strip()):]
    assert not content_paints_the_page(tail)


# -- placement -------------------------------------------------------------------
#
# The cover's summary raster varies in height, and older reports carried a
# visit table and timeline on page 1, so the box is placed per report in the
# lowest ink-free band. Covers here are built to put ink at known heights.

def _cover_with_ink_down_to(tmp_path, ink_bottom_in, footer=True, name="cover.pdf"):
    """A Letter page whose rasterized content reaches *ink_bottom_in* from the
    bottom, mimicking the analysis app: a letterhead band, one imshow raster
    with white padding inside it, and a footer text line at 0.22"."""
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path = tmp_path / name
    fig = plt.figure(figsize=(8.5, 11))
    fig.text(0.1, 0.95, "LETTERHEAD", fontsize=16)
    # Raster axes spanning from 1.0" below the top down to the page bottom; the
    # image is white except for a dark block that ends at ink_bottom_in.
    ax = fig.add_axes((0.05, 0.0, 0.9, 10.0 / 11.0))
    height_px = 1000
    img = np.ones((height_px, 800, 3))
    rows_from_bottom = int(round(ink_bottom_in / 10.0 * height_px))
    img[: height_px - rows_from_bottom, :, :] = 0.2
    ax.imshow(img, aspect="auto")
    ax.set_axis_off()
    if footer:
        fig.text(0.5, 0.22 / 11.0, "Page 1 of 9", fontsize=8, ha="center")
    fig.savefig(path, format="pdf")
    plt.close(fig)
    return path


def _plan(path):
    reader = pypdf.PdfReader(str(path))
    from dispatch.stamp import plan_box
    return plan_box(reader.pages[0], full_lines=4, compact_lines=2)


def test_ink_intervals_see_raster_ink_and_text(tmp_path):
    from dispatch.stamp import ink_intervals
    page = pypdf.PdfReader(str(_cover_with_ink_down_to(tmp_path, 3.0))).pages[0]
    intervals = ink_intervals(page)
    tops = [hi for _, hi in intervals]
    bottoms = [lo for lo, _ in intervals]
    # The raster's dark block ends 3.0" from the bottom (216 pt), give or take a row.
    assert any(abs(lo - 216) < 6 for lo in bottoms), bottoms
    # The footer text line sits at 0.22" (16 pt) and the letterhead near the top.
    assert any(lo < 20 for lo in bottoms)
    assert any(hi > 700 for hi in tops)


def test_full_box_goes_in_the_free_band_below_the_content(tmp_path):
    plan = _plan(_cover_with_ink_down_to(tmp_path, 3.0))
    assert not plan.compact and not plan.overlaps
    # Above the footer text, below the ink: 0.45" minimum, and the top must
    # clear the 3.0" ink line with margin.
    assert plan.bottom_in >= 0.45 - 1e-9
    assert plan.bottom_in + plan.height_in <= 3.0


def test_a_blank_cover_gets_the_default_bottom_position(tmp_path):
    plan = _plan(_cover_with_ink_down_to(tmp_path, 10.0, footer=False))
    assert not plan.compact and not plan.overlaps
    assert plan.bottom_in == pytest.approx(0.45)


def test_compact_box_when_only_a_narrow_band_is_free(tmp_path):
    plan = _plan(_cover_with_ink_down_to(tmp_path, 1.5))
    assert plan.compact and not plan.overlaps
    assert plan.bottom_in + plan.height_in <= 1.5


def test_overlap_is_flagged_when_nothing_fits(tmp_path):
    plan = _plan(_cover_with_ink_down_to(tmp_path, 0.6))
    assert plan.overlaps and plan.compact
    assert plan.bottom_in == pytest.approx(0.45)


def test_stamp_reports_the_plan_and_batch_can_warn(tmp_path):
    from dispatch.stamp import Stamped
    src = _cover_with_ink_down_to(tmp_path, 0.6)
    result = stamp_report(src, tmp_path / "out.pdf", KEY, VISIT, Identity(KEY, "x", "A B", "1"))
    assert isinstance(result, Stamped) and result.overlaps
    cover = _texts(result.path)[0]
    assert "PATIENT IDENTIFICATION" in cover and "A B" in cover


def test_source_is_untouched(source_pdf, tmp_path):
    before = source_pdf.read_bytes()
    stamp_report(source_pdf, tmp_path / "out.pdf", KEY, VISIT,
                 Identity(KEY, "x", "A B", "1"))
    assert source_pdf.read_bytes() == before


def test_missing_source_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        stamp_report(tmp_path / "nope.pdf", tmp_path / "out.pdf", KEY, VISIT, None)
