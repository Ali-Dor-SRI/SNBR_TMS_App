"""
Build normalised pandas DataFrames from parsed MEM and CSP record dicts.

This module sits between the parser layer (which returns ``list[dict]``) and
the export / display layers.  It is responsible for:

* Converting record dicts into a typed, column-ordered DataFrame
* Merging CSP records into the main MEM DataFrame (conservative matching)
* Loading a previously exported CSV so only **new** .MEM files are parsed
* Recomputing derived columns (averages, CSP durations) after any merge
* Returning a clean DataFrame ready for display or export

It does **not** perform statistics, visualisation, or CSV export.

Public API
----------
build_mem_dataframe(records)                          -> pd.DataFrame
build_csp_dataframe(records)                          -> pd.DataFrame
merge_csp_into_mem(mem_df, csp_df)                    -> pd.DataFrame
build_combined_dataframe(mem_dir, csp_dir)            -> pd.DataFrame
build_combined_dataframe_incremental(mem_dir, csp_dir, existing_csv) -> pd.DataFrame
participant_data_is_current(participant_id, mem_dir, csv_path) -> bool
load_participant_dataframe(participant_id, mem_dir, csv_path, csp_dir) -> pd.DataFrame
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from parser.mem_parser import (
    A_SICI_ISIS,
    ASICF_ISIS,
    CSP_RMT_LEVELS,
    TSICI_ISIS,
    TSICF_ISIS,
    iter_files,
    iter_mem_files,
    normalize_dirs,
    output_column_order,
    parse_mem_file,
    parse_mem_directory,
)
from parser.CSP_parser import (
    CSP_VALUE_COLUMNS,
    csp_output_columns,
    parse_csp_directory,
)
from parser.cmap_parser import (
    cmap_output_columns,
    parse_cmap_directory,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NUMERIC_OUTPUT_COLUMNS = (
    ["ID", "Age", "RMT50", "RMT200", "RMT1000"]
    + [f"T_SICI_{isi}" for isi in TSICI_ISIS]
    + [f"T_SICF_{isi}" for isi in TSICF_ISIS]
    + [f"A_SICI_{isi}" for isi in A_SICI_ISIS]
    + [f"A_SICF_{isi}" for isi in ASICF_ISIS]
    + list(CSP_VALUE_COLUMNS)
    + ["T_SICI_avg", "T_SICF_avg", "A_SICI_avg", "A_SICF_avg"]
)

CSP_NUMERIC_COLUMNS = (
    ["ID", "Age"]
    + list(CSP_VALUE_COLUMNS)
)

ACQUISITION_TOKEN_PATTERN = re.compile(
    r"([A-Z]+(?:\d+C|C)\d+[A-Z])", flags=re.IGNORECASE
)

SOURCE_FILE_SEPARATOR = "; "


def _split_source_files(value) -> list[str]:
    """Split a (possibly coalesced) source_file cell into its constituent names."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return []
    return [n.strip() for n in str(value).split(";") if n.strip()]


# ---------------------------------------------------------------------------
# Recompute helpers
# ---------------------------------------------------------------------------

def _recompute_average_column(
    df: pd.DataFrame,
    value_columns: list[str],
    average_column: str,
) -> None:
    """Recompute one average column in-place."""
    df[value_columns] = df[value_columns].apply(pd.to_numeric, errors="coerce")
    df[average_column] = df[value_columns].mean(axis=1, skipna=True)
    all_missing = df[value_columns].isna().all(axis=1)
    df.loc[all_missing, average_column] = np.nan


def _recompute_waveform_averages(df: pd.DataFrame) -> pd.DataFrame:
    """Recompute all four waveform-family averages (single copy)."""
    updated = df.copy()
    _recompute_average_column(updated, [f"T_SICI_{isi}" for isi in TSICI_ISIS], "T_SICI_avg")
    _recompute_average_column(updated, [f"T_SICF_{isi}" for isi in TSICF_ISIS], "T_SICF_avg")
    _recompute_average_column(updated, [f"A_SICI_{isi}" for isi in A_SICI_ISIS], "A_SICI_avg")
    _recompute_average_column(updated, [f"A_SICF_{isi}" for isi in ASICF_ISIS], "A_SICF_avg")
    return updated


