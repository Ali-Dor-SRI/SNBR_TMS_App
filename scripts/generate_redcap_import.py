"""
Generate a REDCap import CSV containing only TMS values that differ
between the Python-parsed data and the current REDCap export.

The output CSV follows REDCap's partial-import convention: each row
contains ``record_id``, ``redcap_event_name``, and **only** the TMS
columns whose values need updating.

Usage
-----
    python scripts/generate_redcap_import.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# Ensure project root is on path
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from processing.df_builder import build_combined_dataframe
from processing.redcap_mapper import to_redcap_dataframe, REDCAP_COLUMN_ORDER

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MEM_DIR = Path(r"C:\Users\Ali D\Desktop\Claude_App\1_Raw_Data\SNBR_MEM")
CSP_DIR = Path(r"C:\Users\Ali D\Desktop\Claude_App\1_Raw_Data\SNBR_CSP_RAW")
REDCAP_CSV = Path(r"C:\Users\Ali D\Desktop\Claude_App\1_Raw_Data\SNBR_REDCap\SNBR_DATA_2026-04-08_1040.csv")
OUTPUT_CSV = Path(r"C:\Users\Ali D\Desktop\Claude_App\1_Raw_Data\SNBR_REDCap\SNBR_TMS_import.csv")

TOLERANCE = 0.01  # values within this are considered matching

# REDCap cortex coding: 1 = Left, 2 = Right
PY_CORTEX_TO_RC = {"L": "1", "R": "2"}
RC_CORTEX_TO_PY = {"1": "L", "2": "R", "1.0": "L", "2.0": "R"}

# REDCap key columns that must always be present in every import row
REQUIRED_KEY_COLS = ["record_id", "redcap_event_name"]

# TMS value columns we compare and potentially import
TMS_VALUE_COLS = [c for c in REDCAP_COLUMN_ORDER]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_py_date(d: str) -> str | None:
    try:
        return datetime.strptime(str(d).strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _normalise_cortex_to_py(val) -> str | None:
    s = str(val).strip()
    if s in RC_CORTEX_TO_PY:
        return RC_CORTEX_TO_PY[s]
    if s.upper() in ("L", "R"):
        return s.upper()
    return None


def _is_numeric_and_valid(val) -> bool:
    """Return True if val is a finite numeric value."""
    try:
        v = float(val)
        return np.isfinite(v)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate_import() -> pd.DataFrame:
    """Build the REDCap import DataFrame and return it."""

    # -- 1. Parse fresh MEM data -----------------------------------------------
    print("Parsing MEM files...")
    py_df = build_combined_dataframe(str(MEM_DIR), str(CSP_DIR))
    py_snbr = py_df[py_df["Study"] == "SNBR"].copy()
    py_snbr["ID"] = pd.to_numeric(py_snbr["ID"], errors="coerce").astype("Int64")
    py_snbr["date_iso"] = py_snbr["Date"].apply(_parse_py_date)
    py_snbr["cortex_py"] = py_snbr["Stimulated_cortex"].apply(
        lambda v: str(v).strip().upper() if pd.notna(v) else None
    )

    # Transform to REDCap column names (for value lookup)
    py_rc = to_redcap_dataframe(py_snbr)
    py_rc["_record_id"] = pd.to_numeric(py_rc["record_id"], errors="coerce").astype("Int64")
    py_rc["_date_iso"] = py_snbr["date_iso"].values
    py_rc["_cortex_py"] = py_snbr["cortex_py"].values

    # Deduplicate Python records: when multiple MEM files exist for the same
    # (ID, date, cortex), keep the row with the most non-null TMS values.
    tms_cols_for_count = [c for c in REDCAP_COLUMN_ORDER if c in py_rc.columns]
    py_rc["_tms_count"] = py_rc[tms_cols_for_count].notna().sum(axis=1)
    py_rc = (
        py_rc.sort_values("_tms_count", ascending=False)
        .drop_duplicates(subset=["_record_id", "_date_iso", "_cortex_py"], keep="first")
        .drop(columns=["_tms_count"])
    )
    print(f"  Python SNBR records after dedup: {len(py_rc)}")

    # -- 2. Load REDCap data ---------------------------------------------------
    print("Loading REDCap data...")
    # record_id is REDCap's own key and is read as text: this project pads it
    # to three digits ("005"), and an import row keyed "5" names no record, so
    # REDCap creates one. Match on the number, write the key back verbatim.
    rc_df = pd.read_csv(REDCAP_CSV, low_memory=False, dtype={"record_id": str})
    rc_df["_record_key"] = rc_df["record_id"].fillna("").astype(str).str.strip()
    rc_df["record_id"] = pd.to_numeric(rc_df["_record_key"], errors="coerce").astype("Int64")
    rc_df["tt_test_date"] = rc_df["tt_test_date"].astype(str).str.strip()
    rc_df["_cortex_py"] = rc_df["cortex"].astype(str).str.strip().apply(_normalise_cortex_to_py)

    # Identify which TMS columns exist in both datasets
    shared_tms_cols = [c for c in TMS_VALUE_COLS if c in py_rc.columns and c in rc_df.columns]

    # -- 3. Match and diff -----------------------------------------------------
    print("Matching records and computing diffs...")
    import_rows: list[dict] = []
    stats = {"matched": 0, "rows_with_diffs": 0, "cells_changed": 0, "cells_filled": 0}
    per_col_changes: dict[str, int] = {}

    for _, py_row in py_rc.iterrows():
        pid = py_row["_record_id"]
        py_date = py_row.get("_date_iso", "")
        py_cortex = py_row.get("_cortex_py", "")
        if pd.isna(pid) or not py_date or not py_cortex:
            continue

        # Find matching REDCap row
        mask = (
            (rc_df["record_id"] == pid)
            & (rc_df["tt_test_date"] == py_date)
            & (rc_df["_cortex_py"] == py_cortex)
        )
        rc_match = rc_df[mask]
        if len(rc_match) == 0:
            continue

        stats["matched"] += 1
        rc_row = rc_match.iloc[0]
        event_name = rc_row["redcap_event_name"]
        record_key = rc_row["_record_key"]

        # Compare each TMS column
        changed_cols: dict[str, float | str] = {}
        for col in shared_tms_cols:
            py_val = py_row.get(col)
            rc_val = rc_row.get(col)

            py_has = _is_numeric_and_valid(py_val)
            rc_has = _is_numeric_and_valid(rc_val)

            if py_has and rc_has:
                # Both have values — include if they differ
                if abs(float(py_val) - float(rc_val)) > TOLERANCE:
                    changed_cols[col] = round(float(py_val), 2)
                    per_col_changes[col] = per_col_changes.get(col, 0) + 1
                    stats["cells_changed"] += 1
            elif py_has and not rc_has:
                # Python has data, REDCap is blank — fill the gap
                changed_cols[col] = round(float(py_val), 2)
                per_col_changes[col] = per_col_changes.get(col, 0) + 1
                stats["cells_filled"] += 1
            # else: Python blank or both blank → skip

        if changed_cols:
            row = {
                "record_id": record_key,
                "redcap_event_name": event_name,
            }
            row.update(changed_cols)
            import_rows.append(row)
            stats["rows_with_diffs"] += 1

    # -- 4. Build DataFrame, deduplicate, and order columns --------------------
    if not import_rows:
        print("No differences found — nothing to import.")
        return pd.DataFrame(columns=REQUIRED_KEY_COLS)

    import_df = pd.DataFrame(import_rows)

    # Deduplicate: multiple MEM files for the same session produce multiple
    # rows targeting the same (record_id, redcap_event_name).  Merge them
    # by keeping the first non-null value per column.
    key_cols = ["record_id", "redcap_event_name"]
    if import_df.duplicated(subset=key_cols, keep=False).any():
        deduped_rows = []
        for (pid, evt), group in import_df.groupby(key_cols, sort=False):
            merged = {"record_id": pid, "redcap_event_name": evt}
            for col in import_df.columns:
                if col in key_cols:
                    continue
                vals = group[col].dropna()
                if len(vals) > 0:
                    merged[col] = vals.iloc[0]
            deduped_rows.append(merged)
        before = len(import_df)
        import_df = pd.DataFrame(deduped_rows)
        print(f"  Deduplicated: {before} rows -> {len(import_df)} rows")

    # Order: key cols first, then TMS cols in REDCap order
    tms_cols_present = [c for c in TMS_VALUE_COLS if c in import_df.columns]
    col_order = REQUIRED_KEY_COLS + tms_cols_present
    import_df = import_df[col_order]

    # -- 5. Print summary ------------------------------------------------------
    print()
    print("=" * 60)
    print("  IMPORT CSV SUMMARY")
    print("=" * 60)
    print(f"  Matched records:          {stats['matched']}")
    print(f"  Rows with differences:    {stats['rows_with_diffs']}")
    print(f"  Cells changed (override): {stats['cells_changed']}")
    print(f"  Cells filled (was blank): {stats['cells_filled']}")
    print(f"  Total cells to update:    {stats['cells_changed'] + stats['cells_filled']}")
    print()

    print("  Per-column changes:")
    for col in tms_cols_present:
        count = per_col_changes.get(col, 0)
        if count > 0:
            print(f"    {col:<30s}  {count:>4d}")
    print()

    # Participant breakdown
    print("  Per-participant breakdown:")
    for _, row in import_df.iterrows():
        n_vals = sum(1 for c in tms_cols_present if pd.notna(row.get(c)))
        print(f"    ID {str(row['record_id']):>4s}  event={row['redcap_event_name']:<30s}  cols={n_vals}")
    print()

    # -- 6. Quality checks -----------------------------------------------------
    print("  Quality checks:")

    # Check all record_ids exist in REDCap
    valid_ids = set(rc_df["_record_key"].unique())
    bad_ids = [r for r in import_df["record_id"] if r not in valid_ids]
    print(f"    record_id validation:    {'PASS' if not bad_ids else f'FAIL — {bad_ids}'}")

    # Check all event names are valid
    valid_events = set(rc_df["redcap_event_name"].dropna().unique())
    bad_events = [e for e in import_df["redcap_event_name"] if e not in valid_events]
    print(f"    event_name validation:   {'PASS' if not bad_events else f'FAIL — {bad_events}'}")

    # Check no NaN in TMS value cells
    nan_count = import_df[tms_cols_present].isna().sum().sum()
    print(f"    no NaN in value cells:   {'PASS' if nan_count == 0 else f'FAIL — {nan_count} NaN cells'}")

    # Check all numeric values are finite
    all_vals = import_df[tms_cols_present].values.flatten()
    non_nan_vals = all_vals[~pd.isna(all_vals)]
    non_finite = sum(1 for v in non_nan_vals if not np.isfinite(float(v)))
    print(f"    all values finite:       {'PASS' if non_finite == 0 else f'FAIL — {non_finite} non-finite'}")

    print()
    return import_df


if __name__ == "__main__":
    df = generate_import()

    if len(df) > 0:
        OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(OUTPUT_CSV, index=False)
        print(f"  Import CSV written to: {OUTPUT_CSV}")
        print(f"  Rows: {len(df)}, Columns: {len(df.columns)}")
    else:
        print("  No import file generated (no differences found).")
