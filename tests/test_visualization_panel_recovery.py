"""The Visualization page after a graph fails, and what the target filter hides.

Three faults reported together, and they chain.

1. **The target filter deletes a visit.** A recording target carries a side, and
   the page can only offer the targets of the *selected visit*. A participant
   whose visits alternate sides -- SNBR-192, ``L->R`` in May and ``R->L`` in
   August -- therefore has exactly one target per visit, and ticking it drops
   the other visit. Every longitudinal figure shows one visit.

2. **So the trajectory raises**, because one visit is fewer than the two it
   needs.

3. **And the error path then breaks the page.** ``_on_gen_error`` stores ``None``
   in the figure cache as a sentinel; ``_append_cached_items`` subscripted it and
   raised ``TypeError: 'NoneType' object is not subscriptable`` out of
   ``_rebuild_nav_list`` -- which every checkbox calls. One failed graph took the
   whole page's selection and navigation down with it.

Fault 1 is fixed by narrowing to the *muscle* for the figures that overlay
hemispheres, matching the report path. Faults 2 and 3 are fixed independently of
it: a graph can still legitimately fail (no data for that measure), and when it
does the page has to stay usable.
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
from processing.df_builder import build_mem_dataframe
from gui.controller import AppController

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


def _alternating_sides_df():
    """SNBR-192's shape, plus a cohort so the trajectory has something to draw."""
    records = [
        _rec(SUBJECT, "12/05/2026", 96.5, cortex="L", side="R"),
        _rec(SUBJECT, "20/08/2026", 95.2, cortex="R", side="L"),
    ]
    for pid in (10, 11):
        records += [
            _rec(pid, "01/01/2026", 80.0, cortex="L", side="R"),
            _rec(pid, "01/06/2026", 82.0, cortex="L", side="R"),
        ]
    return build_mem_dataframe(records)


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


@pytest.fixture
def controller():
    c = AppController()
    c.set_dataframe(_alternating_sides_df())
    dates = c.get_visit_dates(SUBJECT)
    c.set_selected_participant(SUBJECT, dates[-1])
    return c


# ---------------------------------------------------------------------------
# 1 + 2. The target must not delete the other visit
# ---------------------------------------------------------------------------

def test_the_page_offers_only_one_target_for_an_alternating_visit(controller):
    """The premise: this is why a side filter is fatal here."""
    dates = controller.get_visit_dates(SUBJECT)
    assert len(dates) == 2
    assert controller.get_target_options(SUBJECT, dates[0]) == ["Right FDI"]
    assert controller.get_target_options(SUBJECT, dates[1]) == ["Left FDI"]


@pytest.mark.parametrize("target", ["Left FDI", "Right FDI"])
@pytest.mark.parametrize("graph_type", ["trajectory", "over_time", "visit_profiles"])
def test_a_longitudinal_graph_keeps_both_visits(controller, target, graph_type):
    """Whichever side is ticked, both visits must reach the figure."""
    controller.set_selected_targets([target])

    figure, _axes, data = controller.generate_figure(graph_type, "t_sici")

    assert figure is not None
    if "visit_count" in data:
        assert data["visit_count"] == 2, (
            f"{graph_type} with {target!r} saw {data['visit_count']} visit(s); "
            f"the side filter deleted the other one"
        )


def test_the_trajectory_no_longer_raises_for_alternating_sides(controller):
    """It used to raise 'fewer than two visits', which is what broke the page."""
    controller.set_selected_targets(["Left FDI"])
    figure, _axes, data = controller.generate_figure("trajectory", "t_sici")
    assert figure is not None
    assert data["visit_count"] == 2


def test_a_peripheral_graph_still_narrows_by_side(controller):
    """SR/SD curves are per-side recordings and must keep the side filter."""
    controller.set_selected_targets(["Left FDI"])
    narrowed = controller._get_target_filtered_df("Left FDI")
    rows = narrowed[pd.to_numeric(narrowed["ID"], errors="coerce") == SUBJECT]
    assert len(rows) == 1, (
        "restrict_participant_to_target must still filter the side; only the "
        "hemisphere-overlaying graphs bypass it"
    )


