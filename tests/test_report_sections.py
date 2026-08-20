"""Every report section has to build, not just the default fourteen.

``build_report_figures`` defaults to 14 of the 43 sections
``supported_report_sections()`` offers, and the grouped RMT and CSP builders are
in the other 29. So a report test that leaves ``included_sections`` alone proves
much less than it looks like it does: traced against the real archive, a default
report never enters ``_items_from_panels``, ``_rmt_group_or_message``,
``_csp_group_or_message``, ``_csp_profile_cohort_kwargs``, ``_normalize`` or
``_single_fig_or_msg``. Six functions, none of them reached.

That is not hypothetical. During the last refactor those three were being edited
while the only report check in the suite never executed them.

So these build with ``included_sections="all"``, on a synthetic cohort rather
than the lab share, and one test asserts by call trace that the grouped builders
really did run -- otherwise this file could drift back into the same illusion.
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

from parser.mem_parser import (
    A_SICI_ISIS,
    ASICF_ISIS,
    CSP_RMT_LEVELS,
    TSICF_ISIS,
    TSICI_ISIS,
    initialize_record,
)
from processing.df_builder import build_mem_dataframe
from reports.pdf_layout import ReportItem
from reports.report_builder import build_report_figures, supported_report_sections

REPORT_BUILDER_PY = str((Path(__file__).resolve().parents[1] / "reports" / "report_builder.py").resolve())

# The subject of the report. Three visits so the over-time sections have a line
# to draw, and a trajectory to fit.
SUBJECT_ID = 1
VISIT_DATES = ["01/01/2026", "01/02/2026", "01/03/2026"]


def _record(pid, date, *, subject_type, sex, age, cortex="L", scale=1.0):
    """One fully-populated participant-visit row."""
    r = initialize_record()
    r.update(
        Study="SNBR", ID=pid, Date=date, Age=age, Sex=sex,
        Subject_type=subject_type, Stimulated_cortex=cortex,
        Handedness="R", Muscle="FDI", Recorded_side="R",
        source_file=f"SNBR-{pid:03d}-{date.replace('/', '')}.MEM",
    )

    # Resting motor threshold at the three pulse widths.
    for i, key in enumerate(("RMT50", "RMT200", "RMT1000")):
        r[key] = (40.0 + 5 * i) * scale

    # Cortical silent period: start, end and duration at each %RMT level.
    for i, level in enumerate(CSP_RMT_LEVELS):
        start = 20.0 + i
        duration = (50.0 + 10 * i) * scale
        r[f"CSPs_{level}"] = start
        r[f"CSPe_{level}"] = start + duration
        r[f"CSP_{level}"] = duration

    # Paired-pulse curves.
    for prefix, isis in (
        ("T_SICI", TSICI_ISIS), ("T_SICF", TSICF_ISIS),
        ("A_SICI", A_SICI_ISIS), ("A_SICF", ASICF_ISIS),
    ):
        for j, isi in enumerate(isis):
            r[f"{prefix}_{isi}"] = (70.0 + 3 * j) * scale

    return r


@pytest.fixture(scope="module")
def cohort():
    """A synthetic cohort: the subject, other patients, and controls.

    Both sexes and a spread of ages, so the sex-matched and age-matched
    sections have someone to match against rather than falling through to a
    "not enough data" message and quietly exercising nothing.
    """
    records = []

    # The participant the report is about.
    for date in VISIT_DATES:
        records.append(_record(SUBJECT_ID, date, subject_type="Patient", sex="M", age=60))

    # Reference patients and controls, spanning both sexes and nearby ages.
    pid = 10
    for subject_type in ("Patient", "Control"):
        for sex in ("M", "F"):
            for age in (58, 60, 62):
                for date in VISIT_DATES[:2]:
                    records.append(_record(
                        pid, date, subject_type=subject_type, sex=sex, age=age,
                        scale=1.0 + pid / 200.0,
                    ))
                pid += 1

    return build_mem_dataframe(records)


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


def test_the_cohort_actually_holds_what_the_sections_need(cohort):
    """A frame missing these would make every section below vacuously pass."""
    assert len(cohort) > 20
    assert set(cohort["Subject_type"]) == {"Patient", "Control"}
    assert set(cohort["Sex"]) == {"M", "F"}
    assert cohort[cohort["ID"] == SUBJECT_ID].shape[0] == len(VISIT_DATES)
    for column in ("RMT50", "CSP_80", "T_SICI_2ms", "A_SICI_2.0ms"):
        assert cohort[column].notna().any(), f"{column} is empty in the cohort"


@pytest.mark.parametrize("section", sorted(supported_report_sections()))
def test_each_supported_section_builds(cohort, section):
    """Named one at a time, so a failure says which section broke."""
    items = build_report_figures(SUBJECT_ID, cohort, included_sections=section)

    assert isinstance(items, list)
    for item in items:
        assert isinstance(item, ReportItem), f"{section} yielded a {type(item)}"
        assert item.figure is not None, f"{section} produced an item with no figure"


def test_a_full_report_builds_every_section_at_once(cohort):
    """The whole thing, the way the CLI path builds it."""
    items = build_report_figures(SUBJECT_ID, cohort, included_sections="all")

    assert items, "a full report produced no figures at all"
    assert all(isinstance(i, ReportItem) for i in items)

    sections = {i.section_key for i in items}
    assert len(sections) > len(_default_section_count()), (
        "'all' produced no more sections than the default set -- the argument "
        "is not doing anything"
    )


def _default_section_count():
    from reports.report_builder import DEFAULT_REPORT_SECTIONS
    return DEFAULT_REPORT_SECTIONS


def _trace_report_builder(participant_id, df, included_sections):
    """Which report_builder functions run for this section list."""
    called: set[str] = set()

    def tracer(frame, event, arg):
        if event == "call" and frame.f_code.co_filename == REPORT_BUILDER_PY:
            called.add(frame.f_code.co_name)
        return None

    sys.settrace(tracer)
    try:
        build_report_figures(participant_id, df, included_sections=included_sections)
    finally:
        sys.settrace(None)
    return called


# The builders that only a full report reaches. If this list ever goes stale the
# test below says so rather than silently checking nothing.
GROUPED_ONLY_BUILDERS = [
    "_items_from_panels",
    "_rmt_group_or_message",
    "_csp_group_or_message",
]


def test_the_grouped_builders_are_reached_only_by_a_full_report(cohort):
    """The whole reason this file passes included_sections="all".

    Asserts both halves: that the default set really does miss these, and that
    "all" really does reach them. If someone adds them to the default set this
    fails and points at the list above -- which is the correct outcome, because
    then the cheaper default report would be exercising them too.
    """
    default_calls = _trace_report_builder(SUBJECT_ID, cohort, None)
    all_calls = _trace_report_builder(SUBJECT_ID, cohort, "all")

    missed_by_default = [f for f in GROUPED_ONLY_BUILDERS if f not in default_calls]
    reached_by_all = [f for f in GROUPED_ONLY_BUILDERS if f in all_calls]

    assert reached_by_all == GROUPED_ONLY_BUILDERS, (
        f"a full report did not reach {sorted(set(GROUPED_ONLY_BUILDERS) - all_calls)} "
        f"-- this file is not testing what it claims to"
    )
    assert missed_by_default == GROUPED_ONLY_BUILDERS, (
        f"{sorted(set(GROUPED_ONLY_BUILDERS) - set(missed_by_default))} now run "
        f"under the default section set too; update GROUPED_ONLY_BUILDERS"
    )


def test_an_unknown_section_name_is_rejected(cohort):
    """A typo in a section list must not silently produce an empty report."""
    with pytest.raises(ValueError, match="not_a_section"):
        build_report_figures(SUBJECT_ID, cohort, included_sections="not_a_section")


# --------------------------------------------------------------------------
# Each panel keeps its own caption
# --------------------------------------------------------------------------

# The grouped builders return one figure per panel plus a parallel list of
# figure keys, and _items_from_panels pairs them up by index. Get that pairing
# wrong and every figure is captioned with another panel's raw values -- a
# report that looks right and reads wrong.
GROUPED_PANEL_ORDER = [
    ("rmt_overall", ["RMT50", "RMT200", "RMT1000"]),
    ("csp_overall", ["CSP_80", "CSP_100", "CSP_120", "CSP_140", "CSP_160"]),
]


@pytest.mark.parametrize("section,expected_panels", GROUPED_PANEL_ORDER)
def test_grouped_panels_keep_each_figure_with_its_own_caption(
    cohort, section, expected_panels,
):
    items = build_report_figures(SUBJECT_ID, cohort, included_sections=section)

    captions = [i.caption for i in items]
    assert all(captions), f"{section}: a panel came out with no caption: {captions}"
    assert len(set(captions)) == len(captions), (
        f"{section}: two panels share a caption, so the pairing has slipped"
    )

    found = [c.split()[0] for c in captions]
    assert found == expected_panels, (
        f"{section}: captions are paired with the wrong panels -- got {found}, "
        f"expected {expected_panels}"
    )
