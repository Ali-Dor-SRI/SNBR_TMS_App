"""
Parse CSP-focused .MEM files and extract cortical silent period data.

Returns lists of plain dicts (no DataFrames). CSP durations are computed
as simple arithmetic (CSPe - CSPs) on each record dict.

Public API
----------
parse_csp_file(filepath)  -> dict
parse_csp_directory(input_dir) -> list[dict]
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Callable

from parser._common import (
    apply_header_prefix_table,
    base_header_parsers,
    extract_study_and_id,
    read_source_lines,
)
from parser.handedness import HANDEDNESS_COLUMN
from parser.mem_parser import iter_files, normalize_dirs
from parser.recording_target import MUSCLE_COLUMN, SIDE_COLUMN

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CSP_RMT_LEVELS = ["80", "100", "120", "140", "160"]
CSP_VALUE_COLUMNS = (
    [f"CSPs_{level}" for level in CSP_RMT_LEVELS]
    + [f"CSPe_{level}" for level in CSP_RMT_LEVELS]
    + [f"CSP_{level}" for level in CSP_RMT_LEVELS]
)

_SECTION_DERIVED = "DERIVED EXCITABILITY VARIABLES"
_SECTION_EXTRA_VARS = "EXTRA VARIABLES"
_SECTION_WAVEFORMS = "EXTRA WAVEFORMS"

_CSP_VALUE_PATTERN = re.compile(r"^(CSPs|CSPe)-(\d+)\(ms\)\s*=\s*([-\d.]+)")


def csp_output_columns() -> list[str]:
    """Return the stable output schema for parsed CSP records."""
    return (
        ["Study", "ID", "Date", "Age", "Sex", HANDEDNESS_COLUMN,
         "Subject_type", "Stimulated_cortex",
         MUSCLE_COLUMN, SIDE_COLUMN]
        + list(CSP_VALUE_COLUMNS)
        + ["source_file"]
    )


# ---------------------------------------------------------------------------
# Record initialisation
# ---------------------------------------------------------------------------

def initialize_csp_record() -> dict:
    """Return an empty parsed CSP record with all expected keys set to None."""
    record: dict = {
        "Study": None,
        "ID": None,
        "Date": None,
        "Age": None,
        "Sex": None,
        HANDEDNESS_COLUMN: None,
        "Subject_type": None,
        "Stimulated_cortex": None,
        MUSCLE_COLUMN: None,
        SIDE_COLUMN: None,
    }
    for col in CSP_VALUE_COLUMNS:
        record[col] = None
    return record


# ---------------------------------------------------------------------------
# Header-field parsing helpers (pure-Python, no pandas/numpy)
# ---------------------------------------------------------------------------

# CSP exports carry exactly the shared header fields — no CSP-only additions.
_HEADER_PARSERS: dict[str, tuple[str, Callable] | Callable] = base_header_parsers()


def _parse_header_field(stripped: str, record: dict) -> None:
    apply_header_prefix_table(stripped, record, _HEADER_PARSERS)


# ---------------------------------------------------------------------------
# EXTRA VARIABLES section parsing (CSP values)
# ---------------------------------------------------------------------------

def _parse_extra_vars_line(stripped: str, record: dict) -> None:
    match = _CSP_VALUE_PATTERN.match(stripped)
    if match is None:
        return

    value_prefix, level, raw_value = match.groups()
    if level not in CSP_RMT_LEVELS:
        return

    try:
        record[f"{value_prefix}_{level}"] = float(raw_value)
    except ValueError:
        warnings.warn(f"Could not convert CSP value {value_prefix}_{level}: {raw_value!r}")
        return


# ---------------------------------------------------------------------------
# CSP duration computation (pure dict arithmetic)
# ---------------------------------------------------------------------------

def _compute_csp_durations(record: dict) -> None:
    """Compute CSP = CSPe - CSPs for each RMT level directly on the dict."""
    for level in CSP_RMT_LEVELS:
        start = record.get(f"CSPs_{level}")
        end = record.get(f"CSPe_{level}")
        if start is not None and end is not None:
            duration = end - start
            if duration < 0:
                warnings.warn(f"Negative CSP duration at {level}% RMT: CSPe={end} < CSPs={start}")
                record[f"CSP_{level}"] = None
            else:
                record[f"CSP_{level}"] = duration
        else:
            record[f"CSP_{level}"] = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_csp_file(filepath: str | Path) -> dict:
    """Parse one CSP .MEM file and return the extracted record as a plain dict.

    The returned dict uses ``None`` for missing values. CSP durations are
    computed in-place. The ``source_file`` key is NOT set here -- the caller
    adds it after parsing.
    """
    filepath_obj = Path(filepath)
    lines = read_source_lines(filepath_obj)

    record = initialize_csp_record()
    filename_study, filename_id = extract_study_and_id(filepath_obj.name)
    current_section = "header"

    for raw_line in lines:
        stripped = raw_line.strip()

        if _SECTION_DERIVED in stripped:
            current_section = "derived"
            continue
        if _SECTION_EXTRA_VARS in stripped:
            current_section = "extra_vars"
            continue
        if _SECTION_WAVEFORMS in stripped:
            break
        if not stripped:
            continue

        if current_section == "header":
            _parse_header_field(stripped, record)
        elif current_section == "extra_vars":
            _parse_extra_vars_line(stripped, record)

    # Fallback Study from filename
    if record["Study"] is None and filename_study is not None:
        record["Study"] = filename_study

    # Fallback ID from filename
    if record["ID"] is None and filename_id is not None:
        record["ID"] = filename_id

    # Compute derived CSP durations
    _compute_csp_durations(record)

    return record


def parse_csp_directory(
    input_dir: str | Path | list[str | Path] | None,
    recursive: bool = True,
    files: list[Path] | None = None,
) -> list[dict]:
    """Parse every CSP .MEM file in *input_dir* and return a list of record dicts.

    *input_dir* may be a single directory or a list of directories; each
    dict has a ``source_file`` key set to the filename.  When *recursive*
    is ``True`` (default) subfolders are searched too; when ``False`` only
    files directly inside each root are parsed.

    Pass *files* to parse exactly that list instead of scanning — used when the
    CSP and MEM selections are one folder and the caller has already sorted the
    CSP recordings out of it.
    """
    roots = normalize_dirs(input_dir)
    if not roots:
        raise FileNotFoundError("No CSP directory was provided")

    mem_files = (
        list(files) if files is not None
        else iter_files(roots, "*.MEM", recursive=recursive)
    )
    if not mem_files:
        shown = ", ".join(str(r) for r in roots)
        raise FileNotFoundError(f"No CSP .MEM files found in: {shown}")

    records: list[dict] = []
    for filepath in mem_files:
        record = parse_csp_file(filepath)
        record["source_file"] = filepath.name
        records.append(record)

    return records
