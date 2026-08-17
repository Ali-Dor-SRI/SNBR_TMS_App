"""
Raw-value caption helpers for PDF report visualizations.

Each plot function in :mod:`processing._v1_visualization` returns a
``plot_data`` dict that already contains the numeric summaries that should
appear beneath the figure in the report (patient value, control mean, ALS
mean, latest-visit value, etc.).  This module turns those dicts into the
short text lines drawn under each image in the composed PDF.

The same dispatcher is used by both:

* :mod:`reports.report_builder` (CLI / scripted report pipeline)
* :mod:`gui.visualization_panel` (GUI report pipeline), so that captions
  appear in *any* exported PDF — not only when
  :func:`report_builder.build_report_figures` is the origin.

Public API
----------
format_value(value)                                       -> str
grouped_caption(plot_data, metric_label=None)             -> str | None
latest_visit_caption(visit_summary, metric_label=None)    -> str | None
profile_caption(plot_data, metric_label=None)             -> str | None
csp_profile_caption(plot_data)                            -> str | None
caption_for(graph_type, measure, plot_data, figure_key=None) -> str | None
"""

from __future__ import annotations

import math
from typing import Any


# ---------------------------------------------------------------------------
# Value formatting
# ---------------------------------------------------------------------------

def format_value(value: Any) -> str:
    """Format a numeric value for the caption line, handling NaN / None."""
    if value is None:
        return "N/A"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(v):
        return "N/A"
    return f"{v:.2f}"


# ---------------------------------------------------------------------------
# Individual caption builders
# ---------------------------------------------------------------------------

def grouped_caption(plot_data: dict, metric_label: str | None = None) -> str | None:
    """Caption for single-scalar cohort comparison plots.

    Expected ``plot_data`` keys: ``highlight_value``, ``patient_mean``,
    ``control_mean``, ``patient_rows``, ``control_rows``, ``value_column``.
    """
    if not isinstance(plot_data, dict):
        return None
    highlight = plot_data.get("highlight_value")
    patient_mean = plot_data.get("patient_mean")
    control_mean = plot_data.get("control_mean")
    if highlight is None and patient_mean is None and control_mean is None:
        return None
    patient_rows = plot_data.get("patient_rows")
    control_rows = plot_data.get("control_rows")
    n_patients = len(patient_rows) if patient_rows is not None else 0
    n_controls = len(control_rows) if control_rows is not None else 0
    label = metric_label or plot_data.get("value_column") or ""
    prefix = f"{label} — " if label else ""
    return (
        f"{prefix}Patient: {format_value(highlight)}   |   "
        f"Controls (n={n_controls}): {format_value(control_mean)}   |   "
        f"ALS (n={n_patients}): {format_value(patient_mean)}"
    )


def latest_visit_caption(visit_summary, metric_label: str | None = None) -> str | None:
    """Caption for over-time plots: latest-visit date + value."""
    if visit_summary is None:
        return None
    try:
        empty = getattr(visit_summary, "empty", True)
    except Exception:
        return None
    if empty:
        return None
    last = visit_summary.iloc[-1]
    date_text = str(last.get("visit_label", last.get("visit_date", "")))
    value = last.get("visit_value")
    prefix = f"{metric_label} — " if metric_label else ""
    return f"{prefix}Latest visit ({date_text}): {format_value(value)}"


def profile_caption(plot_data: dict, metric_label: str | None = None) -> str | None:
    """Caption for waveform profile plots: participant's profile mean."""
    if not isinstance(plot_data, dict):
        return None
    sel = plot_data.get("selected_rows")
    if sel is None or getattr(sel, "empty", True):
        return None
    value_column = plot_data.get("value_column")
    if value_column and value_column in sel.columns:
        try:
            mean_val = sel[value_column].mean()
        except Exception:
            return None
        prefix = f"{metric_label} — " if metric_label else ""
        return f"{prefix}Patient profile mean: {format_value(mean_val)}"
    return None


def csp_profile_caption(plot_data: dict) -> str | None:
    """Caption for the CSP profile curve: participant vs control vs ALS means."""
    if not isinstance(plot_data, dict):
        return None
    sel = plot_data.get("selected_profile")
    if sel is None or getattr(sel, "empty", True) or "value" not in getattr(sel, "columns", []):
        return None
    patient_val = sel["value"].mean()
    parts = [f"Patient mean: {format_value(patient_val)}"]
    ctl = plot_data.get("control_profile")
    pat = plot_data.get("patient_profile")
    if ctl is not None and not getattr(ctl, "empty", True) and "value" in ctl.columns:
        parts.append(f"Controls mean: {format_value(ctl['value'].mean())}")
    if pat is not None and not getattr(pat, "empty", True) and "value" in pat.columns:
        parts.append(f"ALS mean: {format_value(pat['value'].mean())}")
    return "CSP profile — " + "   |   ".join(parts)


# ---------------------------------------------------------------------------
# Graph-type dispatcher
# ---------------------------------------------------------------------------

_GROUPED_TYPES = {
    "grouped", "grouped_graph", "cohort", "group_comparison", "comparison",
    "rmt_grouped", "rmt_grouped_graph", "rmt_matched",
    "rmt_comparison", "rmt_group_comparison", "rmt_overall",
}

