"""
Map internal TMS DataFrame columns to REDCap field names.

The internal DataFrame (produced by ``df_builder``) uses its own naming
conventions (e.g. ``RMT50``, ``T_SICI_1.0ms``).  REDCap expects lowercase,
underscore-separated names with protocol qualifiers (e.g. ``rmt50``,
``t_sici_p_1_0_ms``).

This module keeps the internal schema untouched and provides a translation
layer that produces a REDCap-ready DataFrame on demand.

Public API
----------
to_redcap_dataframe(df)   -> pd.DataFrame
get_column_mapping()      -> dict[str, str]
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from parser.mem_parser import (
    A_SICI_ISIS,
    ASICF_ISIS,
    CSP_RMT_LEVELS,
    TSICI_ISIS,
    TSICF_ISIS,
)
from parser.handedness import HANDEDNESS_COLUMN
from parser.sr_parser import SR_CURVE_COLUMN
from parser.strength_duration_parser import (
    SD_POINTS_COLUMN,
    SD_RHEOBASE_COLUMN,
    SD_TAU_COLUMN,
)

# ---------------------------------------------------------------------------
# REDCap ISI definitions  (superset of what the parser currently extracts)
# ---------------------------------------------------------------------------

# SICI protocols use 9 ISIs in the current REDCap template (1.0 … 7.0 ms).
# The earlier dictionary had 14 ISIs going up to 30 ms — those high-end ISIs
# were dropped from the form so we no longer emit them.
REDCAP_SICI_ISI_VALUES = [
    1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 7.0,
]

# SICF protocols use 20 ISIs in the current REDCap template — a mix of
# 0.3-step values (the default 14-ISI protocol) plus extra half-step values
# (1.5, 2.0, 3.0, 3.5, 5.0) that appear in the new "1-7ms 9 ISIs" protocol.
REDCAP_SICF_ISI_VALUES = [
    1.0, 1.3, 1.5, 1.6, 1.9, 2.0, 2.2, 2.5, 2.8, 3.0,
    3.1, 3.4, 3.5, 3.7, 4.0, 4.3, 4.6, 4.9, 5.0, 7.0,
]

# ---------------------------------------------------------------------------
# Helper: convert a numeric ISI to its REDCap field token  (e.g. 1.0 → "1_0")
# ---------------------------------------------------------------------------

def _isi_to_redcap_token(isi_value: float) -> str:
    """Convert a numeric ISI value to the REDCap underscore format.

    Examples: 1.0 → ``"1_0"``, 2.5 → ``"2_5"``, 30.0 → ``"30_0"``
    """
    if isi_value == int(isi_value):
        return f"{int(isi_value)}_0"
    whole = int(isi_value)
    frac = round((isi_value - whole) * 10)
    return f"{whole}_{frac}"


def _internal_isi_to_float(isi_label: str) -> float:
    """Convert an internal ISI label like ``"1.0ms"`` or ``"2ms"`` to float."""
    return float(isi_label.rstrip("ms"))

# ---------------------------------------------------------------------------
# Build the column mapping
# ---------------------------------------------------------------------------

def _build_mapping() -> tuple[dict[str, str], list[str]]:
    """Build (internal→redcap rename dict, redcap-only columns list).

    Returns
    -------
    rename_map : dict
        Keys are internal column names present in the DataFrame, values are
        the corresponding REDCap field names.
    redcap_only : list
        REDCap field names that have **no** internal counterpart (expanded
        ISIs).  These will be added as NaN columns.
    """
    rename: dict[str, str] = {}
    redcap_only: list[str] = []

    # -- RMT --
    rename["RMT50"] = "rmt50"
    rename["RMT200"] = "rmt200"
    rename["RMT1000"] = "rmt1000"

    # -- CSP (duration only — start/end are internal-only) --
    for level in CSP_RMT_LEVELS:
        rename[f"CSP_{level}"] = f"csp_{level}"

    # -- T-SICI  (internal prefix T_SICI → redcap prefix t_sici_p) --
    internal_tsici_floats = {_internal_isi_to_float(isi) for isi in TSICI_ISIS}
    for isi_val in REDCAP_SICI_ISI_VALUES:
        rc_col = f"t_sici_p_{_isi_to_redcap_token(isi_val)}_ms"
        if isi_val in internal_tsici_floats:
            # Find the matching internal label
            for isi_label in TSICI_ISIS:
                if _internal_isi_to_float(isi_label) == isi_val:
                    rename[f"T_SICI_{isi_label}"] = rc_col
                    break
        else:
            redcap_only.append(rc_col)

    # -- T-SICF  (internal prefix T_SICF → redcap prefix t_sicf_p) --
    internal_tsicf_floats = {_internal_isi_to_float(isi) for isi in TSICF_ISIS}
    for isi_val in REDCAP_SICF_ISI_VALUES:
        rc_col = f"t_sicf_p_{_isi_to_redcap_token(isi_val)}_ms"
        if isi_val in internal_tsicf_floats:
            for isi_label in TSICF_ISIS:
                if _internal_isi_to_float(isi_label) == isi_val:
                    rename[f"T_SICF_{isi_label}"] = rc_col
                    break
        else:
            redcap_only.append(rc_col)

    # -- A-SICI  (internal prefix A_SICI → redcap prefix a_sici_1000) --
    internal_asici_floats = {_internal_isi_to_float(isi) for isi in A_SICI_ISIS}
    for isi_val in REDCAP_SICI_ISI_VALUES:
        rc_col = f"a_sici_1000_{_isi_to_redcap_token(isi_val)}_ms"
        if isi_val in internal_asici_floats:
            for isi_label in A_SICI_ISIS:
                if _internal_isi_to_float(isi_label) == isi_val:
                    rename[f"A_SICI_{isi_label}"] = rc_col
                    break
        else:
            redcap_only.append(rc_col)

    # -- A-SICF  (internal prefix A_SICF → redcap prefix a_sicf) --
    internal_asicf_floats = {_internal_isi_to_float(isi) for isi in ASICF_ISIS}
    for isi_val in REDCAP_SICF_ISI_VALUES:
        rc_col = f"a_sicf_{_isi_to_redcap_token(isi_val)}_ms"
        if isi_val in internal_asicf_floats:
            for isi_label in ASICF_ISIS:
                if _internal_isi_to_float(isi_label) == isi_val:
                    rename[f"A_SICF_{isi_label}"] = rc_col
                    break
        else:
            redcap_only.append(rc_col)

    # -- Per-protocol ISI count radios (tms_values form) --
    rename["T_SICI_isi_n"] = "t_sici_p_isi_n"
    rename["T_SICF_isi_n"] = "t_sicf_p_isi_n"
    rename["A_SICI_isi_n"] = "a_sici_1000_isi_n"
    rename["A_SICF_isi_n"] = "a_sicf_isi_n"

    # -- TMS coil (string in internal schema, mapped to int by exporter) --
    rename["TMS_coil"] = "tms_coil"

    return rename, redcap_only


_RENAME_MAP, _REDCAP_ONLY_COLS = _build_mapping()

# Completion gates have no internal counterpart — the exporter computes them
# on the fly. Surface them as REDCap-only columns so the shared-column join
# in the exporter (py_rc ∩ rc_df) keeps them in scope.
_REDCAP_COMPLETION_COL_NAMES = (
    "tsicip_completion",
    "tsicfp_completion",
    "asici1000_completion",
    "asicf_completion",
    "csp_completion",
)
_REDCAP_ONLY_COLS = list(_REDCAP_ONLY_COLS) + list(_REDCAP_COMPLETION_COL_NAMES)

# Columns that exist internally but are NOT exported to REDCap
_INTERNAL_ONLY_COLUMNS = (
    # CSP start / end columns (REDCap only stores the duration)
    [f"CSPs_{level}" for level in CSP_RMT_LEVELS]
    + [f"CSPe_{level}" for level in CSP_RMT_LEVELS]
    # Average columns (REDCap does not have these)
    + ["T_SICI_avg", "T_SICF_avg", "A_SICI_avg", "A_SICF_avg"]
    # Strength-duration scalars + the persisted SR/SD plot data (JSON): kept in
    # the internal DataFrame / CSV only, with no REDCap counterpart.
    + [SD_RHEOBASE_COLUMN, SD_TAU_COLUMN, SR_CURVE_COLUMN, SD_POINTS_COLUMN]
    # Metadata columns that don't map directly to REDCap TMS fields.
    # Handedness is read from the .MEM header to pick which hemisphere feeds
    # cohort averages (see processing.cohort_filters); REDCap has no field
    # for it.
    + ["Study", "Subject_type", HANDEDNESS_COLUMN, "source_file"]
)

# Completion-gate yesno fields on the tms_values form. REDCap branching
# logic hides every per-ISI/CSP field unless the matching gate is set to 1.
REDCAP_COMPLETION_COLS = (
    "tsicip_completion",
    "tsicfp_completion",
    "asici1000_completion",
    "asicf_completion",
    "csp_completion",
)

# Mapping from a completion-gate field name to the REDCap-side prefix(es)
# whose presence implies that gate should be set to 1.
REDCAP_COMPLETION_GATE_FOR_PREFIX = {
    "tsicip_completion": ("t_sici_p_",),
    "tsicfp_completion": ("t_sicf_p_",),
    "asici1000_completion": ("a_sici_1000_",),
    "asicf_completion": ("a_sicf_",),
    "csp_completion": ("csp_",),
}

# REDCap radio fields on the tms_values form — option codes are integers and
# must be written without decimals (REDCap rejects "1.0" for a radio field).
REDCAP_RADIO_INT_COLS = (
    "t_sici_p_isi_n",
    "t_sicf_p_isi_n",
    "a_sici_1000_isi_n",
    "a_sicf_isi_n",
    "tms_coil",
) + REDCAP_COMPLETION_COLS

# Mapping for the TMS coil radio: internal canonical string → REDCap option code.
TMS_COIL_TO_CODE = {
    "D70^2": 1,
    "D70": 2,
    "DCC": 3,
}


# REDCap TMS value column order (matches the tms_values form layout)
REDCAP_COLUMN_ORDER = (
    # T-SICI completion + ISI-count radio + per-ISI values
    ["tsicip_completion", "t_sici_p_isi_n"]
    + [f"t_sici_p_{_isi_to_redcap_token(v)}_ms" for v in REDCAP_SICI_ISI_VALUES]
    # A-SICI completion + ISI-count radio + per-ISI values
    + ["asici1000_completion", "a_sici_1000_isi_n"]
    + [f"a_sici_1000_{_isi_to_redcap_token(v)}_ms" for v in REDCAP_SICI_ISI_VALUES]
    # A-SICF completion + ISI-count radio + per-ISI values
    + ["asicf_completion", "a_sicf_isi_n"]
    + [f"a_sicf_{_isi_to_redcap_token(v)}_ms" for v in REDCAP_SICF_ISI_VALUES]
    # T-SICF completion + ISI-count radio + per-ISI values
    + ["tsicfp_completion", "t_sicf_p_isi_n"]
    + [f"t_sicf_p_{_isi_to_redcap_token(v)}_ms" for v in REDCAP_SICF_ISI_VALUES]
    # CSP completion + per-RMT-level values
    + ["csp_completion"]
    + [f"csp_{level}" for level in CSP_RMT_LEVELS]
    # RMT (no completion gate)
    + ["rmt50", "rmt200", "rmt1000"]
    # Coil
    + ["tms_coil"]
)

# Metadata columns to carry forward (renamed for REDCap conventions)
_METADATA_RENAME = {
    "ID": "record_id",
    "Date": "date",
    "Age": "age",
    "Sex": "sex",
    "Stimulated_cortex": "cortex",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_column_mapping() -> dict[str, str]:
    """Return a copy of the internal→REDCap column rename dictionary.

    Useful for debugging and documentation.
    """
    return dict(_RENAME_MAP)


def to_redcap_dataframe(
    df: pd.DataFrame,
    *,
    include_metadata: bool = True,
) -> pd.DataFrame:
    """Transform an internal TMS DataFrame into REDCap-compatible format.

    Parameters
    ----------
    df : pd.DataFrame
        Internal DataFrame produced by ``df_builder`` (or loaded from CSV).
    include_metadata : bool
        If ``True`` (default), carry forward metadata columns (record_id,
        date, age, sex, cortex) ahead of the TMS value columns.

    Returns
    -------
    pd.DataFrame
        New DataFrame with REDCap field names, expanded ISI columns (NaN
        where no internal data exists), and internal-only columns removed.
    """
    out = df.copy()

    # 1. Rename columns that have a direct mapping
    cols_to_rename = {k: v for k, v in _RENAME_MAP.items() if k in out.columns}
    out = out.rename(columns=cols_to_rename)

    # 2. Add REDCap-only columns (expanded ISIs) as NaN
    for rc_col in _REDCAP_ONLY_COLS:
        if rc_col not in out.columns:
            out[rc_col] = np.nan

    # 3. Drop internal-only columns
    cols_to_drop = [c for c in _INTERNAL_ONLY_COLUMNS if c in out.columns]
    out = out.drop(columns=cols_to_drop, errors="ignore")

    # 4. Rename metadata columns
    if include_metadata:
        meta_rename = {k: v for k, v in _METADATA_RENAME.items() if k in out.columns}
        out = out.rename(columns=meta_rename)

    # 4b. Map tms_coil string labels to REDCap radio option codes (1/2/3).
    if "tms_coil" in out.columns:
        out["tms_coil"] = out["tms_coil"].map(
            lambda v: TMS_COIL_TO_CODE.get(v) if isinstance(v, str) else
            (v if pd.notna(v) else np.nan)
        )

    # 5. Build final column order
    if include_metadata:
        meta_cols = [v for v in _METADATA_RENAME.values() if v in out.columns]
    else:
        meta_cols = []

    ordered_cols = meta_cols + [c for c in REDCAP_COLUMN_ORDER if c in out.columns]

    # Include any remaining columns not in our explicit order
    remaining = [c for c in out.columns if c not in ordered_cols]
    ordered_cols += remaining

    return out[ordered_cols]
