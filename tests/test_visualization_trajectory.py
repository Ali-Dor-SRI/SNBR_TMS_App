"""Tests for the T-SICI cohort trajectory graph.

Covers the plotting function, the ``plot_mem_graph`` dispatch, the controller
availability gate (only participants with >= 2 visits), and the report path
(default section + <2-visit gating).
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser.mem_parser import TSICI_ISIS, initialize_record
from processing.df_builder import build_mem_dataframe
from processing._v1_visualization import (
    plot_mem_graph,
    plot_participant_measure_trajectory,
)
from reports.report_builder import build_report_figures, supported_report_sections
from gui.controller import AppController
from gui.visualization_panel import GRAPH_REGISTRY

_RED = "#C0392B"


def _rec(pid, date, avg, subject_type="Patient", cortex="L"):
    """One MEM row whose T_SICI_avg will recompute to *avg*."""
    r = initialize_record()
    r.update(
        ID=pid, Date=date, Subject_type=subject_type, Stimulated_cortex=cortex,
        source_file=f"SNBR-{pid}-{date.replace('/', '')}.MEM",
    )
    for isi in TSICI_ISIS:
        r[f"T_SICI_{isi}"] = avg
    return r


# Patients 1-4 have three visits; patient 5 has a single visit; participant 6
# is a control with two visits (must be excluded from a patient's cohort).
_VISIT_DATES = ["01/01/2026", "01/02/2026", "01/03/2026"]
_PATIENT_TRACES = {
    1: [95.0, 90.0, 85.0],
    2: [98.0, 96.0, 94.0],
    3: [92.0, 88.0, 80.0],
    4: [100.0, 97.0, 93.0],
}


def _df():
    records = []
    for pid, vals in _PATIENT_TRACES.items():
        for date, v in zip(_VISIT_DATES, vals):
            records.append(_rec(pid, date, v))
    records.append(_rec(5, "01/01/2026", 90.0))                     # single visit
    records.append(_rec(6, "01/01/2026", 70.0, subject_type="Control"))
    records.append(_rec(6, "01/02/2026", 72.0, subject_type="Control"))
    return build_mem_dataframe(records)


def test_trajectory_returns_figure_and_cohort_stats():
    df = _df()
    fig, ax, data = plot_participant_measure_trajectory(
        measure="t_sici", participant_id=1, data_df=df, show=False,
    )
    assert isinstance(fig, Figure)
    assert data["subject_type"] == "Patient"
    assert data["visit_count"] == 3
    # Cohort = the four patients with >= 2 visits; the 1-visit patient and the
    # control are excluded.
    assert data["cohort_size"] == 4
    assert 5 not in data["cohort_ids"]
    assert 6 not in data["cohort_ids"]
    # A mean is defined at each of the three visit numbers.
    assert set(data["cohort_mean_by_visit"]) == {1, 2, 3}
    # The selected participant's line is drawn in red.
    assert any(line.get_color() == _RED for line in ax.lines)
    plt_close(fig)


def test_trajectory_requires_repeated_visits():
    df = _df()
    with pytest.raises(ValueError):
        plot_participant_measure_trajectory(
            measure="t_sici", participant_id=5, data_df=df, show=False,
        )


def test_dispatch_via_plot_mem_graph():
    df = _df()
    fig, _ax, data = plot_mem_graph(
        graph_type="trajectory", measure="t_sici", participant_id=2, data_df=df,
        show=False,
    )
    assert isinstance(fig, Figure)
    assert data["participant_id"] == 2
    plt_close(fig)


def _controller(df, pid, date):
    c = AppController()
    c.set_dataframe(df)
    c.set_selected_participant(pid, date)
    return c


def test_availability_gated_on_repeat_visits():
    df = _df()
    c = _controller(df, 1, datetime(2026, 1, 1))
    avail = c.graph_availability_map(GRAPH_REGISTRY)
    assert avail["trajectory__t_sici"] is True
    assert c.has_data_for_graph("trajectory", "t_sici") is True

    # A single-visit participant must have the trajectory greyed out.
    c.set_selected_participant(5, datetime(2026, 1, 1))
    avail = c.graph_availability_map(GRAPH_REGISTRY)
    assert avail["trajectory__t_sici"] is False
    assert c.has_data_for_graph("trajectory", "t_sici") is False


def test_controller_generate_figure():
    df = _df()
    c = _controller(df, 1, datetime(2026, 1, 1))
    figs, _axes, data = c.generate_figure("trajectory", "t_sici")
    assert isinstance(figs, Figure)
    assert data["cohort_size"] == 4
    plt_close(figs)


def test_report_section_registered_and_built():
    df = _df()
    assert "t_sici_trajectory" in supported_report_sections()
    items = build_report_figures(1, df, included_sections="t_sici_trajectory")
    assert any(getattr(it, "section_key", None) == "t_sici_trajectory" for it in items)


def test_report_section_omitted_for_single_visit():
    df = _df()
    items = build_report_figures(5, df, included_sections="t_sici_trajectory")
    assert not any(
        getattr(it, "section_key", None) == "t_sici_trajectory" for it in items
    )


def plt_close(fig):
    import matplotlib.pyplot as plt
    plt.close(fig)
