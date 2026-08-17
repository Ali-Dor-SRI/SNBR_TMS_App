"""
Report section definitions and figure generation for participant MEM reports.

This module defines what sections a report can contain, builds the summary
page, and generates per-section matplotlib figures.  It does **not** assemble
those figures into a PDF — that responsibility belongs to
:mod:`reports.pdf_renderer`.

Public API
----------
supported_report_sections()           -> list[str]
normalize_report_sections(included)   -> list[str]
build_report_figures(participant_id, data_df, included_sections, ...)
                                      -> list[ReportItem]
"""

from __future__ import annotations

import pandas as pd

from parser.recording_target import MUSCLE_COLUMN, SIDE_COLUMN, target_label
from processing.df_builder import restrict_participant_to_target, target_labels_in
from reports.captions import (
    caption_for,
    csp_profile_caption,
    grouped_caption,
    latest_visit_caption,
)
from reports.pdf_layout import ReportItem, generation_date_string
from processing.visualizer import (
    CSP_MEASURE_LABEL,
    VISIT_TABLE_COLUMN_WIDTHS,
    apply_visit_summary_table_layout,
    build_participant_visit_test_summary,
    build_participant_visit_timeline_data,
    draw_participant_visit_timeline_axis,
    format_participant_label,
    load_mem_dataframe,
    plot_csp_grouped_graph,
    plot_csp_profile,
    plot_measure_grouped_graph,
    plot_participant_csp_over_time,
    plot_participant_csp_visit_profiles,
    plot_participant_measure_over_time,
    plot_participant_measure_trajectory,
    plot_participant_measure_visit_profiles,
    plot_participant_rmt_over_time,
    plot_participant_visit_test_table,
    plot_rmt_grouped_graph,
    normalize_mem_date,
    resolve_participant_context,
    waveform_measure_config,
)
from processing.figure_style import enlarge_axes_fonts

# Sections whose figures are tables (CMAP / MUNIX / visit table) or the
# letterhead summary. Their layouts are hand-tuned, so the axis-text
# enlargement (processing.figure_style) skips them.
_SKIP_FONT_ENLARGE = frozenset({"summary", "visit_table", "cmap_table", "munix_table"})

# ---------------------------------------------------------------------------
# Section catalogue
# ---------------------------------------------------------------------------

WAVEFORM_REPORT_MEASURES = ["t_sici", "a_sici", "a_sicf", "t_sicf"]

CSP_REPORT_SECTIONS = [
    "csp_profile",
    "csp_overall",
    "csp_age_matched",
    "csp_sex_matched",
    "csp_sex_age_matched",
    "csp_over_time",
    "csp_visit_profiles",
]

ALL_REPORT_SECTION_ALIASES = {"everything", "all", "all_sections", "full_report"}

_LONGITUDINAL_SUFFIXES = ("_over_time", "_visit_profiles", "_trajectory")

_SECTIONS_REQUIRING_DATES = {"visit_table"}

_DATE_DEPENDENT_SUFFIXES = (
    "_over_time", "_visit_profiles", "_trajectory",
    "_overall", "_age_matched", "_sex_matched", "_sex_age_matched",
    "_profile",
)

_WAVEFORM_SECTION_SUFFIXES = (
    "_overall",
    "_age_matched",
    "_sex_matched",
    "_sex_age_matched",
    "_over_time",
    "_visit_profiles",
)


def _waveform_sections(measure: str) -> list[str]:
    return [f"{measure}{suffix}" for suffix in _WAVEFORM_SECTION_SUFFIXES]


DEFAULT_REPORT_SECTIONS = [
    "summary",
    "visit_table",
    "cmap_table",
    "munix_table",
    "strength_duration_curve",
    "charge_duration_weiss",
    *_waveform_sections("t_sici"),
    "t_sici_trajectory",
    "rmt_over_time",
]


def supported_report_sections() -> list[str]:
    """Return all supported report-section keys in canonical order.

    Order: summary + visit-overview tables, then every t-SICI section, then
    every RMT section, then the remaining waveform measures grouped by
    measure (a_sici → a_sicf → t_sicf), then CSP last.
    """
    keys = [
        "summary",
        "visit_table",
        "cmap_table",
        "munix_table",
        "strength_duration_curve",
        "charge_duration_weiss",
    ]
    keys.extend(_waveform_sections("t_sici"))
    keys.append("t_sici_trajectory")
    keys.extend([
        "rmt_over_time",
        "rmt_overall",
        "rmt_age_matched",
        "rmt_sex_matched",
        "rmt_sex_age_matched",
    ])
    for measure in ("a_sici", "a_sicf", "t_sicf"):
        keys.extend(_waveform_sections(measure))
    keys.extend(CSP_REPORT_SECTIONS)
    return keys


def requests_all_report_sections(included_sections=None) -> bool:
    """Return whether the caller asked for the full report via an alias."""
    if included_sections is None:
        return False
    raw = (
        included_sections.split(",")
        if isinstance(included_sections, str)
        else list(included_sections)
    )
    tokens = [
        str(t).strip().lower().replace("-", "_").replace(" ", "_")
        for t in raw if str(t).strip()
    ]
    return any(t in ALL_REPORT_SECTION_ALIASES for t in tokens)


def normalize_report_sections(included_sections=None) -> list[str]:
    """Validate and deduplicate the requested section list."""
    if included_sections is None:
        requested = list(DEFAULT_REPORT_SECTIONS)
    elif isinstance(included_sections, str):
        requested = [
            t.strip().lower().replace("-", "_").replace(" ", "_")
            for t in included_sections.split(",") if t.strip()
        ]
    else:
        requested = [
            str(t).strip().lower().replace("-", "_").replace(" ", "_")
            for t in included_sections if str(t).strip()
        ]

    if not requested:
        raise ValueError("Report section list must not be empty.")

    supported = supported_report_sections()
    if any(s in ALL_REPORT_SECTION_ALIASES for s in requested):
        return list(supported)

    bad = [s for s in requested if s not in supported]
    if bad:
        raise ValueError(
            f"Unsupported section(s): {', '.join(bad)}. "
            f"Supported: {', '.join(supported)}"
        )

    seen: set[str] = set()
    deduped: list[str] = []
    for s in requested:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    return deduped


# ---------------------------------------------------------------------------
# Summary-page helpers
# ---------------------------------------------------------------------------

def _format_numeric_demographic(value) -> str:
    if pd.isna(value):
        return "Unknown"
    v = float(value)
    return str(int(v)) if v.is_integer() else f"{v:.1f}"


def _latest_non_missing_age(rows: pd.DataFrame) -> str:
    ages = pd.to_numeric(rows["Age"], errors="coerce").dropna()
    return _format_numeric_demographic(ages.iloc[-1]) if not ages.empty else "Unknown"


def _latest_non_missing_sex(rows: pd.DataFrame) -> str:
    vals = (
        rows["Sex"].astype("string").fillna("").str.strip()
        .replace("", pd.NA).dropna()
    )
    return str(vals.iloc[-1]).upper() if not vals.empty else "Unknown"


def _latest_non_missing_study(rows: pd.DataFrame) -> str:
    if "Study" not in rows.columns:
        return "Unknown"
    vals = (
        rows["Study"].astype("string").fillna("").str.strip()
        .replace("", pd.NA).dropna()
    )
    return str(vals.iloc[-1]) if not vals.empty else "Unknown"


def _recording_targets_text(rows: pd.DataFrame) -> str:
    """List the muscles/sides these rows were recorded from, e.g. ``"Right FDI"``.

    Always shown on the report's title page. When a visit recorded only one
    target this is the *only* place the muscle is named — the individual plot
    titles stay uncluttered — so it must not be omitted just because there is
    nothing to disambiguate.
    """
    if MUSCLE_COLUMN not in rows.columns:
        return "Unknown"
    labels: list[str] = []
    for _, row in rows.iterrows():
        label = target_label(row[MUSCLE_COLUMN], row.get(SIDE_COLUMN))
        if label and label not in labels:
            labels.append(label)
    return ", ".join(labels) if labels else "Unknown"