def test_selecting_a_muscle_still_narrows_a_multi_muscle_participant():
    """The bypass must not become a way of ignoring the selection entirely."""
    records = [
        _rec(SUBJECT, "12/05/2026", 96.5, cortex="L", side="R"),
        _rec(SUBJECT, "20/08/2026", 95.2, cortex="R", side="L"),
        _rec(SUBJECT, "12/05/2026", 60.0, cortex="L", side="R", muscle="TA"),
        _rec(SUBJECT, "20/08/2026", 61.0, cortex="R", side="L", muscle="TA"),
    ]
    for pid in (10, 11):
        records += [
            _rec(pid, "01/01/2026", 80.0, cortex="L", side="R"),
            _rec(pid, "01/06/2026", 82.0, cortex="L", side="R"),
        ]
    c = AppController()
    c.set_dataframe(build_mem_dataframe(records))
    dates = c.get_visit_dates(SUBJECT)
    c.set_selected_participant(SUBJECT, dates[-1])
    c.set_selected_targets(["Left FDI"])

    narrowed = c._get_muscle_filtered_df("FDI")
    rows = narrowed[pd.to_numeric(narrowed["ID"], errors="coerce") == SUBJECT]
    assert set(rows["Muscle"]) == {"FDI"}, "the TA rows leaked into an FDI figure"
    assert len(rows) == 2, "both FDI visits must survive"


# ---------------------------------------------------------------------------
# 3. A failed graph must not take the page down
# ---------------------------------------------------------------------------

@pytest.fixture
def panel(controller):
    """A real VisualizationPanel, or a skip when Tk cannot open a display."""
    try:
        import customtkinter as ctk

        from gui.visualization_panel import VisualizationPanel
        root = ctk.CTk()
        root.withdraw()
        widget = VisualizationPanel(
            root, controller, on_next=lambda: None, on_back=lambda: None,
        )
        widget.update()
    except Exception as exc:  # pragma: no cover - headless CI
        pytest.skip(f"no display available: {exc}")
    yield widget
    root.destroy()


FAILED_KEY = "trajectory__t_sici"
OTHER_KEY = "over_time__t_sici"


def test_a_failed_graph_leaves_the_other_checkboxes_working(panel):
    """_rebuild_nav_list is what every checkbox calls; it must not raise."""
    panel._check_vars[FAILED_KEY].set(True)
    panel._rebuild_nav_list()
    panel._on_gen_error(FAILED_KEY, "forced failure")

    panel._check_vars[OTHER_KEY].set(True)
    panel._rebuild_nav_list()          # used to raise TypeError on the sentinel

    assert len(panel._nav_list) == 1
    assert panel._nav_list[0].entry_key == OTHER_KEY


def test_re_ticking_a_failed_graph_does_not_raise(panel):
    """The sentinel stays in the cache, so the crash came back on a re-tick."""
    panel._check_vars[FAILED_KEY].set(True)
    panel._rebuild_nav_list()
    panel._on_gen_error(FAILED_KEY, "forced failure")

    panel._check_vars[FAILED_KEY].set(True)
    panel._rebuild_nav_list()          # used to raise TypeError

    assert FAILED_KEY in panel._figure_cache
    assert panel._figure_cache[FAILED_KEY] is None


def test_navigation_recovers_after_a_failure(panel, controller):
    """After a failure and a working graph, the page must be navigable again."""
    panel._check_vars[FAILED_KEY].set(True)
    panel._rebuild_nav_list()
    panel._on_gen_error(FAILED_KEY, "forced failure")

    panel._check_vars[OTHER_KEY].set(True)
    panel._rebuild_nav_list()
    panel._on_gen_success(OTHER_KEY, controller.generate_figure("over_time", "t_sici"))

    assert not panel._generating
    assert panel._nav_list, "nothing left to navigate"
    assert 0 <= panel._nav_index < len(panel._nav_list)


def test_a_graph_yielding_no_figures_does_not_strand_the_page(panel):
    """_on_gen_success indexed the nav list unguarded, which left it disabled."""
    panel._check_vars[OTHER_KEY].set(True)
    panel._rebuild_nav_list()

    # A result whose figure list is empty: nothing to show, nothing to index.
    panel._on_gen_success(OTHER_KEY, ([], [], {}))

    assert not panel._generating
    assert 0 <= panel._nav_index <= max(0, len(panel._nav_list) - 1)