_OVER_TIME_TYPES = {
    "over_time", "participant_over_time", "timeline", "longitudinal",
    "rmt_over_time", "participant_rmt_over_time",
    "csp_over_time",
}

_PROFILE_TYPES = {"profile", "measure_profile", "csp_profile"}

_TRAJECTORY_TYPES = {"trajectory", "measure_trajectory", "cohort_trajectory"}


def _measure_display_label(measure: str | None) -> str:
    """Best-effort human label for a measure key."""
    if measure is None:
        return ""
    if measure == "csp":
        try:
            from processing.visualizer import CSP_MEASURE_LABEL  # noqa: WPS433
            return CSP_MEASURE_LABEL
        except Exception:
            return "CSP"
    try:
        from processing.visualizer import waveform_measure_config  # noqa: WPS433
        return waveform_measure_config(measure)["label"]
    except Exception:
        return str(measure).upper()


def caption_for(
    graph_type: str,
    measure: str | None,
    plot_data: Any,
    figure_key: str | None = None,
) -> str | None:
    """Return a caption line for the given graph, or ``None`` if inapplicable.

    Parameters
    ----------
    graph_type : str
        The graph-type identifier used by the visualization registry
        (e.g. ``"grouped"``, ``"over_time"``, ``"rmt_grouped"``).
    measure : str or None
        Measure key (``"t_sici"``, ``"a_sici"``, ``"a_sicf"``, ``"t_sicf"``,
        ``"csp"``) or ``None`` for RMT / visit views.
    plot_data : dict
        The third element of a plot-function return tuple.
    figure_key : str or None
        For multi-figure results (RMT, CSP at multiple levels), the key of
        the specific sub-figure being captioned.  ``None`` for single-figure
        returns.
    """
    if not isinstance(plot_data, dict):
        return None

    norm_type = str(graph_type).strip().lower().replace("-", "_").replace(" ", "_")
    metric_label = _measure_display_label(measure)

    # --- Stimulus-Response (peripheral recruitment scatter) ---
    if norm_type == "stimulus_response":
        max_cmap = plot_data.get("sr_max_cmap_1ms")
        if max_cmap is None:
            return None
        point_count = plot_data.get("sr_point_count")
        base = f"Max CMAP at 1 ms: {format_value(max_cmap)} mV"
        return f"{base}   |   {int(point_count)} points" if point_count else base

    # --- Strength-duration curve (participant only) ---
    if norm_type == "strength_duration_curve":
        rheobase = plot_data.get("rheobase_mA")
        tau = plot_data.get("tau_sd_ms")
        if rheobase is None and tau is None:
            return None
        point_count = plot_data.get("sd_point_count")
        base = (
            f"Rheobase: {format_value(rheobase)} mA   |   "
            f"τSD: {format_value(tau)} ms"
        )
        return f"{base}   |   {int(point_count)} points" if point_count else base

    # --- Charge-duration (Weiss linearization) ---
    if norm_type == "charge_duration_weiss":
        rheobase = plot_data.get("rheobase_mA")
        tau = plot_data.get("tau_sd_ms")
        if rheobase is None and tau is None:
            return None
        r_squared = plot_data.get("r_squared")
        point_count = plot_data.get("sd_point_count")
        parts = [f"Slope (rheobase): {format_value(rheobase)} mA"]
        if tau is not None:
            parts.append(f"x-intercept: {format_value(-tau)} ms")
        if r_squared is not None:
            parts.append(f"R² = {r_squared:.3f}")
        if point_count:
            parts.append(f"{int(point_count)} points")
        return "   |   ".join(parts)

    # --- Grouped / cohort comparison ---
    # The violin group-comparison plots now render per-column summary stats
    # (n, mean ± sd, per-cortex values) directly below each x-tick label in
    # matplotlib, so the separate caption line below the figure is redundant
    # and was duplicating the values. Return None here to suppress it.
    if norm_type in _GROUPED_TYPES:
        return None

    # --- Over-time ---
    if norm_type in _OVER_TIME_TYPES:
        # Multi-figure over-time plots (RMT columns, CSP levels) key summaries by column.
        if figure_key:
            summaries = plot_data.get("visit_summaries") or {}
            sub = summaries.get(figure_key)
            if sub is not None:
                return latest_visit_caption(sub, metric_label=figure_key)
        summary = plot_data.get("visit_summary")
        if summary is not None:
            return latest_visit_caption(
                summary,
                metric_label=plot_data.get("value_column") or metric_label,
            )
        return None

    # --- Cohort trajectory (repeated-visit line vs same-type cohort) ---
    if norm_type in _TRAJECTORY_TYPES:
        summary = plot_data.get("visit_summary")
        base = (
            latest_visit_caption(summary, metric_label=metric_label)
            if summary is not None else None
        )
        n = plot_data.get("cohort_size")
        visits = plot_data.get("visit_count")
        extra = []
        if visits:
            extra.append(f"{int(visits)} visits")
        if n:
            extra.append(f"cohort n={int(n)}")
        if base and extra:
            return f"{base}   |   " + "   |   ".join(extra)
        return base

    # --- Profile ---
    if norm_type in _PROFILE_TYPES:
        if measure == "csp":
            return csp_profile_caption(plot_data)
        return profile_caption(plot_data, metric_label=metric_label)

    # Visit table, visit timeline, visit profiles → no caption.
    return None