def _latest_non_missing_stimulated_cortex(rows: pd.DataFrame) -> str:
    if "Stimulated_cortex" not in rows.columns:
        return "Unknown"
    vals = (
        rows["Stimulated_cortex"].astype("string").fillna("").str.strip()
        .replace("", pd.NA).dropna()
    )
    if vals.empty:
        return "Unknown"
    unique = vals.unique().tolist()
    return " & ".join(unique) if len(unique) > 1 else str(unique[0])


_SUBJECT_TYPE_DISPLAY = {
    "Patient": "ALS",
    "Control": "Healthy Control",
}


def _latest_non_missing_subject_type(rows: pd.DataFrame) -> str:
    vals = (
        rows["Subject_type"].astype("string").fillna("").str.strip()
        .replace("", pd.NA).dropna()
    )
    if vals.empty:
        return "Unknown"
    raw = str(vals.iloc[-1])
    return _SUBJECT_TYPE_DISPLAY.get(raw, raw)


def _build_visit_table_rows(visit_summary: pd.DataFrame) -> list[list[str]]:
    table_rows = []
    for row in visit_summary.itertuples(index=False):
        elapsed = row.days_since_previous_visit
        elapsed_text = "N/A" if pd.isna(elapsed) else str(int(elapsed))
        sides = str(getattr(row, "sides_tested", "N/A"))
        table_rows.append([
            f"Visit {int(row.visit_number)}",
            str(row.visit_label),
            elapsed_text,
            str(int(row.mem_file_count)),
            sides,
            str(getattr(row, "tests_present_wrapped_text", row.tests_present_text)),
        ])
    return table_rows


def _build_summary_figure(
    participant_label, participant_rows, visit_summary, visit_timeline,
    anchor_date_text, all_participant_rows=None,
):
    """Build the page-1 figure: demographics block + visit table.

    *all_participant_rows* is the participant's rows before any
    recording-target restriction, so the "Recorded muscle(s)" field names every
    muscle even when the report's plots cover one of them.

    The letterhead banner is rendered above this figure by
    :func:`reports.pdf_layout.build_letterhead_banner_page`.  Fonts are
    intentionally compact so both the demographic fields and the visit
    table fit together below the banner on US-Letter portrait page 1.
    """
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(7.7, 8.2))
    grid = fig.add_gridspec(2, 1, height_ratios=[0.85, 1.15], hspace=0.18)
    info_ax = fig.add_subplot(grid[0])
    table_ax = fig.add_subplot(grid[1])
    info_ax.axis("off")
    table_ax.axis("off")

    study = _latest_non_missing_study(participant_rows)
    age = _latest_non_missing_age(participant_rows)
    sex = _latest_non_missing_sex(participant_rows)
    subject_type = _latest_non_missing_subject_type(participant_rows)
    cortex = _latest_non_missing_stimulated_cortex(participant_rows)
    target_rows = (
        participant_rows if all_participant_rows is None else all_participant_rows
    )
    visit_count = len(visit_timeline) if visit_timeline is not None else 0

    info_ax.text(
        0.0, 0.99, f"{participant_label} | Participant MEM report",
        fontsize=14, fontweight="bold", color="#1F2A36",
        ha="left", va="top", transform=info_ax.transAxes,
    )

    field_rows = [
        ("Study", study),
        ("Patient ID", participant_label),
        ("Patient type", subject_type),
        ("Age", age),
        ("Sex", sex),
        ("Stimulated Cortex", cortex),
        ("Recorded muscle(s)", _recording_targets_text(target_rows)),
        ("Visit count", str(visit_count)),
        ("Comparison visit", anchor_date_text),
        ("Date generated", generation_date_string()),
    ]

    top = 0.82
    line_step = 0.088
    label_x = 0.0
    value_x = 0.32
    for i, (label, value) in enumerate(field_rows):
        y = top - i * line_step
        info_ax.text(
            label_x, y, f"{label}:",
            fontsize=10, fontweight="bold", color="#1F2A36",
            ha="left", va="top", transform=info_ax.transAxes,
        )
        info_ax.text(
            value_x, y, str(value),
            fontsize=10, color="#36495C",
            ha="left", va="top", transform=info_ax.transAxes,
        )

    table_ax.text(
        0.0, 1.0, f"{participant_label} | Visit summary and tests present",
        fontsize=11, fontweight="bold", color="#1F2A36",
        ha="left", va="top", transform=table_ax.transAxes,
    )

    if visit_summary is not None and not visit_summary.empty:
        tbl = table_ax.table(
            cellText=_build_visit_table_rows(visit_summary),
            colLabels=["Visit", "Date", "Days Since Previous", "MEM Files", "Sides Tested", "Tests Present"],
            cellLoc="left", colLoc="left",
            colWidths=VISIT_TABLE_COLUMN_WIDTHS,
            bbox=(0.0, 0.10, 1.0, 0.84),
        )
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(7.5)
        for (ri, _), cell in tbl.get_celld().items():
            cell.set_edgecolor("#D8E0EA")
            cell.set_linewidth(0.8)
            if ri == 0:
                cell.set_facecolor("#E9EEF4")
                cell.set_text_props(weight="bold", color="#223142")
            else:
                cell.set_facecolor("#FFFFFF")
        apply_visit_summary_table_layout(
            tbl,
            row_line_counts=visit_summary["tests_present_line_count"].tolist(),
            bbox_height=0.84,
        )

        table_ax.text(
            0.0, 0.04,
            "Visit rows represent unique visit dates. Same-day MEM files are "
            "grouped into one visit, and all extracted tests present that day are listed.",
            fontsize=7.0, color="#5A6B7C",
            ha="left", va="bottom", transform=table_ax.transAxes,
        )

    fig.subplots_adjust(top=0.97, bottom=0.04, left=0.06, right=0.97)
    return fig


def _build_visit_overview_figure(
    participant_label, visit_summary, visit_timeline,
):
    """Build the visit timeline figure for the ``visit_table`` section.

    The visit table itself is rendered on page 1 alongside the participant
    demographics (see :func:`_build_summary_figure`).  This figure now
    carries only the visit timeline so it composes naturally inside the
    4-per-page body grid that follows.
    """
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(7.7, 4.0))
    timeline_ax = fig.add_subplot(111)
    draw_participant_visit_timeline_axis(
        axis=timeline_ax, visit_timeline=visit_timeline,
        participant_label=participant_label,
        title=f"{participant_label} | Visit timeline",
    )
    fig.subplots_adjust(top=0.92, bottom=0.14, left=0.08, right=0.97)
    return fig


def _build_summary_figure_no_dates(participant_label, participant_rows):
    """Build a summary page when no valid visit dates are available."""
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(7.7, 7.8))
    ax = fig.add_subplot(111)
    ax.axis("off")

    study = _latest_non_missing_study(participant_rows)
    age = _latest_non_missing_age(participant_rows)
    sex = _latest_non_missing_sex(participant_rows)
    subject_type = _latest_non_missing_subject_type(participant_rows)
    cortex = _latest_non_missing_stimulated_cortex(participant_rows)

    ax.text(
        0.0, 0.98, f"{participant_label} | Participant MEM report",
        fontsize=16, fontweight="bold", color="#1F2A36",
        ha="left", va="top", transform=ax.transAxes,
    )
    ax.text(
        0.0, 0.85,
        f"Study: {study}   |   Patient ID: {participant_label}   |   "
        f"Patient type: {subject_type}\n"
        f"Age: {age}   |   Sex: {sex}   |   Stimulated Cortex: {cortex}\n"
        f"Visit count: 0   |   Latest visit used for comparisons: No valid dates\n"
        f"Date generated: {generation_date_string()}",
        fontsize=10.5, color="#36495C", linespacing=1.5,
        ha="left", va="top", transform=ax.transAxes,
    )
    ax.text(
        0.0, 0.60,
        "No valid visit dates were found for this participant.\n"
        "Visit table, timeline, longitudinal, and comparison sections\n"
        "have been omitted.",
        fontsize=11, color="#8B4513",
        ha="left", va="top", transform=ax.transAxes,
    )
    fig.subplots_adjust(top=0.96, bottom=0.07, left=0.06, right=0.97)
    return fig


