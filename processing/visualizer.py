"""
Visualization bridge — re-exports the plotting API from the bundled V1 module.

The V1 visualization code is now included directly in this package as
``processing._v1_visualization`` (and its dependency ``processing._v1_parse_mem_files``).
This module re-exports every public symbol so the rest of the V2 app can
import from ``processing.visualizer`` without knowing the internal layout.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Re-export the public API from the bundled V1 visualization module.
# ---------------------------------------------------------------------------

from processing._v1_visualization import (  # noqa: F401
    # Constants / helpers
    normalize_mem_date,
    CORTEX_COLORS,
    CORTEX_FACE_COLORS,
    cortex_color,
    CSP_MEASURE_KEY,
    CSP_MEASURE_LABEL,
    CSP_PROFILE_COLUMNS,
    POINTPLOT_CATEGORY_X,
    RMT_COLUMNS,
    STANDARD_FIGSIZE,
    VISIT_TABLE_COLUMN_WIDTHS,
    WAVEFORM_MEASURE_CONFIGS,
    # Config helpers
    waveform_measure_config,
    normalize_measure_key,
    # Data loading / resolution (accepts data_df kwarg)
    load_mem_dataframe,
    resolve_participant_context,
    resolve_selected_rows,
    # Visit & timeline builders
    build_participant_visit_timeline_data,
    build_participant_visit_test_summary,
    build_participant_visit_summary,
    # Profile builders
    waveform_long_format,
    build_participant_visit_profiles,
    build_participant_measure_visit_profiles,
    # Formatting
    format_participant_label,
    apply_visit_summary_table_layout,
    draw_participant_visit_timeline_axis,
    # Plot functions — RMT
    plot_participant_rmt_over_time,
    plot_rmt_grouped_graph,
    # Plot functions — T-SICI (backward-compat wrappers)
    plot_tsici_profile,
    plot_tsici_group_comparison,
    plot_tsici_grouped_graph,
    plot_participant_tsici_over_time,
    plot_participant_tsici_visit_profiles,
    # Plot functions — generic waveform measures
    plot_measure_profile,
    plot_measure_group_comparison,
    plot_measure_grouped_graph,
    plot_participant_measure_over_time,
    plot_participant_measure_visit_profiles,
    plot_participant_measure_trajectory,
    # Plot functions — CSP
    plot_csp_profile,
    plot_csp_grouped_graph,
    plot_participant_csp_over_time,
    plot_participant_csp_visit_profiles,
    # Plot functions — participant visit
    plot_participant_visit_timeline,
    plot_participant_visit_test_table,
    # Convenience dispatcher
    plot_mem_graph,
    plot_tsici_graph,
)

__all__ = [
    "normalize_mem_date",
    "CSP_MEASURE_KEY",
    "CSP_MEASURE_LABEL",
    "CSP_PROFILE_COLUMNS",
    "POINTPLOT_CATEGORY_X",
    "RMT_COLUMNS",
    "STANDARD_FIGSIZE",
    "VISIT_TABLE_COLUMN_WIDTHS",
    "WAVEFORM_MEASURE_CONFIGS",
    "waveform_measure_config",
    "normalize_measure_key",
    "load_mem_dataframe",
    "resolve_participant_context",
    "resolve_selected_rows",
    "build_participant_visit_timeline_data",
    "build_participant_visit_test_summary",
    "build_participant_visit_summary",
    "waveform_long_format",
    "build_participant_visit_profiles",
    "build_participant_measure_visit_profiles",
    "format_participant_label",
    "apply_visit_summary_table_layout",
    "draw_participant_visit_timeline_axis",
    "plot_participant_rmt_over_time",
    "plot_rmt_grouped_graph",
    "plot_tsici_profile",
    "plot_tsici_group_comparison",
    "plot_tsici_grouped_graph",
    "plot_participant_tsici_over_time",
    "plot_participant_tsici_visit_profiles",
    "plot_measure_profile",
    "plot_measure_group_comparison",
    "plot_measure_grouped_graph",
    "plot_participant_measure_over_time",
    "plot_participant_measure_visit_profiles",
    "plot_participant_measure_trajectory",
    "plot_csp_profile",
    "plot_csp_grouped_graph",
    "plot_participant_csp_over_time",
    "plot_participant_csp_visit_profiles",
    "plot_participant_visit_timeline",
    "plot_participant_visit_test_table",
    "plot_mem_graph",
    "plot_tsici_graph",
]