def _recompute_csp_durations(df: pd.DataFrame) -> pd.DataFrame:
    """Recompute CSP = CSPe - CSPs for every RMT level."""
    updated = df.copy()
    # Coerce all CSP start/end columns to numeric once.
    all_csp_cols = []
    for level in CSP_RMT_LEVELS:
        for prefix in (f"CSPs_{level}", f"CSPe_{level}"):
            if prefix not in updated.columns:
                updated[prefix] = np.nan
            all_csp_cols.append(prefix)
    updated[all_csp_cols] = updated[all_csp_cols].apply(pd.to_numeric, errors="coerce")
    # Compute durations.
    for level in CSP_RMT_LEVELS:
        s_col, e_col, d_col = f"CSPs_{level}", f"CSPe_{level}", f"CSP_{level}"
        updated[d_col] = updated[e_col] - updated[s_col]
        missing = updated[s_col].isna() | updated[e_col].isna()
        updated.loc[missing, d_col] = np.nan
    return updated


# ---------------------------------------------------------------------------
# Normalisation (column typing, ordering, derived columns)
# ---------------------------------------------------------------------------

def _normalize_mem_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Align a DataFrame to the full MEM output schema."""
    norm = df.copy()
    for col in output_column_order():
        if col not in norm.columns:
            norm[col] = np.nan
    for col in NUMERIC_OUTPUT_COLUMNS:
        if col in norm.columns:
            norm[col] = pd.to_numeric(norm[col], errors="coerce")
    norm = norm[output_column_order()]
    norm = _recompute_waveform_averages(norm)
    norm = _recompute_csp_durations(norm)
    return (
        norm.sort_values(["ID", "source_file"], na_position="last")
        .reset_index(drop=True)
    )


def _normalize_csp_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Align a DataFrame to the CSP output schema."""
    norm = df.copy()
    for col in csp_output_columns():
        if col not in norm.columns:
            norm[col] = np.nan
    for col in CSP_NUMERIC_COLUMNS:
        if col in norm.columns:
            norm[col] = pd.to_numeric(norm[col], errors="coerce")
    norm = _recompute_csp_durations(norm)
    norm = norm[csp_output_columns()]
    return (
        norm.sort_values(["ID", "source_file"], na_position="last")
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# Build DataFrames from parser output
# ---------------------------------------------------------------------------

def build_mem_dataframe(records: list[dict]) -> pd.DataFrame:
    """Convert a list of parsed MEM record dicts into a normalised DataFrame."""
    if not records:
        return _normalize_mem_dataframe(
            pd.DataFrame(columns=output_column_order())
        )
    return _normalize_mem_dataframe(
        pd.DataFrame(records, columns=output_column_order())
    )


def build_csp_dataframe(records: list[dict]) -> pd.DataFrame:
    """Convert a list of parsed CSP record dicts into a normalised DataFrame."""
    if not records:
        return _normalize_csp_dataframe(
            pd.DataFrame(columns=csp_output_columns())
        )
    return _normalize_csp_dataframe(
        pd.DataFrame(records, columns=csp_output_columns())
    )


# ---------------------------------------------------------------------------
# CSP merge (conservative matching — ported from V1)
# ---------------------------------------------------------------------------

def _acquisition_token(source_name) -> str:
    """Extract the acquisition token from a source filename for matching."""
    if source_name is None or (isinstance(source_name, float) and np.isnan(source_name)):
        return ""
    stem = Path(str(source_name)).stem.upper()
    tokens = ACQUISITION_TOKEN_PATTERN.findall(stem)
    return tokens[-1] if tokens else ""


def _match_key_maps(
    df: pd.DataFrame,
    key_columns: list[str],
    allowed_indices: set[int] | None = None,
) -> dict[tuple, list[int]]:
    """Map composite keys to row indices, skipping rows with missing key values."""
    indices = list(df.index) if allowed_indices is None else list(allowed_indices)
    key_map: dict[tuple, list[int]] = defaultdict(list)
    for idx in indices:
        row = df.loc[idx]
        vals: list = []
        skip = False
        for col in key_columns:
            v = row[col]
            if pd.isna(v) or (isinstance(v, str) and not v.strip()):
                skip = True
                break
            vals.append(v)
        if not skip:
            key_map[tuple(vals)].append(idx)
    return key_map


def merge_csp_into_mem(
    mem_df: pd.DataFrame,
    csp_df: pd.DataFrame,
) -> pd.DataFrame:
    """Merge CSP rows into a MEM DataFrame using conservative matching.

    Matching strategy (two passes):
    1. Exact match on (ID, Date, acquisition-token).
    2. Fallback match on (ID, Date) for remaining unmatched rows.
    Only 1-to-1 matches are accepted in each pass.

    CSP values are written into matched MEM rows. Unmatched CSP rows are
    appended as new rows so no data is lost.
    """
    main = _normalize_mem_dataframe(mem_df)
    csp = _normalize_mem_dataframe(csp_df)

    if csp.empty:
        result = main.copy()
        result.attrs["csp_rows_loaded"] = 0
        result.attrs["csp_rows_merged"] = 0
        result.attrs["csp_rows_appended"] = 0
        return result

    main_work = main.copy()
    csp_work = csp.copy()

    for frame in (main_work, csp_work):
        frame["_match_id"] = pd.to_numeric(frame["ID"], errors="coerce")
        frame["_match_date"] = (
            frame["Date"].astype("string").fillna("").str.strip()
        )
        frame["_match_token"] = frame["source_file"].apply(_acquisition_token)

    matched_pairs: list[tuple[int, int]] = []
    matched_main: set[int] = set()
    matched_csp: set[int] = set()

    # Pass 1: exact (ID, Date, token)
    exact_main = _match_key_maps(
        main_work, ["_match_id", "_match_date", "_match_token"]
    )
    exact_csp = _match_key_maps(
        csp_work, ["_match_id", "_match_date", "_match_token"]
    )
    for key in sorted(set(exact_main) & set(exact_csp)):
        mi, ci = exact_main[key], exact_csp[key]
        if len(mi) == 1 and len(ci) == 1:
            matched_pairs.append((mi[0], ci[0]))
            matched_main.add(mi[0])
            matched_csp.add(ci[0])

    # Pass 2: fallback (ID, Date) for remaining rows
    fb_main = _match_key_maps(
        main_work,
        ["_match_id", "_match_date"],
        allowed_indices={i for i in main_work.index if i not in matched_main},
    )
    fb_csp = _match_key_maps(
        csp_work,
        ["_match_id", "_match_date"],
        allowed_indices={i for i in csp_work.index if i not in matched_csp},
    )
    for key in sorted(set(fb_main) & set(fb_csp)):
        mi, ci = fb_main[key], fb_csp[key]
        if len(mi) == 1 and len(ci) == 1:
            matched_pairs.append((mi[0], ci[0]))
            matched_main.add(mi[0])
            matched_csp.add(ci[0])

    # Write CSP values into matched MEM rows
    for m_idx, c_idx in matched_pairs:
        for col in CSP_VALUE_COLUMNS:
            csp_val = csp_work.at[c_idx, col]
            if not pd.isna(csp_val):
                main_work.at[m_idx, col] = csp_val
        # Fill in missing demographics from CSP when MEM is blank
        for col in ["Date", "Age", "Sex", "Subject_type", "Stimulated_cortex"]:
            if pd.isna(main_work.at[m_idx, col]):
                csp_val = csp_work.at[c_idx, col]
                if not pd.isna(csp_val):
                    main_work.at[m_idx, col] = csp_val

    # Append unmatched CSP rows
    unmatched_csp_indices = [
        i for i in csp_work.index if i not in matched_csp
    ]
    appended = csp_work.loc[unmatched_csp_indices, output_column_order()].copy()
    combined = pd.concat(
        [main_work[output_column_order()], appended], ignore_index=True
    )
    combined = _normalize_mem_dataframe(combined)

    combined.attrs["csp_rows_loaded"] = len(csp_work)
    combined.attrs["csp_rows_merged"] = len(matched_pairs)
    combined.attrs["csp_rows_appended"] = len(appended)
    return combined


# ---------------------------------------------------------------------------
# CMAP (motor nerve conduction study) merge
# ---------------------------------------------------------------------------

def build_cmap_dataframe(records: list[dict]) -> pd.DataFrame:
    """Convert parsed CMAP record dicts into a minimal DataFrame."""
    if not records:
        return pd.DataFrame(columns=cmap_output_columns())
    df = pd.DataFrame(records, columns=cmap_output_columns())
    df["ID"] = pd.to_numeric(df["ID"], errors="coerce")
    return df


def merge_cmap_into_mem(
    mem_df: pd.DataFrame,
    cmap_df: pd.DataFrame,
) -> pd.DataFrame:
    """Merge CMAP records into the MEM DataFrame on ``(ID, Date)``.

    CMAP is supplementary to MEM: every CMAP table is written onto the
    matching MEM row(s) for the same ``(ID, Date)``. When more than one MEM
    row shares the same key (e.g. two hemispheres recorded on the same
    visit), the CMAP table is written onto every match so the data is
    available regardless of which hemisphere the user views.

    Unmatched CMAP records (participant has no MEM file on that date) are
    **dropped**, not appended — they would otherwise show up as phantom
    visit dates with no MEM data, breaking participant/visit selection for
    every other graph type.  The number of dropped records is reported via
    ``df.attrs["cmap_rows_dropped"]`` so callers can surface a warning.
    """
    main = _normalize_mem_dataframe(mem_df)

    if cmap_df is None or cmap_df.empty:
        result = main.copy()
        result.attrs["cmap_rows_loaded"] = 0
        result.attrs["cmap_rows_merged"] = 0
        result.attrs["cmap_rows_dropped"] = 0
        return result

    main_work = main.copy()
    # CMAP_table / MUNIX_table hold JSON strings; pandas may infer them as
    # float64 when the columns are created empty. Force object dtype so
    # string assignments work.
    for col in ("CMAP_table", "MUNIX_table"):
        if col in main_work.columns:
            main_work[col] = main_work[col].astype(object)
    cmap_work = cmap_df.copy()
    if "MUNIX_table" not in cmap_work.columns:
        cmap_work["MUNIX_table"] = None
    cmap_work["_match_id"] = pd.to_numeric(cmap_work["ID"], errors="coerce")
    cmap_work["_match_date"] = (
        cmap_work["Date"].astype("string").fillna("").str.strip()
    )

    main_work["_match_id"] = pd.to_numeric(main_work["ID"], errors="coerce")
    main_work["_match_date"] = (
        main_work["Date"].astype("string").fillna("").str.strip()
    )

    matched_cmap: set[int] = set()
    merged_rows = 0
    for c_idx, c_row in cmap_work.iterrows():
        cid, cdate = c_row["_match_id"], c_row["_match_date"]
        if pd.isna(cid) or not cdate:
            continue
        hits = main_work.index[
            (main_work["_match_id"] == cid)
            & (main_work["_match_date"] == cdate)
        ].tolist()
        if not hits:
            continue
        cmap_val = c_row.get("CMAP_table")
        munix_val = c_row.get("MUNIX_table")
        for m_idx in hits:
            if not pd.isna(cmap_val):
                main_work.at[m_idx, "CMAP_table"] = cmap_val
            if not pd.isna(munix_val):
                main_work.at[m_idx, "MUNIX_table"] = munix_val
        matched_cmap.add(c_idx)
        merged_rows += len(hits)

    dropped = len(cmap_work) - len(matched_cmap)
    combined = main_work[output_column_order()].copy()
    combined = _normalize_mem_dataframe(combined)
    combined.attrs["cmap_rows_loaded"] = len(cmap_work)
    combined.attrs["cmap_rows_merged"] = merged_rows
    combined.attrs["cmap_rows_dropped"] = dropped
    return combined


def _apply_cmap_merge(
    df: pd.DataFrame,
    cmap_dir: str | Path | list[str | Path] | None,
    *,
    recursive: bool = True,
) -> pd.DataFrame:
    """Helper — parse CMAP files (if any) and merge into *df*."""
    if not normalize_dirs(cmap_dir):
        return df
    records = parse_cmap_directory(cmap_dir, recursive=recursive)
    if not records:
        return df
    cmap_df = build_cmap_dataframe(records)
    return merge_cmap_into_mem(df, cmap_df)


# ---------------------------------------------------------------------------
# Same-session row coalescing
# ---------------------------------------------------------------------------

def _coalesce_same_session_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse rows sharing the same (ID, Date) into a single row.

    Multiple .MEM files for the same participant collected on the same date
    typically hold complementary measures (e.g. one file carries RMT data,
    another the T-SICI block). This combines them by taking the first
    non-null value per column across the group. ``source_file`` is joined
    with ``SOURCE_FILE_SEPARATOR`` so the provenance of every contributing
    file is preserved. Rows lacking ID or Date are passed through unchanged.
    """
    if df.empty or "ID" not in df.columns or "Date" not in df.columns:
        return df

    work = df.copy()
    work["_g_id"] = pd.to_numeric(work["ID"], errors="coerce")
    work["_g_date"] = work["Date"].astype("string").fillna("").str.strip()
    groupable = work["_g_id"].notna() & work["_g_date"].ne("")
    keyed = work[groupable]
    unkeyed = work[~groupable].drop(columns=["_g_id", "_g_date"])

    if keyed.empty:
        return unkeyed[df.columns.tolist()].reset_index(drop=True)

    output_cols = [c for c in df.columns if c not in ("_g_id", "_g_date")]
    combined_rows: list[dict] = []
    for _, group in keyed.groupby(["_g_id", "_g_date"], sort=False):
        if len(group) == 1:
            row = group.iloc[0]
            combined_rows.append({c: row[c] for c in output_cols})
            continue
        out: dict = {}
        for col in output_cols:
            if col == "source_file":
                names: list[str] = []
                seen: set[str] = set()
                for v in group[col].tolist():
                    for n in _split_source_files(v):
                        if n not in seen:
                            seen.add(n)
                            names.append(n)
                out[col] = SOURCE_FILE_SEPARATOR.join(names) if names else np.nan
                continue
            non_null = group[col].dropna()
            out[col] = non_null.iloc[0] if not non_null.empty else np.nan
        combined_rows.append(out)

    combined = pd.DataFrame(combined_rows, columns=output_cols)
    if unkeyed.empty:
        return combined.reset_index(drop=True)
    return pd.concat(
        [combined, unkeyed[output_cols]], ignore_index=True
    )


# ---------------------------------------------------------------------------
# Loading a previously exported CSV (for incremental builds)
# ---------------------------------------------------------------------------

def _source_file_set(df: pd.DataFrame) -> set[str]:
    """Return the set of non-empty source filenames in *df*.

    A single ``source_file`` cell may list several filenames joined by
    ``SOURCE_FILE_SEPARATOR`` (rows coalesced from multiple .MEM files for
    the same participant/date); this returns every individual filename.
    """
    if "source_file" not in df.columns:
        return set()
    names: set[str] = set()
    for value in df["source_file"].tolist():
        names.update(_split_source_files(value))
    return names


def load_existing_csv(csv_path: str | Path) -> pd.DataFrame:
    """Load a previously exported CSV and normalise it to the current schema.

    Handles legacy T-SICI delta encoding (raw deltas instead of 100-based
    percentages) by auto-upgrading when detected.
    """
    csv_path = Path(csv_path)
    existing = pd.read_csv(csv_path)
    if "source_file" not in existing.columns:
        raise ValueError(
            f"CSV is missing required column 'source_file': {csv_path}"
        )

    # Detect and upgrade legacy T-SICI delta encoding
    tsici_cols = [
        f"T_SICI_{isi}" for isi in TSICI_ISIS
        if f"T_SICI_{isi}" in existing.columns
    ]
    if tsici_cols:
        numeric = existing[tsici_cols].apply(pd.to_numeric, errors="coerce")
        finite = numeric.to_numpy(dtype=float)
        finite = finite[np.isfinite(finite)]
        if finite.size > 0:
            if float(np.nanmin(finite)) < 0.0 or float(np.nanmax(finite)) <= 60.0:
                existing[tsici_cols] = numeric + 100.0

    # Backfill missing Study column for legacy CSVs (all historical data is SNBR)
    if "Study" not in existing.columns:
        existing.insert(0, "Study", "SNBR")

    return _normalize_mem_dataframe(existing)


# ---------------------------------------------------------------------------
# High-level build functions
# ---------------------------------------------------------------------------

def build_combined_dataframe(
    mem_dir: str | Path | list[str | Path],
    csp_dir: str | Path | list[str | Path] | None = None,
    cmap_dir: str | Path | list[str | Path] | None = None,
    *,
    mem_recursive: bool = True,
    csp_recursive: bool = True,
    cmap_recursive: bool = True,
) -> pd.DataFrame:
    """Parse all MEM (and optionally CSP / CMAP) files and return one merged DataFrame.

    Parameters
    ----------
    mem_dir : path or list of paths
        Folder(s) containing .MEM files for the main TMS measures.  When a
        list is given, files are collected from every folder.
    csp_dir, cmap_dir : path or list of paths, optional
        Folder(s) for CSP / CMAP files.  When ``None``, those columns are
        left empty (no merge).
    mem_recursive, csp_recursive, cmap_recursive : bool
        When ``True`` (default) subfolders are searched too.  Set ``False``
        to scan only files directly inside the selected folders.
    """
    mem_records = parse_mem_directory(
        mem_dir, exclude_dirs=[csp_dir, cmap_dir], recursive=mem_recursive,
    )
    mem_df = build_mem_dataframe(mem_records)

    if iter_files(csp_dir, "*.MEM", recursive=csp_recursive):
        csp_records = parse_csp_directory(csp_dir, recursive=csp_recursive)
        csp_df = build_csp_dataframe(csp_records)
        mem_df = merge_csp_into_mem(mem_df, csp_df)

    mem_df = _apply_cmap_merge(mem_df, cmap_dir, recursive=cmap_recursive)

    return _normalize_mem_dataframe(_coalesce_same_session_rows(mem_df))


def build_combined_dataframe_incremental(
    mem_dir: str | Path | list[str | Path],
    csp_dir: str | Path | list[str | Path] | None = None,
    existing_csv: str | Path | None = None,
    cmap_dir: str | Path | list[str | Path] | None = None,
    *,
    mem_recursive: bool = True,
    csp_recursive: bool = True,
    cmap_recursive: bool = True,
) -> pd.DataFrame:
    """Build a DataFrame, only parsing .MEM files not already in *existing_csv*.

    Workflow
    -------
    1. List .MEM filenames in *mem_dir*.
    2. If *existing_csv* is provided, load it and diff the ``source_file``
       column against the folder listing.
    3. If the sets match exactly (no new files, no removed files, schema is
       current) — return the existing DataFrame as-is.
    4. Otherwise, parse only the **new** files, combine with existing rows
       (dropping rows for removed files), re-merge CSP data, normalise, and
       return.

    Parameters
    ----------
    mem_dir : path or list of paths
        Folder(s) containing .MEM files.  A list collects files from each.
    csp_dir : path, optional
        Folder containing CSP .MEM files.
    existing_csv : path, optional
        Path to the latest previously exported CSV.  When ``None``, all files
        are parsed from scratch.

    Returns
    -------
    pd.DataFrame
        The attrs dict on the returned DataFrame contains metadata:

        - ``new_files_parsed`` : int
        - ``removed_files_dropped`` : int
        - ``reused_existing`` : bool
        - ``total_mem_files`` : int
    """
    mem_roots = normalize_dirs(mem_dir)
    if not any(r.exists() for r in mem_roots):
        shown = ", ".join(str(r) for r in mem_roots) or "(none provided)"
        raise FileNotFoundError(f"MEM folder does not exist: {shown}")

    mem_files = iter_mem_files(
        mem_roots, exclude_dirs=[csp_dir, cmap_dir], recursive=mem_recursive,
    )
    if not mem_files:
        shown = ", ".join(str(r) for r in mem_roots)
        raise FileNotFoundError(f"No .MEM files found in: {shown}")

    mem_filenames = {f.name for f in mem_files}

    # Also list CSP folder contents so CSP-appended rows in the existing CSV
    # aren't mistakenly flagged as orphans below (their source_file is a CSP
    # filename, not a MEM one).
    csp_filenames = {
        f.name for f in iter_files(csp_dir, "*.MEM", recursive=csp_recursive)
    }

    # ---- Load existing CSV (if any) ----
    if existing_csv is not None and Path(existing_csv).exists():
        existing_df = load_existing_csv(existing_csv)
        existing_names = _source_file_set(existing_df)
    else:
        existing_df = pd.DataFrame(columns=output_column_order())
        existing_names = set()

    new_names = mem_filenames - existing_names
    # Rows in the CSV whose source file is no longer present in EITHER source
    # folder. Must be dropped to keep the DataFrame in sync with disk.
    orphan_names = existing_names - mem_filenames - csp_filenames

    # ---- Fast path: nothing changed ----
    expected_cols = set(output_column_order()) | {"source_file"}
    schema_current = expected_cols.issubset(set(existing_df.columns))

    if not new_names and not orphan_names and schema_current:
        result = existing_df.copy()
        result.attrs["new_files_parsed"] = 0
        result.attrs["removed_files_dropped"] = 0
        result.attrs["reused_existing"] = True
        result.attrs["total_mem_files"] = len(mem_files)
        return result

    # ---- Incremental path ----
    # Keep only rows whose source files are ALL still present in mem_dir.
    # A coalesced row (multiple .MEM files joined into one row) is dropped
    # in full if any of its constituent files is missing — the remaining
    # files get re-parsed below so the rebuilt row stays consistent.
    if not existing_df.empty:
        def _all_on_disk(value) -> bool:
            files = _split_source_files(value)
            return bool(files) and all(n in mem_filenames for n in files)

        keep_mask = existing_df["source_file"].apply(_all_on_disk)
        kept_df = existing_df.loc[keep_mask].copy()
    else:
        kept_df = existing_df.copy()

    # Re-parse any file not represented in a kept row (covers both genuinely
    # new files and survivors of a partially-orphaned coalesced row).
    kept_filenames = _source_file_set(kept_df)
    files_to_parse = mem_filenames - kept_filenames

    new_records: list[dict] = []
    for filepath in mem_files:
        if filepath.name in files_to_parse:
            record = parse_mem_file(filepath)
            record["source_file"] = filepath.name
            new_records.append(record)

    if new_records:
        new_df = build_mem_dataframe(new_records)
        combined = pd.concat([kept_df, new_df], ignore_index=True)
    else:
        combined = kept_df

    # ---- Re-merge CSP data ----
    if iter_files(csp_dir, "*.MEM", recursive=csp_recursive):
        csp_records = parse_csp_directory(csp_dir, recursive=csp_recursive)
        csp_df = build_csp_dataframe(csp_records)
        combined = merge_csp_into_mem(combined, csp_df)

    # ---- Re-merge CMAP data ----
    combined = _apply_cmap_merge(combined, cmap_dir, recursive=cmap_recursive)

    combined = _coalesce_same_session_rows(_normalize_mem_dataframe(combined))
    combined = _normalize_mem_dataframe(combined)
    combined.attrs["new_files_parsed"] = len(new_names)
    combined.attrs["removed_files_dropped"] = len(orphan_names)
    combined.attrs["reused_existing"] = False
    combined.attrs["total_mem_files"] = len(mem_files)
    return combined


# ---------------------------------------------------------------------------
# Participant-level currency check (for report generation)
# ---------------------------------------------------------------------------

_PARTICIPANT_FILE_PATTERN = re.compile(
    r"[A-Za-z]+\d*-0*(\d+)", flags=re.IGNORECASE
)


def participant_mem_files(
    participant_id: int,
    mem_dir: str | Path,
) -> set[str]:
    """Return the set of .MEM filenames in *mem_dir* belonging to *participant_id*.

    Searches subfolders recursively, mirroring the recursive MEM parse.
    """
    result: set[str] = set()
    for f in iter_mem_files(mem_dir):
        m = _PARTICIPANT_FILE_PATTERN.match(f.name)
        if m and int(m.group(1)) == participant_id:
            result.add(f.name)
    return result


def participant_data_is_current(
    participant_id: int,
    mem_dir: str | Path,
    csv_path: str | Path,
) -> bool:
    """Return ``True`` if every .MEM file for *participant_id* is in the CSV."""
    mem_files = participant_mem_files(participant_id, mem_dir)
    if not mem_files:
        return False
    existing_df = load_existing_csv(csv_path)
    csv_sources = _source_file_set(existing_df)
    return mem_files.issubset(csv_sources)


def load_participant_dataframe(
    participant_id: int,
    mem_dir: str | Path,
    csv_path: str | Path,
    csp_dir: str | Path | list[str | Path] | None = None,
    force_rebuild: bool = False,
    export_csv: bool = False,
    output_dir: str | Path | None = None,
) -> pd.DataFrame:
    """Load a DataFrame for report generation, skipping rebuild if data is current.

    If every .MEM file for *participant_id* already appears in the CSV at
    *csv_path*, the CSV is loaded directly — no new DataFrame is built and
    no new CSV is written.

    Otherwise an incremental in-memory build is performed (new files are
    parsed and merged).

    Parameters
    ----------
    force_rebuild : bool
        When ``True``, skip the currency check and always perform an
        incremental build.
    export_csv : bool
        When ``True``, write the rebuilt DataFrame to a new timestamped CSV
        in *output_dir* (or the same directory as *csv_path* if *output_dir*
        is ``None``).  Ignored when the existing CSV is reused unchanged.
    output_dir : path, optional
        Directory for the exported CSV.  Defaults to the parent directory
        of *csv_path*.
    """
    if not force_rebuild and participant_data_is_current(participant_id, mem_dir, csv_path):
        return load_existing_csv(csv_path)

    df = build_combined_dataframe_incremental(
        mem_dir=mem_dir,
        csp_dir=csp_dir,
        existing_csv=None if force_rebuild else csv_path,
    )

    if export_csv:
        from reports.csv_exporter import export_dataframe
        dest = Path(output_dir) if output_dir is not None else Path(csv_path).parent
        new_csv = export_dataframe(df, dest)
        print(f"CSV exported to: {new_csv}")

    return df
