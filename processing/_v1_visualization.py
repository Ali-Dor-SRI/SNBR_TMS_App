"""
Visualization helpers for parsed MEM T-SICI data.

This module contains plotting utilities that sit on top of the parsing logic in
parse_mem_files.py.
"""

from pathlib import Path
import sys
import textwrap

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from processing._v1_parse_mem_files import (
    A_SICI_ISIS,
    ASICF_ISIS,
    CSP_RMT_LEVELS,
    TSICI_ISIS,
    TSICF_ISIS,
    normalize_output_dataframe,
    parse_mem_directory,
)

POINTPLOT_CATEGORY_X = {
    "highlight": 0.0,
    "patient": 1.0,
    "control": 2.0,
}

# Colors for cortex-side overlays (used when both cortex sides are plotted together)
# Blue for Left stimulation, Red for Right stimulation.
CORTEX_COLORS = ["#526A84", "#C75233"]  # kept for backward compat
CORTEX_FACE_COLORS = ["#DCE6F2", "#F2DCD6"]

_CORTEX_COLOR_MAP = {
    "L": ("#2B6CB0", "#DBEAFE"),   # blue line, blue face
    "R": ("#C53030", "#FED7D7"),   # red line, red face
}
_CORTEX_FALLBACK_COLORS = [("#2B6CB0", "#DBEAFE"), ("#C53030", "#FED7D7")]


def cortex_color(cortex_value: str, index: int = 0) -> tuple[str, str]:
    """Return (line_color, face_color) for a cortex value.

    Parses the first character of *cortex_value* (e.g. ``"R->L"`` → ``"R"``,
    ``"L->R"`` → ``"L"``) and maps to a fixed colour.  Falls back to
    index-based assignment for unrecognised values.
    """
    key = str(cortex_value).strip()[:1].upper()
    if key in _CORTEX_COLOR_MAP:
        return _CORTEX_COLOR_MAP[key]
    return _CORTEX_FALLBACK_COLORS[index % len(_CORTEX_FALLBACK_COLORS)]

WAVEFORM_MEASURE_CONFIGS = {
    "t_sici": {
        "prefix": "T_SICI",
        "label": "T-SICI",
        "avg_column": "T_SICI_avg",
        "isis": TSICI_ISIS,
        "reference_line": 100.0,
    },
    "a_sici": {
        "prefix": "A_SICI",
        "label": "A-SICI",
        "avg_column": "A_SICI_avg",
        "isis": A_SICI_ISIS,
        "reference_line": 100.0,
    },
    "a_sicf": {
        "prefix": "A_SICF",
        "label": "A-SICF",
        "avg_column": "A_SICF_avg",
        "isis": ASICF_ISIS,
        "reference_line": 100.0,
    },
    "t_sicf": {
        "prefix": "T_SICF",
        "label": "T-SICF",
        "avg_column": "T_SICF_avg",
        "isis": TSICF_ISIS,
        "reference_line": 100.0,
    },
}

WAVEFORM_MEASURE_ALIASES = {
    "t_sici": "t_sici",
    "tsici": "t_sici",
    "t-sici": "t_sici",
    "a_sici": "a_sici",
    "asici": "a_sici",
    "a-sici": "a_sici",
    "a_sicf": "a_sicf",
    "asicf": "a_sicf",
    "a-sicf": "a_sicf",
    "t_sicf": "t_sicf",
    "tsicf": "t_sicf",
    "t-sicf": "t_sicf",
}

CSP_MEASURE_KEY = "csp"
CSP_MEASURE_LABEL = "CSP"
CSP_PROFILE_COLUMNS = [f"CSP_{level}" for level in CSP_RMT_LEVELS]
CSP_PROFILE_COLUMN_SET = set(CSP_PROFILE_COLUMNS)
CSP_PROFILE_COLUMN_LABELS = {
    f"CSP_{level}": f"{level}% RMT"
    for level in CSP_RMT_LEVELS
}

STANDARD_FIGSIZE = (9.0, 6.0)

RMT_COLUMNS = ["RMT50", "RMT200", "RMT1000"]
RMT_COLUMN_LABELS = {
    "RMT50": "RMT50",
    "RMT200": "RMT200",
    "RMT1000": "RMT1000",
}
VISIT_TEST_COLUMN_GROUPS = [
    ("RMT50", ["RMT50"]),
    ("RMT200", ["RMT200"]),
    ("RMT1000", ["RMT1000"]),
    ("CSP", [f"CSP_{level}" for level in CSP_RMT_LEVELS]),
    ("T-SICI", ["T_SICI_avg"]),
    ("T-SICF", ["T_SICF_avg"]),
    ("A-SICI", ["A_SICI_avg"]),
    ("A-SICF", ["A_SICF_avg"]),
]
VISIT_TEST_WRAP_WIDTH = 24
VISIT_TABLE_COLUMN_WIDTHS = [0.10, 0.12, 0.15, 0.09, 0.14, 0.40]


def default_mem_input_dir() -> Path:
    """Return the default MEM input directory relative to this script."""
    script_dir = Path(__file__).resolve().parent
    project_dir = script_dir.parent
    return project_dir / "1_Raw_Data" / "SNBR_MEM"


def load_mem_dataframe(input_dir=None, data_df=None) -> pd.DataFrame:
    """Load or normalize the parsed MEM DataFrame used by plotting helpers."""
    if data_df is None:
        resolved_input_dir = Path(input_dir) if input_dir is not None else default_mem_input_dir()
        return parse_mem_directory(resolved_input_dir)
    return normalize_output_dataframe(data_df)


def normalize_csp_measure_for_graph(measure, graph_type=None) -> str | None:
    """Resolve CSP graph aliases, including the requested profile convenience alias."""
    normalized_measure = str(measure).strip().lower().replace("-", "_").replace(" ", "_")
    if normalized_measure == CSP_MEASURE_KEY:
        return CSP_MEASURE_KEY

    normalized_type = str(graph_type).strip().lower().replace("-", "_").replace(" ", "_") if graph_type is not None else ""
    if normalized_type in {"profile", "measure_profile"} and normalized_measure in {
        column_name.lower() for column_name in CSP_PROFILE_COLUMNS
    }:
        return CSP_MEASURE_KEY
    return None


def csp_profile_long_format(row: pd.Series) -> pd.DataFrame:
    """Convert one parsed row to long-format CSP profile data across RMT levels."""
    plot_rows = []
    for level in CSP_RMT_LEVELS:
        column_name = f"CSP_{level}"
        value = row.get(column_name, np.nan)
        if pd.isna(value):
            continue
        plot_rows.append(
            {
                "rmt_label": level,
                "rmt_percent": float(level),
                "value": float(value),
                "source_file": str(row.get("source_file", "")),
            }
        )
    return pd.DataFrame(plot_rows)


def apply_csp_ticks(axis):
    """Apply the fixed CSP %RMT tick layout."""
    tick_positions = [float(level) for level in CSP_RMT_LEVELS]
    axis.set_xticks(tick_positions)
    axis.set_xticklabels(CSP_RMT_LEVELS)
    axis.set_xlim(min(tick_positions) - 5.0, max(tick_positions) + 5.0)


def default_csp_axis_label() -> str:
    """Return the shared y-axis label for CSP duration plots."""
    return "CSP duration (ms)"


def default_csp_profile_title(matched_rows: pd.DataFrame, participant_id=None, mem_date=None, mem_filename=None) -> str:
    """Return the default single-session title for the CSP profile graph."""
    if mem_filename is not None:
        return (
            f"{matched_rows.iloc[0]['source_file']} | "
            f"{format_participant_label(matched_rows.iloc[0].get('ID', participant_id))} | "
            f"{matched_rows.iloc[0]['Date']} | {CSP_MEASURE_LABEL}"
        )

    normalized_date = normalize_mem_date(mem_date)
    return f"{format_participant_label(participant_id)} | {normalized_date} | {CSP_MEASURE_LABEL}"


def default_csp_over_time_title(participant_id) -> str:
    """Return the default longitudinal title for CSP plots."""
    return f"{format_participant_label(participant_id)} | CSP duration over time"


def default_csp_visit_profile_title(participant_id) -> str:
    """Return the default visit-profile title for CSP plots."""
    return f"{format_participant_label(participant_id)} | CSP profile by visit"


def csp_panel_title(value_column: str) -> str:
    """Return the display title for one CSP duration panel."""
    return CSP_PROFILE_COLUMN_LABELS.get(str(value_column), str(value_column).replace("_", " "))


def summarize_profile_rows(rows: pd.DataFrame, value_columns, source_label: str = "") -> pd.Series:
    """Average one set of wide value columns into a single representative profile row."""
    if rows.empty:
        raise ValueError("Cannot summarize an empty set of profile rows.")

    summary_record = {}
    numeric_rows = rows.copy()
    for column_name in value_columns:
        numeric_rows[column_name] = pd.to_numeric(numeric_rows[column_name], errors="coerce")
        available_values = numeric_rows[column_name].dropna()
        summary_record[column_name] = float(available_values.mean()) if not available_values.empty else np.nan

    for column_name in ["ID", "Age"]:
        numeric_values = pd.to_numeric(rows[column_name], errors="coerce").dropna()
        summary_record[column_name] = float(numeric_values.iloc[0]) if not numeric_values.empty else np.nan

    for column_name in ["Date", "Sex", "Subject_type", "Stimulated_cortex"]:
        if column_name not in rows.columns:
            summary_record[column_name] = np.nan
            continue
        values = rows[column_name].astype("string").fillna("").str.strip().replace("", pd.NA).dropna()
        summary_record[column_name] = str(values.iloc[0]) if not values.empty else np.nan

    summary_record["source_file"] = source_label
    return pd.Series(summary_record)


def prepare_csp_profile_group_rows(
    data_df: pd.DataFrame,
    highlight_rows: pd.DataFrame,
    exclude_highlight_from_groups: bool = True,
):
    """Split the dataframe into patient and control rows with any available CSP values."""
    plot_df = data_df.copy()
    for column_name in CSP_PROFILE_COLUMNS:
        plot_df[column_name] = pd.to_numeric(plot_df[column_name], errors="coerce")
    plot_df["Subject_type"] = (
        plot_df["Subject_type"].astype("string").fillna("").str.strip().str.capitalize()
    )

    source_series = plot_df["source_file"].astype("string").fillna("").str.strip()
    excluded_source_files = set()
    if exclude_highlight_from_groups and not highlight_rows.empty:
        excluded_source_files = set(
            highlight_rows["source_file"].astype("string").fillna("").str.strip().tolist()
        )
        excluded_source_files.discard("")
        if excluded_source_files:
            plot_df = plot_df[~source_series.isin(excluded_source_files)].copy()

    usable_rows = plot_df[plot_df[CSP_PROFILE_COLUMNS].notna().any(axis=1)].copy()
    patient_rows = usable_rows[usable_rows["Subject_type"] == "Patient"].copy()
    control_rows = usable_rows[usable_rows["Subject_type"] == "Control"].copy()
    return patient_rows.reset_index(drop=True), control_rows.reset_index(drop=True), excluded_source_files


def normalize_measure_key(measure) -> str:
    """Normalize a waveform measure alias to its canonical key."""
    normalized_measure = str(measure).strip().lower().replace(" ", "_")
    resolved_measure = WAVEFORM_MEASURE_ALIASES.get(normalized_measure)
    if resolved_measure is None:
        supported = ", ".join(sorted(WAVEFORM_MEASURE_CONFIGS))
        raise ValueError(f"Unsupported measure '{measure}'. Supported measures are: {supported}.")
    return resolved_measure


def waveform_measure_config(measure) -> dict:
    """Return plotting metadata for one waveform measure."""
    return WAVEFORM_MEASURE_CONFIGS[normalize_measure_key(measure)]


def waveform_value_columns(measure) -> list[str]:
    """Return the individual wide-value columns for one waveform measure."""
    config = waveform_measure_config(measure)
    return [f"{config['prefix']}_{isi}" for isi in config["isis"]]


def average_value_column_for_measure(measure) -> str:
    """Return the dataframe average column for one waveform measure."""
    return waveform_measure_config(measure)["avg_column"]


def format_isi_tick_label(isi_label: str) -> str:
    """Render an ISI label without the trailing `.0` when possible."""
    numeric_isi = float(str(isi_label).replace("ms", ""))
    return f"{int(numeric_isi)}" if numeric_isi.is_integer() else f"{numeric_isi:.1f}"


def waveform_tick_layout(measure, long_frames) -> tuple[list[float], list[str], tuple[float, float] | None]:
    """Return xtick positions, labels, and x-limits for ISIs that have data."""
    config = waveform_measure_config(measure)

    # Collect the set of ISI values that actually appear in the plotted data.
    available_isis: set[float] = set()
    for long_df in long_frames:
        if long_df is None or long_df.empty:
            continue
        available_isis.update(
            pd.to_numeric(long_df["isi_ms"], errors="coerce").dropna().tolist()
        )

    # Only include ticks for ISIs that have data.
    tick_pairs = []
    for isi in config["isis"]:
        isi_ms = float(isi.replace("ms", ""))
        if isi_ms in available_isis:
            tick_pairs.append((isi_ms, format_isi_tick_label(isi)))

    if not tick_pairs:
        return [], [], None

    tick_positions = [position for position, _ in tick_pairs]
    tick_labels = [label for _, label in tick_pairs]
    if len(tick_positions) == 1:
        x_pad = 0.3
    else:
        step_sizes = np.diff(tick_positions)
        smallest_step = float(np.min(step_sizes)) if len(step_sizes) else 0.3
        x_pad = max(0.18, smallest_step * 0.65)
    x_limits = (tick_positions[0] - x_pad, tick_positions[-1] + x_pad)
    return tick_positions, tick_labels, x_limits


def apply_waveform_ticks(axis, measure, long_frames):
    """Apply ISI ticks only up to the latest available ISI across plotted frames."""
    tick_positions, tick_labels, x_limits = waveform_tick_layout(measure, long_frames)
    if not tick_positions:
        return
    axis.set_xticks(tick_positions)
    axis.set_xticklabels(tick_labels)
    if x_limits is not None:
        axis.set_xlim(*x_limits)


def wrap_visit_tests_text(test_labels, width: int = VISIT_TEST_WRAP_WIDTH) -> str:
    """Wrap a visit's test list so it fits neatly inside summary tables."""
    if isinstance(test_labels, str):
        plain_text = test_labels.strip()
    else:
        labels = [str(label).strip() for label in list(test_labels) if str(label).strip()]
        plain_text = ", ".join(labels)
    if not plain_text:
        plain_text = "No extracted tests"
    return textwrap.fill(
        plain_text,
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
    )


def apply_visit_summary_table_layout(table, row_line_counts, bbox_height: float):
    """Resize visit-summary table rows to accommodate wrapped multi-line text."""
    row_line_counts = [max(1, int(line_count)) for line_count in row_line_counts]
    header_weight = 1.15
    row_weights = [1.0 + 0.72 * (line_count - 1) for line_count in row_line_counts]
    total_weight = header_weight + sum(row_weights)
    if total_weight <= 0:
        return

    base_height = float(bbox_height) / total_weight
    column_indices = sorted({column_index for (_, column_index) in table.get_celld().keys() if column_index >= 0})
    row_heights = [header_weight * base_height] + [row_weight * base_height for row_weight in row_weights]

    for row_index, row_height in enumerate(row_heights):
        for column_index in column_indices:
            cell = table.get_celld().get((row_index, column_index))
            if cell is None:
                continue
            cell.set_height(row_height)
            cell.get_text().set_wrap(True)
            cell.get_text().set_va("center")


def reference_line_for_value_column(value_column: str):
    """Return the default horizontal reference line for a plotted value column, if any."""
    normalized_value_column = str(value_column)
    for config in WAVEFORM_MEASURE_CONFIGS.values():
        if normalized_value_column == config["avg_column"]:
            return float(config["reference_line"])
        if normalized_value_column.startswith(f"{config['prefix']}_"):
            return float(config["reference_line"])
    return None


def _tsici_ylim(y_min: float, y_max: float, pad: float = 5.0):
    """Return (lo, hi) y-axis limits for T-SICI plots.

    Default range is 80-120 (centered on the 100% reference line).
    If data falls outside that range, expand so all points fit with padding.
    """
    lo = min(80.0, y_min - pad)
    hi = max(120.0, y_max + pad)
    return lo, hi


def default_measure_axis_label(measure, summary: bool = False) -> str:
    """Return a readable y-axis label for one waveform measure."""
    config = waveform_measure_config(measure)
    if summary:
        return f"{config['label']} (% Control, averaged available ISIs)"
    return "MEP (% Control)"


def default_measure_over_time_title(measure, participant_id) -> str:
    """Return the default longitudinal title for one waveform measure."""
    return f"{format_participant_label(participant_id)} | Averaged {waveform_measure_config(measure)['label']} over time"


def default_measure_visit_profile_title(measure, participant_id) -> str:
    """Return the default visit-profile title for one waveform measure."""
    return f"{format_participant_label(participant_id)} | {waveform_measure_config(measure)['label']} profile by visit"


def default_measure_profile_title(measure, matched_rows: pd.DataFrame, participant_id=None, mem_date=None, mem_filename=None) -> str:
    """Return the default single-session profile title for one waveform measure."""
    config = waveform_measure_config(measure)
    if mem_filename is not None:
        return (
            f"{matched_rows.iloc[0]['source_file']} | "
            f"{format_participant_label(matched_rows.iloc[0].get('ID', participant_id))} | "
            f"{matched_rows.iloc[0]['Date']} | {config['label']}"
        )

    normalized_date = normalize_mem_date(mem_date)
    return f"{format_participant_label(participant_id)} | {normalized_date} | {config['label']}"


