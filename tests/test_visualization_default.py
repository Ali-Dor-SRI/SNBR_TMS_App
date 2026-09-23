"""Tests for the Visualization page's "Save as default" tick box.

Quick Start used to build every graph the participant had data for, which is a
lot of them and not the set the lab actually reports. The page now offers the
same "Save as default" box as the other pages, and an automated run replays that
selection instead.

The rule with teeth is what happens when a saved graph does not apply to the
participant Quick Start picked: it is dropped and named in the summary, and if
*none* of the saved graphs apply the run falls back to every available graph
rather than exporting a cover page on its own.
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

from core.user_settings import KEY_SELECTED_GRAPHS, load_defaults, save_defaults
from gui.controller import AppController
from gui.visualization_panel import GRAPH_REGISTRY
from parser.mem_parser import TSICI_ISIS, initialize_record
from processing.df_builder import build_mem_dataframe

SUBJECT = 192
TSICI_OVER_TIME = "over_time__t_sici"
TSICI_TRAJECTORY = "trajectory__t_sici"
SAVE_BOX_TEXT = "Save as default"


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

def _rec(pid, date, value, *, cortex="L", side="R", muscle="FDI"):
    r = initialize_record()
    r.update(
        Study="SNBR", ID=pid, Date=date, Subject_type="Patient",
        Stimulated_cortex=cortex, Muscle=muscle, Recorded_side=side,
        source_file=f"SNBR-{pid:03d}-{date.replace('/', '')}-{cortex}.MEM",
    )
    for isi in TSICI_ISIS:
        r[f"T_SICI_{isi}"] = value
    return r


def _df():
    """T-SICI only, so graphs for every other measure are genuinely unavailable."""
    records = [
        _rec(SUBJECT, "12/05/2026", 96.5),
        _rec(SUBJECT, "20/08/2026", 95.2),
    ]
    for pid in (10, 11):
        records += [
            _rec(pid, "01/01/2026", 80.0),
            _rec(pid, "01/06/2026", 82.0),
        ]
    return build_mem_dataframe(records)


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


@pytest.fixture
def controller():
    c = AppController()
    c.set_dataframe(_df())
    dates = c.get_visit_dates(SUBJECT)
    c.set_selected_participant(SUBJECT, dates[-1])
    return c


@pytest.fixture
def panel(tk_root, controller):
    """A fresh VisualizationPanel on the shared root."""
    from gui.visualization_panel import VisualizationPanel

    widget = VisualizationPanel(
        tk_root, controller, on_next=lambda: None, on_back=lambda: None,
    )
    widget.update()
    yield widget
    widget.destroy()


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


def _checkbox_labelled(widget, text):
    import customtkinter as ctk

    for w in _walk(widget):
        if isinstance(w, ctk.CTkCheckBox) and w.cget("text") == text:
            return w
    return None


def _ticked(panel) -> set[str]:
    return {k for k, v in panel._check_vars.items() if v.get()}


def _no_background_generation(panel, monkeypatch):
    """Keep _handle_next's real save path but skip the figure worker.

    The worker outlives the test's Tk root and then fails calling ``after`` on a
    destroyed widget, which pytest reports against whichever test runs next.
    """
    monkeypatch.setattr(panel, "_generate_missing_worker", lambda *a, **k: None)


# --------------------------------------------------------------------------
# The tick box
# --------------------------------------------------------------------------

def test_the_page_offers_a_save_as_default_tick_box(panel):
    assert _checkbox_labelled(panel, SAVE_BOX_TEXT) is not None, (
        "the Visualization page has no 'Save as default' checkbox"
    )


def test_ticking_it_stores_the_checked_graphs(panel, controller, monkeypatch):
    _no_background_generation(panel, monkeypatch)
    panel._check_vars[TSICI_OVER_TIME].set(True)
    _checkbox_labelled(panel, SAVE_BOX_TEXT).select()

    panel._handle_next()

    assert controller.get_selected_graphs_default() == [TSICI_OVER_TIME]


def test_leaving_it_unticked_keeps_the_previous_selection(
    panel, controller, monkeypatch,
):
    _no_background_generation(panel, monkeypatch)
    save_defaults(**{KEY_SELECTED_GRAPHS: [TSICI_TRAJECTORY]})
    panel._check_vars[TSICI_OVER_TIME].set(True)

    panel._handle_next()

    assert controller.get_selected_graphs_default() == [TSICI_TRAJECTORY]


def test_an_empty_selection_does_not_wipe_the_saved_one(panel, controller):
    """The page refuses an empty selection, so it must not store one either.

    Asserted against a *previous* default rather than against "nothing was
    written": saving an empty list clears the key, which is indistinguishable
    from never having saved it.
    """
    save_defaults(**{KEY_SELECTED_GRAPHS: [TSICI_TRAJECTORY]})
    _checkbox_labelled(panel, SAVE_BOX_TEXT).select()

    panel._handle_next()  # refused — nothing is checked

    assert controller.get_selected_graphs_default() == [TSICI_TRAJECTORY]


def test_a_key_from_an_older_version_is_ignored(controller):
    save_defaults(**{KEY_SELECTED_GRAPHS: ["graph_that_no_longer_exists"]})

    assert controller.get_selected_graphs_default() == []


def test_the_saved_order_follows_the_registry(controller):
    """Saved back-to-front, the report still builds in the page's own order."""
    keys = [e.key for e in GRAPH_REGISTRY][:4]
    save_defaults(**{KEY_SELECTED_GRAPHS: list(reversed(keys))})

    assert controller.get_selected_graphs_default() == keys


