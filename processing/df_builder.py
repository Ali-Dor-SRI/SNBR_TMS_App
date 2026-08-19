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
from parser.recording_target import (
    MUSCLE_COLUMN,
    SIDE_COLUMN,
    is_hand_muscle,
    target_key,
    target_label,
)
from parser.sr_parser import SR_MAX_COLUMN
from parser.strength_duration_parser import SD_RHEOBASE_COLUMN, SD_TAU_COLUMN
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
    + [SR_MAX_COLUMN]
    + [SD_RHEOBASE_COLUMN, SD_TAU_COLUMN]
)

CSP_NUMERIC_COLUMNS = (
    ["ID", "Age"]
    + list(CSP_VALUE_COLUMNS)
)

ACQUISITION_TOKEN_PATTERN = re.compile(
    r"([A-Z]+(?:\d+C|C)\d+[A-Z])", flags=re.IGNORECASE
)

SOURCE_FILE_SEPARATOR = "; "


def _has_any_value(df: pd.DataFrame, columns: list[str]) -> bool:
    """Whether *df* holds at least one non-null value across *columns*."""
    present = [c for c in columns if c in df.columns]
    return bool(present) and bool(df[present].notna().any().any())


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

    Matching strategy (three passes):
    1. Exact match on (ID, Date, acquisition-token).
    2. Recording-target match on (ID, Date, muscle, side) — a visit that
       recorded two muscles usually has one CSP file per muscle, and without
       this pass neither could match 1-to-1 on (ID, Date) alone.
    3. Fallback match on (ID, Date) for remaining unmatched rows.
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

    # Passes 2 and 3: recording target, then a bare (ID, Date) fallback.
    for key_columns in (
        ["_match_id", "_match_date", MUSCLE_COLUMN, SIDE_COLUMN],
        ["_match_id", "_match_date"],
    ):
        fb_main = _match_key_maps(
            main_work,
            key_columns,
            allowed_indices={i for i in main_work.index if i not in matched_main},
        )
        fb_csp = _match_key_maps(
            csp_work,
            key_columns,
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

def resolve_visit_targets(group: pd.DataFrame) -> dict:
    """Map each row index of a one-visit *group* to its recording-target key.

    A visit's .MEM files split into targets by (muscle, recorded side), but
    both header fields are frequently absent, so raw keys would fragment
    visits that are really one recording.  Two absorption rules keep that from
    happening:

    * **Side absorption** — a file with a muscle but no side joins that
      muscle's single known side for the visit.  It only keeps an empty side
      (becoming its own "side unspecified" target) when the visit genuinely
      recorded that muscle on two or more sides, so the file cannot be
      attributed.
    * **Single-target collapse** — when the visit resolves to at most one
      identified target, *every* row collapses onto it, including rows with no
      muscle header at all (peripheral nerve-excitability files).  This is the
      overwhelmingly common case and reproduces the historical
      one-row-per-visit behaviour exactly.  Only when two or more targets are
      identified do muscle-less rows stay on their own visit-level row, where
      the cortex/target-independent graph types still find them.
    """
    resolved: dict = {}
    sides_by_muscle: dict[str, set[str]] = defaultdict(set)

    raw: dict = {}
    for idx in group.index:
        muscle, side = target_key(
            group.at[idx, MUSCLE_COLUMN] if MUSCLE_COLUMN in group.columns else None,
            group.at[idx, SIDE_COLUMN] if SIDE_COLUMN in group.columns else None,
        )
        raw[idx] = (muscle, side)
        if muscle and side:
            sides_by_muscle[muscle].add(side)

    for idx, (muscle, side) in raw.items():
        if not muscle:
            resolved[idx] = ("", "")
        elif side:
            resolved[idx] = (muscle, side)
        else:
            known = sides_by_muscle.get(muscle, set())
            resolved[idx] = (muscle, known.pop()) if len(known) == 1 else (muscle, "")

    identified = {t for t in resolved.values() if t[0]}
    if len(identified) <= 1:
        only = identified.pop() if identified else ("", "")
        return {idx: only for idx in resolved}
    return resolved


def target_labels_in(rows: pd.DataFrame) -> list[str]:
    """Return the distinct recording-target labels present in *rows*.

    Ordered hand muscles first, then by muscle and side, so a report lists
    ``["Right FDI", "Right TA"]`` rather than an arbitrary order. Rows with no
    identified muscle contribute nothing — they are visit-level data, not a
    selectable target.
    """
    if MUSCLE_COLUMN not in rows.columns:
        return []
    pairs = {
        target_key(row[MUSCLE_COLUMN], row.get(SIDE_COLUMN))
        for _, row in rows.iterrows()
    }
    pairs = {p for p in pairs if p[0]}
    ordered = sorted(
        pairs, key=lambda p: (0 if is_hand_muscle(p[0]) else 1, p[0], p[1]),
    )
    return [target_label(m, s) for m, s in ordered]


def restrict_participant_to_target(
    df: pd.DataFrame, participant_id, target: str | None,
) -> pd.DataFrame:
    """Return *df* with one participant's rows restricted to one recording target.

    Only that participant is filtered. Cohort reference groups stay pooled
    across muscles by design, so a right-TA trace is still drawn against the
    whole reference cohort rather than a TA-only subset — every other
    participant's rows pass through untouched.

    The participant's own rows that carry no target are kept as well: they hold
    visit-level data (the CMAP/MUNIX tables) that belongs to the visit rather
    than to any one muscle.
    """
    if not target or MUSCLE_COLUMN not in df.columns or participant_id is None:
        return df
    labels = df.apply(
        lambda r: target_label(r[MUSCLE_COLUMN], r.get(SIDE_COLUMN)), axis=1,
    )
    is_participant = pd.to_numeric(df["ID"], errors="coerce") == participant_id
    return df[~is_participant | (labels == target) | (labels == "")]


# ---------------------------------------------------------------------------
# Mislabelled-file detection
# ---------------------------------------------------------------------------

# Study tokens a .MEM filename may carry before the participant number, longest
# first so "AASNBR-080" is not read as the "SNBR-080" nested inside it.
_FILENAME_STUDY_TOKENS = (
    "AASNBR", "SNBR", "NIALS", "NIAL", "NAILS", "QUARTS", "QUART", "TMS",
)
_FILENAME_ID_PATTERN = re.compile(
    r"(?:" + "|".join(_FILENAME_STUDY_TOKENS) + r")[-_ ]?0*(\d+)",
    flags=re.IGNORECASE,
)


def filename_participant_ids(filename) -> set:
    """Return the participant numbers a .MEM filename names.

    Empty when the name carries no ``<study><number>`` token at all — many Qtrac
    exports are named only by their acquisition code (``TMSC20802A.MEM``), and a
    file that never claims a participant cannot contradict one.
    """
    stem = Path(str(filename or "")).stem
    found = set()
    for match in _FILENAME_ID_PATTERN.finditer(stem):
        try:
            found.add(int(match.group(1)))
        except ValueError:
            continue
    return found


def detect_participant_id_mismatches(df: pd.DataFrame) -> list:
    """Return rows whose parsed participant ID contradicts their filename.

    ``parse_mem_file`` takes the participant from the file's ``Name:`` header and
    falls back to the filename only when the header has none — the right order,
    since the header is what the operator recorded at acquisition. But when an
    operator types the wrong subject into Qtrac, the recording silently files
    itself under another participant and simply goes missing from the intended
    one's report: a visit tested on both hemispheres can arrive looking like a
    single-hemisphere visit, with no error anywhere.

    This reports the disagreement so it can be surfaced instead. Nothing is
    reassigned — which of the two is right is a lab decision, not a guess this
    code can make.

    Each entry is ``{"source_file", "parsed_id", "filename_ids", "date",
    "cortex"}``.
    """
    if df is None or df.empty or "source_file" not in df.columns:
        return []

    ids = pd.to_numeric(df.get("ID"), errors="coerce")
    mismatches = []
    for idx, raw_files in df["source_file"].items():
        parsed_id = ids.get(idx)
        if pd.isna(parsed_id):
            continue
        for name in _split_source_files(raw_files):
            named = filename_participant_ids(name)
            if named and int(parsed_id) not in named:
                mismatches.append({
                    "source_file": name,
                    "parsed_id": int(parsed_id),
                    "filename_ids": sorted(named),
                    "date": df.at[idx, "Date"] if "Date" in df.columns else None,
                    "cortex": (
                        df.at[idx, "Stimulated_cortex"]
                        if "Stimulated_cortex" in df.columns else None
                    ),
                })
    return mismatches


def restrict_participant_to_muscle(
    df: pd.DataFrame, participant_id, muscle: str | None,
) -> pd.DataFrame:
    """Return *df* with one participant's rows restricted to one muscle.

    The side is deliberately *not* filtered: a visit tested on both
    hemispheres records the same muscle on the left and the right, and those
    two traces belong on one figure together (overlaid, labelled by stimulated
    cortex) rather than on two separate figures.  Use
    :func:`restrict_participant_to_target` when a single side is wanted.

    As there, only the selected participant is filtered — reference cohorts
    stay pooled across muscles — and the participant's rows that carry no
    muscle at all are kept, since they hold visit-level data (the CMAP/MUNIX
    tables) that belongs to the visit rather than to any one muscle.
    """
    if not muscle or MUSCLE_COLUMN not in df.columns or participant_id is None:
        return df
    wanted = str(muscle).strip().upper()
    muscles = (
        df[MUSCLE_COLUMN].astype("string").fillna("").str.strip().str.upper()
    )
    is_participant = pd.to_numeric(df["ID"], errors="coerce") == participant_id
    return df[~is_participant | (muscles == wanted) | (muscles == "")]


def _merge_group(group: pd.DataFrame, output_cols: list[str]) -> dict:
    """Combine one target's rows by taking the first non-null value per column."""
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
    return out


def _coalesce_same_session_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse rows sharing the same (ID, Date, recording target) into one row.

    Multiple .MEM files for the same participant collected on the same date
    hold either complementary measures of the same recording (e.g. one file
    carries RMT data, another the T-SICI block) or the *same* measure recorded
    from a different muscle/side (left FDI vs right FDI vs right TA).  The
    first kind must combine into one row; the second must not, or one
    recording silently overwrites the other.  Rows are therefore grouped by
    (ID, Date, target) — see :func:`resolve_visit_targets` for how the target
    is decided when the muscle/side headers are missing.

    Within a group, values combine by taking the first non-null per column.
    ``source_file`` is joined with ``SOURCE_FILE_SEPARATOR`` so the provenance
    of every contributing file is preserved, and the resolved muscle/side are
    written back so the row consistently carries its own target.  Rows lacking
    ID or Date are passed through unchanged.
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
    for _, visit in keyed.groupby(["_g_id", "_g_date"], sort=False):
        targets = resolve_visit_targets(visit)
        for target in dict.fromkeys(targets.values()):  # preserve first-seen order
            indices = [i for i, t in targets.items() if t == target]
            group = visit.loc[indices]
            out = (
                {c: group.iloc[0][c] for c in output_cols}
                if len(group) == 1
                else _merge_group(group, output_cols)
            )
            muscle, side = target
            if MUSCLE_COLUMN in output_cols:
                out[MUSCLE_COLUMN] = muscle or np.nan
            if SIDE_COLUMN in output_cols:
                out[SIDE_COLUMN] = side or np.nan
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


# Columns that load_existing_csv synthesises for legacy archives, so their
# absence from an archive must NOT make it look schema-stale.
_SYNTHESISED_LEGACY_COLUMNS = {"Study"}


def _expected_schema_columns() -> set:
    """Parser-derived columns an up-to-date archive must carry (excluding the
    columns load_existing_csv backfills for legacy CSVs)."""
    return (set(output_column_order()) | {"source_file"}) - _SYNTHESISED_LEGACY_COLUMNS


# The columns that define a row's *identity* rather than its contents.
_TARGET_IDENTITY_COLUMNS = {MUSCLE_COLUMN, SIDE_COLUMN}


def archive_predates_recording_targets(raw_existing_cols: set) -> bool:
    """Whether an archive was written before rows were split by recording target.

    Such an archive holds one already-coalesced row per visit: a visit that
    recorded two muscles had them merged together, and whichever values lost
    the first-non-null race are simply gone.  Unlike an ordinary new column
    this cannot be backfilled — the row *identity* is wrong, not just
    incomplete — so the caller must discard those rows and re-parse instead.
    """
    return bool(raw_existing_cols) and not _TARGET_IDENTITY_COLUMNS.issubset(
        raw_existing_cols
    )


def csv_schema_is_current(csv_path: str | Path | None) -> bool:
    """Return whether *csv_path*'s RAW header already carries every parser
    column the current schema expects.

    Judged on the file's original columns (not a normalised frame, which always
    has the full set), so an archive that predates newer columns (e.g. SR/SD) is
    correctly reported as stale. Returns ``False`` when the path is missing or
    its header cannot be read.
    """
    if csv_path is None or not Path(csv_path).exists():
        return False
    try:
        raw_cols = set(pd.read_csv(csv_path, nrows=0).columns)
    except Exception:
        return False
    return _expected_schema_columns().issubset(raw_cols)


def _backfill_new_parser_columns(
    df: pd.DataFrame, mem_files: list, raw_existing_cols: set,
) -> pd.DataFrame:
    """Populate parser-derived columns that a stale archive lacked (e.g. SR/SD)
    onto rows that predate them, by re-parsing each MEM file and matching on
    ``source_file``.

    Only *newly-added* columns are written, and only where currently null, so
    archived data — including CSP/CMAP values that come from other folders and
    are NOT reproduced by ``parse_mem_file`` — is never overwritten or lost.
    """
    missing = [
        c for c in output_column_order()
        if c not in raw_existing_cols and c != "source_file"
    ]
    if not missing or df.empty:
        return df

    lookup: dict[str, dict] = {}
    for filepath in mem_files:
        record = parse_mem_file(filepath)
        lookup[filepath.name] = {c: record.get(c) for c in missing}

    df = df.copy()
    for c in missing:
        if c not in df.columns:
            df[c] = np.nan
        # A column absent from the stale archive normalises to all-NaN float64;
        # cast to object so it can hold either numeric scalars or JSON strings
        # (SR_curve / SD_points). _normalize_mem_dataframe re-coerces the numeric
        # columns afterwards.
        df[c] = df[c].astype(object)
    for idx in df.index:
        for fname in _split_source_files(df.at[idx, "source_file"]):
            payload = lookup.get(fname)
            if not payload:
                continue
            for c in missing:
                value = payload[c]
                current = df.at[idx, c]
                is_null = current is None or (
                    isinstance(current, float) and np.isnan(current)
                )
                if is_null and value is not None:
                    df.at[idx, c] = value
    return df


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
    1. List .MEM filenames in *mem_dir* and (separately) the CSP folder.
    2. If *existing_csv* is provided, load it and diff the ``source_file``
       column against both folder listings.
    3. If nothing changed (no new/removed .MEM files, no new CSP files, schema
       is current) — return the existing DataFrame as-is.
    4. Otherwise, parse only the **new** .MEM files, combine with existing rows
       (dropping rows for removed files), re-merge CSP data — which appends any
       new CSP-only visit as its own row — re-merge CMAP, normalise, and
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

        - ``new_files_parsed`` : int  (new .MEM files)
        - ``new_csp_files_merged`` : int  (new CSP files not previously seen)
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
        # Capture the archive's *raw* columns before load_existing_csv
        # normalises the frame — normalisation backfills any missing columns,
        # which would otherwise mask a stale (older-schema) archive.
        raw_existing_cols = set(pd.read_csv(existing_csv, nrows=0).columns)
        existing_df = load_existing_csv(existing_csv)
        existing_names = _source_file_set(existing_df)
    else:
        raw_existing_cols = set()
        existing_df = pd.DataFrame(columns=output_column_order())
        existing_names = set()

    new_names = mem_filenames - existing_names
    # New CSP files must be diffed separately from MEM files. A follow-up visit
    # often adds *only* a cortical-silent-period recording (no new main .MEM
    # file), and the CSP folder is excluded from the MEM scan above. Without
    # this check the fast path would see no MEM changes and skip the CSP
    # re-merge, so the returning participant's new visit would never enter the
    # DataFrame.
    new_csp_names = csp_filenames - existing_names
    # Rows in the CSV whose source file is no longer present in EITHER source
    # folder. Must be dropped to keep the DataFrame in sync with disk.
    orphan_names = existing_names - mem_filenames - csp_filenames

    # ---- Fast path: nothing changed ----
    # Judge schema-currency on the archive's ORIGINAL columns, not the
    # normalised frame (which always carries the full column set). An archive
    # that predates a column the parser now produces (e.g. SR/SD) is stale and
    # its rows must be backfilled with those columns below, not left NaN.
    schema_current = _expected_schema_columns().issubset(raw_existing_cols)

    if not new_names and not new_csp_names and not orphan_names and schema_current:
        result = existing_df.copy()
        result.attrs["new_files_parsed"] = 0
        result.attrs["new_csp_files_merged"] = 0
        result.attrs["removed_files_dropped"] = 0
        result.attrs["reused_existing"] = True
        # Reaching the fast path means the schema is current, which includes the
        # muscle/side columns — so no target rebuild was needed.
        result.attrs["target_rebuild"] = False
        result.attrs["total_mem_files"] = len(mem_files)
        return result

    # ---- Incremental path ----
    # Keep only rows whose source files are ALL still present in mem_dir.
    # A coalesced row (multiple .MEM files joined into one row) is dropped
    # in full if any of its constituent files is missing — the remaining
    # files get re-parsed below so the rebuilt row stays consistent.
    # Existing rows are ALWAYS kept (never dropped just because the schema is
    # stale): they carry CSP/CMAP data that comes from other folders and is not
    # reproduced by parse_mem_file, so dropping them could lose that data when a
    # folder is unavailable. Newly-added parser columns (e.g. SR/SD) are instead
    # backfilled onto these rows after the merges (see _backfill_new_parser_columns).
    # An archive that predates recording targets is the one exception: its rows
    # merged several muscles together, so they must be discarded and every .MEM
    # file re-parsed rather than kept and backfilled (see
    # archive_predates_recording_targets). CSP/CMAP data is regenerated by the
    # re-merges below, but only from folders selected for THIS run — hence the
    # availability warnings recorded in attrs afterwards.
    target_rebuild = archive_predates_recording_targets(raw_existing_cols)

    if target_rebuild:
        kept_df = existing_df.iloc[0:0].copy()
    elif not existing_df.empty:
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

    # Schema upgrade: the archive predated some parser columns (e.g. SR/SD), so
    # the kept rows are missing them. Backfill just those columns from a re-parse
    # of the MEM files, leaving all other (incl. CSP/CMAP) data untouched.
    # A target rebuild kept no rows, so there is nothing to backfill.
    schema_stale = bool(existing_names) and not schema_current
    if schema_stale and not target_rebuild:
        combined = _normalize_mem_dataframe(
            _backfill_new_parser_columns(combined, mem_files, raw_existing_cols)
        )

    combined.attrs["new_files_parsed"] = len(new_names)
    combined.attrs["new_csp_files_merged"] = len(new_csp_names)
    combined.attrs["removed_files_dropped"] = len(orphan_names)
    combined.attrs["reused_existing"] = False
    combined.attrs["schema_rebuilt"] = schema_stale
    combined.attrs["target_rebuild"] = target_rebuild
    # A rebuild regenerates CSP/CMAP only from the folders selected for this
    # run. If the archive carried data this run cannot reproduce, say so rather
    # than silently returning a thinner DataFrame than the user started with.
    combined.attrs["target_rebuild_lost_csp"] = bool(
        target_rebuild
        and not csp_filenames
        and _has_any_value(existing_df, CSP_VALUE_COLUMNS)
    )
    combined.attrs["target_rebuild_lost_cmap"] = bool(
        target_rebuild
        and not normalize_dirs(cmap_dir)
        and _has_any_value(existing_df, ["CMAP_table", "MUNIX_table"])
    )
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
    """Return ``True`` if every .MEM file for *participant_id* is in the CSV
    AND the CSV's schema is current.

    The schema check prevents reusing an archive that predates newer parser
    columns (e.g. SR/SD): such an archive lists the files but lacks the data, so
    it must fall through to an incremental build that backfills those columns.
    """
    mem_files = participant_mem_files(participant_id, mem_dir)
    if not mem_files:
        return False
    if not csv_schema_is_current(csv_path):
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