def normalize_rmt_column(rmt_column) -> str:
    """Normalize an RMT column alias to one of the supported dataframe columns."""
    normalized_value = str(rmt_column).strip().lower().replace(" ", "")
    alias_map = {
        "rmt50": "RMT50",
        "50": "RMT50",
        "rmt200": "RMT200",
        "200": "RMT200",
        "rmt1000": "RMT1000",
        "1000": "RMT1000",
    }
    resolved_column = alias_map.get(normalized_value)
    if resolved_column is None:
        supported = ", ".join(RMT_COLUMNS)
        raise ValueError(f"Unsupported RMT column '{rmt_column}'. Supported RMT columns are: {supported}.")
    return resolved_column


def normalize_mem_date(mem_date) -> str:
    """Normalize a user-provided MEM date to dd/mm/yyyy."""
    parsed_date = pd.to_datetime(mem_date, dayfirst=True, errors="coerce")
    if pd.isna(parsed_date):
        raise ValueError(f"Could not parse MEM date: {mem_date}")
    return parsed_date.strftime("%d/%m/%Y")


def filter_participant_rows(data_df: pd.DataFrame, participant_id, mem_date) -> pd.DataFrame:
    """Return rows matching a participant ID and MEM date."""
    normalized_date = normalize_mem_date(mem_date)
    numeric_id = pd.to_numeric(data_df["ID"], errors="coerce")
    try:
        normalized_id = int(participant_id)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Could not parse participant ID: {participant_id}") from exc

    matched_rows = data_df[(numeric_id == normalized_id) & (data_df["Date"] == normalized_date)].copy()
    if matched_rows.empty:
        available_rows = (
            data_df[numeric_id == normalized_id][["Date", "source_file"]]
            .drop_duplicates()
            .sort_values(["Date", "source_file"])
        )
        if available_rows.empty:
            raise ValueError(f"No rows found for participant ID {normalized_id}.")
        available_dates = ", ".join(available_rows["Date"].dropna().astype(str).unique().tolist())
        raise ValueError(
            f"No rows found for participant ID {normalized_id} on {normalized_date}. "
            f"Available date(s): {available_dates}"
        )
    return matched_rows.sort_values(["source_file"]).reset_index(drop=True)


def filter_mem_filename_rows(data_df: pd.DataFrame, mem_filename) -> pd.DataFrame:
    """Return rows matching a MEM filename, case-insensitively."""
    requested_name = Path(str(mem_filename)).name.strip().lower()
    if not requested_name:
        raise ValueError("MEM filename must not be empty.")

    source_series = data_df["source_file"].astype("string").fillna("").str.strip().str.lower()
    matched_rows = data_df[source_series == requested_name].copy()
    if matched_rows.empty:
        raise ValueError(f"No rows found for MEM file: {Path(str(mem_filename)).name}")
    return matched_rows.sort_values(["source_file"]).reset_index(drop=True)


def resolve_selected_rows(data_df: pd.DataFrame, participant_id=None, mem_date=None, mem_filename=None) -> pd.DataFrame:
    """Resolve the user-selected MEM rows by filename or by participant/date."""
    if mem_filename is not None:
        return filter_mem_filename_rows(data_df, mem_filename=mem_filename)
    if participant_id is None or mem_date is None:
        raise ValueError("Provide either mem_filename, or both participant_id and mem_date.")
    return filter_participant_rows(data_df, participant_id=participant_id, mem_date=mem_date)


def keep_selected_case(data_df: pd.DataFrame, selected_rows: pd.DataFrame, base_mask: pd.Series) -> pd.DataFrame:
    """Keep rows matching *base_mask* while always preserving the highlighted case."""
    source_series = data_df["source_file"].astype("string").fillna("").str.strip()
    selected_source_files = set(
        selected_rows["source_file"].astype("string").fillna("").str.strip().tolist()
    )
    selected_source_files.discard("")
    final_mask = base_mask.fillna(False) | source_series.isin(selected_source_files)
    return data_df[final_mask].copy()


def normalize_match_by(match_by=None) -> list[str]:
    """Normalize one or more grouping selectors into a canonical ordered list."""
    if match_by is None:
        return []

    if isinstance(match_by, str):
        raw_tokens = (
            match_by.replace("+", ",")
            .replace("/", ",")
            .replace("|", ",")
            .split(",")
        )
    else:
        raw_tokens = list(match_by)

    alias_map = {
        "overall": None,
        "none": None,
        "all": None,
        "sex": "sex",
        "gender": "sex",
        "age": "age",
        "sex_age": ["sex", "age"],
        "age_sex": ["sex", "age"],
    }

    normalized_tokens = []
    for token in raw_tokens:
        cleaned_token = str(token).strip().lower()
        if not cleaned_token:
            continue
        mapped_token = alias_map.get(cleaned_token, cleaned_token)
        if mapped_token is None:
            continue
        if isinstance(mapped_token, list):
            normalized_tokens.extend(mapped_token)
        else:
            normalized_tokens.append(mapped_token)

    unsupported_tokens = [token for token in normalized_tokens if token not in {"sex", "age"}]
    if unsupported_tokens:
        unsupported_text = ", ".join(sorted(set(unsupported_tokens)))
        raise ValueError(
            f"Unsupported match_by value(s): {unsupported_text}. Supported values are: sex, age."
        )

    ordered_unique_tokens = []
    for token in normalized_tokens:
        if token not in ordered_unique_tokens:
            ordered_unique_tokens.append(token)
    return ordered_unique_tokens


def selected_case_value(selected_rows: pd.DataFrame, column_name: str):
    """Return the first non-missing value from the selected case for a given column."""
    series = selected_rows[column_name]
    if column_name == "Age":
        numeric_values = pd.to_numeric(series, errors="coerce").dropna()
        if numeric_values.empty:
            raise ValueError(f"The selected case has no recorded {column_name} value.")
        return float(numeric_values.iloc[0])

    normalized_values = (
        series.astype("string").fillna("").str.strip().replace("", pd.NA).dropna().unique()
    )
    if len(normalized_values) == 0:
        raise ValueError(f"The selected case has no recorded {column_name} value.")
    return str(normalized_values[0])


def filter_to_selected_characteristics(
    data_df: pd.DataFrame,
    selected_rows: pd.DataFrame,
    match_by=None,
    age_window: int = 5,
) -> tuple[pd.DataFrame, dict]:
    """
    Filter *data_df* to observations matching the highlighted case's characteristics.

    Supported selectors in *match_by*: `sex`, `age`, or both.
    """
    normalized_match_by = normalize_match_by(match_by=match_by)
    filtered_df = data_df.copy()
    group_info = {
        "match_by": normalized_match_by,
        "selected_sex": "",
        "selected_age": np.nan,
        "age_window": int(age_window),
    }

    for selector in normalized_match_by:
        if selector == "sex":
            selected_sex = selected_case_value(selected_rows, "Sex").upper()
            sex_series = filtered_df["Sex"].astype("string").fillna("").str.strip().str.upper()
            filtered_df = keep_selected_case(filtered_df, selected_rows, sex_series == selected_sex)
            group_info["selected_sex"] = selected_sex
        elif selector == "age":
            selected_age = float(selected_case_value(selected_rows, "Age"))
            age_series = pd.to_numeric(filtered_df["Age"], errors="coerce")
            age_mask = age_series.between(
                selected_age - int(age_window),
                selected_age + int(age_window),
                inclusive="both",
            )
            filtered_df = keep_selected_case(filtered_df, selected_rows, age_mask)
            group_info["selected_age"] = selected_age

    return filtered_df.reset_index(drop=True), group_info


def build_grouped_plot_text(
    match_info: dict,
    patient_label_base: str,
    control_label_base: str,
    title: str = None,
):
    """Build default plot labels from the requested matching characteristics.

    When *title* is provided the grouping criteria are appended as a
    ``" | <tag>"`` suffix so the rendered title always shows which cohort
    subset is displayed.
    """
    match_by = match_info.get("match_by", [])

    # -- Compute grouping descriptor parts (needed for title and labels) ----
    grouping_parts = []
    if "sex" in match_by and match_info.get("selected_sex"):
        grouping_parts.append(str(match_info["selected_sex"]))
    if "age" in match_by and pd.notna(match_info.get("selected_age", np.nan)):
        age_window = int(match_info.get("age_window", 0))
        grouping_parts.append(f"+/- {age_window} years")

    # Concise tag: "Overall", "Sex-matched (M)", "Age-matched (…)", etc.
    if not match_by:
        grouping_tag = "Overall"
    elif not grouping_parts:
        grouping_tag = "Matched"
    elif len(match_by) == 1 and match_by[0] == "sex":
        grouping_tag = f"Sex-matched ({grouping_parts[0]})"
    elif len(match_by) == 1 and match_by[0] == "age":
        grouping_tag = f"Age-matched ({grouping_parts[0]})"
    else:
        grouping_tag = "Matched (" + ", ".join(grouping_parts) + ")"

    # -- Resolve title -------------------------------------------------------
    if title is not None:
        resolved_title = f"{title} | {grouping_tag}"
    elif not match_by:
        resolved_title = "Overall grouped comparison"
    else:
        if not grouping_parts:
            resolved_title = "Matched grouped comparison"
        elif len(match_by) == 1 and match_by[0] == "sex":
            resolved_title = f"Sex-matched grouped comparison ({grouping_parts[0]})"
        elif len(match_by) == 1 and match_by[0] == "age":
            resolved_title = f"Age-matched grouped comparison ({grouping_parts[0]})"
        else:
            resolved_title = "Matched grouped comparison (" + ", ".join(grouping_parts) + ")"

    # -- Label suffix --------------------------------------------------------
    label_suffix = ""
    label_parts = []
    if "sex" in match_by and match_info.get("selected_sex"):
        label_parts.append(str(match_info["selected_sex"]))
    if "age" in match_by and pd.notna(match_info.get("selected_age", np.nan)):
        age_window = int(match_info.get("age_window", 0))
        label_parts.append(f"age {match_info['selected_age']:.0f} +/- {age_window}")
    if label_parts:
        label_suffix = " (" + ", ".join(label_parts) + ")"

    return (
        f"{patient_label_base}{label_suffix}",
        f"{control_label_base}{label_suffix}",
        resolved_title,
    )