# --------------------------------------------------------------------------
# Reopening the page on the saved selection
# --------------------------------------------------------------------------

def test_the_page_reopens_with_the_saved_graphs_ticked(panel, monkeypatch):
    save_defaults(**{KEY_SELECTED_GRAPHS: [TSICI_OVER_TIME]})
    monkeypatch.setattr(panel, "_show_current", lambda: None)

    panel.refresh()

    assert TSICI_OVER_TIME in _ticked(panel)


def test_a_saved_graph_the_visit_cannot_draw_is_not_ticked(
    panel, controller, monkeypatch,
):
    """Availability disables those boxes; a ticked-but-disabled graph is a trap."""
    unavailable = "over_time__t_sicf"
    availability = controller.graph_availability_map(GRAPH_REGISTRY)
    assert not availability[unavailable], "fixture no longer has a gap"
    save_defaults(**{KEY_SELECTED_GRAPHS: [TSICI_OVER_TIME, unavailable]})
    monkeypatch.setattr(panel, "_show_current", lambda: None)

    panel.refresh()

    assert _ticked(panel) == {TSICI_OVER_TIME}


def test_with_nothing_saved_the_page_still_opens_unticked(panel, monkeypatch):
    monkeypatch.setattr(panel, "_show_current", lambda: None)

    panel.refresh()

    assert _ticked(panel) == set()


# --------------------------------------------------------------------------
# What Quick Start then builds (phase 5)
# --------------------------------------------------------------------------

def _run_phase_five(controller):
    return controller.run_default_phases(5, 6)


def test_with_nothing_saved_quick_start_builds_every_available_graph(controller):
    summary = _run_phase_five(controller)

    label = next(e.label for e in GRAPH_REGISTRY if e.key == TSICI_OVER_TIME)
    assert label in summary["graphs"]
    assert len(summary["graphs"]) > 1, "fixture should make several graphs available"
    assert summary["graphs_skipped"] == []


def test_a_saved_selection_narrows_the_report(controller):
    save_defaults(**{KEY_SELECTED_GRAPHS: [TSICI_OVER_TIME]})

    summary = _run_phase_five(controller)

    label = next(e.label for e in GRAPH_REGISTRY if e.key == TSICI_OVER_TIME)
    assert summary["graphs"] == [label]
    assert summary["graphs_fell_back"] is False


def test_a_saved_graph_with_no_data_is_dropped_and_named(controller):
    unavailable = "over_time__t_sicf"
    save_defaults(**{KEY_SELECTED_GRAPHS: [TSICI_OVER_TIME, unavailable]})

    summary = _run_phase_five(controller)

    kept = next(e.label for e in GRAPH_REGISTRY if e.key == TSICI_OVER_TIME)
    dropped = next(e.label for e in GRAPH_REGISTRY if e.key == unavailable)
    assert summary["graphs"] == [kept]
    assert summary["graphs_skipped"] == [dropped]


def test_a_selection_that_fits_nothing_falls_back_to_every_graph(controller):
    """Never export a report that is a cover page and nothing else."""
    save_defaults(**{KEY_SELECTED_GRAPHS: ["over_time__t_sicf"]})

    summary = _run_phase_five(controller)

    assert summary["graphs_fell_back"] is True
    assert len(summary["graphs"]) > 1


# --------------------------------------------------------------------------
# What the run then tells the user
# --------------------------------------------------------------------------

def test_the_summary_names_the_graphs_it_had_to_skip():
    from gui.welcome_panel import graph_summary_lines

    lines = graph_summary_lines({
        "graphs": ["A"], "figure_count": 3, "graphs_skipped": ["B", "C"],
    })

    assert any("B, C" in line for line in lines)


def test_the_summary_says_when_it_fell_back_to_every_graph():
    from gui.welcome_panel import graph_summary_lines

    lines = graph_summary_lines({
        "graphs": ["A"], "figure_count": 3, "graphs_fell_back": True,
    })

    assert any("every available graph" in line for line in lines)


def test_the_summary_stays_quiet_when_nothing_was_skipped():
    from gui.welcome_panel import graph_summary_lines

    assert graph_summary_lines({"graphs": ["A"], "figure_count": 3}) == [
        "1. A", "Total figures: 3",
    ]


# --------------------------------------------------------------------------
# Where the user can see what is saved
# --------------------------------------------------------------------------

def test_the_settings_page_lists_the_saved_graphs(tk_root, controller):
    import customtkinter as ctk

    from gui.settings_panel import SettingsPanel

    save_defaults(**{KEY_SELECTED_GRAPHS: [TSICI_OVER_TIME]})
    panel = SettingsPanel(tk_root, controller, on_back=lambda: None)
    try:
        panel.refresh()

        texts = [
            w.cget("text") for w in _walk(panel)
            if isinstance(w, ctk.CTkLabel)
        ]
        label = next(e.label for e in GRAPH_REGISTRY if e.key == TSICI_OVER_TIME)
        assert any(t.endswith(label) for t in texts)
        assert any("saved selection" in t for t in texts)
        # The whole registry must no longer be listed as if it were the default.
        assert not any("all available" in t for t in texts)
    finally:
        panel.destroy()