def _build_message_figure(title: str, message: str):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8.4, 5.8))
    ax.axis("off")
    ax.text(0.02, 0.92, title, fontsize=16, fontweight="bold",
            color="#1F2A36", ha="left", va="top", transform=ax.transAxes)
    ax.text(0.02, 0.72, message, fontsize=12, color="#36495C",
            ha="left", va="top", wrap=True, transform=ax.transAxes)
    fig.tight_layout()
    return fig


def _extract_cmap_rows_for_visit(
    participant_rows: pd.DataFrame,
    visit_date: str | None,
) -> list[dict]:
    """Return the list of CMAP row-dicts for the given visit, or [].

    Looks at the ``CMAP_table`` column (JSON string). When *visit_date* is
    given, only rows whose ``Date`` matches (normalized ``dd/mm/YYYY``) are
    considered; otherwise the most-recent non-null entry wins. Multiple files
    for the same visit concatenate in source order.
    """
    import json

    if "CMAP_table" not in participant_rows.columns:
        return []

    rows = participant_rows.copy()
    if visit_date is not None and "Date" in rows.columns:
        rows = rows[rows["Date"].astype("string").fillna("").str.strip() == visit_date]
    rows = rows[rows["CMAP_table"].notna()]
    if rows.empty:
        return []

    # When two MEM rows (e.g. L + R hemispheres) share the same visit, the
    # same CMAP JSON is written onto both. De-duplicate on the raw payload so
    # the report table doesn't show doubled entries.
    seen: set[str] = set()
    out: list[dict] = []
    for raw in rows["CMAP_table"].tolist():
        s = str(raw).strip()
        if not s or s.lower() == "nan":
            continue
        if s in seen:
            continue
        seen.add(s)
        try:
            parsed = json.loads(s)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, list):
            out.extend(p for p in parsed if isinstance(p, dict))
    return out


def _extract_munix_rows_for_visit(
    participant_rows: pd.DataFrame,
    visit_date: str | None,
) -> list[dict]:
    """Return the list of MUNIX row-dicts for the given visit, or []."""
    import json

    if "MUNIX_table" not in participant_rows.columns:
        return []

    rows = participant_rows.copy()
    if visit_date is not None and "Date" in rows.columns:
        rows = rows[rows["Date"].astype("string").fillna("").str.strip() == visit_date]
    rows = rows[rows["MUNIX_table"].notna()]
    if rows.empty:
        return []

    seen: set[str] = set()
    out: list[dict] = []
    for raw in rows["MUNIX_table"].tolist():
        s = str(raw).strip()
        if not s or s.lower() == "nan":
            continue
        if s in seen:  # de-duplicate when two hemisphere rows carry the same payload
            continue
        seen.add(s)
        try:
            parsed = json.loads(s)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, list):
            out.extend(p for p in parsed if isinstance(p, dict))
    return out


def _format_number(value, fmt: str = "{:.2f}") -> str:
    try:
        if value is None:
            return ""
        fv = float(value)
        if fv != fv:  # NaN
            return ""
        return fmt.format(fv)
    except (TypeError, ValueError):
        return str(value)


def _visit_subtitle(visit_date: str | None, target_label: str | None = None) -> str:
    """Build the trailing ``" | 12/01/2026 | Right FDI"`` fragment of a title.

    *target_label* is supplied only when the visit recorded more than one
    muscle/side; with a single recording it stays empty and the muscle is
    stated once on the report's title page instead.
    """
    return "".join(f" | {p}" for p in (visit_date, target_label) if p)