def resolve_participant_context(
    data_df: pd.DataFrame,
    participant_id=None,
    mem_date=None,
    mem_filename=None,
):
    """Resolve a participant selection for longitudinal plotting."""
    numeric_id = pd.to_numeric(data_df["ID"], errors="coerce")

    if mem_filename is not None:
        selected_rows = filter_mem_filename_rows(data_df, mem_filename=mem_filename)
        selected_ids = pd.to_numeric(selected_rows["ID"], errors="coerce").dropna().astype(int).unique()
        if len(selected_ids) == 0:
            raise ValueError(f"MEM file {Path(str(mem_filename)).name} does not contain a valid participant ID.")
        if len(selected_ids) > 1:
            raise ValueError(f"MEM file {Path(str(mem_filename)).name} matches multiple participant IDs.")
        resolved_id = int(selected_ids[0])
    elif participant_id is not None:
        try:
            resolved_id = int(participant_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Could not parse participant ID: {participant_id}") from exc

        if mem_date is not None:
            selected_rows = filter_participant_rows(data_df, participant_id=resolved_id, mem_date=mem_date)
        else:
            participant_rows = data_df[numeric_id == resolved_id].copy()
            if participant_rows.empty:
                raise ValueError(f"No rows found for participant ID {resolved_id}.")
            selected_rows = participant_rows.sort_values(["Date", "source_file"]).reset_index(drop=True)
    else:
        raise ValueError("Provide participant_id or mem_filename for participant-over-time plotting.")

    participant_rows = data_df[numeric_id == resolved_id].copy()
    if participant_rows.empty:
        raise ValueError(f"No rows found for participant ID {resolved_id}.")
    participant_rows = participant_rows.sort_values(["Date", "source_file"]).reset_index(drop=True)
    return participant_rows, selected_rows.reset_index(drop=True), resolved_id


def build_participant_visit_summary(
    participant_rows: pd.DataFrame,
    value_column: str = "T_SICI_avg",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aggregate one participant's rows into one averaged value per visit date."""
    plot_rows = coerce_value_column(participant_rows, value_column=value_column)
    plot_rows["visit_date"] = pd.to_datetime(plot_rows["Date"], dayfirst=True, errors="coerce")
    plot_rows["source_file"] = plot_rows["source_file"].astype("string").fillna("").str.strip()
    plot_rows = plot_rows[plot_rows["visit_date"].notna()].copy()
    if plot_rows.empty:
        raise ValueError("This participant has no valid visit dates available for plotting.")

    numeric_rows = plot_rows[plot_rows[value_column].notna()].copy()
    if numeric_rows.empty:
        raise ValueError(f"This participant has no available '{value_column}' values to plot over time.")

    visit_summary = (
        numeric_rows.groupby("visit_date", as_index=False)
        .agg(
            visit_value=(value_column, "mean"),
            mem_file_count=("source_file", "size"),
            source_files=("source_file", lambda values: [str(value) for value in values if str(value)]),
        )
        .sort_values("visit_date")
        .reset_index(drop=True)
    )
    visit_summary["visit_label"] = visit_summary["visit_date"].dt.strftime("%d/%m/%Y")
    return visit_summary, numeric_rows.reset_index(drop=True)


def build_participant_visit_timeline_data(participant_rows: pd.DataFrame) -> pd.DataFrame:
    """Aggregate one participant's rows into one ordered visit-timeline table."""
    timeline_rows = participant_rows.copy()
    timeline_rows["visit_date"] = pd.to_datetime(timeline_rows["Date"], dayfirst=True, errors="coerce")
    timeline_rows["source_file"] = timeline_rows["source_file"].astype("string").fillna("").str.strip()
    timeline_rows = timeline_rows[timeline_rows["visit_date"].notna()].copy()
    if timeline_rows.empty:
        raise ValueError("This participant has no valid visit dates available for timeline plotting.")

    visit_timeline = (
        timeline_rows.groupby("visit_date", as_index=False)
        .agg(
            Date=("Date", "first"),
            mem_file_count=("source_file", "size"),
            source_files=("source_file", lambda values: [str(value) for value in values if str(value)]),
        )
        .sort_values("visit_date")
        .reset_index(drop=True)
    )
    visit_timeline["visit_number"] = np.arange(1, len(visit_timeline) + 1)
    visit_timeline["visit_label"] = visit_timeline["visit_date"].dt.strftime("%d/%m/%Y")
    visit_timeline["days_since_previous_visit"] = visit_timeline["visit_date"].diff().dt.days.astype("Int64")
    visit_timeline["days_since_first_visit"] = (
        visit_timeline["visit_date"] - visit_timeline["visit_date"].iloc[0]
    ).dt.days.astype("Int64")
    return visit_timeline


def summarize_visit_tests(visit_rows: pd.DataFrame) -> list[str]:
    """Return the ordered test labels present across one grouped visit."""
    test_labels = []
    for label, columns in VISIT_TEST_COLUMN_GROUPS:
        for column_name in columns:
            if column_name not in visit_rows.columns:
                continue
            numeric_values = pd.to_numeric(visit_rows[column_name], errors="coerce")
            if numeric_values.notna().any():
                test_labels.append(label)
                break
    return test_labels


def build_participant_visit_test_summary(participant_rows: pd.DataFrame) -> pd.DataFrame:
    """Build one visit-summary table with all extracted tests present on each date."""
    summary_rows = participant_rows.copy()
    summary_rows["visit_date"] = pd.to_datetime(summary_rows["Date"], dayfirst=True, errors="coerce")
    summary_rows["source_file"] = summary_rows["source_file"].astype("string").fillna("").str.strip()
    summary_rows = summary_rows[summary_rows["visit_date"].notna()].copy()
    if summary_rows.empty:
        raise ValueError("This participant has no valid visit dates available for visit-summary plotting.")

    visit_summary_rows = []
    previous_visit_date = None
    for visit_index, (visit_date, visit_group) in enumerate(summary_rows.groupby("visit_date", sort=True), start=1):
        elapsed_days = pd.NA if previous_visit_date is None else int((visit_date - previous_visit_date).days)
        test_labels = summarize_visit_tests(visit_group)
        tests_present_text = ", ".join(test_labels) if test_labels else "No extracted tests"
        tests_present_wrapped_text = wrap_visit_tests_text(tests_present_text)

        # Extract unique stimulated cortex values for this visit
        if "Stimulated_cortex" in visit_group.columns:
            cx_vals = (
                visit_group["Stimulated_cortex"].astype("string")
                .fillna("").str.strip().replace("", pd.NA).dropna().unique()
            )
            sides_tested = ", ".join(sorted(str(v) for v in cx_vals)) if len(cx_vals) > 0 else "N/A"
        else:
            sides_tested = "N/A"

        visit_summary_rows.append(
            {
                "visit_date": visit_date,
                "visit_number": visit_index,
                "Date": visit_group["Date"].iloc[0],
                "visit_label": visit_date.strftime("%d/%m/%Y"),
                "mem_file_count": int(visit_group["source_file"].ne("").sum()),
                "source_files": visit_group["source_file"].tolist(),
                "days_since_previous_visit": elapsed_days,
                "sides_tested": sides_tested,
                "tests_present": test_labels,
                "tests_present_text": tests_present_text,
                "tests_present_wrapped_text": tests_present_wrapped_text,
                "tests_present_line_count": tests_present_wrapped_text.count("\n") + 1,
            }
        )
        previous_visit_date = visit_date

    return pd.DataFrame(visit_summary_rows)


def build_participant_measure_visit_profiles(
    participant_rows: pd.DataFrame,
    measure="t_sici",
    merge_same_day: bool = True,
) -> pd.DataFrame:
    """Build one averaged waveform profile per visit date for a participant."""
    value_columns = waveform_value_columns(measure)
    return build_participant_value_column_visit_profiles(
        participant_rows=participant_rows,
        value_columns=value_columns,
        merge_same_day=merge_same_day,
    )


def build_participant_value_column_visit_profiles(
    participant_rows: pd.DataFrame,
    value_columns,
    merge_same_day: bool = True,
) -> pd.DataFrame:
    """Build one averaged visit profile from an arbitrary ordered list of value columns."""
    profile_rows = participant_rows.copy()
    for column_name in value_columns:
        profile_rows[column_name] = pd.to_numeric(profile_rows[column_name], errors="coerce")

    profile_rows["visit_date"] = pd.to_datetime(profile_rows["Date"], dayfirst=True, errors="coerce")
    profile_rows["source_file"] = profile_rows["source_file"].astype("string").fillna("").str.strip()
    profile_rows = profile_rows[profile_rows["visit_date"].notna()].copy()
    if profile_rows.empty:
        raise ValueError("This participant has no valid visit dates available for visit-profile plotting.")

    if merge_same_day:
        aggregation_map = {column_name: "mean" for column_name in value_columns}
        aggregation_map["source_file"] = lambda values: [str(value) for value in values if str(value)]
        aggregation_map["Date"] = "first"

        visit_profiles = (
            profile_rows.groupby("visit_date", as_index=False)
            .agg(aggregation_map)
            .sort_values("visit_date")
            .reset_index(drop=True)
        )
        visit_profiles["mem_file_count"] = visit_profiles["source_file"].apply(len)
        visit_profiles["profile_kind"] = "visit_average"
    else:
        visit_profiles = profile_rows.sort_values(["visit_date", "source_file"]).reset_index(drop=True)
        visit_profiles["mem_file_count"] = 1
        visit_profiles["profile_kind"] = "mem_file"

    visit_profiles["visit_label"] = visit_profiles["visit_date"].dt.strftime("%d/%m/%Y")
    visit_profiles["profile_label"] = visit_profiles["visit_label"]
    return visit_profiles


def build_participant_csp_visit_profiles(
    participant_rows: pd.DataFrame,
    merge_same_day: bool = True,
) -> pd.DataFrame:
    """Build one averaged CSP profile per visit date for a participant."""
    return build_participant_value_column_visit_profiles(
        participant_rows=participant_rows,
        value_columns=CSP_PROFILE_COLUMNS,
        merge_same_day=merge_same_day,
    )


def build_participant_visit_profiles(
    participant_rows: pd.DataFrame,
    merge_same_day: bool = True,
) -> pd.DataFrame:
    """Build one averaged T-SICI profile per visit date for a participant."""
    return build_participant_measure_visit_profiles(
        participant_rows=participant_rows,
        measure="t_sici",
        merge_same_day=merge_same_day,
    )


def draw_participant_visit_timeline_axis(
    axis,
    visit_timeline: pd.DataFrame,
    participant_label: str = None,
    title: str = None,
):
    """Render a visit-only timeline graph onto an existing matplotlib axis."""
    if visit_timeline.empty:
        raise ValueError("Visit timeline data must not be empty.")

    line_color = "#526A84"
    point_face = "#ECE8E0"
    timeline_y = np.zeros(len(visit_timeline), dtype=float)

    if len(visit_timeline) > 1:
        axis.plot(
            visit_timeline["visit_date"],
            timeline_y,
            color=line_color,
            linewidth=1.8,
            alpha=0.98,
            zorder=2,
        )

    axis.scatter(
        visit_timeline["visit_date"],
        timeline_y,
        s=230,
        facecolors=point_face,
        edgecolors=line_color,
        linewidths=1.2,
        alpha=0.98,
        zorder=3,
    )

    for row in visit_timeline.itertuples(index=False):
        axis.annotate(
            f"V{int(row.visit_number)}",
            (row.visit_date, 0.0),
            xytext=(0, 12),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=10,
            color="#2F3E4F",
        )

    if len(visit_timeline) == 1:
        single_date = visit_timeline.iloc[0]["visit_date"]
        axis.set_xlim(single_date - pd.Timedelta(days=14), single_date + pd.Timedelta(days=14))
    else:
        first_date = visit_timeline["visit_date"].iloc[0]
        last_date = visit_timeline["visit_date"].iloc[-1]
        date_span_days = max(1, int((last_date - first_date).days))
        pad_days = max(10, int(round(date_span_days * 0.08)))
        axis.set_xlim(first_date - pd.Timedelta(days=pad_days), last_date + pd.Timedelta(days=pad_days))

    if title is None:
        title = "Visit timeline"
        if participant_label:
            title = f"{participant_label} | Visit timeline"

    axis.set_title(title, fontsize=14, pad=14)
    axis.set_xlabel("Visit date")
    axis.set_xticks(visit_timeline["visit_date"])
    axis.set_xticklabels(visit_timeline["visit_label"], rotation=35, ha="right")
    axis.set_yticks([])
    axis.set_ylim(-0.65, 0.65)
    axis.set_facecolor("#FFFFFF")
    axis.grid(False)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.spines["left"].set_visible(False)
    axis.spines["bottom"].set_color("#73839A")
    axis.spines["bottom"].set_linewidth(1.1)
    axis.tick_params(axis="x", colors="#17202A", labelsize=10, length=0, pad=10)
    return axis


def waveform_long_format(row: pd.Series, measure="t_sici") -> pd.DataFrame:
    """Convert one parsed MEM row to long format for one waveform measure."""
    config = waveform_measure_config(measure)
    plot_rows = []
    for isi in config["isis"]:
        value = row.get(f"{config['prefix']}_{isi}", np.nan)
        if pd.isna(value):
            continue
        plot_rows.append(
            {
                "isi_label": isi,
                "isi_ms": float(isi.replace("ms", "")),
                "value": float(value),
                "source_file": str(row.get("source_file", "")),
            }
        )
    return pd.DataFrame(plot_rows)


def tsici_long_format(row: pd.Series) -> pd.DataFrame:
    """Backward-compatible wrapper for T-SICI long-format plotting data."""
    return waveform_long_format(row, measure="t_sici")


def draw_reference_line(axis, reference_value: float, label: str = None):
    """Draw a light dashed horizontal reference line, with an optional label."""
    axis.axhline(
        reference_value,
        color="#7E8FA8",
        linewidth=1.0,
        alpha=0.95,
        linestyle=(0, (3, 3)),
        zorder=1,
    )
    if label:
        axis.text(
            1.01,
            reference_value,
            label,
            transform=axis.get_yaxis_transform(),
            ha="left",
            va="bottom",
            fontsize=10,
            color="#526A84",
        )


def _format_group_stats(mean: float, sd: float) -> str:
    """Render ``"mean ± sd"`` for a cohort. Falls back to the mean alone
    when the sample SD is undefined (n < 2), and to an empty string when
    the mean itself isn't finite."""
    if not np.isfinite(mean):
        return ""
    if not np.isfinite(sd):
        return f"{mean:.2f}"
    return f"{mean:.2f} ± {sd:.2f}"


def _format_highlight_stats(
    cortex_values: list | None,
    per_cortex_means: list[float],
    fallback_value: float,
) -> str:
    """Render the highlight participant's values.

    When the highlight has data from more than one cortex each cortex is
    shown on its own line (e.g. ``"L: 75.20\\nR: 82.10"``). Otherwise the
    single pooled value is returned.
    """
    if (
        cortex_values
        and len(cortex_values) > 1
        and len(per_cortex_means) == len(cortex_values)
    ):
        parts = [
            f"{cv}: {val:.2f}"
            for cv, val in zip(cortex_values, per_cortex_means)
            if np.isfinite(val)
        ]
        if parts:
            return "\n".join(parts)
    if np.isfinite(fallback_value):
        return f"{fallback_value:.2f}"
    return ""


def default_value_axis_label(value_column: str) -> str:
    """Return a readable y-axis label for a parsed MEM value column."""
    for config in WAVEFORM_MEASURE_CONFIGS.values():
        if value_column == config["avg_column"]:
            return f"{config['label']} (% Control, averaged available ISIs)"
        if value_column.startswith(f"{config['prefix']}_"):
            suffix = value_column.replace(f"{config['prefix']}_", "")
            return f"{config['label']} {suffix}"
    if value_column in CSP_PROFILE_COLUMN_SET:
        level = value_column.replace("CSP_", "")
        return f"CSP duration at {level}% RMT (ms)"
    if value_column.startswith("CSPs_"):
        level = value_column.replace("CSPs_", "")
        return f"CSP start at {level}% RMT (ms)"
    if value_column.startswith("CSPe_"):
        level = value_column.replace("CSPe_", "")
        return f"CSP end at {level}% RMT (ms)"
    if value_column in RMT_COLUMNS:
        return "RMT value"
    return value_column.replace("_", " ")


def format_participant_label(participant_id) -> str:
    """Format a participant ID in the SNBR-000 style when possible."""
    try:
        return f"SNBR-{int(float(participant_id)):03d}"
    except (TypeError, ValueError):
        return "Selected case"


def build_highlight_category_label(
    highlight_rows: pd.DataFrame,
    participant_id=None,
    mem_date=None,
    mem_filename=None,
    highlight_label=None,
) -> str:
    """Build the category label for the highlighted observation."""
    if highlight_label:
        return str(highlight_label)

    first_row = highlight_rows.iloc[0]
    participant_text = format_participant_label(first_row.get("ID", participant_id))
    date_text = first_row.get("Date", np.nan)

    if mem_filename is not None:
        label_lines = [participant_text]
        if pd.notna(date_text):
            label_lines.append(str(date_text))
        return "\n".join(label_lines)

    normalized_date = normalize_mem_date(mem_date)
    label_lines = [format_participant_label(participant_id), normalized_date]
    return "\n".join(label_lines)


def coerce_value_column(data_df: pd.DataFrame, value_column: str) -> pd.DataFrame:
    """Return a copy with the plotting value column converted to numeric."""
    if value_column not in data_df.columns:
        raise ValueError(f"Column '{value_column}' is not present in the parsed MEM DataFrame.")
    updated_df = data_df.copy()
    updated_df[value_column] = pd.to_numeric(updated_df[value_column], errors="coerce")
    return updated_df


def summarize_highlight_value(highlight_rows: pd.DataFrame, value_column: str):
    """Return the numeric rows and aggregated value used for the highlighted point."""
    numeric_rows = coerce_value_column(highlight_rows, value_column=value_column)
    numeric_rows = numeric_rows[numeric_rows[value_column].notna()].copy()
    if numeric_rows.empty:
        selection_name = highlight_rows.iloc[0].get("source_file", "selected MEM rows")
        raise ValueError(f"No available '{value_column}' value found for {selection_name}.")
    return numeric_rows.reset_index(drop=True), float(numeric_rows[value_column].mean())


def prepare_group_rows(
    data_df: pd.DataFrame,
    highlight_rows: pd.DataFrame,
    value_column: str,
    exclude_highlight_from_groups: bool = True,
):
    """Split the normalized dataframe into patient and control rows for cohort plotting."""
    plot_df = coerce_value_column(data_df, value_column=value_column)
    plot_df["Subject_type"] = (
        plot_df["Subject_type"].astype("string").fillna("").str.strip().str.capitalize()
    )

    source_series = plot_df["source_file"].astype("string").fillna("").str.strip()
    excluded_source_files = set()
    if exclude_highlight_from_groups and not highlight_rows.empty:
        excluded_source_files = set(
            highlight_rows["source_file"].astype("string").fillna("").str.strip().tolist()
        )
        excluded_source_files.discard("")
        if excluded_source_files:
            plot_df = plot_df[~source_series.isin(excluded_source_files)].copy()

    usable_rows = plot_df[plot_df[value_column].notna()].copy()
    patient_rows = usable_rows[usable_rows["Subject_type"] == "Patient"].copy()
    control_rows = usable_rows[usable_rows["Subject_type"] == "Control"].copy()

    return patient_rows.reset_index(drop=True), control_rows.reset_index(drop=True), excluded_source_files


def draw_group_sd_lines(axis, specs, darken=0.5):
    """Overlay mean ± 1 SD whiskers on cohort violins.

    *specs* is an iterable of ``(x_position, mean, std, color)`` tuples — one
    per group. Each whisker is drawn in a darkened shade of the group's colour
    (scaled toward black by *darken*) at full opacity so it reads clearly
    against the pale violin body. Whiskers with a non-finite or non-positive SD
    are skipped (e.g. a cohort of one, whose sample SD is undefined). Returns
    the list of y-extents drawn so the caller can widen the axis limits to fit
    the caps.
    """
    from matplotlib.colors import to_rgb

    extents = []
    for x_pos, mean_value, std_value, color in specs:
        if not np.isfinite(mean_value) or not np.isfinite(std_value) or std_value <= 0:
            continue
        r, g, b = to_rgb(color)
        dark_color = (r * darken, g * darken, b * darken)
        axis.errorbar(
            x_pos,
            mean_value,
            yerr=std_value,
            fmt="none",
            ecolor=dark_color,
            elinewidth=1.8,
            capsize=7,
            capthick=1.8,
            alpha=1.0,
            zorder=4.5,
        )
        extents.extend([mean_value - std_value, mean_value + std_value])
    return extents


def jittered_x_positions(center_x: float, count: int, jitter_width: float = 0.18, seed: int = 0) -> np.ndarray:
    """Return deterministic jittered x positions for a categorical point plot."""
    if count <= 0:
        return np.array([], dtype=float)
    if count == 1:
        return np.array([center_x], dtype=float)

    rng = np.random.default_rng(seed)
    offsets = rng.uniform(-jitter_width, jitter_width, size=count)
    return center_x + offsets


def style_group_point_rows(
    group_rows: pd.DataFrame,
    category_key: str,
    category_label: str,
    value_column: str,
    jitter_seed: int,
) -> pd.DataFrame:
    """Attach plotting metadata for a point-plot category."""
    styled_rows = group_rows.sort_values([value_column, "source_file"]).reset_index(drop=True).copy()
    styled_rows["category_key"] = category_key
    styled_rows["category_label"] = category_label
    styled_rows["x_position"] = jittered_x_positions(
        center_x=POINTPLOT_CATEGORY_X[category_key],
        count=len(styled_rows),
        seed=jitter_seed,
    )
    return styled_rows


def plot_tsici_profile(participant_id=None, mem_date=None, mem_filename=None, input_dir=None, data_df=None, show: bool = True):
    """
    Plot a clean point-and-line T-SICI profile for one participant/date or one MEM filename.

    If multiple MEM files match the same participant/date, they are overlaid on the same axes
    and distinguished by source filename. If *mem_filename* is provided, it takes precedence.
    """
    try:
        import matplotlib
        if not show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError("matplotlib is required for plotting T-SICI profiles.") from exc

    data_df = load_mem_dataframe(input_dir=input_dir, data_df=data_df)
    matched_rows = resolve_selected_rows(
        data_df,
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
    )

    if mem_filename is not None:
        title_text = (
            f"{matched_rows.iloc[0]['source_file']} | "
            f"Participant {int(float(matched_rows.iloc[0]['ID'])):03d} | "
            f"{matched_rows.iloc[0]['Date']}"
        )
    else:
        normalized_date = normalize_mem_date(mem_date)
        title_text = f"Participant {int(participant_id):03d} | {normalized_date}"

    figure, axis = plt.subplots(figsize=STANDARD_FIGSIZE)

    color_cycle = ["#5B6F8A", "#A06C4F", "#5B8A72", "#8D5B7B", "#7B8797", "#4F6DA0"]
    global_values = []
    plotted_long_frames = []

    for index, row_dict in enumerate(matched_rows.to_dict(orient="records"), start=0):
        long_df = tsici_long_format(pd.Series(row_dict))
        if long_df.empty:
            continue
        plotted_long_frames.append(long_df)
        color = color_cycle[index % len(color_cycle)]
        global_values.extend(long_df["value"].tolist())
        axis.plot(
            long_df["isi_ms"],
            long_df["value"],
            color=color,
            linewidth=1.8,
            marker="o",
            markersize=11,
            markerfacecolor="#F1F4F8",
            markeredgecolor=color,
            markeredgewidth=1.4,
            label=row_dict["source_file"],
            zorder=3,
        )

    if not global_values:
        if mem_filename is not None:
            raise ValueError(f"MEM file {Path(str(mem_filename)).name} has no available T-SICI values to plot.")
        raise ValueError(f"Participant ID {int(participant_id)} has no available T-SICI values to plot on {normalized_date}.")

    axis.axhline(100.0, color="#8C9AAF", linewidth=1.0, alpha=0.9, zorder=1)
    apply_waveform_ticks(axis, "t_sici", plotted_long_frames)
    axis.set_xlabel("T-SICI interval")
    axis.set_ylabel("T-SICI value (% of baseline)")
    axis.set_title(title_text, fontsize=14, pad=14)

    y_min = min(global_values)
    y_max = max(global_values)
    axis.set_ylim(*_tsici_ylim(y_min, y_max))

    axis.set_facecolor("#FFFFFF")
    axis.grid(axis="y", color="#D8E0EA", linewidth=0.9, alpha=0.85)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.spines["left"].set_color("#73839A")
    axis.spines["bottom"].set_color("#73839A")
    axis.spines["left"].set_linewidth(1.1)
    axis.spines["bottom"].set_linewidth(1.1)
    axis.tick_params(axis="both", colors="#4C5B70", labelsize=11)

    if len(matched_rows) == 1:
        axis.text(
            0.99,
            0.97,
            matched_rows.iloc[0]["source_file"],
            transform=axis.transAxes,
            ha="right",
            va="top",
            fontsize=9,
            color="#68778C",
        )
    else:
        axis.legend(frameon=False, loc="best", fontsize=9, title="MEM file")

    figure.tight_layout()
    if show and plt.get_backend().lower() != "agg":
        plt.show()
    return figure, axis, matched_rows


def plot_tsici_group_comparison(
    participant_id=None,
    mem_date=None,
    mem_filename=None,
    input_dir=None,
    data_df=None,
    value_column: str = "T_SICI_avg",
    y_label: str = None,
    title: str = None,
    highlight_label: str = None,
    patient_label: str = "Patients",
    control_label: str = "Healthy controls",
    exclude_highlight_from_groups: bool = True,
    highlight_cortex_values: list | None = None,
    output_png=None,
    png_dpi: int = 300,
    show: bool = True,
):
    """
    Plot one highlighted MEM observation beside patient and control cohort point plots.

    The highlighted point can be selected by *mem_filename* or by *participant_id* plus
    *mem_date*. If multiple MEM files match the participant/date selection, their plotted
    value is averaged into one highlighted point. Cohort distributions are shown as violins
    with one overlaid point per observation. Set *output_png* to save the figure.
    """
    try:
        import matplotlib
        if not show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError("matplotlib is required for cohort comparison plots.") from exc

    data_df = load_mem_dataframe(input_dir=input_dir, data_df=data_df)
    highlight_rows = resolve_selected_rows(
        data_df,
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
    )
    numeric_highlight_rows, highlight_value = summarize_highlight_value(
        highlight_rows,
        value_column=value_column,
    )

    patient_rows, control_rows, excluded_source_files = prepare_group_rows(
        data_df=data_df,
        highlight_rows=highlight_rows,
        value_column=value_column,
        exclude_highlight_from_groups=exclude_highlight_from_groups,
    )

    if patient_rows.empty:
        raise ValueError(f"No patient rows with a '{value_column}' value are available for plotting.")
    if control_rows.empty:
        raise ValueError(f"No control rows with a '{value_column}' value are available for plotting.")

    patient_rows = style_group_point_rows(
        patient_rows,
        category_key="patient",
        category_label=f"{patient_label}\nn={len(patient_rows)}",
        value_column=value_column,
        jitter_seed=11,
    )
    control_rows = style_group_point_rows(
        control_rows,
        category_key="control",
        category_label=f"{control_label}\nn={len(control_rows)}",
        value_column=value_column,
        jitter_seed=29,
    )

    highlight_category_label = build_highlight_category_label(
        highlight_rows,
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
        highlight_label=highlight_label,
    )

    figure, axis = plt.subplots(figsize=STANDARD_FIGSIZE)

    patient_edge = "#526A84"
    control_edge = "#6B7280"
    highlight_edge = "#7F1D1D"
    patient_face = "#DCE6F2"
    control_face = "#E8E5DF"

    violin = axis.violinplot(
        [
            patient_rows[value_column].to_numpy(dtype=float),
            control_rows[value_column].to_numpy(dtype=float),
        ],
        positions=[
            POINTPLOT_CATEGORY_X["patient"],
            POINTPLOT_CATEGORY_X["control"],
        ],
        widths=0.56,
        showmeans=False,
        showmedians=False,
        showextrema=False,
    )
    violin_bodies = violin["bodies"]
    violin_bodies[0].set_facecolor(patient_face)
    violin_bodies[0].set_edgecolor(patient_edge)
    violin_bodies[0].set_alpha(0.42)
    violin_bodies[0].set_linewidth(1.0)
    violin_bodies[1].set_facecolor(control_face)
    violin_bodies[1].set_edgecolor(control_edge)
    violin_bodies[1].set_alpha(0.42)
    violin_bodies[1].set_linewidth(1.0)

    patient_mean = float(patient_rows[value_column].mean())
    control_mean = float(control_rows[value_column].mean())
    patient_std = float(patient_rows[value_column].std(ddof=1))
    control_std = float(control_rows[value_column].std(ddof=1))

    axis.scatter(
        patient_rows["x_position"],
        patient_rows[value_column],
        s=84,
        facecolors="#F8F8F6",
        edgecolors=patient_edge,
        linewidths=1.0,
        alpha=0.95,
        zorder=4,
    )
    axis.scatter(
        control_rows["x_position"],
        control_rows[value_column],
        s=84,
        facecolors="#F8F8F6",
        edgecolors=control_edge,
        linewidths=1.0,
        alpha=0.95,
        zorder=4,
    )
    # Highlight point(s) — split by cortex when requested
    _cortex_highlight_values = []
    if (
        highlight_cortex_values
        and len(highlight_cortex_values) > 1
        and "Stimulated_cortex" in highlight_rows.columns
    ):
        x_base = POINTPLOT_CATEGORY_X["highlight"]
        offsets = [-0.18, 0.18] if len(highlight_cortex_values) == 2 else [0.0]
        for ci, cx_val in enumerate(highlight_cortex_values):
            cx_rows = highlight_rows[
                highlight_rows["Stimulated_cortex"].astype("string").fillna("").str.strip() == cx_val
            ]
            cx_numeric = pd.to_numeric(cx_rows[value_column], errors="coerce").dropna()
            if cx_numeric.empty:
                continue
            cx_value = float(cx_numeric.mean())
            _cortex_highlight_values.append(cx_value)
            color, _ = cortex_color(cx_val, ci)
            x_pos = x_base + (offsets[ci] if ci < len(offsets) else 0.0)
            axis.scatter(
                [x_pos], [cx_value],
                s=190, facecolors=color, edgecolors="none",
                linewidths=0, alpha=0.98, zorder=5, label=str(cx_val),
            )
        axis.legend(frameon=False, loc="upper right", fontsize=9, title="Cortex", labelspacing=1.4)
    else:
        _cortex_highlight_values = [highlight_value]
        axis.scatter(
            [POINTPLOT_CATEGORY_X["highlight"]],
            [highlight_value],
            s=190,
            facecolors="#E53935",
            edgecolors=highlight_edge,
            linewidths=1.2,
            alpha=0.98,
            zorder=5,
        )

    axis.scatter(
        [POINTPLOT_CATEGORY_X["patient"]],
        [patient_mean],
        s=110,
        marker="D",
        facecolors=patient_edge,
        edgecolors="#FFFFFF",
        linewidths=1.0,
        alpha=0.98,
        zorder=5,
    )
    axis.scatter(
        [POINTPLOT_CATEGORY_X["control"]],
        [control_mean],
        s=110,
        marker="D",
        facecolors=control_edge,
        edgecolors="#FFFFFF",
        linewidths=1.0,
        alpha=0.98,
        zorder=5,
    )

    # Mean ± 1 SD whiskers on each cohort violin.
    sd_extents = draw_group_sd_lines(
        axis,
        [
            (POINTPLOT_CATEGORY_X["patient"], patient_mean, patient_std, patient_edge),
            (POINTPLOT_CATEGORY_X["control"], control_mean, control_std, control_edge),
        ],
    )

    y_values = (
        _cortex_highlight_values
        + patient_rows[value_column].tolist()
        + control_rows[value_column].tolist()
        + sd_extents
    )
    y_min = min(y_values)
    y_max = max(y_values)

    reference_line = reference_line_for_value_column(value_column)
    if reference_line is not None:
        draw_reference_line(axis, reference_line)

    # Append per-column summary stats below each x-tick label (replaces
    # the previous "mean ± sd" text that sat beside each diamond).
    highlight_stats = _format_highlight_stats(
        highlight_cortex_values, _cortex_highlight_values, highlight_value,
    )
    patient_stats = _format_group_stats(patient_mean, patient_std)
    control_stats = _format_group_stats(control_mean, control_std)

    highlight_tick = (
        f"{highlight_category_label}\n{highlight_stats}"
        if highlight_stats else highlight_category_label
    )
    patient_tick = patient_rows["category_label"].iloc[0]
    if patient_stats:
        patient_tick = f"{patient_tick}\n{patient_stats}"
    control_tick = control_rows["category_label"].iloc[0]
    if control_stats:
        control_tick = f"{control_tick}\n{control_stats}"

    axis.set_xlim(-0.55, 2.55)
    axis.set_ylim(*_tsici_ylim(y_min, y_max))
    axis.set_xticks(
        [
            POINTPLOT_CATEGORY_X["highlight"],
            POINTPLOT_CATEGORY_X["patient"],
            POINTPLOT_CATEGORY_X["control"],
        ]
    )
    axis.set_xticklabels([highlight_tick, patient_tick, control_tick])
    axis.set_ylabel(y_label or default_value_axis_label(value_column))

    if title:
        axis.set_title(title, fontsize=14, pad=16)

    axis.set_facecolor("#FFFFFF")
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.spines["left"].set_color("#73839A")
    axis.spines["bottom"].set_color("#73839A")
    axis.spines["left"].set_linewidth(1.1)
    axis.spines["bottom"].set_linewidth(1.1)
    axis.tick_params(axis="x", colors="#17202A", labelsize=11, length=0, pad=14)
    axis.tick_params(axis="y", colors="#4C5B70", labelsize=11)
    axis.grid(False)

    saved_png = ""
    if output_png is not None:
        output_path = Path(output_png)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(output_path, dpi=png_dpi, bbox_inches="tight")
        saved_png = str(output_path.resolve())

    plot_data = {
        "value_column": value_column,
        "highlight_value": highlight_value,
        "highlight_rows": highlight_rows.reset_index(drop=True),
        "highlight_value_rows": numeric_highlight_rows.reset_index(drop=True),
        "patient_rows": patient_rows.reset_index(drop=True),
        "control_rows": control_rows.reset_index(drop=True),
        "patient_mean": patient_mean,
        "control_mean": control_mean,
        "patient_std": patient_std,
        "control_std": control_std,
        "excluded_source_files": sorted(excluded_source_files),
        "saved_png": saved_png,
    }

    figure.tight_layout()
    if show and plt.get_backend().lower() != "agg":
        plt.show()
    return figure, axis, plot_data


def plot_tsici_grouped_graph(
    participant_id=None,
    mem_date=None,
    mem_filename=None,
    input_dir=None,
    data_df=None,
    match_by=None,
    age_window: int = 5,
    value_column: str = "T_SICI_avg",
    y_label: str = None,
    title: str = None,
    highlight_label: str = None,
    patient_label_base: str = "SNBR ALS",
    control_label_base: str = "SNBR Controls",
    exclude_highlight_from_groups: bool = True,
    highlight_cortex_values: list | None = None,
    output_png=None,
    png_dpi: int = 300,
    show: bool = True,
):
    """
    Create a grouped cohort graph in one line by naming the matching characteristics.

    Examples
    --------
    plot_tsici_grouped_graph(mem_filename="SNBR-079-TP3C50214A.MEM", data_df=df)
    plot_tsici_grouped_graph(mem_filename="SNBR-079-TP3C50214A.MEM", data_df=df, match_by="sex")
    plot_tsici_grouped_graph(mem_filename="SNBR-079-TP3C50214A.MEM", data_df=df, match_by=["sex", "age"], age_window=5)
    """
    resolved_df = load_mem_dataframe(input_dir=input_dir, data_df=data_df)
    highlight_rows = resolve_selected_rows(
        resolved_df,
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
    )
    filtered_df, match_info = filter_to_selected_characteristics(
        resolved_df,
        selected_rows=highlight_rows,
        match_by=match_by,
        age_window=age_window,
    )
    patient_label, control_label, resolved_title = build_grouped_plot_text(
        match_info=match_info,
        patient_label_base=patient_label_base,
        control_label_base=control_label_base,
        title=title,
    )

    figure, axis, plot_data = plot_tsici_group_comparison(
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
        data_df=filtered_df,
        value_column=value_column,
        y_label=y_label,
        title=resolved_title,
        highlight_label=highlight_label,
        patient_label=patient_label,
        control_label=control_label,
        exclude_highlight_from_groups=exclude_highlight_from_groups,
        highlight_cortex_values=highlight_cortex_values,
        output_png=output_png,
        png_dpi=png_dpi,
        show=show,
    )
    plot_data["match_info"] = match_info
    plot_data["filtered_data_df"] = filtered_df.reset_index(drop=True)
    return figure, axis, plot_data


def plot_participant_tsici_over_time(
    participant_id=None,
    mem_date=None,
    mem_filename=None,
    input_dir=None,
    data_df=None,
    value_column: str = "T_SICI_avg",
    y_label: str = None,
    title: str = None,
    group_by_cortex: bool = False,
    output_png=None,
    png_dpi: int = 300,
    show: bool = True,
):
    """
    Plot one participant's averaged T-SICI value over time across visit dates.

    Multiple MEM files collected on the same date are averaged into a single visit point.
    The participant can be selected by *participant_id* alone, by *participant_id* plus
    *mem_date*, or by *mem_filename*.

    When *group_by_cortex* is True and the data contains multiple Stimulated_cortex
    values, separate lines are drawn for each cortex side with a color legend.
    """
    try:
        import matplotlib
        if not show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError("matplotlib is required for participant-over-time plots.") from exc

    resolved_df = load_mem_dataframe(input_dir=input_dir, data_df=data_df)
    participant_rows, selected_rows, resolved_id = resolve_participant_context(
        resolved_df,
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
    )

    # Determine whether to split by cortex
    _do_cortex_split = False
    _cortex_vals = []
    if group_by_cortex and "Stimulated_cortex" in participant_rows.columns:
        _cortex_vals = sorted(
            participant_rows["Stimulated_cortex"].astype("string")
            .fillna("").str.strip().replace("", pd.NA).dropna().unique()
        )
        if len(_cortex_vals) > 1:
            _do_cortex_split = True

    figure, axis = plt.subplots(figsize=STANDARD_FIGSIZE)

    all_y_values = []
    all_visit_dates = set()

    if _do_cortex_split:
        for ci, cx_val in enumerate(_cortex_vals):
            cx_rows = participant_rows[
                participant_rows["Stimulated_cortex"].astype("string").fillna("").str.strip() == cx_val
            ]
            cx_summary, _ = build_participant_visit_summary(cx_rows, value_column=value_column)
            if cx_summary.empty:
                continue
            color, face = cortex_color(cx_val, ci)
            all_y_values.extend(cx_summary["visit_value"].tolist())
            all_visit_dates.update(cx_summary["visit_date"].tolist())
            if len(cx_summary) > 1:
                axis.plot(
                    cx_summary["visit_date"], cx_summary["visit_value"],
                    color=color, linewidth=1.4, alpha=0.98, zorder=2,
                )
            axis.scatter(
                cx_summary["visit_date"], cx_summary["visit_value"],
                s=270, facecolors=face, edgecolors=color,
                linewidths=1.2, alpha=0.98, zorder=3, label=str(cx_val),
            )
        # Shared x-axis from all visit dates
        visit_summary, numeric_rows = build_participant_visit_summary(
            participant_rows, value_column=value_column,
        )
    else:
        visit_summary, numeric_rows = build_participant_visit_summary(
            participant_rows, value_column=value_column,
        )
        line_color = "#526A84"
        point_face = "#ECE8E0"
        all_y_values = visit_summary["visit_value"].tolist()
        if len(visit_summary) > 1:
            axis.plot(
                visit_summary["visit_date"], visit_summary["visit_value"],
                color=line_color, linewidth=1.4, alpha=0.98, zorder=2,
            )
        axis.scatter(
            visit_summary["visit_date"], visit_summary["visit_value"],
            s=270, facecolors=point_face, edgecolors=line_color,
            linewidths=1.2, alpha=0.98, zorder=3,
        )

    reference_line = reference_line_for_value_column(value_column)
    if reference_line is not None:
        draw_reference_line(axis, reference_line)

    y_min = min(all_y_values)
    y_max = max(all_y_values)

    axis.set_ylim(*_tsici_ylim(y_min, y_max))
    axis.set_xticks(visit_summary["visit_date"])
    axis.set_xticklabels(visit_summary["visit_label"], rotation=55, ha="right")
    axis.set_xlabel("Visit date")
    axis.set_ylabel(y_label or default_value_axis_label(value_column))

    if title is None:
        title = f"{format_participant_label(resolved_id)} | Averaged T-SICI over time"
    axis.set_title(title, fontsize=14, pad=14)

    axis.set_facecolor("#FFFFFF")
    axis.grid(False)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.spines["left"].set_color("#73839A")
    axis.spines["bottom"].set_color("#73839A")
    axis.spines["left"].set_linewidth(1.1)
    axis.spines["bottom"].set_linewidth(1.1)
    axis.tick_params(axis="x", colors="#17202A", labelsize=11, length=0, pad=12)
    axis.tick_params(axis="y", colors="#4C5B70", labelsize=11)

    if _do_cortex_split:
        axis.legend(frameon=False, loc="best", fontsize=9, title="Stimulated cortex", labelspacing=1.4)

    saved_png = ""
    if output_png is not None:
        output_path = Path(output_png)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(output_path, dpi=png_dpi, bbox_inches="tight")
        saved_png = str(output_path.resolve())

    plot_data = {
        "value_column": value_column,
        "participant_id": resolved_id,
        "participant_rows": participant_rows.reset_index(drop=True),
        "selected_rows": selected_rows.reset_index(drop=True),
        "value_rows": numeric_rows.reset_index(drop=True),
        "visit_summary": visit_summary.reset_index(drop=True),
        "visit_count": int(len(visit_summary)),
        "saved_png": saved_png,
    }

    figure.tight_layout()
    if show and plt.get_backend().lower() != "agg":
        plt.show()
    return figure, axis, plot_data


def plot_participant_visit_timeline(
    participant_id=None,
    mem_date=None,
    mem_filename=None,
    input_dir=None,
    data_df=None,
    title: str = None,
    output_png=None,
    png_dpi: int = 300,
    show: bool = True,
):
    """
    Plot one participant's visit dates as a visit-only timeline.

    Multiple MEM files collected on the same date are merged into one visit marker.
    The participant can be selected by *participant_id* alone, by *participant_id* plus
    *mem_date*, or by *mem_filename*.
    """
    try:
        import matplotlib
        if not show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError("matplotlib is required for participant visit-timeline plots.") from exc

    resolved_df = load_mem_dataframe(input_dir=input_dir, data_df=data_df)
    participant_rows, selected_rows, resolved_id = resolve_participant_context(
        resolved_df,
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
    )
    visit_timeline = build_participant_visit_timeline_data(participant_rows)

    figure, axis = plt.subplots(figsize=STANDARD_FIGSIZE)
    draw_participant_visit_timeline_axis(
        axis=axis,
        visit_timeline=visit_timeline,
        participant_label=format_participant_label(resolved_id),
        title=title,
    )

    saved_png = ""
    if output_png is not None:
        output_path = Path(output_png)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(output_path, dpi=png_dpi, bbox_inches="tight")
        saved_png = str(output_path.resolve())

    plot_data = {
        "participant_id": resolved_id,
        "participant_rows": participant_rows.reset_index(drop=True),
        "selected_rows": selected_rows.reset_index(drop=True),
        "visit_timeline": visit_timeline.reset_index(drop=True),
        "visit_count": int(len(visit_timeline)),
        "saved_png": saved_png,
    }

    figure.tight_layout()
    if show and plt.get_backend().lower() != "agg":
        plt.show()
    return figure, axis, plot_data


def plot_participant_tsici_visit_profiles(
    participant_id=None,
    mem_date=None,
    mem_filename=None,
    input_dir=None,
    data_df=None,
    merge_same_day: bool = True,
    y_label: str = None,
    title: str = None,
    output_png=None,
    png_dpi: int = 300,
    show: bool = True,
):
    """
    Plot one T-SICI profile subplot per visit for a participant.

    Each subplot shows the visit's individual T-SICI ISI values across the standard
    1.0-3.5ms intervals. By default, multiple MEM files from the same date are averaged
    into one visit profile.
    """
    try:
        import matplotlib
        if not show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError("matplotlib is required for visit-profile plots.") from exc

    resolved_df = load_mem_dataframe(input_dir=input_dir, data_df=data_df)
    participant_rows, selected_rows, resolved_id = resolve_participant_context(
        resolved_df,
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
    )
    visit_profiles = build_participant_visit_profiles(
        participant_rows,
        merge_same_day=merge_same_day,
    )

    valid_profile_rows = []
    all_values = []
    for row_dict in visit_profiles.to_dict(orient="records"):
        long_df = tsici_long_format(pd.Series(row_dict))
        if long_df.empty:
            continue
        valid_profile_rows.append((row_dict, long_df))
        all_values.extend(long_df["value"].tolist())

    if not valid_profile_rows:
        raise ValueError("This participant has no visit profiles with available T-SICI values to plot.")

    profile_count = len(valid_profile_rows)
    n_cols = min(3, max(1, profile_count))
    n_rows = int(np.ceil(profile_count / n_cols))
    figure, axes = plt.subplots(
        n_rows,
        n_cols,
        figsize=(max(STANDARD_FIGSIZE[0], 4.4 * n_cols), max(STANDARD_FIGSIZE[1], 4.1 * n_rows)),
        sharex=True,
        sharey=True,
    )
    axes = np.atleast_1d(axes).ravel()

    line_color = "#526A84"
    point_face = "#ECE8E0"
    tick_positions, tick_labels, x_limits = waveform_tick_layout(
        "t_sici",
        [long_df for _, long_df in valid_profile_rows],
    )

    y_min = min(all_values)
    y_max = max(all_values)
    ylim_lo, ylim_hi = _tsici_ylim(y_min, y_max)

    for axis_index, axis in enumerate(axes):
        if axis_index >= profile_count:
            axis.set_visible(False)
            continue

        row_dict, long_df = valid_profile_rows[axis_index]
        axis.plot(
            long_df["isi_ms"],
            long_df["value"],
            color=line_color,
            linewidth=1.4,
            alpha=0.98,
            zorder=2,
        )
        axis.scatter(
            long_df["isi_ms"],
            long_df["value"],
            s=220,
            facecolors=point_face,
            edgecolors=line_color,
            linewidths=1.1,
            alpha=0.98,
            zorder=3,
        )
        axis.axhline(100.0, color="#7E8FA8", linewidth=1.0, alpha=0.95, zorder=1)
        axis.set_ylim(ylim_lo, ylim_hi)
        axis.set_xticks(tick_positions)
        axis.set_xticklabels(tick_labels)
        if x_limits is not None:
            axis.set_xlim(*x_limits)
        axis.set_title(str(row_dict["visit_label"]), fontsize=12, pad=10)

        axis.set_facecolor("#FFFFFF")
        axis.grid(False)
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        axis.spines["left"].set_color("#73839A")
        axis.spines["bottom"].set_color("#73839A")
        axis.spines["left"].set_linewidth(1.1)
        axis.spines["bottom"].set_linewidth(1.1)
        axis.tick_params(axis="x", colors="#17202A", labelsize=10, length=0, pad=10)
        axis.tick_params(axis="y", colors="#4C5B70", labelsize=10)

        if axis_index % n_cols == 0:
            axis.set_ylabel(y_label or "T-SICI (% of baseline)")

    if title is None:
        title = f"{format_participant_label(resolved_id)} | T-SICI profile by visit"
    figure.suptitle(title, fontsize=16, y=0.99)

    saved_png = ""
    if output_png is not None:
        output_path = Path(output_png)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(output_path, dpi=png_dpi, bbox_inches="tight")
        saved_png = str(output_path.resolve())

    plot_data = {
        "participant_id": resolved_id,
        "participant_rows": participant_rows.reset_index(drop=True),
        "selected_rows": selected_rows.reset_index(drop=True),
        "visit_profiles": visit_profiles.reset_index(drop=True),
        "profile_count": int(profile_count),
        "saved_png": saved_png,
    }

    figure.tight_layout(rect=(0.0, 0.0, 1.0, 0.95))
    if show and plt.get_backend().lower() != "agg":
        plt.show()
    return figure, axes, plot_data


def plot_measure_profile(
    measure="t_sici",
    participant_id=None,
    mem_date=None,
    mem_filename=None,
    input_dir=None,
    data_df=None,
    y_label: str = None,
    title: str = None,
    show: bool = True,
):
    """Plot one clean waveform profile for the requested measure."""
    try:
        import matplotlib
        if not show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError("matplotlib is required for waveform profile plots.") from exc

    config = waveform_measure_config(measure)
    resolved_df = load_mem_dataframe(input_dir=input_dir, data_df=data_df)
    matched_rows = resolve_selected_rows(
        resolved_df,
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
    )

    resolved_title = title or default_measure_profile_title(
        measure,
        matched_rows=matched_rows,
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
    )

    figure, axis = plt.subplots(figsize=STANDARD_FIGSIZE)
    point_edge = "#4B5E79"
    point_face = "#ECE8E0"
    global_values = []
    plotted_long_frames = []
    color_cycle = ["#526A84", "#8A6748", "#5B8A72", "#8D5B7B", "#6A7E95", "#3E6891"]

    # Determine if cortex values should be used for legend labels
    _use_cortex_legend = False
    if (
        len(matched_rows) > 1
        and "Stimulated_cortex" in matched_rows.columns
    ):
        _cortex_vals = (
            matched_rows["Stimulated_cortex"].astype("string")
            .fillna("").str.strip().replace("", pd.NA).dropna().unique()
        )
        if len(_cortex_vals) > 1:
            _use_cortex_legend = True

    for index, row_dict in enumerate(matched_rows.to_dict(orient="records"), start=0):
        long_df = waveform_long_format(pd.Series(row_dict), measure=measure)
        if long_df.empty:
            continue
        plotted_long_frames.append(long_df)
        if _use_cortex_legend:
            raw_cx = str(row_dict.get("Stimulated_cortex", "")).strip()
            series_color, _ = cortex_color(raw_cx, index)
        else:
            series_color = color_cycle[index % len(color_cycle)]
        global_values.extend(long_df["value"].tolist())
        axis.plot(
            long_df["isi_ms"],
            long_df["value"],
            color=series_color,
            linewidth=1.2,
            alpha=0.98,
            zorder=2,
        )

        # Choose legend label: cortex value when available, else source_file
        if len(matched_rows) > 1:
            if _use_cortex_legend:
                raw_cortex = str(row_dict.get("Stimulated_cortex", "")).strip()
                legend_label = raw_cortex if raw_cortex else row_dict["source_file"]
            else:
                legend_label = row_dict["source_file"]
        else:
            legend_label = None

        axis.scatter(
            long_df["isi_ms"],
            long_df["value"],
            s=220,
            facecolors=point_face,
            edgecolors=series_color if len(matched_rows) > 1 else point_edge,
            linewidths=1.1,
            alpha=0.98,
            zorder=3,
            label=legend_label,
        )

    if not global_values:
        if mem_filename is not None:
            raise ValueError(
                f"MEM file {Path(str(mem_filename)).name} has no available {config['label']} values to plot."
            )
        normalized_date = normalize_mem_date(mem_date)
        raise ValueError(
            f"Participant ID {int(participant_id)} has no available {config['label']} values to plot on {normalized_date}."
        )

    y_min = min(global_values)
    y_max = max(global_values)

    apply_waveform_ticks(axis, measure, plotted_long_frames)
    axis.set_xlabel("ISI (ms)")
    axis.set_ylabel(y_label or default_measure_axis_label(measure))
    axis.set_title(resolved_title, fontsize=14, pad=14)
    if measure == "t_sici":
        axis.set_ylim(*_tsici_ylim(y_min, y_max))
    else:
        y_pad = max(6.0, (y_max - y_min) * 0.18 if y_max > y_min else 8.0)
        axis.set_ylim(y_min - y_pad, y_max + y_pad)

    # Draw the reference line AFTER ylim is set so we can suppress it when
    # the reference (e.g. 100%) falls far outside the data range. Otherwise
    # its label would be rendered far above the axes and bbox_inches="tight"
    # would stretch the saved figure into an unreadable tall strip.
    if config["reference_line"] is not None:
        ref_val = float(config["reference_line"])
        y_lo, y_hi = axis.get_ylim()
        if y_lo <= ref_val <= y_hi:
            draw_reference_line(axis, ref_val, label="100%")
    axis.set_facecolor("#FFFFFF")
    axis.grid(False)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.spines["left"].set_color("#73839A")
    axis.spines["bottom"].set_color("#73839A")
    axis.spines["left"].set_linewidth(1.1)
    axis.spines["bottom"].set_linewidth(1.1)
    axis.tick_params(axis="both", colors="#4C5B70", labelsize=11)

    if len(matched_rows) > 1:
        legend_title = "Stimulated cortex" if _use_cortex_legend else "MEM file"
        axis.legend(frameon=False, loc="best", fontsize=9, title=legend_title)

    figure.tight_layout()
    if show and plt.get_backend().lower() != "agg":
        plt.show()
    return figure, axis, matched_rows


def plot_measure_group_comparison(
    measure="t_sici",
    participant_id=None,
    mem_date=None,
    mem_filename=None,
    input_dir=None,
    data_df=None,
    value_column: str = None,
    y_label: str = None,
    title: str = None,
    highlight_label: str = None,
    patient_label: str = "Patients",
    control_label: str = "Healthy controls",
    exclude_highlight_from_groups: bool = True,
    output_png=None,
    png_dpi: int = 300,
    show: bool = True,
):
    """Create one cohort-comparison figure for any waveform measure."""
    config = waveform_measure_config(measure)
    resolved_value_column = value_column or config["avg_column"]
    return plot_tsici_group_comparison(
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
        input_dir=input_dir,
        data_df=data_df,
        value_column=resolved_value_column,
        y_label=y_label or default_measure_axis_label(measure, summary=True),
        title=title,
        highlight_label=highlight_label,
        patient_label=patient_label,
        control_label=control_label,
        exclude_highlight_from_groups=exclude_highlight_from_groups,
        output_png=output_png,
        png_dpi=png_dpi,
        show=show,
    )


def plot_measure_grouped_graph(
    measure="t_sici",
    participant_id=None,
    mem_date=None,
    mem_filename=None,
    input_dir=None,
    data_df=None,
    match_by=None,
    age_window: int = 5,
    value_column: str = None,
    y_label: str = None,
    title: str = None,
    highlight_label: str = None,
    patient_label_base: str = "SNBR ALS",
    control_label_base: str = "SNBR Controls",
    exclude_highlight_from_groups: bool = True,
    highlight_cortex_values: list | None = None,
    output_png=None,
    png_dpi: int = 300,
    show: bool = True,
):
    """Create one grouped cohort figure for any waveform measure."""
    config = waveform_measure_config(measure)
    resolved_value_column = value_column or config["avg_column"]
    return plot_tsici_grouped_graph(
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
        input_dir=input_dir,
        data_df=data_df,
        match_by=match_by,
        age_window=age_window,
        value_column=resolved_value_column,
        y_label=y_label or default_measure_axis_label(measure, summary=True),
        title=title,
        highlight_label=highlight_label,
        patient_label_base=patient_label_base,
        control_label_base=control_label_base,
        exclude_highlight_from_groups=exclude_highlight_from_groups,
        highlight_cortex_values=highlight_cortex_values,
        output_png=output_png,
        png_dpi=png_dpi,
        show=show,
    )


def plot_participant_measure_over_time(
    measure="t_sici",
    participant_id=None,
    mem_date=None,
    mem_filename=None,
    input_dir=None,
    data_df=None,
    value_column: str = None,
    y_label: str = None,
    title: str = None,
    group_by_cortex: bool = False,
    output_png=None,
    png_dpi: int = 300,
    show: bool = True,
):
    """Plot one participant's averaged waveform value over time for any measure."""
    config = waveform_measure_config(measure)
    resolved_df = load_mem_dataframe(input_dir=input_dir, data_df=data_df)
    _, _, resolved_id = resolve_participant_context(
        resolved_df,
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
    )
    resolved_value_column = value_column or config["avg_column"]
    resolved_title = title or default_measure_over_time_title(measure, resolved_id)
    return plot_participant_tsici_over_time(
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
        data_df=resolved_df,
        value_column=resolved_value_column,
        y_label=y_label or default_measure_axis_label(measure, summary=True),
        title=resolved_title,
        group_by_cortex=group_by_cortex,
        output_png=output_png,
        png_dpi=png_dpi,
        show=show,
    )


def plot_participant_measure_visit_profiles(
    measure="t_sici",
    participant_id=None,
    mem_date=None,
    mem_filename=None,
    input_dir=None,
    data_df=None,
    merge_same_day: bool = True,
    y_label: str = None,
    title: str = None,
    group_by_cortex: bool = False,
    output_png=None,
    png_dpi: int = 300,
    show: bool = True,
):
    """Plot one waveform-profile subplot per visit for a participant.

    When *group_by_cortex* is True and visit data contains multiple cortex
    values, both cortex profiles are overlaid on each subplot with a legend.
    """
    try:
        import matplotlib
        if not show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError("matplotlib is required for visit-profile plots.") from exc

    config = waveform_measure_config(measure)
    resolved_df = load_mem_dataframe(input_dir=input_dir, data_df=data_df)
    participant_rows, selected_rows, resolved_id = resolve_participant_context(
        resolved_df,
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
    )

    # Determine cortex split
    _do_cortex_split = False
    _cortex_vals = []
    if group_by_cortex and "Stimulated_cortex" in participant_rows.columns:
        _cortex_vals = sorted(
            participant_rows["Stimulated_cortex"].astype("string")
            .fillna("").str.strip().replace("", pd.NA).dropna().unique()
        )
        if len(_cortex_vals) > 1:
            _do_cortex_split = True

    visit_profiles = build_participant_measure_visit_profiles(
        participant_rows,
        measure=measure,
        merge_same_day=merge_same_day,
    )

    # When doing cortex split, also build per-cortex visit profiles
    _cortex_visit_profiles = {}
    if _do_cortex_split:
        for cx_val in _cortex_vals:
            cx_rows = participant_rows[
                participant_rows["Stimulated_cortex"].astype("string").fillna("").str.strip() == cx_val
            ]
            try:
                cx_profiles = build_participant_measure_visit_profiles(
                    cx_rows, measure=measure, merge_same_day=merge_same_day,
                )
                _cortex_visit_profiles[cx_val] = cx_profiles
            except (ValueError, KeyError):
                pass

    valid_profile_rows = []
    all_values = []
    for row_dict in visit_profiles.to_dict(orient="records"):
        long_df = waveform_long_format(pd.Series(row_dict), measure=measure)
        if long_df.empty:
            continue
        valid_profile_rows.append((row_dict, long_df))
        all_values.extend(long_df["value"].tolist())

    # Also include cortex-split values for y-axis limits
    if _do_cortex_split:
        for cx_val, cx_profiles in _cortex_visit_profiles.items():
            for row_dict in cx_profiles.to_dict(orient="records"):
                long_df = waveform_long_format(pd.Series(row_dict), measure=measure)
                if not long_df.empty:
                    all_values.extend(long_df["value"].tolist())

    if not valid_profile_rows:
        raise ValueError(
            f"This participant has no visit profiles with available {config['label']} values to plot."
        )

    profile_count = len(valid_profile_rows)
    n_cols = min(3, max(1, profile_count))
    n_rows = int(np.ceil(profile_count / n_cols))
    figure, axes = plt.subplots(
        n_rows,
        n_cols,
        figsize=(max(STANDARD_FIGSIZE[0], 4.4 * n_cols), max(STANDARD_FIGSIZE[1], 4.1 * n_rows)),
        sharex=True,
        sharey=True,
    )
    axes = np.atleast_1d(axes).ravel()

    tick_positions, tick_labels, x_limits = waveform_tick_layout(
        measure,
        [long_df for _, long_df in valid_profile_rows],
    )
    y_min = min(all_values)
    y_max = max(all_values)
    if measure == "t_sici":
        ylim_lo, ylim_hi = _tsici_ylim(y_min, y_max)
    else:
        y_pad = max(6.0, (y_max - y_min) * 0.18 if y_max > y_min else 8.0)
        ylim_lo, ylim_hi = y_min - y_pad, y_max + y_pad

    for axis_index, axis in enumerate(axes):
        if axis_index >= profile_count:
            axis.set_visible(False)
            continue

        row_dict, long_df = valid_profile_rows[axis_index]
        visit_label = str(row_dict["visit_label"])

        if _do_cortex_split:
            # Overlay per-cortex profiles for this visit
            _drew_any = False
            for ci, cx_val in enumerate(_cortex_vals):
                cx_profiles = _cortex_visit_profiles.get(cx_val)
                if cx_profiles is None:
                    continue
                # Find the matching visit row by visit_label
                cx_match = [
                    r for r in cx_profiles.to_dict(orient="records")
                    if str(r.get("visit_label", "")) == visit_label
                ]
                if not cx_match:
                    continue
                cx_long = waveform_long_format(pd.Series(cx_match[0]), measure=measure)
                if cx_long.empty:
                    continue
                color, face = cortex_color(cx_val, ci)
                axis.plot(
                    cx_long["isi_ms"], cx_long["value"],
                    color=color, linewidth=1.2, alpha=0.98, zorder=2,
                )
                # Only add label on first subplot to avoid duplicate legend entries
                axis.scatter(
                    cx_long["isi_ms"], cx_long["value"],
                    s=220, facecolors=face, edgecolors=color,
                    linewidths=1.1, alpha=0.98, zorder=3,
                    label=str(cx_val) if axis_index == 0 else None,
                )
                _drew_any = True
            if not _drew_any:
                # Fallback to merged profile
                axis.plot(
                    long_df["isi_ms"], long_df["value"],
                    color="#526A84", linewidth=1.2, alpha=0.98, zorder=2,
                )
                axis.scatter(
                    long_df["isi_ms"], long_df["value"],
                    s=220, facecolors="#ECE8E0", edgecolors="#526A84",
                    linewidths=1.1, alpha=0.98, zorder=3,
                )
        else:
            axis.plot(
                long_df["isi_ms"], long_df["value"],
                color="#526A84", linewidth=1.2, alpha=0.98, zorder=2,
            )
            axis.scatter(
                long_df["isi_ms"], long_df["value"],
                s=220, facecolors="#ECE8E0", edgecolors="#526A84",
                linewidths=1.1, alpha=0.98, zorder=3,
            )

        if config["reference_line"] is not None:
            draw_reference_line(axis, float(config["reference_line"]))
        axis.set_ylim(ylim_lo, ylim_hi)
        axis.set_xticks(tick_positions)
        axis.set_xticklabels(tick_labels)
        if x_limits is not None:
            axis.set_xlim(*x_limits)
        axis.set_title(visit_label, fontsize=12, pad=10)
        axis.set_facecolor("#FFFFFF")
        axis.grid(False)
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        axis.spines["left"].set_color("#73839A")
        axis.spines["bottom"].set_color("#73839A")
        axis.spines["left"].set_linewidth(1.1)
        axis.spines["bottom"].set_linewidth(1.1)
        axis.tick_params(axis="x", colors="#17202A", labelsize=10, length=0, pad=10)
        axis.tick_params(axis="y", colors="#4C5B70", labelsize=10)
        if axis_index % n_cols == 0:
            axis.set_ylabel(y_label or default_measure_axis_label(measure))

    figure.suptitle(title or default_measure_visit_profile_title(measure, resolved_id), fontsize=16, y=0.99)

    if _do_cortex_split:
        figure.legend(
            *axes[0].get_legend_handles_labels(),
            loc="upper right", frameon=False, fontsize=9, title="Stimulated cortex",
            labelspacing=1.4,
        )

    saved_png = ""
    if output_png is not None:
        output_path = Path(output_png)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(output_path, dpi=png_dpi, bbox_inches="tight")
        saved_png = str(output_path.resolve())

    plot_data = {
        "measure": normalize_measure_key(measure),
        "participant_id": resolved_id,
        "participant_rows": participant_rows.reset_index(drop=True),
        "selected_rows": selected_rows.reset_index(drop=True),
        "visit_profiles": visit_profiles.reset_index(drop=True),
        "profile_count": int(profile_count),
        "saved_png": saved_png,
    }

    figure.tight_layout(rect=(0.0, 0.0, 1.0, 0.95))
    if show and plt.get_backend().lower() != "agg":
        plt.show()
    return figure, axes, plot_data


def plot_csp_profile(
    participant_id=None,
    mem_date=None,
    mem_filename=None,
    input_dir=None,
    data_df=None,
    title: str = None,
    exclude_highlight_from_groups: bool = True,
    output_png=None,
    png_dpi: int = 300,
    show: bool = True,
):
    """Plot one CSP duration profile across %RMT for the selected case and cohort means."""
    try:
        import matplotlib
        if not show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError("matplotlib is required for CSP profile plots.") from exc

    resolved_df = load_mem_dataframe(input_dir=input_dir, data_df=data_df)
    matched_rows = resolve_selected_rows(
        resolved_df,
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
    )

    selected_profile = summarize_profile_rows(
        matched_rows,
        value_columns=CSP_PROFILE_COLUMNS,
        source_label="selected_case",
    )
    selected_long = csp_profile_long_format(selected_profile)
    if selected_long.empty:
        if mem_filename is not None:
            raise ValueError(f"MEM file {Path(str(mem_filename)).name} has no available CSP duration values to plot.")
        normalized_date = normalize_mem_date(mem_date)
        raise ValueError(
            f"Participant ID {int(participant_id)} has no available CSP duration values to plot on {normalized_date}."
        )

    patient_rows, control_rows, excluded_source_files = prepare_csp_profile_group_rows(
        resolved_df,
        highlight_rows=matched_rows,
        exclude_highlight_from_groups=exclude_highlight_from_groups,
    )
    if patient_rows.empty:
        raise ValueError("No patient cohort rows with available CSP duration values are available for plotting.")
    if control_rows.empty:
        raise ValueError("No control cohort rows with available CSP duration values are available for plotting.")

    patient_profile = summarize_profile_rows(patient_rows, value_columns=CSP_PROFILE_COLUMNS, source_label="patient_mean")
    control_profile = summarize_profile_rows(control_rows, value_columns=CSP_PROFILE_COLUMNS, source_label="control_mean")
    patient_long = csp_profile_long_format(patient_profile)
    control_long = csp_profile_long_format(control_profile)
    if patient_long.empty:
        raise ValueError("The patient cohort has no plottable CSP duration profile values.")
    if control_long.empty:
        raise ValueError("The control cohort has no plottable CSP duration profile values.")

    resolved_title = title or default_csp_profile_title(
        matched_rows=matched_rows,
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
    )

    figure, axis = plt.subplots(figsize=STANDARD_FIGSIZE)

    # Check if matched rows have multiple cortex values
    _cortex_split = False
    if "Stimulated_cortex" in matched_rows.columns:
        _cx_vals = (
            matched_rows["Stimulated_cortex"].astype("string")
            .fillna("").str.strip().replace("", pd.NA).dropna().unique()
        )
        if len(_cx_vals) > 1:
            _cortex_split = True

    trace_specs = []
    if _cortex_split:
        # One trace per cortex for the selected participant
        for ci, cx_val in enumerate(_cx_vals):
            cx_rows = matched_rows[
                matched_rows["Stimulated_cortex"].astype("string").fillna("").str.strip() == cx_val
            ]
            cx_profile = summarize_profile_rows(cx_rows, value_columns=CSP_PROFILE_COLUMNS, source_label=cx_val)
            cx_long = csp_profile_long_format(cx_profile)
            if not cx_long.empty:
                color, face = cortex_color(cx_val, ci)
                trace_specs.append((str(cx_val), cx_long, color, face, 260))
    else:
        trace_specs.append(("Selected participant", selected_long, "#4F79C7", "#EAF0FA", 260))

    trace_specs.extend([
        ("ALS patients (mean)", patient_long, "#F28A2E", "#FBEEE2", 220),
        ("Controls (mean)", control_long, "#BFC6D1", "#F4F5F7", 220),
    ])

    all_values = []
    for trace_label, long_df, line_color, face_color, point_size in trace_specs:
        all_values.extend(long_df["value"].tolist())
        axis.plot(
            long_df["rmt_percent"],
            long_df["value"],
            color=line_color,
            linewidth=1.6,
            alpha=0.98,
            zorder=2,
            label=trace_label,
        )
        axis.scatter(
            long_df["rmt_percent"],
            long_df["value"],
            s=point_size,
            facecolors=face_color,
            edgecolors=line_color,
            linewidths=1.2,
            alpha=0.99,
            zorder=3,
        )

    y_min = min(all_values)
    y_max = max(all_values)
    y_pad = max(6.0, (y_max - y_min) * 0.16 if y_max > y_min else 8.0)

    apply_csp_ticks(axis)
    axis.set_xlabel("Stimulus intensity (%RMT)")
    axis.set_ylabel(default_csp_axis_label())
    axis.set_title(resolved_title, fontsize=14, pad=14)
    axis.set_ylim(y_min - y_pad, y_max + y_pad)
    axis.set_facecolor("#FFFFFF")
    axis.grid(False)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.spines["left"].set_color("#73839A")
    axis.spines["bottom"].set_color("#73839A")
    axis.spines["left"].set_linewidth(1.1)
    axis.spines["bottom"].set_linewidth(1.1)
    axis.tick_params(axis="both", colors="#4C5B70", labelsize=11)
    axis.legend(frameon=False, loc="best", fontsize=10)

    saved_png = ""
    if output_png is not None:
        output_path = Path(output_png)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(output_path, dpi=png_dpi, bbox_inches="tight")
        saved_png = str(output_path.resolve())

    plot_data = {
        "measure": CSP_MEASURE_KEY,
        "selected_rows": matched_rows.reset_index(drop=True),
        "selected_profile": selected_long.reset_index(drop=True),
        "patient_rows": patient_rows.reset_index(drop=True),
        "patient_profile": patient_long.reset_index(drop=True),
        "control_rows": control_rows.reset_index(drop=True),
        "control_profile": control_long.reset_index(drop=True),
        "excluded_source_files": sorted(excluded_source_files),
        "saved_png": saved_png,
    }

    figure.tight_layout()
    if show and plt.get_backend().lower() != "agg":
        plt.show()
    return figure, axis, plot_data


def plot_csp_grouped_graph(
    participant_id=None,
    mem_date=None,
    mem_filename=None,
    input_dir=None,
    data_df=None,
    match_by=None,
    age_window: int = 5,
    title: str = None,
    highlight_label: str = None,
    patient_label_base: str = "SNBR ALS",
    control_label_base: str = "SNBR Controls",
    exclude_highlight_from_groups: bool = True,
    highlight_cortex_values: list | None = None,
    output_png=None,
    png_dpi: int = 300,
    show: bool = True,
):
    """Create one separate matched CSP comparison figure for each available %RMT level."""
    try:
        import matplotlib
        if not show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError("matplotlib is required for CSP grouped-comparison plots.") from exc

    resolved_df = load_mem_dataframe(input_dir=input_dir, data_df=data_df)
    highlight_rows = resolve_selected_rows(
        resolved_df,
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
    )
    filtered_df, match_info = filter_to_selected_characteristics(
        resolved_df,
        selected_rows=highlight_rows,
        match_by=match_by,
        age_window=age_window,
    )
    patient_label, control_label, resolved_title = build_grouped_plot_text(
        match_info=match_info,
        patient_label_base=patient_label_base,
        control_label_base=control_label_base,
        title=title or "Matched CSP comparison",
    )

    figures = []
    axes = []
    plot_data = {
        "measure": CSP_MEASURE_KEY,
        "match_info": match_info,
        "filtered_data_df": filtered_df.reset_index(drop=True),
        "panels": {},
        "figure_keys": [],
        "saved_pngs": {},
    }

    for value_column in CSP_PROFILE_COLUMNS:
        figure, axis = plt.subplots(figsize=STANDARD_FIGSIZE)
        try:
            panel_data = draw_scalar_group_axis(
                axis=axis,
                data_df=filtered_df,
                highlight_rows=highlight_rows,
                value_column=value_column,
                participant_id=participant_id,
                mem_date=mem_date,
                mem_filename=mem_filename,
                highlight_label=highlight_label,
                patient_label=patient_label,
                control_label=control_label,
                exclude_highlight_from_groups=exclude_highlight_from_groups,
                highlight_cortex_values=highlight_cortex_values,
            )
            style_panel_axis(
                axis,
                title=panel_title_from_base(resolved_title, value_column),
                y_label=default_value_axis_label(value_column),
            )
            plot_data["panels"][value_column] = panel_data
        except ValueError as exc:
            plt.close(figure)
            plot_data["panels"][value_column] = {"error": str(exc)}
            continue

        output_path = output_path_with_suffix(output_png, value_column)
        saved_png = ""
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            figure.savefig(output_path, dpi=png_dpi, bbox_inches="tight")
            saved_png = str(output_path.resolve())
        plot_data["saved_pngs"][value_column] = saved_png
        figures.append(figure)
        axes.append(axis)
        plot_data["figure_keys"].append(value_column)

    if not figures:
        raise ValueError("No CSP panels could be rendered for the selected case and available cohorts.")

    for figure in figures:
        figure.tight_layout()
    if show and plt.get_backend().lower() != "agg":
        plt.show()
    return figures, axes, plot_data


def plot_participant_csp_over_time(
    participant_id=None,
    mem_date=None,
    mem_filename=None,
    input_dir=None,
    data_df=None,
    title: str = None,
    group_by_cortex: bool = False,
    output_png=None,
    png_dpi: int = 300,
    show: bool = True,
):
    """Plot one separate CSP-over-time figure for each available %RMT level."""
    try:
        import matplotlib
        if not show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError("matplotlib is required for CSP-over-time plots.") from exc

    resolved_df = load_mem_dataframe(input_dir=input_dir, data_df=data_df)
    participant_rows, selected_rows, resolved_id = resolve_participant_context(
        resolved_df,
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
    )

    # Determine cortex split
    _do_cortex_split = False
    _cortex_vals = []
    if group_by_cortex and "Stimulated_cortex" in participant_rows.columns:
        _cortex_vals = sorted(
            participant_rows["Stimulated_cortex"].astype("string")
            .fillna("").str.strip().replace("", pd.NA).dropna().unique()
        )
        if len(_cortex_vals) > 1:
            _do_cortex_split = True

    base_title = title or default_csp_over_time_title(resolved_id)
    figures = []
    axes = []
    plot_data = {
        "measure": CSP_MEASURE_KEY,
        "participant_id": resolved_id,
        "participant_rows": participant_rows.reset_index(drop=True),
        "selected_rows": selected_rows.reset_index(drop=True),
        "visit_summaries": {},
        "figure_keys": [],
        "saved_pngs": {},
    }

    for value_column in CSP_PROFILE_COLUMNS:
        # Get overall visit summary for shared x-axis ticks
        try:
            visit_summary, numeric_rows = build_participant_visit_summary(
                participant_rows, value_column=value_column,
            )
        except ValueError:
            plot_data["visit_summaries"][value_column] = pd.DataFrame()
            continue

        figure, axis = plt.subplots(figsize=STANDARD_FIGSIZE)

        if _do_cortex_split:
            all_y = []
            for ci, cx_val in enumerate(_cortex_vals):
                cx_rows = participant_rows[
                    participant_rows["Stimulated_cortex"].astype("string").fillna("").str.strip() == cx_val
                ]
                try:
                    cx_summary, _ = build_participant_visit_summary(cx_rows, value_column=value_column)
                except ValueError:
                    continue
                color, face = cortex_color(cx_val, ci)
                all_y.extend(cx_summary["visit_value"].tolist())
                if len(cx_summary) > 1:
                    axis.plot(
                        cx_summary["visit_date"], cx_summary["visit_value"],
                        color=color, linewidth=1.4, alpha=0.98, zorder=2,
                    )
                axis.scatter(
                    cx_summary["visit_date"], cx_summary["visit_value"],
                    s=180, facecolors=face, edgecolors=color,
                    linewidths=1.1, alpha=0.98, zorder=3, label=str(cx_val),
                )
            if not all_y:
                plt.close(figure)
                continue
            y_min, y_max = min(all_y), max(all_y)
            axis.legend(frameon=False, loc="best", fontsize=9, title="Stimulated cortex", labelspacing=1.4)
        else:
            if len(visit_summary) > 1:
                axis.plot(
                    visit_summary["visit_date"], visit_summary["visit_value"],
                    color="#526A84", linewidth=1.4, alpha=0.98, zorder=2,
                )
            axis.scatter(
                visit_summary["visit_date"], visit_summary["visit_value"],
                s=180, facecolors="#ECE8E0", edgecolors="#526A84",
                linewidths=1.1, alpha=0.98, zorder=3,
            )
            y_values = visit_summary["visit_value"].tolist()
            y_min, y_max = min(y_values), max(y_values)

        y_pad = max(6.0, (y_max - y_min) * 0.18 if y_max > y_min else 8.0)
        axis.set_ylim(y_min - y_pad, y_max + y_pad)
        axis.set_xticks(visit_summary["visit_date"])
        axis.set_xticklabels(visit_summary["visit_label"], rotation=55, ha="right")
        axis.set_xlabel("Visit date")
        style_panel_axis(
            axis,
            title=panel_title_from_base(base_title, value_column),
            y_label=default_value_axis_label(value_column),
        )
        plot_data["visit_summaries"][value_column] = visit_summary.reset_index(drop=True)
        plot_data[f"{value_column}_value_rows"] = numeric_rows.reset_index(drop=True)
        output_path = output_path_with_suffix(output_png, value_column)
        saved_png = ""
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            figure.savefig(output_path, dpi=png_dpi, bbox_inches="tight")
            saved_png = str(output_path.resolve())
        plot_data["saved_pngs"][value_column] = saved_png
        figures.append(figure)
        axes.append(axis)
        plot_data["figure_keys"].append(value_column)

    if not figures:
        raise ValueError("This participant has no available CSP duration values to plot over time.")

    for figure in figures:
        figure.tight_layout()
    if show and plt.get_backend().lower() != "agg":
        plt.show()
    return figures, axes, plot_data


def plot_participant_csp_visit_profiles(
    participant_id=None,
    mem_date=None,
    mem_filename=None,
    input_dir=None,
    data_df=None,
    merge_same_day: bool = True,
    y_label: str = None,
    title: str = None,
    group_by_cortex: bool = False,
    output_png=None,
    png_dpi: int = 300,
    show: bool = True,
):
    """Plot one separate CSP profile figure per visit for a participant."""
    try:
        import matplotlib
        if not show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError("matplotlib is required for CSP visit-profile plots.") from exc

    resolved_df = load_mem_dataframe(input_dir=input_dir, data_df=data_df)
    participant_rows, selected_rows, resolved_id = resolve_participant_context(
        resolved_df,
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
    )

    # Determine cortex split
    _do_cortex_split = False
    _cortex_vals = []
    if group_by_cortex and "Stimulated_cortex" in participant_rows.columns:
        _cortex_vals = sorted(
            participant_rows["Stimulated_cortex"].astype("string")
            .fillna("").str.strip().replace("", pd.NA).dropna().unique()
        )
        if len(_cortex_vals) > 1:
            _do_cortex_split = True

    visit_profiles = build_participant_csp_visit_profiles(
        participant_rows,
        merge_same_day=merge_same_day,
    )

    # Build per-cortex visit profiles if needed
    _cortex_visit_profiles = {}
    if _do_cortex_split:
        for cx_val in _cortex_vals:
            cx_rows = participant_rows[
                participant_rows["Stimulated_cortex"].astype("string").fillna("").str.strip() == cx_val
            ]
            try:
                cx_profiles = build_participant_csp_visit_profiles(
                    cx_rows, merge_same_day=merge_same_day,
                )
                _cortex_visit_profiles[cx_val] = cx_profiles
            except (ValueError, KeyError):
                pass

    valid_profile_rows = []
    all_values = []
    for row_dict in visit_profiles.to_dict(orient="records"):
        long_df = csp_profile_long_format(pd.Series(row_dict))
        if long_df.empty:
            continue
        valid_profile_rows.append((row_dict, long_df))
        all_values.extend(long_df["value"].tolist())

    # Include cortex-split values for y-axis range
    if _do_cortex_split:
        for cx_val, cx_profiles in _cortex_visit_profiles.items():
            for row_dict in cx_profiles.to_dict(orient="records"):
                long_df = csp_profile_long_format(pd.Series(row_dict))
                if not long_df.empty:
                    all_values.extend(long_df["value"].tolist())

    if not valid_profile_rows:
        raise ValueError("This participant has no visit profiles with available CSP duration values to plot.")

    base_title = title or default_csp_visit_profile_title(resolved_id)
    y_min = min(all_values)
    y_max = max(all_values)
    y_pad = max(4.0, (y_max - y_min) * 0.18 if y_max > y_min else 5.0)
    figures = []
    axes = []
    plot_data = {
        "measure": CSP_MEASURE_KEY,
        "participant_id": resolved_id,
        "participant_rows": participant_rows.reset_index(drop=True),
        "selected_rows": selected_rows.reset_index(drop=True),
        "visit_profiles": visit_profiles.reset_index(drop=True),
        "profile_count": int(len(valid_profile_rows)),
        "figure_keys": [],
        "saved_pngs": {},
    }

    for row_dict, long_df in valid_profile_rows:
        visit_label = str(row_dict["visit_label"])
        figure, axis = plt.subplots(figsize=STANDARD_FIGSIZE)

        if _do_cortex_split:
            _drew_any = False
            for ci, cx_val in enumerate(_cortex_vals):
                cx_profiles = _cortex_visit_profiles.get(cx_val)
                if cx_profiles is None:
                    continue
                cx_match = [
                    r for r in cx_profiles.to_dict(orient="records")
                    if str(r.get("visit_label", "")) == visit_label
                ]
                if not cx_match:
                    continue
                cx_long = csp_profile_long_format(pd.Series(cx_match[0]))
                if cx_long.empty:
                    continue
                color, face = cortex_color(cx_val, ci)
                axis.plot(
                    cx_long["rmt_percent"], cx_long["value"],
                    color=color, linewidth=1.4, alpha=0.98, zorder=2,
                )
                axis.scatter(
                    cx_long["rmt_percent"], cx_long["value"],
                    s=220, facecolors=face, edgecolors=color,
                    linewidths=1.1, alpha=0.98, zorder=3, label=str(cx_val),
                )
                _drew_any = True
            if not _drew_any:
                axis.plot(
                    long_df["rmt_percent"], long_df["value"],
                    color="#526A84", linewidth=1.4, alpha=0.98, zorder=2,
                )
                axis.scatter(
                    long_df["rmt_percent"], long_df["value"],
                    s=220, facecolors="#ECE8E0", edgecolors="#526A84",
                    linewidths=1.1, alpha=0.98, zorder=3,
                )
            if _drew_any:
                axis.legend(frameon=False, loc="best", fontsize=9, title="Stimulated cortex", labelspacing=1.4)
        else:
            axis.plot(
                long_df["rmt_percent"], long_df["value"],
                color="#526A84", linewidth=1.4, alpha=0.98, zorder=2,
            )
            axis.scatter(
                long_df["rmt_percent"], long_df["value"],
                s=220, facecolors="#ECE8E0", edgecolors="#526A84",
                linewidths=1.1, alpha=0.98, zorder=3,
            )

        axis.set_ylim(y_min - y_pad, y_max + y_pad)
        apply_csp_ticks(axis)
        axis.set_facecolor("#FFFFFF")
        axis.grid(False)
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        axis.spines["left"].set_color("#73839A")
        axis.spines["bottom"].set_color("#73839A")
        axis.spines["left"].set_linewidth(1.1)
        axis.spines["bottom"].set_linewidth(1.1)
        axis.tick_params(axis="x", colors="#17202A", labelsize=10, length=0, pad=10)
        axis.tick_params(axis="y", colors="#4C5B70", labelsize=10)
        axis.set_xlabel("Stimulus intensity (%RMT)")
        axis.set_ylabel(y_label or default_csp_axis_label())
        axis.set_title(
            f"{base_title} | {visit_label}",
            fontsize=13,
            pad=12,
        )

        figure_key = f"visit_{visit_label.replace('/', '-')}"
        output_path = output_path_with_suffix(output_png, figure_key)
        saved_png = ""
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            figure.savefig(output_path, dpi=png_dpi, bbox_inches="tight")
            saved_png = str(output_path.resolve())
        plot_data["saved_pngs"][figure_key] = saved_png
        plot_data["figure_keys"].append(figure_key)
        figures.append(figure)
        axes.append(axis)

    for figure in figures:
        figure.tight_layout()
    if show and plt.get_backend().lower() != "agg":
        plt.show()
    return figures, axes, plot_data


def plot_participant_visit_test_table(
    participant_id=None,
    mem_date=None,
    mem_filename=None,
    input_dir=None,
    data_df=None,
    title: str = None,
    show: bool = True,
):
    """Render a participant visit-summary table with all tests present on each visit date."""
    try:
        import matplotlib
        if not show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError("matplotlib is required for participant visit-summary tables.") from exc

    resolved_df = load_mem_dataframe(input_dir=input_dir, data_df=data_df)
    participant_rows, selected_rows, resolved_id = resolve_participant_context(
        resolved_df,
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
    )
    visit_summary = build_participant_visit_test_summary(participant_rows)

    extra_wrapped_lines = int(
        max(0, pd.to_numeric(visit_summary["tests_present_line_count"], errors="coerce").fillna(1).sum() - len(visit_summary))
    )
    figure_height = max(4.8, 1.9 + 0.48 * len(visit_summary) + 0.26 * extra_wrapped_lines)
    figure, axis = plt.subplots(figsize=(11.2, figure_height))
    axis.axis("off")
    axis.set_title(
        title or f"{format_participant_label(resolved_id)} | Visit summary and tests present",
        fontsize=15,
        pad=18,
    )

    table_rows = []
    for row in visit_summary.itertuples(index=False):
        elapsed_text = "N/A" if pd.isna(row.days_since_previous_visit) else str(int(row.days_since_previous_visit))
        sides = getattr(row, "sides_tested", "N/A")
        table_rows.append(
            [
                f"Visit {int(row.visit_number)}",
                str(row.visit_label),
                elapsed_text,
                str(int(row.mem_file_count)),
                str(sides),
                str(row.tests_present_wrapped_text),
            ]
        )

    visit_table = axis.table(
        cellText=table_rows,
        colLabels=["Visit", "Date", "Days Since Previous", "MEM Files", "Sides Tested", "Tests Present"],
        cellLoc="left",
        colLoc="left",
        colWidths=VISIT_TABLE_COLUMN_WIDTHS,
        bbox=(0.02, 0.02, 0.96, 0.9),
    )
    visit_table.auto_set_font_size(False)
    visit_table.set_fontsize(10)
    visit_table.scale(1.0, 1.45)
    for (row_index, _), cell in visit_table.get_celld().items():
        cell.set_edgecolor("#D8E0EA")
        cell.set_linewidth(0.8)
        if row_index == 0:
            cell.set_facecolor("#E9EEF4")
            cell.set_text_props(weight="bold", color="#223142")
        else:
            cell.set_facecolor("#FFFFFF")
    apply_visit_summary_table_layout(
        visit_table,
        row_line_counts=visit_summary["tests_present_line_count"].tolist(),
        bbox_height=0.9,
    )

    figure.tight_layout()
    if show and plt.get_backend().lower() != "agg":
        plt.show()
    plot_data = {
        "participant_id": resolved_id,
        "participant_rows": participant_rows.reset_index(drop=True),
        "selected_rows": selected_rows.reset_index(drop=True),
        "visit_summary": visit_summary.reset_index(drop=True),
    }
    return figure, axis, plot_data


def style_panel_axis(axis, title: str, y_label: str = None):
    """Apply the shared subplot styling used by RMT and CSP multi-panel figures."""
    axis.set_title(title, fontsize=13, pad=12)
    axis.set_facecolor("#FFFFFF")
    axis.grid(False)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.spines["left"].set_color("#73839A")
    axis.spines["bottom"].set_color("#73839A")
    axis.spines["left"].set_linewidth(1.1)
    axis.spines["bottom"].set_linewidth(1.1)
    axis.tick_params(axis="x", colors="#17202A", labelsize=10, length=0, pad=10)
    axis.tick_params(axis="y", colors="#4C5B70", labelsize=10)
    if y_label is not None:
        axis.set_ylabel(y_label)


def style_rmt_axis(axis, title: str, y_label: str = None):
    """Backward-compatible wrapper for the shared scalar-panel styling."""
    style_panel_axis(axis=axis, title=title, y_label=y_label)


def show_axis_message(axis, title: str, message: str):
    """Replace one subplot with a centered explanatory message."""
    axis.set_title(title, fontsize=13, pad=12)
    axis.axis("off")
    axis.text(
        0.5,
        0.5,
        message,
        ha="center",
        va="center",
        wrap=True,
        fontsize=11,
        color="#536578",
        transform=axis.transAxes,
    )


def panel_label_for_value_column(value_column: str) -> str:
    """Return a short display label for one scalar value column."""
    if value_column in RMT_COLUMN_LABELS:
        return RMT_COLUMN_LABELS[value_column]
    if value_column in CSP_PROFILE_COLUMN_SET:
        return csp_panel_title(value_column)
    return str(value_column).replace("_", " ")


def panel_title_from_base(base_title: str, value_column: str) -> str:
    """Append a scalar panel label to one base title."""
    panel_label = panel_label_for_value_column(value_column)
    if not base_title:
        return panel_label
    return f"{base_title} | {panel_label}"


def output_path_with_suffix(output_png, figure_key: str) -> Path | None:
    """Resolve one optional output path with a stable suffix for figure collections."""
    if output_png is None:
        return None

    output_path = Path(output_png)
    suffix = output_path.suffix if output_path.suffix else ".png"
    normalized_key = (
        str(figure_key)
        .strip()
        .replace("%", "pct")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(" ", "_")
    )
    return output_path.with_name(f"{output_path.stem}_{normalized_key}{suffix}")


def plot_participant_rmt_over_time(
    participant_id=None,
    mem_date=None,
    mem_filename=None,
    input_dir=None,
    data_df=None,
    title: str = None,
    group_by_cortex: bool = False,
    output_png=None,
    png_dpi: int = 300,
    show: bool = True,
):
    """Plot one separate RMT-over-time figure for each available RMT column."""
    try:
        import matplotlib
        if not show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError("matplotlib is required for RMT-over-time plots.") from exc

    resolved_df = load_mem_dataframe(input_dir=input_dir, data_df=data_df)
    participant_rows, selected_rows, resolved_id = resolve_participant_context(
        resolved_df,
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
    )

    # Determine cortex split
    _do_cortex_split = False
    _cortex_vals = []
    if group_by_cortex and "Stimulated_cortex" in participant_rows.columns:
        _cortex_vals = sorted(
            participant_rows["Stimulated_cortex"].astype("string")
            .fillna("").str.strip().replace("", pd.NA).dropna().unique()
        )
        if len(_cortex_vals) > 1:
            _do_cortex_split = True

    base_title = title or f"{format_participant_label(resolved_id)} | RMT thresholds over time"
    figures = []
    axes = []
    plot_data = {
        "participant_id": resolved_id,
        "participant_rows": participant_rows.reset_index(drop=True),
        "selected_rows": selected_rows.reset_index(drop=True),
        "visit_summaries": {},
        "figure_keys": [],
        "saved_pngs": {},
    }

    for rmt_column in RMT_COLUMNS:
        # Get overall visit summary for shared x-axis ticks
        try:
            visit_summary, numeric_rows = build_participant_visit_summary(
                participant_rows,
                value_column=rmt_column,
            )
        except ValueError:
            plot_data["visit_summaries"][rmt_column] = pd.DataFrame()
            continue

        figure, axis = plt.subplots(figsize=STANDARD_FIGSIZE)

        if _do_cortex_split:
            all_y = []
            for ci, cx_val in enumerate(_cortex_vals):
                cx_rows = participant_rows[
                    participant_rows["Stimulated_cortex"].astype("string").fillna("").str.strip() == cx_val
                ]
                try:
                    cx_summary, _ = build_participant_visit_summary(cx_rows, value_column=rmt_column)
                except ValueError:
                    continue
                color, face = cortex_color(cx_val, ci)
                all_y.extend(cx_summary["visit_value"].tolist())
                if len(cx_summary) > 1:
                    axis.plot(
                        cx_summary["visit_date"], cx_summary["visit_value"],
                        color=color, linewidth=1.4, alpha=0.98, zorder=2,
                    )
                axis.scatter(
                    cx_summary["visit_date"], cx_summary["visit_value"],
                    s=180, facecolors=face, edgecolors=color,
                    linewidths=1.1, alpha=0.98, zorder=3, label=str(cx_val),
                )
            if not all_y:
                plt.close(figure)
                continue
            y_min, y_max = min(all_y), max(all_y)
            axis.legend(frameon=False, loc="best", fontsize=9, title="Stimulated cortex", labelspacing=1.4)
        else:
            if len(visit_summary) > 1:
                axis.plot(
                    visit_summary["visit_date"], visit_summary["visit_value"],
                    color="#526A84", linewidth=1.4, alpha=0.98, zorder=2,
                )
            axis.scatter(
                visit_summary["visit_date"], visit_summary["visit_value"],
                s=180, facecolors="#ECE8E0", edgecolors="#526A84",
                linewidths=1.1, alpha=0.98, zorder=3,
            )
            y_values = visit_summary["visit_value"].tolist()
            y_min, y_max = min(y_values), max(y_values)

        y_pad = max(6.0, (y_max - y_min) * 0.18 if y_max > y_min else 8.0)
        axis.set_ylim(y_min - y_pad, y_max + y_pad)
        axis.set_xticks(visit_summary["visit_date"])
        axis.set_xticklabels(visit_summary["visit_label"], rotation=55, ha="right")
        axis.set_xlabel("Visit date")
        style_rmt_axis(
            axis,
            title=panel_title_from_base(base_title, rmt_column),
            y_label="RMT value",
        )
        plot_data["visit_summaries"][rmt_column] = visit_summary.reset_index(drop=True)
        plot_data[f"{rmt_column}_value_rows"] = numeric_rows.reset_index(drop=True)
        output_path = output_path_with_suffix(output_png, rmt_column)
        saved_png = ""
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            figure.savefig(output_path, dpi=png_dpi, bbox_inches="tight")
            saved_png = str(output_path.resolve())
        plot_data["saved_pngs"][rmt_column] = saved_png
        figures.append(figure)
        axes.append(axis)
        plot_data["figure_keys"].append(rmt_column)

    if not figures:
        raise ValueError("This participant has no available RMT50, RMT200, or RMT1000 values to plot over time.")

    for figure in figures:
        figure.tight_layout()
    if show and plt.get_backend().lower() != "agg":
        plt.show()
    return figures, axes, plot_data


def draw_scalar_group_axis(
    axis,
    data_df: pd.DataFrame,
    highlight_rows: pd.DataFrame,
    value_column: str,
    participant_id=None,
    mem_date=None,
    mem_filename=None,
    highlight_label: str = None,
    patient_label: str = "SNBR ALS",
    control_label: str = "SNBR Controls",
    exclude_highlight_from_groups: bool = True,
    highlight_cortex_values: list | None = None,
):
    """Render one scalar violin comparison panel onto an axis.

    When *highlight_cortex_values* contains 2+ cortex labels the highlight
    point is split into one marker per cortex, each with its own colour.
    """
    numeric_highlight_rows, highlight_value = summarize_highlight_value(highlight_rows, value_column=value_column)
    patient_rows, control_rows, excluded_source_files = prepare_group_rows(
        data_df=data_df,
        highlight_rows=highlight_rows,
        value_column=value_column,
        exclude_highlight_from_groups=exclude_highlight_from_groups,
    )
    if patient_rows.empty:
        raise ValueError(f"No patient rows with a '{value_column}' value are available for plotting.")
    if control_rows.empty:
        raise ValueError(f"No control rows with a '{value_column}' value are available for plotting.")

    patient_rows = style_group_point_rows(
        patient_rows,
        category_key="patient",
        category_label=f"{patient_label}\nn={len(patient_rows)}",
        value_column=value_column,
        jitter_seed=13,
    )
    control_rows = style_group_point_rows(
        control_rows,
        category_key="control",
        category_label=f"{control_label}\nn={len(control_rows)}",
        value_column=value_column,
        jitter_seed=31,
    )
    highlight_category_label = build_highlight_category_label(
        highlight_rows,
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
        highlight_label=highlight_label,
    )

    patient_edge = "#526A84"
    control_edge = "#6B7280"
    highlight_edge = "#7F1D1D"
    patient_face = "#DCE6F2"
    control_face = "#E8E5DF"

    violin = axis.violinplot(
        [
            patient_rows[value_column].to_numpy(dtype=float),
            control_rows[value_column].to_numpy(dtype=float),
        ],
        positions=[
            POINTPLOT_CATEGORY_X["patient"],
            POINTPLOT_CATEGORY_X["control"],
        ],
        widths=0.56,
        showmeans=False,
        showmedians=False,
        showextrema=False,
    )
    violin_bodies = violin["bodies"]
    violin_bodies[0].set_facecolor(patient_face)
    violin_bodies[0].set_edgecolor(patient_edge)
    violin_bodies[0].set_alpha(0.42)
    violin_bodies[0].set_linewidth(1.0)
    violin_bodies[1].set_facecolor(control_face)
    violin_bodies[1].set_edgecolor(control_edge)
    violin_bodies[1].set_alpha(0.42)
    violin_bodies[1].set_linewidth(1.0)

    patient_mean = float(patient_rows[value_column].mean())
    control_mean = float(control_rows[value_column].mean())
    patient_std = float(patient_rows[value_column].std(ddof=1))
    control_std = float(control_rows[value_column].std(ddof=1))
    axis.scatter(
        patient_rows["x_position"],
        patient_rows[value_column],
        s=84,
        facecolors="#F8F8F6",
        edgecolors=patient_edge,
        linewidths=1.0,
        alpha=0.95,
        zorder=4,
    )
    axis.scatter(
        control_rows["x_position"],
        control_rows[value_column],
        s=84,
        facecolors="#F8F8F6",
        edgecolors=control_edge,
        linewidths=1.0,
        alpha=0.95,
        zorder=4,
    )
    # Highlight point(s) — split by cortex when requested
    _cortex_highlight_values = []
    if (
        highlight_cortex_values
        and len(highlight_cortex_values) > 1
        and "Stimulated_cortex" in highlight_rows.columns
    ):
        x_base = POINTPLOT_CATEGORY_X["highlight"]
        offsets = [-0.18, 0.18] if len(highlight_cortex_values) == 2 else [0.0]
        for ci, cx_val in enumerate(highlight_cortex_values):
            cx_rows = highlight_rows[
                highlight_rows["Stimulated_cortex"].astype("string").fillna("").str.strip() == cx_val
            ]
            cx_numeric = pd.to_numeric(cx_rows[value_column], errors="coerce").dropna()
            if cx_numeric.empty:
                continue
            cx_value = float(cx_numeric.mean())
            _cortex_highlight_values.append(cx_value)
            color, _ = cortex_color(cx_val, ci)
            x_pos = x_base + (offsets[ci] if ci < len(offsets) else 0.0)
            axis.scatter(
                [x_pos], [cx_value],
                s=190, facecolors=color, edgecolors="none",
                linewidths=0, alpha=0.98, zorder=5, label=str(cx_val),
            )
    else:
        _cortex_highlight_values = [highlight_value]
        axis.scatter(
            [POINTPLOT_CATEGORY_X["highlight"]],
            [highlight_value],
            s=190,
            facecolors="#E53935",
            edgecolors=highlight_edge,
            linewidths=1.2,
            alpha=0.98,
            zorder=5,
        )

    axis.scatter(
        [POINTPLOT_CATEGORY_X["patient"]],
        [patient_mean],
        s=120,
        facecolors=patient_edge,
        edgecolors="#FFFFFF",
        linewidths=1.0,
        alpha=0.98,
        zorder=5,
    )
    axis.scatter(
        [POINTPLOT_CATEGORY_X["control"]],
        [control_mean],
        s=120,
        facecolors=control_edge,
        edgecolors="#FFFFFF",
        linewidths=1.0,
        alpha=0.98,
        zorder=5,
    )

    if highlight_cortex_values and len(highlight_cortex_values) > 1:
        axis.legend(frameon=False, loc="upper right", fontsize=9, title="Cortex", labelspacing=1.4)

    # Mean ± 1 SD whiskers on each cohort violin.
    sd_extents = draw_group_sd_lines(
        axis,
        [
            (POINTPLOT_CATEGORY_X["patient"], patient_mean, patient_std, patient_edge),
            (POINTPLOT_CATEGORY_X["control"], control_mean, control_std, control_edge),
        ],
    )

    y_values = (
        _cortex_highlight_values
        + patient_rows[value_column].tolist()
        + control_rows[value_column].tolist()
        + sd_extents
    )
    y_min = min(y_values)
    y_max = max(y_values)
    y_pad = max(6.0, (y_max - y_min) * 0.18 if y_max > y_min else 8.0)

    # Append per-column summary stats below each x-tick label.
    highlight_stats = _format_highlight_stats(
        highlight_cortex_values, _cortex_highlight_values, highlight_value,
    )
    patient_stats = _format_group_stats(patient_mean, patient_std)
    control_stats = _format_group_stats(control_mean, control_std)

    highlight_tick = (
        f"{highlight_category_label}\n{highlight_stats}"
        if highlight_stats else highlight_category_label
    )
    patient_tick = patient_rows["category_label"].iloc[0]
    if patient_stats:
        patient_tick = f"{patient_tick}\n{patient_stats}"
    control_tick = control_rows["category_label"].iloc[0]
    if control_stats:
        control_tick = f"{control_tick}\n{control_stats}"

    axis.set_xlim(-0.55, 2.55)
    axis.set_ylim(y_min - y_pad, y_max + y_pad)
    axis.set_xticks(
        [
            POINTPLOT_CATEGORY_X["highlight"],
            POINTPLOT_CATEGORY_X["patient"],
            POINTPLOT_CATEGORY_X["control"],
        ]
    )
    axis.set_xticklabels([highlight_tick, patient_tick, control_tick])
    axis.tick_params(axis="x", colors="#17202A", labelsize=11, length=0, pad=14)
    axis.tick_params(axis="y", colors="#4C5B70", labelsize=11)

    return {
        "value_column": value_column,
        "highlight_rows": highlight_rows.reset_index(drop=True),
        "highlight_value_rows": numeric_highlight_rows.reset_index(drop=True),
        "highlight_value": highlight_value,
        "patient_rows": patient_rows.reset_index(drop=True),
        "control_rows": control_rows.reset_index(drop=True),
        "patient_mean": patient_mean,
        "control_mean": control_mean,
        "patient_std": patient_std,
        "control_std": control_std,
        "excluded_source_files": sorted(excluded_source_files),
    }


def draw_rmt_group_axis(
    axis,
    data_df: pd.DataFrame,
    highlight_rows: pd.DataFrame,
    value_column: str,
    participant_id=None,
    mem_date=None,
    mem_filename=None,
    highlight_label: str = None,
    patient_label: str = "SNBR ALS",
    control_label: str = "SNBR Controls",
    exclude_highlight_from_groups: bool = True,
    highlight_cortex_values: list | None = None,
):
    """Backward-compatible wrapper for one RMT violin comparison panel."""
    return draw_scalar_group_axis(
        axis=axis,
        data_df=data_df,
        highlight_rows=highlight_rows,
        value_column=value_column,
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
        highlight_label=highlight_label,
        patient_label=patient_label,
        control_label=control_label,
        exclude_highlight_from_groups=exclude_highlight_from_groups,
        highlight_cortex_values=highlight_cortex_values,
    )


def plot_rmt_group_comparison(
    participant_id=None,
    mem_date=None,
    mem_filename=None,
    input_dir=None,
    data_df=None,
    title: str = None,
    highlight_label: str = None,
    patient_label: str = "SNBR ALS",
    control_label: str = "SNBR Controls",
    exclude_highlight_from_groups: bool = True,
    highlight_cortex_values: list | None = None,
    output_png=None,
    png_dpi: int = 300,
    show: bool = True,
):
    """Create one separate RMT comparison figure for each available RMT column."""
    try:
        import matplotlib
        if not show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError("matplotlib is required for RMT comparison plots.") from exc

    resolved_df = load_mem_dataframe(input_dir=input_dir, data_df=data_df)
    highlight_rows = resolve_selected_rows(
        resolved_df,
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
    )
    base_title = title or "RMT comparison by cohort"
    figures = []
    axes = []
    plot_data = {"panels": {}, "figure_keys": [], "saved_pngs": {}}

    for rmt_column in RMT_COLUMNS:
        figure, axis = plt.subplots(figsize=STANDARD_FIGSIZE)
        try:
            panel_data = draw_rmt_group_axis(
                axis=axis,
                data_df=resolved_df,
                highlight_rows=highlight_rows,
                value_column=rmt_column,
                participant_id=participant_id,
                mem_date=mem_date,
                mem_filename=mem_filename,
                highlight_label=highlight_label,
                patient_label=patient_label,
                control_label=control_label,
                exclude_highlight_from_groups=exclude_highlight_from_groups,
                highlight_cortex_values=highlight_cortex_values,
            )
            style_rmt_axis(
                axis,
                title=panel_title_from_base(base_title, rmt_column),
                y_label="RMT value",
            )
            plot_data["panels"][rmt_column] = panel_data
        except ValueError as exc:
            plt.close(figure)
            plot_data["panels"][rmt_column] = {"error": str(exc)}
            continue

        output_path = output_path_with_suffix(output_png, rmt_column)
        saved_png = ""
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            figure.savefig(output_path, dpi=png_dpi, bbox_inches="tight")
            saved_png = str(output_path.resolve())
        plot_data["saved_pngs"][rmt_column] = saved_png
        figures.append(figure)
        axes.append(axis)
        plot_data["figure_keys"].append(rmt_column)

    if not figures:
        raise ValueError("No RMT panels could be rendered for the selected case and available cohorts.")

    for figure in figures:
        figure.tight_layout()
    if show and plt.get_backend().lower() != "agg":
        plt.show()
    return figures, axes, plot_data


def plot_rmt_grouped_graph(
    participant_id=None,
    mem_date=None,
    mem_filename=None,
    input_dir=None,
    data_df=None,
    match_by=None,
    age_window: int = 5,
    title: str = None,
    highlight_label: str = None,
    patient_label_base: str = "SNBR ALS",
    control_label_base: str = "SNBR Controls",
    exclude_highlight_from_groups: bool = True,
    highlight_cortex_values: list | None = None,
    output_png=None,
    png_dpi: int = 300,
    show: bool = True,
):
    """Create a matched three-panel RMT scatter comparison."""
    resolved_df = load_mem_dataframe(input_dir=input_dir, data_df=data_df)
    highlight_rows = resolve_selected_rows(
        resolved_df,
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
    )
    filtered_df, match_info = filter_to_selected_characteristics(
        resolved_df,
        selected_rows=highlight_rows,
        match_by=match_by,
        age_window=age_window,
    )
    patient_label, control_label, resolved_title = build_grouped_plot_text(
        match_info=match_info,
        patient_label_base=patient_label_base,
        control_label_base=control_label_base,
        title=title or "Matched RMT comparison",
    )
    figure, axes, plot_data = plot_rmt_group_comparison(
        participant_id=participant_id,
        mem_date=mem_date,
        mem_filename=mem_filename,
        data_df=filtered_df,
        title=resolved_title,
        highlight_label=highlight_label,
        patient_label=patient_label,
        control_label=control_label,
        exclude_highlight_from_groups=exclude_highlight_from_groups,
        highlight_cortex_values=highlight_cortex_values,
        output_png=output_png,
        png_dpi=png_dpi,
        show=show,
    )
    plot_data["match_info"] = match_info
    plot_data["filtered_data_df"] = filtered_df.reset_index(drop=True)
    return figure, axes, plot_data


def plot_mem_graph(graph_type: str = "grouped", measure: str = "t_sici", **kwargs):
    """Create a supported MEM graph by naming the graph type and optional measure."""
    normalized_type = str(graph_type).strip().lower().replace("-", "_").replace(" ", "_")
    normalized_csp_measure = normalize_csp_measure_for_graph(measure, graph_type=normalized_type)

    if normalized_csp_measure == CSP_MEASURE_KEY:
        if normalized_type in {"profile", "measure_profile"}:
            return plot_csp_profile(**kwargs)
        if normalized_type in {"grouped", "grouped_graph", "cohort", "group_comparison", "comparison"}:
            return plot_csp_grouped_graph(**kwargs)
        if normalized_type in {"participant_over_time", "over_time", "timeline", "longitudinal"}:
            return plot_participant_csp_over_time(**kwargs)
        if normalized_type in {"participant_visit_profiles", "visit_profiles", "visit_profile_grid"}:
            return plot_participant_csp_visit_profiles(**kwargs)

    if normalized_type in {"profile", "measure_profile"}:
        return plot_measure_profile(measure=measure, **kwargs)
    if normalized_type in {"grouped", "grouped_graph", "cohort", "group_comparison", "comparison"}:
        return plot_measure_grouped_graph(measure=measure, **kwargs)
    if normalized_type in {"participant_over_time", "over_time", "timeline", "longitudinal"}:
        return plot_participant_measure_over_time(measure=measure, **kwargs)
    if normalized_type in {"participant_visit_profiles", "visit_profiles", "visit_profile_grid"}:
        return plot_participant_measure_visit_profiles(measure=measure, **kwargs)
    if normalized_type in {"participant_visit_timeline", "visit_timeline", "visit_dates"}:
        return plot_participant_visit_timeline(**kwargs)
    if normalized_type in {"visit_table", "visit_tests", "visit_summary", "visit_test_table"}:
        return plot_participant_visit_test_table(**kwargs)
    if normalized_type in {"rmt_over_time", "participant_rmt_over_time"}:
        return plot_participant_rmt_over_time(**kwargs)
    if normalized_type in {"rmt_comparison", "rmt_group_comparison", "rmt_overall"}:
        return plot_rmt_group_comparison(**kwargs)
    if normalized_type in {"rmt_grouped", "rmt_grouped_graph", "rmt_matched"}:
        return plot_rmt_grouped_graph(**kwargs)

    raise ValueError(
        "Unsupported graph_type. Supported values are: profile, grouped, participant_over_time, "
        "participant_visit_profiles, participant_visit_timeline, visit_table, rmt_over_time, "
        "rmt_comparison, rmt_grouped."
    )


def plot_tsici_graph(graph_type: str = "grouped", **kwargs):
    """Create a supported T-SICI graph by naming the graph type in one line."""
    return plot_mem_graph(graph_type=graph_type, measure="t_sici", **kwargs)
