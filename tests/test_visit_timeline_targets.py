"""The visit timeline describes the visit, not one recording.

``visit_timeline``, ``visit_table``, ``cmap_table`` and ``munix_table`` are
already declared ``_TARGET_INDEPENDENT_GRAPH_TYPES`` -- "the visit's date list
and the nerve-conduction tables read the same no matter which muscle the user is
looking at". But that set was only consulted when deciding how many figures to
render, never when narrowing the data, so a selected recording target still
filtered their rows.

Two consequences, both reported from the lab against SNBR-192:

  - the timeline showed **one** of their two visits, because the other was
    recorded from the opposite side and the target carries a side; and
  - selecting the target belonging to the *other* visit raised
    ``No rows found for participant ID 192 on 20/08/2026`` outright.

The SR and SD curves are deliberately still narrowed by side: a left-APB
recruitment curve is a different recording from the right APB's, not the same
test on the other hemisphere.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui.controller import AppController
from parser.mem_parser import TSICI_ISIS, initialize_record
from processing.df_builder import build_mem_dataframe

SUBJECT = 192


def _rec(pid, date, value, *, cortex, side, muscle="FDI", cmap=None, munix=None):
    r = initialize_record()
    r.update(
        Study="SNBR", ID=pid, Date=date, Subject_type="Patient",
        Stimulated_cortex=cortex, Muscle=muscle, Recorded_side=side,
        source_file=f"SNBR-{pid:03d}-{date.replace('/', '')}-{cortex}.MEM",
    )
    for isi in TSICI_ISIS:
        r[f"T_SICI_{isi}"] = value
    if cmap is not None:
        r["CMAP_table"] = cmap
    if munix is not None:
        r["MUNIX_table"] = munix
    return r


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


@pytest.fixture
def controller():
    """SNBR-192's shape: two visits, opposite sides, one target each."""
    df = build_mem_dataframe([
        _rec(SUBJECT, "12/05/2026", 96.5, cortex="L", side="R"),
        _rec(SUBJECT, "20/08/2026", 95.2, cortex="R", side="L"),
    ])
    c = AppController()
    c.set_dataframe(df)
    c.set_selected_participant(SUBJECT, c.get_visit_dates(SUBJECT)[-1])
    return c


def _visit_count(data) -> int:
    if "visit_count" in data:
        return int(data["visit_count"])
    for key in ("visit_timeline", "visit_summary"):
        if key in data:
            return len(data[key])
    raise AssertionError(f"no visit information in plot_data: {sorted(data)}")


@pytest.mark.parametrize("graph_type", ["visit_timeline", "visit_table"])
@pytest.mark.parametrize("targets", [[], ["Left FDI"], ["Right FDI"]])
def test_the_timeline_shows_every_visit_whatever_is_selected(
    controller, graph_type, targets,
):
    controller.set_selected_targets(targets)

    _figure, _axes, data = controller.generate_figure(graph_type, None)

    assert _visit_count(data) == 2, (
        f"{graph_type} with {targets!r} showed {_visit_count(data)} of 2 visits"
    )


@pytest.mark.parametrize("graph_type", ["visit_timeline", "visit_table"])
def test_a_target_from_another_visit_does_not_raise(controller, graph_type):
    """"Right FDI" belongs to the May visit; the selected date is August."""
    controller.set_selected_targets(["Right FDI"])
    figure, _axes, _data = controller.generate_figure(graph_type, None)
    assert figure is not None


def test_the_nerve_conduction_table_is_not_narrowed_either():
    """A CMAP result sits on the row of the muscle it was recorded from.

    Narrowing to another target hid it, even though the table describes the
    visit rather than that muscle.
    """
    rows = json.dumps([
        {"nerve_site": "Left Ulnar / Wrist", "muscle": "ADM",
         "latency_ms": 4.21, "amplitude_mv": 2.2},
    ])
    df = build_mem_dataframe([
        # The CMAP result is attached to the ADM recording...
        _rec(SUBJECT, "20/08/2026", 95.2, cortex="R", side="L",
             muscle="ADM", cmap=rows),
        # ...while the user is looking at FDI.
        _rec(SUBJECT, "20/08/2026", 90.0, cortex="R", side="L", muscle="FDI"),
    ])
    c = AppController()
    c.set_dataframe(df)
    c.set_selected_participant(SUBJECT, c.get_visit_dates(SUBJECT)[-1])
    c.set_selected_targets(["Left FDI"])

    scoped = c._target_scoped_dataframe("cmap_table")
    mine = scoped[pd.to_numeric(scoped["ID"], errors="coerce") == SUBJECT]
    assert mine["CMAP_table"].notna().any(), (
        "the CMAP result was filtered out because it sits on the ADM row"
    )


def test_the_peripheral_curves_are_still_narrowed_by_side(controller):
    """SR/SD are per-side recordings and must keep the target filter."""
    controller.set_selected_targets(["Left FDI"])

    scoped = controller._target_scoped_dataframe("stimulus_response")
    mine = scoped[pd.to_numeric(scoped["ID"], errors="coerce") == SUBJECT]
    assert len(mine) == 1, (
        "a stimulus-response curve must stay scoped to the selected side"
    )

    # ...and with no graph_type given, the old narrowing still applies.
    assert len(
        controller._target_scoped_dataframe()[
            pd.to_numeric(controller._dataframe["ID"], errors="coerce") == SUBJECT
        ]
    ) == 1