def _build_cmap_table_figure(
    participant_label: str,
    cmap_rows: list[dict],
    visit_date: str | None,
    target_label: str | None = None,
):
    """Render the CMAP table page for one participant visit."""
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(7.7, 5.2))
    ax = fig.add_subplot(111)
    ax.axis("off")

    subtitle = _visit_subtitle(visit_date, target_label)
    ax.text(
        0.0, 0.98,
        f"{participant_label} | Motor nerve conduction study{subtitle}",
        fontsize=14, fontweight="bold", color="#1F2A36",
        ha="left", va="top", transform=ax.transAxes,
    )

    table_rows = [
        [
            str(r.get("nerve_site", "") or ""),
            str(r.get("muscle", "") or ""),
            _format_number(r.get("latency_ms")),
            _format_number(r.get("amplitude_mv"), "{:.1f}"),
        ]
        for r in cmap_rows
    ]

    tbl = ax.table(
        cellText=table_rows,
        colLabels=["Nerve / Site", "Muscle", "Latency (ms)", "Amplitude (mV)"],
        cellLoc="left", colLoc="left",
        colWidths=[0.46, 0.16, 0.18, 0.20],
        bbox=(0.0, 0.05, 1.0, 0.82),
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(10)
    for (ri, _), cell in tbl.get_celld().items():
        cell.set_edgecolor("#D8E0EA")
        cell.set_linewidth(0.8)
        if ri == 0:
            cell.set_facecolor("#E9EEF4")
            cell.set_text_props(weight="bold", color="#223142")
        else:
            cell.set_facecolor("#FFFFFF")

    fig.subplots_adjust(top=0.96, bottom=0.05, left=0.06, right=0.97)
    return fig


def _build_munix_table_figure(
    participant_label: str,
    munix_rows: list[dict],
    visit_date: str | None,
    target_label: str | None = None,
):
    """Render the MUNIX table page for one participant visit.

    Columns: ``# SIP``, ``A``, ``Alpha``, ``MUNIX``, ``MUSIX``.
    """
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(7.7, 4.2))
    ax = fig.add_subplot(111)
    ax.axis("off")

    subtitle = _visit_subtitle(visit_date, target_label)
    ax.text(
        0.0, 0.97,
        f"{participant_label} | MUNIX{subtitle}",
        fontsize=14, fontweight="bold", color="#1F2A36",
        ha="left", va="top", transform=ax.transAxes,
    )

    def _fmt(val, fmt="{:.2f}"):
        try:
            if val is None:
                return ""
            fv = float(val)
            if fv != fv:  # NaN
                return ""
            # Integers render without decimals; floats keep 2dp except Alpha
            # which is already small.
            if fv.is_integer():
                return str(int(fv))
            return fmt.format(fv)
        except (TypeError, ValueError):
            return str(val)

    table_rows = [
        [
            _fmt(r.get("num_sip"), "{:.0f}"),
            _fmt(r.get("a"), "{:.0f}"),
            _fmt(r.get("alpha"), "{:.2f}"),
            _fmt(r.get("munix"), "{:.0f}"),
            _fmt(r.get("musix"), "{:.0f}"),
        ]
        for r in munix_rows
    ]

    tbl = ax.table(
        cellText=table_rows,
        colLabels=["# SIP", "A", "Alpha", "MUNIX", "MUSIX"],
        cellLoc="left", colLoc="left",
        colWidths=[0.18, 0.20, 0.20, 0.20, 0.20],
        bbox=(0.0, 0.10, 0.80, 0.75),
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(10)
    for (ri, _), cell in tbl.get_celld().items():
        cell.set_edgecolor("#D8E0EA")
        cell.set_linewidth(0.8)
        if ri == 0:
            cell.set_facecolor("#E9EEF4")
            cell.set_text_props(weight="bold", color="#223142")
        else:
            cell.set_facecolor("#FFFFFF")

    fig.subplots_adjust(top=0.96, bottom=0.05, left=0.06, right=0.97)
    return fig


def _build_sr_figure(
    participant_label: str,
    sr_points: list[dict],
    max_cmap_1ms: float | None,
    visit_date: str | None,
    target_label: str | None = None,
):
    """Render the stimulus-response recruitment scatter for one participant visit.

    ``sr_points`` is the curve from :func:`parser.sr_parser.extract_sr_block`
    (one dict per ``SR.n`` row with ``stimulus_mA`` and ``cmap_mV``).  The
    x-axis is stimulus intensity (mA) and the y-axis is absolute CMAP size
    (mV); the reference Max CMAP at 1 ms is annotated across the top of the
    plot as requested.  The curve covers this participant only.
    """
    import matplotlib.pyplot as plt

    xs = [
        p["stimulus_mA"] for p in sr_points
        if p.get("stimulus_mA") is not None and p.get("cmap_mV") is not None
    ]
    ys = [
        p["cmap_mV"] for p in sr_points
        if p.get("stimulus_mA") is not None and p.get("cmap_mV") is not None
    ]

    fig = plt.figure(figsize=(7.7, 5.2))
    ax = fig.add_subplot(111)

    ax.scatter(
        xs, ys,
        s=34, color="#2B6CB0", edgecolor="#1F2A36", linewidth=0.5,
        alpha=0.9, zorder=3,
    )

    ax.set_xlabel("Stimulus intensity (mA)", fontsize=11, color="#1F2A36")
    ax.set_ylabel("CMAP size (mV)", fontsize=11, color="#1F2A36")
    ax.tick_params(labelsize=9, colors="#36495C")
    ax.grid(True, color="#E2E8F0", linewidth=0.8, zorder=0)
    for spine_name in ("top", "right"):
        ax.spines[spine_name].set_visible(False)
    for spine_name in ("left", "bottom"):
        ax.spines[spine_name].set_color("#B7C2CF")
    if ys:
        ax.set_ylim(bottom=min(0.0, min(ys)))

    subtitle = _visit_subtitle(visit_date, target_label)
    ax.text(
        0.5, 1.10, f"{participant_label} | Stimulus-Response{subtitle}",
        transform=ax.transAxes, ha="center", va="bottom",
        fontsize=13, fontweight="bold", color="#1F2A36",
    )
    max_text = (
        f"Max CMAP at 1 ms = {max_cmap_1ms:.2f} mV"
        if max_cmap_1ms is not None
        else "Max CMAP at 1 ms = N/A"
    )
    ax.text(
        0.5, 1.02, max_text,
        transform=ax.transAxes, ha="center", va="bottom",
        fontsize=11, fontweight="bold", color="#2B6CB0",
    )

    fig.subplots_adjust(top=0.85, bottom=0.11, left=0.10, right=0.96)
    return fig


def _sd_xy(sd_points: list[dict], y_key: str) -> tuple[list[float], list[float]]:
    """Return parallel (duration, *y_key*) lists for the finite measured points."""
    xs = [
        p["duration_ms"] for p in sd_points
        if p.get("duration_ms") is not None and p.get(y_key) is not None
    ]
    ys = [
        p[y_key] for p in sd_points
        if p.get("duration_ms") is not None and p.get(y_key) is not None
    ]
    return xs, ys


def _sd_title(
    ax, participant_label: str, name: str, visit_date: str | None,
    target_label: str | None = None,
):
    """Draw the shared bold title used by both strength-duration figures."""
    subtitle = _visit_subtitle(visit_date, target_label)
    ax.text(
        0.5, 1.10, f"{participant_label} | {name}{subtitle}",
        transform=ax.transAxes, ha="center", va="bottom",
        fontsize=13, fontweight="bold", color="#1F2A36",
    )


def _build_strength_duration_curve_figure(
    participant_label: str,
    sd_points: list[dict],
    rheobase_mA: float | None,
    tau_sd_ms: float | None,
    visit_date: str | None,
    target_label: str | None = None,
):
    """Render the strength-duration curve for one participant visit.

    ``sd_points`` is the list from
    :func:`parser.strength_duration_parser.extract_sd_block` (one dict per
    ``QT.n`` row with ``duration_ms`` and ``threshold_mA``).  The x-axis is
    stimulus duration (ms) and the y-axis is threshold current (mA); a fitted
    hyperbola ``I = rheobase*(1 + tau/d)`` is drawn through the points using the
    QtracP-derived rheobase and tau (not refitted), with the rheobase asymptote
    and tau annotated.  The curve covers this participant only.
    """
    import matplotlib.pyplot as plt
    import numpy as np

    xs, ys = _sd_xy(sd_points, "threshold_mA")

    fig = plt.figure(figsize=(7.7, 5.2))
    ax = fig.add_subplot(111)

    ax.scatter(
        xs, ys,
        s=34, color="#2B6CB0", edgecolor="#1F2A36", linewidth=0.5,
        alpha=0.9, zorder=3, label="Measured",
    )

    if rheobase_mA is not None and tau_sd_ms is not None and xs:
        d_max = max(xs)
        # Sample the hyperbola from a small positive duration (avoid the d=0
        # singularity) out to just past the widest measured pulse width.
        d_lo = max(min(xs) * 0.5, 1e-3)
        d_fit = np.linspace(d_lo, d_max * 1.05, 240)
        i_fit = rheobase_mA * (1.0 + tau_sd_ms / d_fit)
        ax.plot(
            d_fit, i_fit,
            color="#C05621", linewidth=1.8, zorder=2,
            label="Fit: I = rheobase·(1 + τSD/d)",
        )
        # Rheobase asymptote (the current the curve approaches as d -> inf).
        ax.axhline(
            rheobase_mA, color="#718096", linestyle="--", linewidth=1.0, zorder=1,
        )
        ax.text(
            0.99, rheobase_mA, f" rheobase = {rheobase_mA:.2f} mA",
            transform=ax.get_yaxis_transform(), va="bottom", ha="right",
            fontsize=9, color="#4A5568",
        )
        # Mark tau on the x-axis where the curve reaches 2 x rheobase
        # (I = rheobase*(1 + tau/tau) = 2*rheobase), if tau is in range.
        if d_lo <= tau_sd_ms <= d_max * 1.05:
            ax.plot(
                [tau_sd_ms], [2.0 * rheobase_mA],
                marker="o", markersize=5, markerfacecolor="none",
                markeredgecolor="#C05621", zorder=4,
            )
            ax.annotate(
                f"τSD = {tau_sd_ms:.2f} ms",
                xy=(tau_sd_ms, 2.0 * rheobase_mA),
                xytext=(12, 10), textcoords="offset points",
                fontsize=9, color="#C05621",
                arrowprops=dict(arrowstyle="->", color="#C05621", linewidth=0.8),
            )
        ax.legend(loc="upper right", fontsize=9, frameon=False)

    ax.set_xlabel("Stimulus duration (ms)", fontsize=11, color="#1F2A36")
    ax.set_ylabel("Threshold current (mA)", fontsize=11, color="#1F2A36")
    ax.tick_params(labelsize=9, colors="#36495C")
    ax.grid(True, color="#E2E8F0", linewidth=0.8, zorder=0)
    for spine_name in ("top", "right"):
        ax.spines[spine_name].set_visible(False)
    for spine_name in ("left", "bottom"):
        ax.spines[spine_name].set_color("#B7C2CF")
    if ys:
        ax.set_ylim(bottom=0.0)

    _sd_title(
        ax, participant_label, "Strength-Duration Curve", visit_date, target_label,
    )
    scalars_text = (
        f"Rheobase = {rheobase_mA:.2f} mA   |   τSD = {tau_sd_ms:.2f} ms"
        if rheobase_mA is not None and tau_sd_ms is not None
        else "Rheobase / τSD = N/A"
    )
    ax.text(
        0.5, 1.02, scalars_text,
        transform=ax.transAxes, ha="center", va="bottom",
        fontsize=11, fontweight="bold", color="#2B6CB0",
    )

    fig.subplots_adjust(top=0.85, bottom=0.11, left=0.10, right=0.96)
    return fig


def _build_charge_duration_figure(
    participant_label: str,
    sd_points: list[dict],
    rheobase_mA: float | None,
    tau_sd_ms: float | None,
    r_squared: float | None,
    visit_date: str | None,
    target_label: str | None = None,
):
    """Render the charge-duration (Weiss linearization) plot for one visit.

    The x-axis is stimulus duration (ms) and the y-axis is threshold charge
    (mA*ms).  A straight line ``Q = rheobase*(d + tau)`` is drawn from the
    QtracP-derived rheobase and tau (slope = rheobase, x-intercept = -tau); the
    slope, x-intercept and fit R^2 are annotated.  Covers this participant only.
    """
    import matplotlib.pyplot as plt
    import numpy as np

    xs, ys = _sd_xy(sd_points, "charge_mA_ms")

    fig = plt.figure(figsize=(7.7, 5.2))
    ax = fig.add_subplot(111)

    ax.scatter(
        xs, ys,
        s=34, color="#2B6CB0", edgecolor="#1F2A36", linewidth=0.5,
        alpha=0.9, zorder=3, label="Measured",
    )

    if rheobase_mA is not None and tau_sd_ms is not None and xs:
        x_int = -tau_sd_ms  # Weiss line crosses Q = 0 at d = -tau.
        d_max = max(xs)
        # Draw the line from its x-intercept through the measured range so the
        # slope = rheobase and x-intercept = -tau are both visible.
        d_line = np.linspace(x_int, d_max * 1.05, 240)
        q_line = rheobase_mA * (d_line + tau_sd_ms)
        ax.plot(
            d_line, q_line,
            color="#C05621", linewidth=1.8, zorder=2,
            label="Fit: Q = rheobase·(d + τSD)",
        )
        # Reference axes through the origin so the x-intercept reads cleanly.
        ax.axhline(0.0, color="#CBD5E0", linewidth=0.8, zorder=1)
        ax.axvline(0.0, color="#CBD5E0", linewidth=0.8, zorder=1)
        # Mark the x-intercept (-tau, 0).
        ax.plot(
            [x_int], [0.0],
            marker="o", markersize=5, markerfacecolor="none",
            markeredgecolor="#C05621", zorder=4,
        )
        ax.annotate(
            f"x-intercept = −τSD = {x_int:.2f} ms",
            xy=(x_int, 0.0),
            xytext=(10, -16), textcoords="offset points",
            fontsize=9, color="#C05621",
            arrowprops=dict(arrowstyle="->", color="#C05621", linewidth=0.8),
        )
        ax.legend(loc="upper left", fontsize=9, frameon=False)

    ax.set_xlabel("Stimulus duration (ms)", fontsize=11, color="#1F2A36")
    ax.set_ylabel("Threshold charge (mA·ms)", fontsize=11, color="#1F2A36")
    ax.tick_params(labelsize=9, colors="#36495C")
    ax.grid(True, color="#E2E8F0", linewidth=0.8, zorder=0)
    for spine_name in ("top", "right"):
        ax.spines[spine_name].set_visible(False)
    for spine_name in ("left", "bottom"):
        ax.spines[spine_name].set_color("#B7C2CF")

    _sd_title(
        ax, participant_label, "Charge-Duration (Weiss)", visit_date, target_label,
    )
    r2_text = f"R² = {r_squared:.3f}" if r_squared is not None else "R² = N/A"
    slope_text = (
        f"Slope (rheobase) = {rheobase_mA:.2f} mA"
        if rheobase_mA is not None else "Slope = N/A"
    )
    ax.text(
        0.5, 1.02, f"{slope_text}   |   {r2_text}",
        transform=ax.transAxes, ha="center", va="bottom",
        fontsize=11, fontweight="bold", color="#2B6CB0",
    )

    fig.subplots_adjust(top=0.85, bottom=0.11, left=0.10, right=0.96)
    return fig


def build_header_only_figure(
    participant_rows: pd.DataFrame,
    participant_label: str | None = None,
):
    """Build a standalone patient-info figure for the letterhead page.

    Fields displayed (in order): Study, Patient ID, Patient type, Age, Sex,
    Stimulated Cortex, Recorded muscle(s).

    This is used by the GUI workflow — it is placed on page 1 beneath the
    institutional letterhead banner.  The figure is sized for portrait
    US-Letter composition (``reports.pdf_layout.build_letterhead_banner_page``).
    """
    import matplotlib.pyplot as plt

    study = _latest_non_missing_study(participant_rows)
    age = _latest_non_missing_age(participant_rows)
    sex = _latest_non_missing_sex(participant_rows)
    subject_type = _latest_non_missing_subject_type(participant_rows)
    cortex = _latest_non_missing_stimulated_cortex(participant_rows)

    if participant_label is None:
        participant_label = format_participant_label(
            int(pd.to_numeric(participant_rows["ID"], errors="coerce").dropna().iloc[0])
        )

    fig = plt.figure(figsize=(7.7, 5.2))
    ax = fig.add_subplot(111)
    ax.axis("off")

    ax.text(
        0.0, 0.98, f"{participant_label} | Participant MEM report",
        fontsize=18, fontweight="bold", color="#1F2A36",
        ha="left", va="top", transform=ax.transAxes,
    )

    field_rows = [
        ("Study", study),
        ("Patient ID", participant_label),
        ("Patient type", subject_type),
        ("Age", age),
        ("Sex", sex),
        ("Stimulated Cortex", cortex),
        ("Recorded muscle(s)", _recording_targets_text(participant_rows)),
        ("Date generated", generation_date_string()),
    ]

    top = 0.82
    line_step = 0.09
    label_x = 0.0
    value_x = 0.42
    for i, (label, value) in enumerate(field_rows):
        y = top - i * line_step
        ax.text(
            label_x, y, f"{label}:",
            fontsize=12, fontweight="bold", color="#1F2A36",
            ha="left", va="top", transform=ax.transAxes,
        )
        ax.text(
            value_x, y, str(value),
            fontsize=12, color="#36495C",
            ha="left", va="top", transform=ax.transAxes,
        )

    fig.subplots_adjust(top=0.96, bottom=0.05, left=0.06, right=0.97)
    return fig


# ---------------------------------------------------------------------------
# Group-comparison figure builders with message fallback
# ---------------------------------------------------------------------------

def _group_plot_title(label, anchor_date, comparison):
    return f"{label} | Latest visit vs {comparison} | {anchor_date}"


def _items_from_message(section_key: str, title: str, message: str) -> list[ReportItem]:
    """Wrap an error/info message as a single ReportItem (no caption)."""
    return [ReportItem(
        figure=_build_message_figure(title, message),
        caption=None,
        section_key=section_key,
    )]


def _measure_group_or_message(
    section_key, measure, pid, anchor, label, df, comp, match_by=None,
    age_window=5, show=False, skip=False,
) -> list[ReportItem]:
    mlabel = waveform_measure_config(measure)["label"]
    title = _group_plot_title(label, anchor, f"{mlabel} vs {comp}")
    try:
        fig, _, plot_data = plot_measure_grouped_graph(
            measure=measure, participant_id=pid, mem_date=anchor,
            data_df=df, match_by=match_by, age_window=age_window,
            title=title, show=show,
        )
    except ValueError as exc:
        return [] if skip else _items_from_message(section_key, title, str(exc))
    return [ReportItem(
        figure=fig,
        caption=grouped_caption(plot_data, metric_label=mlabel),
        section_key=section_key,
    )]


def _rmt_group_or_message(
    section_key, pid, anchor, label, df, comp, match_by=None,
    age_window=5, show=False, skip=False,
) -> list[ReportItem]:
    title = _group_plot_title(label, anchor, f"RMT vs {comp}")
    try:
        figs, _, plot_data = plot_rmt_grouped_graph(
            participant_id=pid, mem_date=anchor, data_df=df,
            match_by=match_by, age_window=age_window,
            title=title, show=show,
        )
    except ValueError as exc:
        return [] if skip else _items_from_message(section_key, title, str(exc))

    items: list[ReportItem] = []
    fig_list = figs if isinstance(figs, list) else [figs]
    figure_keys = plot_data.get("figure_keys") if isinstance(plot_data, dict) else None
    panels = plot_data.get("panels") if isinstance(plot_data, dict) else None
    for idx, fig in enumerate(fig_list):
        panel_key = figure_keys[idx] if figure_keys and idx < len(figure_keys) else None
        panel_data = panels.get(panel_key) if panels and panel_key else None
        caption = grouped_caption(panel_data, metric_label=panel_key) if panel_data else None
        items.append(ReportItem(figure=fig, caption=caption, section_key=section_key))
    return items


def _csp_group_or_message(
    section_key, pid, anchor, label, df, comp, match_by=None,
    age_window=5, show=False, skip=False,
) -> list[ReportItem]:
    title = _group_plot_title(label, anchor, f"{CSP_MEASURE_LABEL} vs {comp}")
    try:
        fig, _, plot_data = plot_csp_grouped_graph(
            participant_id=pid, mem_date=anchor, data_df=df,
            match_by=match_by, age_window=age_window,
            title=title, show=show,
        )
    except ValueError as exc:
        return [] if skip else _items_from_message(section_key, title, str(exc))

    # plot_csp_grouped_graph returns either a single figure (single CSP level)
    # or a list (one per level). Handle both uniformly.
    if isinstance(fig, list):
        fig_list = fig
        figure_keys = plot_data.get("figure_keys") if isinstance(plot_data, dict) else None
        panels = plot_data.get("panels") if isinstance(plot_data, dict) else None
        items: list[ReportItem] = []
        for idx, f in enumerate(fig_list):
            panel_key = figure_keys[idx] if figure_keys and idx < len(figure_keys) else None
            panel_data = panels.get(panel_key) if panels and panel_key else None
            caption = grouped_caption(panel_data, metric_label=panel_key) if panel_data else None
            items.append(ReportItem(figure=f, caption=caption, section_key=section_key))
        return items

    return [ReportItem(
        figure=fig,
        caption=grouped_caption(plot_data, metric_label=CSP_MEASURE_LABEL),
        section_key=section_key,
    )]


# ---------------------------------------------------------------------------
# Strength-duration data loader (headless / CLI path)
# ---------------------------------------------------------------------------

def _first_json_list_df(rows: pd.DataFrame, column: str) -> list[dict]:
    """Return the first non-empty JSON list stored in *column*, or ``[]``."""
    import json

    if column not in rows.columns:
        return []
    for raw in rows[column].tolist():
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            continue
        text = str(raw).strip()
        if not text or text.lower() == "nan" or text == "[]":
            continue
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, list) and parsed:
            return [p for p in parsed if isinstance(p, dict)]
    return []


