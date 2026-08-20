"""Visits on different hemispheres still get a longitudinal graph, plus a note.

Splitting a longitudinal figure by hemisphere is the right default: the two
sides are not interchangeable, and the split is what lets a both-sides visit be
read left against right.

It goes wrong in exactly one case. A participant whose visits *alternate* sides
-- SNBR-192 was recorded ``L->R`` in May and ``R->L`` in August -- has a single
point per hemisphere and therefore no line anywhere, so the figure stops showing
the change across visits that is its whole purpose.

Those are pooled into one series so the trend is drawn, and the figure carries a
note saying the measurements are not all from the same side. The note matters:
T-SICI is not interchangeable between hemispheres, so a line through both is
comparing things that are not strictly like for like. Showing it is still right
-- it is the only way to see those visits together -- but the reader has to be
told.

What must *not* change: a participant recorded on both sides at a single visit
keeps the split and gets no note, because there is no trend either way and the
left-versus-right comparison is the whole point of that figure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser.mem_parser import TSICI_ISIS, initialize_record
from processing._v1_visualization import RMT_COLUMNS
from processing import _v1_visualization as v1
from processing.df_builder import build_mem_dataframe

SUBJECT = 192


def _rec(pid, date, value, *, cortex, subject_type="Patient"):
    r = initialize_record()
    r.update(
        Study="SNBR", ID=pid, Date=date, Subject_type=subject_type,
        Stimulated_cortex=cortex, Muscle="FDI",
        Recorded_side=("R" if cortex == "L" else "L"),
        source_file=f"SNBR-{pid:03d}-{date.replace('/', '')}-{cortex}.MEM",
    )
    for isi in TSICI_ISIS:
        r[f"T_SICI_{isi}"] = value
    for i, column in enumerate(RMT_COLUMNS):
        r[column] = 40.0 + 5 * i
    return r


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


def _note_texts(axis):
    return [t.get_text() for t in axis.texts if "hemisphere" in t.get_text().lower()]


def _cohort(extra):
    """Two repeated-visit patients, so the trajectory has a cohort to draw."""
    records = list(extra)
    for pid in (10, 11):
        records += [
            _rec(pid, "01/01/2026", 80.0, cortex="L"),
            _rec(pid, "01/06/2026", 82.0, cortex="L"),
        ]
    return build_mem_dataframe(records)


ALTERNATING = [
    _rec(SUBJECT, "12/05/2026", 96.5, cortex="L"),
    _rec(SUBJECT, "20/08/2026", 95.2, cortex="R"),
]
ONE_SIDE_REPEATED = [
    _rec(SUBJECT, "12/05/2026", 96.5, cortex="L"),
    _rec(SUBJECT, "20/08/2026", 95.2, cortex="L"),
]
BOTH_SIDES_ONE_VISIT = [
    _rec(SUBJECT, "12/05/2026", 96.5, cortex="L"),
    _rec(SUBJECT, "12/05/2026", 90.0, cortex="R"),
]


# ---------------------------------------------------------------------------
# The trajectory
# ---------------------------------------------------------------------------

def test_alternating_sides_are_drawn_as_one_trajectory_with_a_note():
    df = _cohort(ALTERNATING)
    _fig, axis, data = v1.plot_participant_measure_trajectory(
        measure="t_sici", participant_id=SUBJECT, data_df=df, show=False,
    )

    own = [line for line in axis.get_lines() if str(line.get_label()).startswith("SNBR")]
    assert len(own) == 1, f"expected one pooled trajectory, got {len(own)}"
    assert len(own[0].get_xdata()) == 2, (
        "the two visits must be joined into a line, not left as isolated points"
    )
    assert data["visit_count"] == 2
    assert _note_texts(axis), "no note that the visits span different hemispheres"


def test_a_repeated_single_hemisphere_gets_no_note():
    df = _cohort(ONE_SIDE_REPEATED)
    _fig, axis, _data = v1.plot_participant_measure_trajectory(
        measure="t_sici", participant_id=SUBJECT, data_df=df, show=False,
    )
    assert not _note_texts(axis), "noted a mix where every visit is the same side"


def test_both_sides_at_one_visit_stay_split_and_unnoted():
    """The left-versus-right comparison is the point of that figure.

    Checked on the over-time plot rather than the trajectory: a single visit has
    no trajectory to draw at all, so that is where this case shows up.
    """
    df = _cohort(BOTH_SIDES_ONE_VISIT)
    _fig, axis, _data = v1.plot_participant_measure_over_time(
        measure="t_sici", participant_id=SUBJECT, data_df=df, show=False,
        group_by_cortex=True,
    )

    labels = (
        {str(t.get_text()) for t in axis.get_legend().get_texts()}
        if axis.get_legend() else set()
    )
    assert {"L", "R"} <= labels, f"the two sides must stay separate: {labels}"
    assert not _note_texts(axis), (
        "pooling a single visit gains nothing, so nothing should be noted"
    )


# ---------------------------------------------------------------------------
# The over-time figures
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("plot,kwargs", [
    (v1.plot_participant_measure_over_time, {"measure": "t_sici"}),
    (v1.plot_participant_rmt_over_time, {}),
])
def test_over_time_joins_alternating_visits_and_notes_it(plot, kwargs):
    df = _cohort(ALTERNATING)
    result = plot(
        participant_id=SUBJECT, data_df=df, show=False,
        group_by_cortex=True, **kwargs,
    )
    figure, axis = result[0], result[1]
    axes = list(axis) if isinstance(axis, (list, tuple)) else [axis]
    if isinstance(figure, (list, tuple)):
        axes = [a for a in axis] if isinstance(axis, (list, tuple)) else axes

    joined = any(
        len(line.get_xdata()) > 1 for a in axes for line in a.get_lines()
    )
    noted = any(_note_texts(a) for a in axes)

    assert joined, "the two visits were left as isolated points, showing no trend"
    assert noted, "no note that the visits span different hemispheres"


def test_over_time_keeps_the_split_when_a_side_has_its_own_series():
    """SNBR-080's shape: left recorded twice, right once. Keep them apart."""
    records = [
        _rec(SUBJECT, "22/04/2024", 96.5, cortex="L"),
        _rec(SUBJECT, "18/08/2026", 95.2, cortex="L"),
        _rec(SUBJECT, "18/08/2026", 90.0, cortex="R"),
    ]
    df = _cohort(records)

    _fig, axis, _data = v1.plot_participant_measure_over_time(
        measure="t_sici", participant_id=SUBJECT, data_df=df, show=False,
        group_by_cortex=True,
    )

    labels = {str(t.get_text()) for t in axis.get_legend().get_texts()} \
        if axis.get_legend() else set()
    assert {"L", "R"} <= labels, f"expected both cortices in the legend: {labels}"
    assert not _note_texts(axis), (
        "nothing is mixed here -- each series is one hemisphere"
    )


# ---------------------------------------------------------------------------
# The wording
# ---------------------------------------------------------------------------

def test_the_note_names_the_hemispheres_involved():
    df = _cohort(ALTERNATING)
    _fig, axis, _data = v1.plot_participant_measure_trajectory(
        measure="t_sici", participant_id=SUBJECT, data_df=df, show=False,
    )
    text = _note_texts(axis)[0]
    assert "L" in text and "R" in text, f"the note must name the sides: {text!r}"
    assert len(text) < 200, "the note is meant to be small"
