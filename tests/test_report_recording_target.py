"""The report must honour the recording target -- and not lose a visit doing it.

Two faults met here, pulling in opposite directions.

``build_report_figures`` narrowed the participant *after*
``load_mem_dataframe``, and that normalisation drops ``Muscle`` and
``Recorded_side`` (105 columns down to 86). ``restrict_participant_to_target``
returns the frame untouched when it finds no muscle column, so the restriction
silently did nothing while every figure title still named a target. The
Visualization page, which works off the raw frame, did apply it -- so the report
and the app showed different data for the same selection.

Applying it correctly would then have introduced the opposite bug. SNBR-192's
two visits were recorded ``L->R`` and ``R->L``, so they resolve to *different*
targets -- "Right FDI" and "Left FDI" -- and filtering to either leaves one
visit. That is the reported symptom: a participant with two visits showing one.

So the narrowing is by **muscle**, not by the full target. A visit tested on
both hemispheres records the same muscle on the left and the right, and those
belong on one figure overlaid by stimulated cortex, which is what
``restrict_participant_to_muscle`` is for.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser.mem_parser import TSICI_ISIS, initialize_record
from processing._v1_visualization import (
    build_participant_visit_timeline_data,
    load_mem_dataframe,
)
from processing.df_builder import build_mem_dataframe
from reports import report_builder

SUBJECT = 192


def _rec(pid, date, value, *, cortex, side, muscle="FDI", subject_type="Patient"):
    r = initialize_record()
    r.update(
        Study="SNBR", ID=pid, Date=date, Subject_type=subject_type,
        Stimulated_cortex=cortex, Muscle=muscle, Recorded_side=side,
        source_file=f"SNBR-{pid:03d}-{date.replace('/', '')}-{cortex}.MEM",
    )
    for isi in TSICI_ISIS:
        r[f"T_SICI_{isi}"] = value
    return r


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


@pytest.fixture
def alternating_sides():
    """SNBR-192's shape: visit 1 stimulates L and records right FDI, visit 2 the
    other way round."""
    return build_mem_dataframe([
        _rec(SUBJECT, "12/05/2026", 96.5, cortex="L", side="R"),
        _rec(SUBJECT, "20/08/2026", 95.2, cortex="R", side="L"),
    ])


def _visits_in_report(df, pid, target):
    """How many visits the report's own timeline ends up with."""
    seen: list[int] = []
    original = report_builder.build_participant_visit_timeline_data

    def spy(rows):
        timeline = original(rows)
        seen.append(len(timeline))
        return timeline

    report_builder.build_participant_visit_timeline_data = spy
    try:
        report_builder.build_report_figures(
            pid, df, included_sections="t_sici_over_time", recording_target=target,
        )
    finally:
        report_builder.build_participant_visit_timeline_data = original
    return seen[0] if seen else 0


# ---------------------------------------------------------------------------
# The visit that went missing
# ---------------------------------------------------------------------------

def test_the_normalisation_really_does_drop_the_target_columns():
    """The premise of this whole file, asserted rather than assumed."""
    df = build_mem_dataframe([_rec(SUBJECT, "12/05/2026", 96.5, cortex="L", side="R")])
    assert {"Muscle", "Recorded_side"} <= set(df.columns)

    normalised = load_mem_dataframe(data_df=df)
    assert "Muscle" not in normalised.columns
    assert "Recorded_side" not in normalised.columns


@pytest.mark.parametrize("target", [None, "Right FDI", "Left FDI"])
def test_both_visits_survive_whichever_side_is_selected(alternating_sides, target):
    """The two visits are one muscle on two sides; neither may be dropped."""
    assert _visits_in_report(alternating_sides, SUBJECT, target) == 2, (
        f"target={target!r} lost a visit -- filtering the side as well as the "
        f"muscle deletes the other hemisphere's visit"
    )


def test_the_participants_own_rows_keep_both_hemispheres(alternating_sides):
    """Both cortices must reach the figures, to be overlaid rather than halved."""
    df = report_builder.restrict_participant_to_muscle(
        alternating_sides, SUBJECT, "FDI",
    )
    rows = df[pd.to_numeric(df["ID"], errors="coerce") == SUBJECT]
    assert set(rows["Stimulated_cortex"]) == {"L", "R"}
    assert len(build_participant_visit_timeline_data(rows)) == 2


# ---------------------------------------------------------------------------
# ...without the target becoming a no-op
# ---------------------------------------------------------------------------

@pytest.fixture
def two_muscles():
    """One participant recorded from FDI at two visits and TA at three."""
    records = []
    for date, value in (("12/05/2026", 96.5), ("20/08/2026", 95.2)):
        records.append(_rec(SUBJECT, date, value, cortex="L", side="R"))
    for date, value in (("12/05/2026", 60.0), ("20/08/2026", 61.0), ("01/12/2026", 62.0)):
        records.append(
            _rec(SUBJECT, date, value, cortex="L", side="R", muscle="TA")
        )
    return build_mem_dataframe(records)


def test_selecting_a_muscle_still_narrows_the_report(two_muscles):
    """Otherwise the fix above would just be a different way of doing nothing."""
    everything = _visits_in_report(two_muscles, SUBJECT, None)
    assert everything == 3, f"expected all three visit dates, got {everything}"

    assert _visits_in_report(two_muscles, SUBJECT, "Right FDI") == 2
    assert _visits_in_report(two_muscles, SUBJECT, "Right TA") == 3


def test_an_unknown_target_leaves_the_report_alone(two_muscles):
    """A label that matches no row must not silently empty the report."""
    assert _visits_in_report(two_muscles, SUBJECT, "Left ADM") == 3


def test_a_frame_without_muscle_data_is_unaffected():
    """Archives predating recording targets fall back to the cortex selector."""
    df = build_mem_dataframe([
        _rec(SUBJECT, "12/05/2026", 96.5, cortex="L", side="R"),
        _rec(SUBJECT, "20/08/2026", 95.2, cortex="R", side="L"),
    ]).drop(columns=["Muscle", "Recorded_side"])

    assert _visits_in_report(df, SUBJECT, "Right FDI") == 2