def _load_sd_for_visit(
    participant_rows: pd.DataFrame,
    visit_date: str | None,
    mem_dir=None,
) -> tuple[list[dict], float | None, float | None]:
    """Load the charge-duration points for a visit (headless/CLI report path).

    Prefers the points persisted in the DataFrame/CSV (``SD_points``) so the
    report can be built from an archived CSV alone. Falls back to re-parsing the
    source .MEM (older archives that predate the stored column); when *mem_dir*
    is ``None`` the configured ``core.config.MEM_DIR`` is used. Derived scalars
    prefer the DataFrame's stored ``Rheobase_mA`` / ``Tau_SD_ms`` values.
    Returns ``([], None, None)`` when nothing is found.
    """
    from parser.strength_duration_parser import (
        SD_POINTS_COLUMN,
        SD_RHEOBASE_COLUMN,
        SD_TAU_COLUMN,
        parse_strength_duration_file,
    )

    rows = participant_rows
    if visit_date is not None and "Date" in rows.columns:
        rows = rows[
            rows["Date"].astype("string").fillna("").str.strip() == visit_date
        ]
    if rows.empty:
        return [], None, None

    def _stored_scalar(col):
        if col in rows.columns:
            s = pd.to_numeric(rows[col], errors="coerce").dropna()
            if not s.empty:
                return float(s.iloc[0])
        return None

    rheobase = _stored_scalar(SD_RHEOBASE_COLUMN)
    tau = _stored_scalar(SD_TAU_COLUMN)

    # 1) Stored points column — no source .MEM needed (works from an archived CSV).
    points = _first_json_list_df(rows, SD_POINTS_COLUMN)
    if points:
        return points, rheobase, tau

    # 2) Fall back to re-reading the source .MEM.
    from parser.mem_parser import iter_mem_files
    from core.config import MEM_DIR

    if "source_file" not in rows.columns:
        return [], rheobase, tau
    names: list[str] = []
    for value in rows["source_file"].tolist():
        if value is None or (isinstance(value, float) and pd.isna(value)):
            continue
        names.extend(n.strip() for n in str(value).split(";") if n.strip())
    if not names:
        return [], rheobase, tau

    search_dir = mem_dir if mem_dir is not None else (
        str(MEM_DIR) if MEM_DIR.is_dir() else None
    )
    if search_dir is None:
        return [], rheobase, tau

    file_index = {p.name: p for p in iter_mem_files(search_dir, recursive=True)}
    for name in names:
        path = file_index.get(name)
        if path is None:
            continue
        try:
            block = parse_strength_duration_file(path)
        except OSError:
            continue
        if block.get("points"):
            return (
                block["points"],
                rheobase if rheobase is not None else block.get("rheobase_mA"),
                tau if tau is not None else block.get("tau_sd_ms"),
            )
    return [], rheobase, tau


