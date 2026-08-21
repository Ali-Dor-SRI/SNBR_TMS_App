"""SR-SD recording side allocation and multi-recording rendering.

A visit may hold several SR-SD (peripheral) files, one per side.  The side is
named nowhere structured: ``S/R sites:`` in the recent exports reads
``Wrist-FDI`` (no side), and the operator records the side in the free-text
``Comments:`` line (``LEFT FDI``) — or nowhere at all.  Before these rules,
SNBR-213's left and right FDI recordings coalesced onto one row and the right
recording's whole curve was silently discarded by the first-non-null merge.

The rules protected here, in resolution order:

1. ``Comments:`` fills the side (and muscle) on SR-SD files only, never
   overriding ``S/R sites:``, and only for the two unmistakable spellings.
2. A side-less SR-SD file takes the side of the visit's same-muscle TMS
   recording when that is unambiguous — never a side from another SR-SD file.
3. Recordings that still cannot be attributed stay on separate rows (both
   curves survive), render one figure each, and carry an amber caveat.
4. Two exports of one Qtrac acquisition (same filename token — SNBR-197's
   M-scan + excitability files) are one recording and still merge.
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from parser.mem_parser import parse_mem_file
from processing.df_builder import build_combined_dataframe
from reports.captions import caption_for

VISIT_DATE = datetime.date(2026, 8, 21)


# ---------------------------------------------------------------------------
# Synthetic .MEM builders (shapes copied from the real 21/08/2026 exports)
# ---------------------------------------------------------------------------

def _sr_mem(
    folder: Path,
    filename: str,
    *,
    subject: str = "SNBR-300",
    sites: str = "Wrist-FDI",
    comments: str = "",
    max_cmap: float = 9.89,
) -> Path:
    """Write a minimal SR-SD export carrying an SR and a charge-duration block."""
    text = (
        f" File:              \tc:\\Qtrac\\Data\\{Path(filename).stem.split('-')[-1]}.QZD\n"
        f" Name:              \t{subject} REGISTRY      \n"
        " Protocol:\n"
        " Date:              \t21/8/26  \n"
        f" S/R sites:         \t{sites}     \n"
        " Operator:          \tAD\n"
        f" Comments:          \t{comments}                \n"
        "\n"
        " STIMULUS-RESPONSE DATA (2.1-1.3m)\n"
        "\n"
        f" Max CMAP  1 ms =  {max_cmap} mV\n"
        "\n"
        "                    \t% Max               \tStimulus(2)\n"
        "SR.2                \t 2                  \t 6.114755\n"
        "SR.4                \t 4                  \t 6.973871\n"
        "\n"
        "  CHARGE DURATION DATA (2.1-2.9m)\n"
        "\n"
        "                    \tDuration (ms)       \t Threshold (mA)     \t  Threshold charge (mA.mS)\n"
        "QT.1                \t .2                 \t 21.7259            \t 4.345181\n"
        "QT.2                \t .4                 \t 14.85222           \t 5.940888\n"
        "QT.3                \t 1                  \t 9.940566           \t 9.940566\n"
        "\n"
        " DERIVED EXCITABILITY VARIABLES\n"
        "\n"
        " 3.                 \t0.443               \tStrength-duration\\time constant (ms)\n"
        f" 4.                 \t{max_cmap / 1.5:.3f}               \tRheobase (mA)\n"
    )
    path = folder / filename
    path.write_text(text, encoding="utf-8")
    return path


def _tms_mem(
    folder: Path,
    filename: str,
    *,
    subject: str = "SNBR-300",
    stim_record: str = "L->R",
    muscle: str = "FDI",
    comments: str = "TSICI ASICI CSP",
) -> Path:
    """Write a minimal cortical TMS export (RMT only)."""
    text = (
        f" File:              \tc:\\Qtrac\\Data\\{Path(filename).stem.split('-')[-1]}.QZD\n"
        f" Name:              \t{subject} REGISTRY      \n"
        " Date:              \t21/8/26  \n"
        f" Stim/record:       \t{stim_record}\n"
        f" Muscle:            \t{muscle}\n"
        f" Comments:          \t{comments}         \n"
        "\n"
        " EXTRA VARIABLES\n"
        "\n"
        " RMT200 = 55.0\n"
    )
    path = folder / filename
    path.write_text(text, encoding="utf-8")
    return path


def _rows(df: pd.DataFrame, pid: int) -> pd.DataFrame:
    return df[pd.to_numeric(df["ID"], errors="coerce") == pid]


def _figure_texts(fig) -> list[str]:
    return [t.get_text() for ax in fig.axes for t in ax.texts]


def _note_texts(fig) -> list[str]:
    return [t for t in _figure_texts(fig) if t.startswith("Note:")]


def _close_all():
    plt.close("all")


# ---------------------------------------------------------------------------
# 1. Comments: parsing — strict spellings only, SR-SD files only, fill-only
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("comment, expected", [
    ("LEFT FDI", ("FDI", "L")),
    ("RIGHT FDI", ("FDI", "R")),
    ("L-FDI", ("FDI", "L")),
    ("l ta", ("TA", "L")),
    ("LEFT", (None, "L")),
    ("repeat RIGHT ADM trial", ("ADM", "R")),
])
def test_comment_target_reads_the_unmistakable_spellings(comment, expected):
    # Imported here, not at module level, so the behavioural tests below
    # still collect and run against code predating the function.
    from parser.recording_target import extract_comment_target

    assert extract_comment_target(f"Comments: {comment}") == expected


@pytest.mark.parametrize("comment", [
    "SR-SD",                     # the R touches SD, not a side
    "Pt didnt tolrt <3ms",
    "TSICI ASICI CSP",
    "Only use 2nd trial RC",
    "OUTC PM. SR SD. QUARTS-1",
    "BSL D2 QUARTS-1",
    "TRIAL RUN",
    "R TAKE 2",                  # TAKE is not a muscle
    "LCX TO RH",                 # stimulated-cortex shorthand, not a side
    "",
])
def test_comment_noise_reads_as_nothing(comment):
    from parser.recording_target import extract_comment_target

    assert extract_comment_target(f"Comments: {comment}") == (None, None)


def test_sr_file_side_comes_from_comments(tmp_path):
    path = _sr_mem(tmp_path, "SNBR-300-L-FDI-TP3C60821A.MEM", comments="LEFT FDI")
    record = parse_mem_file(path)
    assert record["Muscle"] == "FDI"
    assert record["Recorded_side"] == "L"


def test_comments_never_override_sr_sites(tmp_path):
    # S/R sites names the muscle and side; a conflicting comment fills nothing.
    path = _sr_mem(
        tmp_path, "SNBR-300-TP3C60821A.MEM",
        sites="R WR-APB", comments="LEFT FDI",
    )
    record = parse_mem_file(path)
    assert record["Muscle"] == "APB"
    assert record["Recorded_side"] == "R"


def test_comments_never_touch_a_tms_file(tmp_path):
    # A side-shaped comment on a cortical file must be ignored even when the
    # file's own Stim/record names no side (the older no-arrow format): the
    # comment is protocol shorthand there, not a recording target. Only files
    # carrying an SR or SD block read their comment.
    path = _tms_mem(
        tmp_path, "SNBR-300-TP3C60821A.MEM",
        stim_record="L-R.", muscle="FDI", comments="LEFT TA",
    )
    record = parse_mem_file(path)
    assert record["Muscle"] == "FDI"
    assert record["Recorded_side"] is None


# ---------------------------------------------------------------------------
# 2. Row identity — both curves must survive, sides resolved when they can be
# ---------------------------------------------------------------------------

def test_two_sided_sr_files_keep_their_own_rows(tmp_path):
    _sr_mem(tmp_path, "SNBR-300-L-FDI-TP3C60821A.MEM",
            comments="LEFT FDI", max_cmap=9.89)
    _sr_mem(tmp_path, "SNBR-300-R-FDI-TP2C60821A.MEM",
            comments="RIGHT FDI", max_cmap=11.82)
    rows = _rows(build_combined_dataframe(tmp_path), 300)
    assert len(rows) == 2
    by_side = {r["Recorded_side"]: r for _, r in rows.iterrows()}
    assert set(by_side) == {"L", "R"}
    assert by_side["L"]["SR_max_cmap_1ms"] == pytest.approx(9.89)
    assert by_side["R"]["SR_max_cmap_1ms"] == pytest.approx(11.82)


def test_unattributable_sr_files_still_keep_both_curves(tmp_path):
    # No comments, no TMS that day: the sides stay unknown, but merging the
    # rows would silently discard one recording's curve.
    _sr_mem(tmp_path, "SNBR-300-L-FDI-TP3C60821A.MEM", max_cmap=9.89)
    _sr_mem(tmp_path, "SNBR-300-R-FDI-TP2C60821A.MEM", max_cmap=11.82)
    rows = _rows(build_combined_dataframe(tmp_path), 300)
    assert len(rows) == 2
    stored = sorted(pd.to_numeric(rows["SR_max_cmap_1ms"], errors="coerce"))
    assert stored == [pytest.approx(9.89), pytest.approx(11.82)]
    assert rows["Recorded_side"].isna().all()


def test_single_sr_file_joins_the_tms_recordings_side(tmp_path):
    # SNBR-207's shape: one TMS recording (recorded side R) plus one side-less
    # SR file of the same muscle -> one row, side R, TMS and SR data together.
    _tms_mem(tmp_path, "SNBR-300-BSL-TH3C60821A.MEM", stim_record="L->R")
    _sr_mem(tmp_path, "SNBR-300-TH3C60821B.MEM")
    rows = _rows(build_combined_dataframe(tmp_path), 300)
    assert len(rows) == 1
    row = rows.iloc[0]
    assert row["Recorded_side"] == "R"
    assert row["RMT200"] == pytest.approx(55.0)
    assert pd.notna(row["SR_max_cmap_1ms"])


def test_sr_side_never_leaks_from_another_sr_file(tmp_path):
    # One file commented LEFT, the other commentless, no TMS: the commentless
    # recording could be the right side or a left repeat, so it must keep an
    # unknown side rather than borrow L — and both rows must survive.
    _sr_mem(tmp_path, "SNBR-300-L-FDI-TP3C60821A.MEM",
            comments="LEFT FDI", max_cmap=9.89)
    _sr_mem(tmp_path, "SNBR-300-FDI-TP2C60821A.MEM", max_cmap=11.82)
    rows = _rows(build_combined_dataframe(tmp_path), 300)
    assert len(rows) == 2
    sides = rows["Recorded_side"].astype("string").fillna("").tolist()
    assert sorted(sides) == ["", "L"]


def test_two_sided_sr_files_ignore_a_single_tms_side(tmp_path):
    # Two side-less SR acquisitions cannot both have come from the TMS
    # recording's side; attributing either would be a guess.
    _tms_mem(tmp_path, "SNBR-300-BSL-TH3C60821A.MEM", stim_record="L->R")
    _sr_mem(tmp_path, "SNBR-300-A-FDI-TP3C60821A.MEM", max_cmap=9.89)
    _sr_mem(tmp_path, "SNBR-300-B-FDI-TP2C60821A.MEM", max_cmap=11.82)
    rows = _rows(build_combined_dataframe(tmp_path), 300)
    sr_rows = rows[pd.to_numeric(rows["SR_max_cmap_1ms"], errors="coerce").notna()]
    assert len(sr_rows) == 2
    assert sr_rows["Recorded_side"].isna().all()


def test_two_exports_of_one_acquisition_still_merge(tmp_path):
    # SNBR-197's shape: the M-scan export and the excitability export of the
    # SAME .QZD share the filename token — one recording, one row.
    _sr_mem(tmp_path, "SNBR-300-MSCAN-TP3C60821B.MEM",
            sites="Wrist-ADM", max_cmap=1.74)
    _sr_mem(tmp_path, "SNBR-300-NET-TP3C60821B.MEM",
            sites="Wrist-ADM", max_cmap=1.74)
    rows = _rows(build_combined_dataframe(tmp_path), 300)
    assert len(rows) == 1
    assert "MSCAN" in rows.iloc[0]["source_file"]
    assert "NET" in rows.iloc[0]["source_file"]


# ---------------------------------------------------------------------------
# 3. GUI figures — one per recording, caveat only where it belongs
# ---------------------------------------------------------------------------

def _controller_for(tmp_path):
    from gui.controller import AppController

    controller = AppController()
    controller.set_dataframe(build_combined_dataframe(tmp_path))
    return controller


NOTE_PREFIX = "Note: this visit has several SR-SD recordings"


def test_gui_renders_one_figure_per_unattributable_recording(tmp_path):
    _sr_mem(tmp_path, "SNBR-300-L-FDI-TP3C60821A.MEM", max_cmap=9.89)
    _sr_mem(tmp_path, "SNBR-300-R-FDI-TP2C60821A.MEM", max_cmap=11.82)
    controller = _controller_for(tmp_path)
    try:
        figs, _, data = controller._build_sr_figure_for_selected(300, VISIT_DATE)
        assert isinstance(figs, list) and len(figs) == 2
        assert data["figure_keys"] == ["recording_1", "recording_2"]
        for fig in figs:
            assert any(NOTE_PREFIX in t for t in _note_texts(fig))
        # Each figure annotates its own recording's reference amplitude.
        assert any("9.89" in t for t in _figure_texts(figs[0]))
        assert any("11.82" in t for t in _figure_texts(figs[1]))
    finally:
        _close_all()


def test_gui_sd_figures_split_with_the_note_too(tmp_path):
    _sr_mem(tmp_path, "SNBR-300-L-FDI-TP3C60821A.MEM", max_cmap=9.89)
    _sr_mem(tmp_path, "SNBR-300-R-FDI-TP2C60821A.MEM", max_cmap=11.82)
    controller = _controller_for(tmp_path)
    try:
        for builder in (
            controller._build_strength_duration_curve_for_selected,
            controller._build_charge_duration_weiss_for_selected,
        ):
            figs, _, data = builder(300, VISIT_DATE)
            assert isinstance(figs, list) and len(figs) == 2
            assert data["figure_keys"] == ["recording_1", "recording_2"]
            for fig in figs:
                assert any(NOTE_PREFIX in t for t in _note_texts(fig))
    finally:
        _close_all()


def test_gui_sided_recordings_get_side_labels_not_notes(tmp_path):
    _sr_mem(tmp_path, "SNBR-300-L-FDI-TP3C60821A.MEM",
            comments="LEFT FDI", max_cmap=9.89)
    _sr_mem(tmp_path, "SNBR-300-R-FDI-TP2C60821A.MEM",
            comments="RIGHT FDI", max_cmap=11.82)
    controller = _controller_for(tmp_path)
    try:
        figs, _, _ = controller._build_sr_figure_for_selected(300, VISIT_DATE)
        assert isinstance(figs, list) and len(figs) == 2
        titles = [t for fig in figs for t in _figure_texts(fig) if "Stimulus-Response" in t]
        assert any("Left FDI" in t for t in titles)
        assert any("Right FDI" in t for t in titles)
        for fig in figs:
            assert not _note_texts(fig)
    finally:
        _close_all()


def test_gui_single_recording_keeps_the_old_shape(tmp_path):
    from matplotlib.figure import Figure

    _tms_mem(tmp_path, "SNBR-300-BSL-TH3C60821A.MEM", stim_record="L->R")
    _sr_mem(tmp_path, "SNBR-300-TH3C60821B.MEM")
    controller = _controller_for(tmp_path)
    try:
        fig, axes, data = controller._build_sr_figure_for_selected(300, VISIT_DATE)
        assert isinstance(fig, Figure)
        assert axes is None
        assert "figure_keys" not in data
        assert not _note_texts(fig)
    finally:
        _close_all()


# ---------------------------------------------------------------------------
# 4. CLI report path — every recording rendered, captions per recording
# ---------------------------------------------------------------------------

def test_report_sd_sections_render_every_recording(tmp_path):
    from reports.report_builder import build_report_figures

    _sr_mem(tmp_path, "SNBR-300-L-FDI-TP3C60821A.MEM", max_cmap=9.89)
    _sr_mem(tmp_path, "SNBR-300-R-FDI-TP2C60821A.MEM", max_cmap=11.82)
    df = build_combined_dataframe(tmp_path)
    try:
        items = build_report_figures(
            300, df,
            included_sections=["strength_duration_curve", "charge_duration_weiss"],
        )
        by_section: dict = {}
        for item in items:
            by_section.setdefault(item.section_key, []).append(item)
        assert len(by_section["strength_duration_curve"]) == 2
        assert len(by_section["charge_duration_weiss"]) == 2
        for item in items:
            assert any(NOTE_PREFIX in t for t in _note_texts(item.figure))
        # The two recordings carry different rheobase values, and each caption
        # must quote its own figure's.
        curve_captions = [i.caption for i in by_section["strength_duration_curve"]]
        assert len(set(curve_captions)) == 2
    finally:
        _close_all()


def test_report_sd_sections_single_recording_unchanged(tmp_path):
    from reports.report_builder import build_report_figures

    _tms_mem(tmp_path, "SNBR-300-BSL-TH3C60821A.MEM", stim_record="L->R")
    _sr_mem(tmp_path, "SNBR-300-TH3C60821B.MEM")
    df = build_combined_dataframe(tmp_path)
    try:
        items = build_report_figures(
            300, df,
            included_sections=["strength_duration_curve", "charge_duration_weiss"],
        )
        assert len(items) == 2
        for item in items:
            assert not _note_texts(item.figure)
    finally:
        _close_all()


def test_caption_quotes_the_recording_it_sits_under():
    data = {
        "sr_max_cmap_1ms": 9.89, "sr_point_count": 10,
        "figure_keys": ["recording_1", "recording_2"],
        "recordings": {
            "recording_1": {"sr_max_cmap_1ms": 9.89, "sr_point_count": 10},
            "recording_2": {"sr_max_cmap_1ms": 11.82, "sr_point_count": 12},
        },
    }
    second = caption_for("stimulus_response", None, data, "recording_2")
    assert "11.82" in second
    assert "12 points" in second
    first = caption_for("stimulus_response", None, data, "recording_1")
    assert "9.89" in first
