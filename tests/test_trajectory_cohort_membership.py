"""Who gets a line on the T-SICI trajectory, and who was being dropped.

Reported from the lab: SNBR-080's trajectory showed almost none of the
participants who have repeated visits, and SNBR-192 showed one visit when they
have two. Three separate causes, all of them silent -- no error, no warning, and
a plot that looks finished.

1. **Subject type read from the wrong visit.** ``_latest_non_missing`` is named
   for the latest visit but took the last *row*. The cohort frame is not
   date-sorted, so for a participant whose rows disagree it read the oldest
   visit. SNBR-080 is Control at baseline and Patient at both follow-ups, so
   their trajectory was drawn against the 4 SNBR controls with repeated visits
   instead of the 39 patients.

2. **Study matched per row instead of per participant.** 40 participants carry
   more than one study token across their visits and a quarter of rows name no
   study at all, so restricting row-wise deleted visits from participants who
   were in the study all along, pushing them under the two-visit minimum.

3. **The hemisphere restriction applied to a longitudinal figure.** Keeping one
   cortex per cohort member is right for a cross-sectional average, where it
   stops a both-sides participant counting twice. A trajectory already collapses
   each visit date to a single mean, so nothing can be double-counted; all the
   restriction did was delete follow-up visits, and every participant whose
   visits alternate sides fell below two.

The cohort now draws one line per participant *per hemisphere*, so a participant
followed on both contributes two lines rather than the two being averaged into
one.
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
from processing._v1_visualization import plot_participant_measure_trajectory
from processing.cohort_filters import restrict_cohort_to_study
from processing.df_builder import build_mem_dataframe

SUBJECT = 1


def _rec(pid, date, value, *, subject_type="Patient", cortex="L", study="SNBR"):
    r = initialize_record()
    r.update(
        Study=study, ID=pid, Date=date, Subject_type=subject_type,
        Stimulated_cortex=cortex, Muscle="FDI",
        Recorded_side=("R" if cortex == "L" else "L"),
        source_file=f"SNBR-{pid:03d}-{date.replace('/', '')}-{cortex}.MEM",
    )
    for isi in TSICI_ISIS:
        r[f"T_SICI_{isi}"] = value
    return r


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


def _trajectory(df, pid=SUBJECT, **kwargs):
    _fig, _ax, data = plot_participant_measure_trajectory(
        measure="t_sici", participant_id=pid, data_df=df, show=False, **kwargs
    )
    return data


# ---------------------------------------------------------------------------
# 1. Subject type comes from the latest visit, not the last row
# ---------------------------------------------------------------------------

def test_subject_type_is_read_from_the_most_recent_visit():
    """A participant whose rows disagree must be typed by their latest visit.

    The dates matter. resolve_participant_context sorts the participant's rows
    by the date *string*, so "18/08/2026" sorts before "22/04/2024" -- 18 < 22 --
    and the newest visit ends up first with the oldest last. That is exactly how
    SNBR-080's rows arrive, and it is what makes reading the last row read their
    oldest visit. Pick a baseline whose day-of-month is higher than the
    follow-up's, or the string order coincides with date order and the bug
    cannot be seen at all.
    """
    records = [
        # The subject: Patient at the 2026 follow-up, Control at 2024 baseline.
        _rec(SUBJECT, "01/03/2026", 70.0),
        _rec(SUBJECT, "22/01/2024", 72.0, subject_type="Control"),
    ]
    # Two repeated-visit patients, one repeated-visit control.
    for pid in (10, 11):
        records += [_rec(pid, "01/01/2026", 80.0), _rec(pid, "01/06/2026", 82.0)]
    records += [
        _rec(20, "01/01/2026", 60.0, subject_type="Control"),
        _rec(20, "01/06/2026", 62.0, subject_type="Control"),
    ]

    df = build_mem_dataframe(records)

    # Guard: reproduce the ordering the real cohort frame has, or this test
    # passes for the wrong reason.
    from processing._v1_visualization import resolve_participant_context
    seen, _, _ = resolve_participant_context(df, participant_id=SUBJECT)
    assert str(seen["Subject_type"].iloc[-1]) == "Control", (
        f"the last row must be the oldest visit or this test is vacuous; "
        f"got {list(seen['Date'])}"
    )

    data = _trajectory(df)

    assert data["subject_type"] == "Patient", (
        "typed from the oldest visit -- the trajectory is drawn against the "
        "wrong reference group entirely"
    )
    assert 10 in data["cohort_ids"] and 11 in data["cohort_ids"]
    assert 20 not in data["cohort_ids"], "a control leaked into a patient cohort"


# ---------------------------------------------------------------------------
# 2. Study is resolved per participant, not per row
# ---------------------------------------------------------------------------

def test_a_participant_keeps_every_visit_when_one_row_names_another_study():
    """Their study is decided once; individual rows do not each have to agree."""
    records = [
        _rec(SUBJECT, "01/01/2026", 70.0),
        _rec(SUBJECT, "01/06/2026", 71.0),
        # In the study, but the second visit was filed under NIALS.
        _rec(10, "01/01/2026", 80.0, study="SNBR"),
        _rec(10, "01/06/2026", 82.0, study="NIALS"),
        # A control so the study restriction is usable at all.
        _rec(20, "01/01/2026", 60.0, subject_type="Control"),
        _rec(20, "01/06/2026", 62.0, subject_type="Control"),
    ]
    df = build_mem_dataframe(records)

    restricted, applied = restrict_cohort_to_study(df, "SNBR", exempt_id=SUBJECT)
    assert applied, "guard: the study restriction must actually be in force"

    kept = restricted[pd.to_numeric(restricted["ID"], errors="coerce") == 10]
    assert len(kept) == 2, (
        f"participant 10 kept {len(kept)} of 2 visits -- matching row by row "
        f"deletes the visit whose Study cell names a different study"
    )

    data = _trajectory(restricted)
    assert 10 in data["cohort_ids"], "they fell under the two-visit minimum"


def test_a_participant_of_another_study_is_still_excluded():
    """The restriction must still restrict."""
    records = [
        _rec(SUBJECT, "01/01/2026", 70.0),
        _rec(SUBJECT, "01/06/2026", 71.0),
        _rec(10, "01/01/2026", 80.0, study="NIALS"),
        _rec(10, "01/06/2026", 82.0, study="NIALS"),
        # The exempt subject cannot vouch for their own cohort, so the study
        # needs another patient of its own or the restriction falls back.
        _rec(11, "01/01/2026", 84.0),
        _rec(11, "01/06/2026", 86.0),
        _rec(20, "01/01/2026", 60.0, subject_type="Control"),
        _rec(20, "01/06/2026", 62.0, subject_type="Control"),
    ]
    restricted, applied = restrict_cohort_to_study(
        build_mem_dataframe(records), "SNBR", exempt_id=SUBJECT,
    )
    assert applied
    ids = set(pd.to_numeric(restricted["ID"], errors="coerce").dropna().astype(int))
    assert 10 not in ids


# ---------------------------------------------------------------------------
# 3. Hemispheres: one line each, and none deleted
# ---------------------------------------------------------------------------

def test_a_participant_followed_on_both_hemispheres_gets_two_lines():
    """Averaging the two into one trajectory would hide the difference."""
    records = [_rec(SUBJECT, "01/01/2026", 70.0), _rec(SUBJECT, "01/06/2026", 71.0)]
    for cortex in ("L", "R"):
        records += [
            _rec(10, "01/01/2026", 80.0, cortex=cortex),
            _rec(10, "01/06/2026", 82.0, cortex=cortex),
        ]

    data = _trajectory(build_mem_dataframe(records))

    assert data["cohort_ids"] == [SUBJECT, 10]
    # Two grey lines for participant 10, plus the subject's own single-cortex line.
    assert data["cohort_line_count"] == 3, (
        f"expected one line per (participant, hemisphere), got "
        f"{data['cohort_line_count']}"
    )


def test_visits_recorded_on_alternating_sides_are_not_deleted():
    """SNBR-192's shape: visit 1 on the left cortex, visit 2 on the right.

    Restricting them to a single analysis hemisphere leaves one visit, and the
    participant vanishes from every longitudinal figure.
    """
    records = [
        _rec(SUBJECT, "01/01/2026", 70.0, cortex="L"),
        _rec(SUBJECT, "01/06/2026", 71.0, cortex="R"),
    ]
    for pid in (10, 11):
        records += [_rec(pid, "01/01/2026", 80.0), _rec(pid, "01/06/2026", 82.0)]

    data = _trajectory(build_mem_dataframe(records))

    assert data["visit_count"] == 2, (
        "the selected participant lost a visit to the hemisphere split"
    )
    # Their two visits are drawn as one trajectory rather than two isolated
    # points -- see test_mixed_hemisphere_note.py for why, and for the note that
    # goes with it.
    assert data["cohort_line_count"] >= 3


def test_the_selected_participants_hemispheres_are_drawn_separately():
    """Both sides overlaid on one figure, not merged into a single line."""
    records = [
        _rec(SUBJECT, "01/01/2026", 70.0, cortex="L"),
        _rec(SUBJECT, "01/06/2026", 90.0, cortex="L"),
        _rec(SUBJECT, "01/01/2026", 40.0, cortex="R"),
        _rec(SUBJECT, "01/06/2026", 44.0, cortex="R"),
    ]
    for pid in (10, 11):
        records += [_rec(pid, "01/01/2026", 80.0), _rec(pid, "01/06/2026", 82.0)]

    figure, axis, data = plot_participant_measure_trajectory(
        measure="t_sici", participant_id=SUBJECT,
        data_df=build_mem_dataframe(records), show=False,
    )

    labels = [t.get_text() for t in axis.get_legend().get_texts()]
    named = [l for l in labels if "cortex" in l.lower()]
    assert len(named) == 2, (
        f"expected the two hemispheres named separately in the legend, got {labels}"
    )
    assert data["visit_count"] == 2