def _strength_duration_curve_section(
    plabel, p_rows, anchor, mem_dir, target_label_text=None,
) -> list:
    """Build the strength-duration curve ReportItem for the CLI report path."""
    points, rheobase, tau = _load_sd_for_visit(p_rows, anchor, mem_dir)
    if not points or rheobase is None or tau is None:
        return []
    fig = _build_strength_duration_curve_figure(
        plabel, points, rheobase, tau, anchor, target_label_text,
    )
    caption = caption_for("strength_duration_curve", None, {
        "rheobase_mA": rheobase, "tau_sd_ms": tau, "sd_point_count": len(points),
    })
    return [ReportItem(
        figure=fig, caption=caption, section_key="strength_duration_curve",
    )]


def _charge_duration_weiss_section(
    plabel, p_rows, anchor, mem_dir, target_label_text=None,
) -> list:
    """Build the charge-duration (Weiss) ReportItem for the CLI report path."""
    from parser.strength_duration_parser import charge_duration_r_squared

    points, rheobase, tau = _load_sd_for_visit(p_rows, anchor, mem_dir)
    if not points or rheobase is None or tau is None:
        return []
    r2 = charge_duration_r_squared(points, rheobase, tau)
    fig = _build_charge_duration_figure(
        plabel, points, rheobase, tau, r2, anchor, target_label_text,
    )
    caption = caption_for("charge_duration_weiss", None, {
        "rheobase_mA": rheobase, "tau_sd_ms": tau, "r_squared": r2,
        "sd_point_count": len(points),
    })
    return [ReportItem(
        figure=fig, caption=caption, section_key="charge_duration_weiss",
    )]


# ---------------------------------------------------------------------------
# Main figure builder
# ---------------------------------------------------------------------------

def build_report_figures(
    participant_id,
    data_df: pd.DataFrame,
    included_sections=None,
    age_window: int = 5,
    show: bool = False,
    mem_date: str | None = None,
    mem_dir=None,
    recording_target: str | None = None,
) -> list:
    """Generate all requested report figures for one participant.

    Parameters
    ----------
    participant_id : int
        The SNBR participant ID.
    data_df : pd.DataFrame
        The full parsed MEM DataFrame (from ``df_builder``).
    included_sections : str or list, optional
        Which sections to include.  ``None`` uses the default set.
    age_window : int
        Window for age-matched comparisons (default 5 years).
    show : bool
        Whether to display figures interactively.
    mem_date : str, optional
        Visit date to use as the anchor for group comparisons (any format
        accepted by ``normalize_mem_date``).  When ``None`` or when the date
        has no data for this participant, the most recent visit is used.
    recording_target : str, optional
        Restrict this participant's rows to one recording target (e.g.
        ``"Right FDI"``) and name it in the figure titles.  ``None`` uses every
        row the participant has, which is right for a visit recorded from a
        single muscle.  Reference cohorts stay pooled either way.

    Returns
    -------
    list[ReportItem]
        ReportItems in section order, each carrying a matplotlib figure and
        (optionally) a raw-value caption string, ready for
        :func:`pdf_renderer.render_figures_to_pdf`.
    """
    import matplotlib
    if not show:
        matplotlib.use("Agg")

    resolved_df = load_mem_dataframe(data_df=data_df)
    p_rows, _, resolved_id = resolve_participant_context(resolved_df, participant_id=participant_id)

    # The title page names every muscle the participant was recorded from, even
    # when the plots below are restricted to one of them, so keep an unfiltered
    # copy before narrowing.
    all_participant_rows = p_rows.copy()
    if recording_target:
        resolved_df = restrict_participant_to_target(
            resolved_df, resolved_id, recording_target,
        )
        p_rows, _, resolved_id = resolve_participant_context(
            resolved_df, participant_id=participant_id,
        )

    p_rows = p_rows.copy()
    p_rows["visit_date"] = pd.to_datetime(p_rows["Date"], dayfirst=True, errors="coerce")
    p_rows["source_file"] = p_rows["source_file"].astype("string").fillna("").str.strip()
    p_rows = p_rows.sort_values(["visit_date", "source_file"], na_position="last").reset_index(drop=True)

    try:
        visit_tl = build_participant_visit_timeline_data(p_rows)
        visit_sum = build_participant_visit_test_summary(p_rows)
        has_valid_dates = True
    except ValueError:
        visit_tl = pd.DataFrame()
        visit_sum = pd.DataFrame()
        has_valid_dates = False

    # Resolve anchor date: use requested date if valid, else latest visit
    if has_valid_dates:
        anchor = str(visit_tl.iloc[-1]["Date"])
        if mem_date is not None:
            try:
                normalized = normalize_mem_date(mem_date)
                if normalized in visit_tl["Date"].values:
                    anchor = normalized
            except ValueError:
                pass
    else:
        anchor = None
    plabel = format_participant_label(resolved_id)
    if recording_target:
        # Every title in this path is built as "<plabel> | ...", so naming the
        # recording here puts it on all of them at once.
        plabel = f"{plabel} ({recording_target})"
    skip_missing = requests_all_report_sections(included_sections)
    section_keys = normalize_report_sections(included_sections)

    # Omit all date-dependent sections when no valid dates exist
    if not has_valid_dates:
        section_keys = [
            k for k in section_keys
            if k not in _SECTIONS_REQUIRING_DATES
            and not k.endswith(_DATE_DEPENDENT_SUFFIXES)
        ]
    # Omit longitudinal sections when there is only one visit
    elif len(visit_tl) < 2:
        section_keys = [
            k for k in section_keys
            if not k.endswith(_LONGITUDINAL_SUFFIXES)
        ]

    # --- helpers ---
    def _normalize(output):
        if output is None:
            return []
        if isinstance(output, list):
            return [f for f in output if f is not None]
        return [output]

    def _simple_item(section_key: str, figure, caption: str | None = None) -> list[ReportItem]:
        return [ReportItem(figure=figure, caption=caption, section_key=section_key)]

    def _single_fig_or_msg(
        section_key: str, title: str, plot_callable, caption_fn=None,
    ) -> list[ReportItem]:
        """Call a plotting function that returns (fig, _, plot_data); map to items."""
        try:
            fig, _, plot_data = plot_callable()
        except ValueError as exc:
            if skip_missing:
                return []
            return _items_from_message(section_key, title, str(exc))
        figs = _normalize(fig)
        if not figs:
            if skip_missing:
                return []
            return _items_from_message(section_key, title, "No data were available for this section.")
        # Single figure path
        if len(figs) == 1:
            caption = caption_fn(plot_data, None) if caption_fn else None
            return [ReportItem(figure=figs[0], caption=caption, section_key=section_key)]
        # Multiple figures (e.g. over-time per RMT column): emit one item per fig.
        items: list[ReportItem] = []
        figure_keys = plot_data.get("figure_keys") if isinstance(plot_data, dict) else None
        for idx, f in enumerate(figs):
            fkey = figure_keys[idx] if figure_keys and idx < len(figure_keys) else None
            caption = caption_fn(plot_data, fkey) if caption_fn else None
            items.append(ReportItem(figure=f, caption=caption, section_key=section_key))
        return items

    def _over_time_caption_fn(plot_data, figure_key):
        """Caption for an over-time sub-figure keyed by value column."""
        if not isinstance(plot_data, dict):
            return None
        # Multi-figure case: use visit_summaries[figure_key]
        if figure_key is not None:
            summaries = plot_data.get("visit_summaries") or {}
            return latest_visit_caption(summaries.get(figure_key), metric_label=figure_key)
        # Single-figure case: prefer top-level visit_summary
        summary = plot_data.get("visit_summary")
        if summary is not None:
            return latest_visit_caption(summary, metric_label=plot_data.get("value_column"))
        return None

    # --- section builders ---
    builders: dict = {
        "summary": lambda: _simple_item(
            "summary",
            _build_summary_figure(
                plabel, p_rows, visit_sum, visit_tl, anchor, all_participant_rows,
            )
            if has_valid_dates
            else _build_summary_figure_no_dates(plabel, all_participant_rows),
        ),
        # 'visit_table' now renders the visit timeline only — the visit
        # summary table itself moved onto page 1 alongside the demographics.
        "visit_table": lambda: _simple_item(
            "visit_table",
            _build_visit_overview_figure(plabel, visit_sum, visit_tl)
            if has_valid_dates
            else plot_participant_visit_test_table(
                participant_id=resolved_id, data_df=resolved_df,
                title=f"{plabel} | Visit summary and tests present", show=show,
            )[0],
        ),
        "cmap_table": lambda: (
            _simple_item(
                "cmap_table",
                _build_cmap_table_figure(
                    plabel,
                    _extract_cmap_rows_for_visit(p_rows, anchor),
                    anchor,
                    recording_target,
                ),
            )
            if _extract_cmap_rows_for_visit(p_rows, anchor)
            else []
        ),
        "munix_table": lambda: (
            _simple_item(
                "munix_table",
                _build_munix_table_figure(
                    plabel,
                    _extract_munix_rows_for_visit(p_rows, anchor),
                    anchor,
                    recording_target,
                ),
            )
            if _extract_munix_rows_for_visit(p_rows, anchor)
            else []
        ),
        "strength_duration_curve": lambda: _strength_duration_curve_section(
            plabel, p_rows, anchor, mem_dir, recording_target,
        ),
        "charge_duration_weiss": lambda: _charge_duration_weiss_section(
            plabel, p_rows, anchor, mem_dir, recording_target,
        ),
        "rmt_over_time": lambda: _single_fig_or_msg(
            "rmt_over_time",
            f"{plabel} | RMT thresholds over time",
            lambda: plot_participant_rmt_over_time(
                participant_id=resolved_id, data_df=resolved_df,
                title=f"{plabel} | RMT thresholds over time", show=show,
            ),
            caption_fn=_over_time_caption_fn,
        ),
        "rmt_overall": lambda: _rmt_group_or_message(
            "rmt_overall", resolved_id, anchor, plabel, resolved_df,
            "all participants", show=show, skip=skip_missing, age_window=age_window,
        ),
        "rmt_age_matched": lambda: _rmt_group_or_message(
            "rmt_age_matched", resolved_id, anchor, plabel, resolved_df,
            f"age-matched cohorts (+/- {age_window} years)",
            match_by="age", age_window=age_window, show=show, skip=skip_missing,
        ),
        "rmt_sex_matched": lambda: _rmt_group_or_message(
            "rmt_sex_matched", resolved_id, anchor, plabel, resolved_df,
            "sex-matched cohorts",
            match_by="sex", age_window=age_window, show=show, skip=skip_missing,
        ),
        "rmt_sex_age_matched": lambda: _rmt_group_or_message(
            "rmt_sex_age_matched", resolved_id, anchor, plabel, resolved_df,
            f"sex and age matched cohorts (+/- {age_window} years)",
            match_by=["sex", "age"], age_window=age_window, show=show, skip=skip_missing,
        ),
        # CSP sections
        "csp_profile": lambda: _single_fig_or_msg(
            "csp_profile",
            f"{plabel} | {CSP_MEASURE_LABEL} profile",
            lambda: plot_csp_profile(
                participant_id=resolved_id, mem_date=anchor, data_df=resolved_df,
                title=f"{plabel} | {CSP_MEASURE_LABEL} profile | {anchor}", show=show,
            ),
            caption_fn=lambda pd_, _k: csp_profile_caption(pd_),
        ),
        "csp_overall": lambda: _csp_group_or_message(
            "csp_overall", resolved_id, anchor, plabel, resolved_df,
            "all participants", show=show, skip=skip_missing, age_window=age_window,
        ),
        "csp_age_matched": lambda: _csp_group_or_message(
            "csp_age_matched", resolved_id, anchor, plabel, resolved_df,
            f"age-matched cohorts (+/- {age_window} years)",
            match_by="age", age_window=age_window, show=show, skip=skip_missing,
        ),
        "csp_sex_matched": lambda: _csp_group_or_message(
            "csp_sex_matched", resolved_id, anchor, plabel, resolved_df,
            "sex-matched cohorts",
            match_by="sex", age_window=age_window, show=show, skip=skip_missing,
        ),
        "csp_sex_age_matched": lambda: _csp_group_or_message(
            "csp_sex_age_matched", resolved_id, anchor, plabel, resolved_df,
            f"sex and age matched cohorts (+/- {age_window} years)",
            match_by=["sex", "age"], age_window=age_window, show=show, skip=skip_missing,
        ),
        "csp_over_time": lambda: _single_fig_or_msg(
            "csp_over_time",
            f"{plabel} | {CSP_MEASURE_LABEL} duration over time",
            lambda: plot_participant_csp_over_time(
                participant_id=resolved_id, data_df=resolved_df,
                title=f"{plabel} | {CSP_MEASURE_LABEL} duration over time", show=show,
            ),
            caption_fn=_over_time_caption_fn,
        ),
        "csp_visit_profiles": lambda: _single_fig_or_msg(
            "csp_visit_profiles",
            f"{plabel} | {CSP_MEASURE_LABEL} profile by visit",
            lambda: plot_participant_csp_visit_profiles(
                participant_id=resolved_id, data_df=resolved_df,
                title=f"{plabel} | {CSP_MEASURE_LABEL} profile by visit", show=show,
            ),
            caption_fn=None,
        ),
    }

    # T-SICI cohort trajectory (repeated-visit participants only). Uses the
    # cohort of the same subject type; gated out above when < 2 visits.
    builders["t_sici_trajectory"] = lambda: _single_fig_or_msg(
        "t_sici_trajectory",
        f"{plabel} | T-SICI trajectory vs cohort",
        lambda: plot_participant_measure_trajectory(
            measure="t_sici", participant_id=resolved_id, data_df=resolved_df,
            title=f"{plabel} | T-SICI trajectory vs cohort", show=show,
        ),
        caption_fn=lambda pd_, k: caption_for("trajectory", "t_sici", pd_, k),
    )

    # Waveform measures (T-SICI, A-SICI, A-SICF, T-SICF)
    for m in WAVEFORM_REPORT_MEASURES:
        ml = waveform_measure_config(m)["label"]
        builders[f"{m}_over_time"] = (
            lambda mk=m, mt=ml: _single_fig_or_msg(
                f"{mk}_over_time",
                f"{plabel} | Averaged {mt} over time",
                lambda mk=mk, mt=mt: plot_participant_measure_over_time(
                    measure=mk, participant_id=resolved_id, data_df=resolved_df,
                    title=f"{plabel} | Averaged {mt} over time", show=show,
                ),
                caption_fn=_over_time_caption_fn,
            )
        )
        builders[f"{m}_visit_profiles"] = (
            lambda mk=m, mt=ml: _single_fig_or_msg(
                f"{mk}_visit_profiles",
                f"{plabel} | {mt} profile by visit",
                lambda mk=mk, mt=mt: plot_participant_measure_visit_profiles(
                    measure=mk, participant_id=resolved_id, data_df=resolved_df,
                    title=f"{plabel} | {mt} profile by visit", show=show,
                ),
                caption_fn=None,
            )
        )
        builders[f"{m}_overall"] = (
            lambda mk=m: _measure_group_or_message(
                f"{mk}_overall", mk, resolved_id, anchor, plabel, resolved_df,
                "all participants", show=show, skip=skip_missing, age_window=age_window,
            )
        )
        builders[f"{m}_age_matched"] = (
            lambda mk=m: _measure_group_or_message(
                f"{mk}_age_matched", mk, resolved_id, anchor, plabel, resolved_df,
                f"age-matched cohorts (+/- {age_window} years)",
                match_by="age", age_window=age_window, show=show, skip=skip_missing,
            )
        )
        builders[f"{m}_sex_matched"] = (
            lambda mk=m: _measure_group_or_message(
                f"{mk}_sex_matched", mk, resolved_id, anchor, plabel, resolved_df,
                "sex-matched cohorts",
                match_by="sex", age_window=age_window, show=show, skip=skip_missing,
            )
        )
        builders[f"{m}_sex_age_matched"] = (
            lambda mk=m: _measure_group_or_message(
                f"{mk}_sex_age_matched", mk, resolved_id, anchor, plabel, resolved_df,
                f"sex and age matched cohorts (+/- {age_window} years)",
                match_by=["sex", "age"], age_window=age_window, show=show, skip=skip_missing,
            )
        )

    # --- collect report items ---
    items: list[ReportItem] = []
    for key in section_keys:
        out = builders[key]()
        if out:
            items.extend(out)

    # Enlarge the axis text on plot figures so the exported report matches the
    # in-app previews. Tables and the letterhead summary keep their tuned layout.
    for item in items:
        if item.figure is not None and item.section_key not in _SKIP_FONT_ENLARGE:
            enlarge_axes_fonts(item.figure)

    return items
