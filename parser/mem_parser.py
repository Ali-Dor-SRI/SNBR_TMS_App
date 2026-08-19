"""
Parse .MEM files from TMS recordings and extract participant data.

Returns lists of plain dicts (no DataFrames). Downstream modules such as
``processing.df_builder`` are responsible for converting these records into
DataFrames, merging CSP data, and exporting.

Public API
----------
parse_mem_file(filepath)  -> dict
parse_mem_directory(input_dir) -> list[dict]
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import warnings
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Callable

from parser.handedness import (
    HANDEDNESS_COLUMN,
    HANDEDNESS_LINE_PREFIXES,
    extract_handedness,
)
from parser.recording_target import (
    MUSCLE_COLUMN,
    SIDE_COLUMN,
    extract_muscle,
    extract_recorded_side,
    extract_sr_sites_target,
)
from parser.sr_parser import SR_CURVE_COLUMN, SR_MAX_COLUMN, extract_sr_block
from parser.strength_duration_parser import (
    SD_POINTS_COLUMN,
    SD_RHEOBASE_COLUMN,
    SD_TAU_COLUMN,
    extract_sd_block,
)

# ---------------------------------------------------------------------------
# Constants -- ISI labels and waveform block markers
# ---------------------------------------------------------------------------

TSICI_ISIS = [
    "1.0ms", "1.5ms", "2ms", "2.5ms", "3.0ms", "3.5ms",
    "4ms", "5ms", "7ms",
]
TSICF_ISIS = [f"{tenths / 10:.1f}ms" for tenths in range(10, 71, 3)]
A_SICI_ISIS = [
    "1.0ms", "1.5ms", "2.0ms", "2.5ms", "3.0ms", "3.5ms",
    "4.0ms", "5.0ms", "7.0ms",
]
ASICF_ISIS = [f"{tenths / 10:.1f}ms" for tenths in range(10, 71, 3)]

# Map ISI numeric value → canonical internal T-SICI label (handles the 2ms
# vs 1.0ms convention inconsistency in the existing schema)
_TSICI_FLOAT_TO_LABEL = {
    1.0: "1.0ms", 1.5: "1.5ms", 2.0: "2ms", 2.5: "2.5ms",
    3.0: "3.0ms", 3.5: "3.5ms", 4.0: "4ms", 5.0: "5ms", 7.0: "7ms",
}

TSICF_BLOCK_MARKER = "!T-SICFvISI(%RMT)(Parallel)"
A_SICI_BLOCK_MARKER = "!A-SICIvISI(rel)"
ASICF_BLOCK_MARKER = "!A-SICFvISI(rel)"

_SECTION_DERIVED = "DERIVED EXCITABILITY VARIABLES"
_SECTION_EXTRA_VARS = "EXTRA VARIABLES"
_SECTION_WAVEFORMS = "EXTRA WAVEFORMS"

_STUDY_ID_PATTERN = re.compile(r"([A-Za-z]+)\d*-0*(\d+)", flags=re.IGNORECASE)

_TSICI_GENERIC_PATTERN = re.compile(r"^T-SICI\(70%\)([\d.]+)ms\s*=\s*([-\d.]+)")

# CSP RMT levels -- needed for building the full output schema
CSP_RMT_LEVELS = ["80", "100", "120", "140", "160"]


def output_column_order() -> list[str]:
    """Return the standard output column order for parsed MEM data."""
    return (
        ["Study", "ID", "Date", "Age", "Sex", HANDEDNESS_COLUMN,
         "Subject_type", "Stimulated_cortex",
         MUSCLE_COLUMN, SIDE_COLUMN,
         "RMT50", "RMT200", "RMT1000"]
        + [col for level in CSP_RMT_LEVELS
           for col in (f"CSPs_{level}", f"CSPe_{level}", f"CSP_{level}")]
        + [f"T_SICI_{isi}" for isi in TSICI_ISIS] + ["T_SICI_avg"]
        + [f"T_SICF_{isi}" for isi in TSICF_ISIS] + ["T_SICF_avg"]
        + [f"A_SICI_{isi}" for isi in A_SICI_ISIS] + ["A_SICI_avg"]
        + [f"A_SICF_{isi}" for isi in ASICF_ISIS] + ["A_SICF_avg"]
        + ["T_SICI_isi_n", "T_SICF_isi_n", "A_SICI_isi_n", "A_SICF_isi_n"]
        + ["TMS_coil"]
        + [SR_MAX_COLUMN]
        + [SD_RHEOBASE_COLUMN, SD_TAU_COLUMN]
        + [SR_CURVE_COLUMN, SD_POINTS_COLUMN]
        + ["CMAP_table", "MUNIX_table", "source_file"]
    )


# ---------------------------------------------------------------------------
# Record initialisation
# ---------------------------------------------------------------------------

def initialize_record() -> dict:
    """Return an empty parsed-record dict with the full output schema."""
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
        "RMT50": None,
        "RMT200": None,
        "RMT1000": None,
        "T_SICI_avg": None,
        "T_SICF_avg": None,
        "A_SICI_avg": None,
        "A_SICF_avg": None,
        "T_SICI_isi_n": None,
        "T_SICF_isi_n": None,
        "A_SICI_isi_n": None,
        "A_SICF_isi_n": None,
        "TMS_coil": None,
        SR_MAX_COLUMN: None,
        SD_RHEOBASE_COLUMN: None,
        SD_TAU_COLUMN: None,
        SR_CURVE_COLUMN: None,
        SD_POINTS_COLUMN: None,
    }
    for isi in TSICI_ISIS:
        record[f"T_SICI_{isi}"] = None
    for isi in TSICF_ISIS:
        record[f"T_SICF_{isi}"] = None
    for isi in A_SICI_ISIS:
        record[f"A_SICI_{isi}"] = None
    for isi in ASICF_ISIS:
        record[f"A_SICF_{isi}"] = None
    for level in CSP_RMT_LEVELS:
        record[f"CSPs_{level}"] = None
        record[f"CSPe_{level}"] = None
        record[f"CSP_{level}"] = None
    return record


# ---------------------------------------------------------------------------
# Header-field parsing helpers  (replaces parse_common.py, pure-Python)
# ---------------------------------------------------------------------------

def _extract_study_and_id(text: str | None) -> tuple[str | None, int | None]:
    """Extract (study_name, participant_id) from text like 'SNBR-005' or 'QUARTS-207'."""
    if text is None:
        return None, None
    match = _STUDY_ID_PATTERN.search(str(text))
    if match:
        return match.group(1).upper(), int(match.group(2))
    return None, None


def _extract_date(stripped: str) -> str | None:
    match = re.search(r"Date:\s+(\d{1,2}/\d{1,2}/\d{2,4})", stripped)
    if match:
        raw = match.group(1)
        for fmt in ("%d/%m/%Y", "%d/%m/%y", "%m/%d/%Y", "%m/%d/%y"):
            try:
                parsed = datetime.strptime(raw, fmt)
                return parsed.strftime("%d/%m/%Y")
            except ValueError:
                continue
    return None


_FILENAME_DATE_PATTERN = re.compile(r"C(\d)(\d{2})(\d{2})[A-Z]\.MEM$", flags=re.IGNORECASE)


def _extract_date_from_filename(filename: str) -> str | None:
    """Extract a date from the MEM filename convention.

    The last 7 characters before ``.MEM`` encode a date as ``CYMMDDx``
    where ``C`` is a literal prefix, ``Y`` is a single year digit
    (e.g. 5 = 2025, 6 = 2026), ``MM`` is month, ``DD`` is day, and
    ``x`` is an alphabetic suffix that is ignored.
    """
    match = _FILENAME_DATE_PATTERN.search(filename)
    if not match:
        return None
    year = 2020 + int(match.group(1))
    month = int(match.group(2))
    day = int(match.group(3))
    try:
        parsed = datetime(year, month, day)
        return parsed.strftime("%d/%m/%Y")
    except ValueError:
        return None


def _extract_int(pattern: str, stripped: str) -> int | None:
    match = re.search(pattern, stripped)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    return None


def _extract_match(pattern: str, stripped: str) -> str | None:
    match = re.search(pattern, stripped)
    return match.group(1) if match else None


def _extract_subject_type(stripped: str) -> str | None:
    match = re.search(
        r"Subject type:\s+(Control|Patient)\b", stripped, flags=re.IGNORECASE
    )
    return match.group(1).capitalize() if match else None


def _extract_stimulated_cortex(stripped: str) -> str | None:
    # The colon after "Stim/record" is absent in ~44% of files (older Qtrac
    # export format), so it must be optional here.
    match = re.search(r"Stim/record:?\s*(.*?)\s*->", stripped)
    if match:
        cortex = match.group(1).strip()
        if cortex:
            return cortex
    return None


def _extract_tms_coil(stripped: str) -> str | None:
    """Extract the TMS coil model from a 'TMS Coil:' header line.

    The MEM file encodes it like ``TMS Coil:\tMagStim D70^2``.  We return one
    of the canonical labels ``"D70^2"``, ``"D70"``, or ``"DCC"`` so that
    downstream code can map the string to a REDCap radio option code.
    """
    match = re.search(r"TMS Coil:\s*(.+?)\s*$", stripped)
    if not match:
        return None
    text = match.group(1).strip()
    # Order matters: D70^2 must be checked before D70.
    if "D70^2" in text:
        return "D70^2"
    if re.search(r"\bD70\b", text):
        return "D70"
    if "DCC" in text.upper():
        return "DCC"
    return None


_HEADER_PARSERS: dict[str, tuple[str, Callable] | Callable] = {
    "Name:": lambda s: _extract_study_and_id(s),  # returns (study, id) — special-cased
    "Date:": ("Date", _extract_date),
    "Age:": ("Age", lambda s: _extract_int(r"Age:\s+(\d+)", s)),
    "Sex:": ("Sex", lambda s: _extract_match(r"Sex:\s+([MF])", s)),
    "Subject type:": ("Subject_type", _extract_subject_type),
    "Stim/record": ("Stimulated_cortex", _extract_stimulated_cortex),
    "Muscle:": (MUSCLE_COLUMN, extract_muscle),
    "TMS Coil:": ("TMS_coil", _extract_tms_coil),
}


def _parse_sr_sites(stripped: str, record: dict) -> None:
    """Fill muscle/side from the peripheral files' ``S/R sites:`` header.

    Those files carry neither ``Muscle:`` nor ``Stim/record:``, so this is the
    only way their recording target can be identified — and identifying it is
    what puts a visit's peripheral recording on the same row as the cortical
    recording of the same muscle and side.
    """
    muscle, side = extract_sr_sites_target(stripped)
    if muscle is not None and record[MUSCLE_COLUMN] is None:
        record[MUSCLE_COLUMN] = muscle
    if side is not None and record[SIDE_COLUMN] is None:
        record[SIDE_COLUMN] = side


def _parse_header_field(stripped: str, record: dict) -> None:
    if stripped.startswith("S/R sites:"):
        _parse_sr_sites(stripped, record)
        return
    # Handedness is matched on the whole line rather than through the prefix
    # table below: the older export format ("Subject right-handed") carries no
    # field name, so there is no prefix to key it on.
    if stripped.startswith(HANDEDNESS_LINE_PREFIXES):
        hand = extract_handedness(stripped)
        if hand is not None:
            record[HANDEDNESS_COLUMN] = hand
        return
    for prefix, entry in _HEADER_PARSERS.items():
        if stripped.startswith(prefix):
            if prefix == "Name:":
                study, pid = entry(stripped)
                if study is not None:
                    record["Study"] = study
                if pid is not None:
                    record["ID"] = pid
            else:
                key, parser = entry
                value = parser(stripped)
                if value is not None:
                    record[key] = value
                if prefix == "Stim/record":
                    # The same line carries the recorded side on the right of
                    # the arrow ("L->R": stimulate left cortex, record right).
                    side = extract_recorded_side(stripped)
                    if side is not None:
                        record[SIDE_COLUMN] = side
            return


# ---------------------------------------------------------------------------
# EXTRA VARIABLES section parsing
# ---------------------------------------------------------------------------

def _adjust_tsici_value(raw_value: float) -> float:
    """Convert a T-SICI delta value to its 100-based percentage representation."""
    return 100.0 + float(raw_value)


def _parse_extra_vars_line(stripped: str, record: dict) -> None:
    # RMT summaries
    for rmt_key in ("RMT50", "RMT200", "RMT1000"):
        if re.match(rf"^{rmt_key}\s*=", stripped):
            match = re.search(rf"{rmt_key}\s*=\s*([-\d.]+)", stripped)
            if match:
                try:
                    record[rmt_key] = float(match.group(1))
                except ValueError:
                    pass
            return

    # T-SICI individual ISI values -- flexible: match any T-SICI(70%)Xms entry
    match = _TSICI_GENERIC_PATTERN.match(stripped)
    if match:
        try:
            isi_float = float(match.group(1))
            raw_value = float(match.group(2))
        except ValueError:
            warnings.warn(f"Could not parse T-SICI line: {stripped!r}")
            return
        label = _TSICI_FLOAT_TO_LABEL.get(isi_float)
        if label is not None:
            record[f"T_SICI_{label}"] = _adjust_tsici_value(raw_value)


# ---------------------------------------------------------------------------
# Waveform block extraction
# ---------------------------------------------------------------------------

def _normalize_decimal_isi_label(raw_isi: str) -> str:
    return f"{float(raw_isi):.1f}ms"


def _extract_waveform_block_values(
    lines: list[str],
    marker: str,
    target_isis: list[str],
    value_transform: Callable[[float], float],
) -> dict[str, float]:
    extracted: dict[str, float] = {}
    target_set = set(target_isis)

    for line_index, line in enumerate(lines):
        if line.strip() != marker:
            continue

        # Skip metadata row
        metadata_index = line_index + 1
        while metadata_index < len(lines) and not lines[metadata_index].strip():
            metadata_index += 1
        if metadata_index >= len(lines):
            return extracted

        data_index = metadata_index + 1
        while data_index < len(lines):
            stripped = lines[data_index].strip()
            if not stripped or stripped.startswith("!"):
                break
            parts = re.split(r"\s+", stripped)
            if len(parts) >= 2:
                try:
                    normalized_isi = _normalize_decimal_isi_label(parts[0])
                    raw_value = float(parts[1])
                except ValueError:
                    warnings.warn(f"Skipped malformed waveform line: {stripped!r}")
                    data_index += 1
                    continue
                if normalized_isi in target_set:
                    extracted[normalized_isi] = value_transform(raw_value)
            data_index += 1
        return extracted

    return extracted


def _assign_waveform_values(
    record: dict, prefix: str, extracted: dict[str, float]
) -> None:
    for isi_label, value in extracted.items():
        record[f"{prefix}_{isi_label}"] = value


def _compute_record_average(
    record: dict, prefix: str, isis: list[str], avg_key: str
) -> None:
    values = [
        record[f"{prefix}_{isi}"]
        for isi in isis
        if record.get(f"{prefix}_{isi}") is not None
    ]
    record[avg_key] = sum(values) / len(values) if values else None


# ---------------------------------------------------------------------------
# ISI-count classification for the REDCap ``*_isi_n`` radio fields
# ---------------------------------------------------------------------------

def _isi_label_to_float(label: str) -> float:
    return float(label.rstrip("ms"))


def _present_isi_floats(record: dict, prefix: str, isis: list[str]) -> list[float]:
    """Return the sorted list of ISI floats that have a non-None value."""
    present = [
        _isi_label_to_float(isi)
        for isi in isis
        if record.get(f"{prefix}_{isi}") is not None
    ]
    return sorted(present)


def _classify_tsici_isi_n(record: dict) -> int | None:
    """REDCap t_sici_p_isi_n option: 1=3 ISIs (1,2.5,3) · 2=6 ISIs (1-3.5) · 3=9 ISIs (1-7)."""
    present = _present_isi_floats(record, "T_SICI", TSICI_ISIS)
    if not present:
        return None
    count = len(present)
    if count >= 9 or max(present) >= 7.0:
        return 3
    if count == 3 and set(present) == {1.0, 2.5, 3.0}:
        return 1
    if count == 6 and max(present) <= 3.5:
        return 2
    # Default fallback: pick by count
    if count <= 3:
        return 1
    if count <= 6:
        return 2
    return 3


def _classify_sicf_protocol_shape(present: list[float]) -> int | None:
    """Shared classifier body for both t_sicf_p_isi_n and a_sicf_isi_n.

    Both REDCap radios use the same option codes:
      * 1 = 14 ISIs 1.0-4.9 ms by 0.3
      * 2 = 9 ISIs 1.0-3.4 ms by 0.3
      * 3 = 9 ISIs 2.5-4.9 ms by 0.3
      * 4 = 9 ISIs 1.0-7.0 ms (mixed steps: 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 7.0)
    """
    if not present:
        return None
    count = len(present)
    lo, hi = present[0], present[-1]
    if count >= 14 and hi <= 4.9:
        return 1
    if count == 9:
        if hi >= 7.0:
            return 4
        if lo >= 2.5 and hi <= 4.9:
            return 3
        if hi <= 3.4:
            return 2
    # Fallback by count / range
    if count >= 14:
        return 1
    if hi >= 7.0:
        return 4
    if lo >= 2.5:
        return 3
    return 2


def _classify_tsicf_isi_n(record: dict) -> int | None:
    """REDCap t_sicf_p_isi_n option: 1/2/3/4 (see _classify_sicf_protocol_shape)."""
    return _classify_sicf_protocol_shape(
        _present_isi_floats(record, "T_SICF", TSICF_ISIS)
    )


def _classify_asici_isi_n(record: dict) -> int | None:
    """REDCap a_sici_1000_isi_n: same 1/2/3 options as t_sici_p_isi_n."""
    present = _present_isi_floats(record, "A_SICI", A_SICI_ISIS)
    if not present:
        return None
    count = len(present)
    if count >= 9 or max(present) >= 7.0:
        return 3
    if count == 3 and set(present) == {1.0, 2.5, 3.0}:
        return 1
    if count == 6 and max(present) <= 3.5:
        return 2
    if count <= 3:
        return 1
    if count <= 6:
        return 2
    return 3


def _classify_asicf_isi_n(record: dict) -> int | None:
    """REDCap a_sicf_isi_n option: 1/2/3/4 (see _classify_sicf_protocol_shape)."""
    return _classify_sicf_protocol_shape(
        _present_isi_floats(record, "A_SICF", ASICF_ISIS)
    )


def _assign_isi_counts(record: dict) -> None:
    record["T_SICI_isi_n"] = _classify_tsici_isi_n(record)
    record["T_SICF_isi_n"] = _classify_tsicf_isi_n(record)
    record["A_SICI_isi_n"] = _classify_asici_isi_n(record)
    record["A_SICF_isi_n"] = _classify_asicf_isi_n(record)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_mem_file(filepath: str | Path) -> dict:
    """Parse a single .MEM file and return extracted values as a plain dict.

    The returned dict uses ``None`` for missing values and contains all keys
    from :func:`output_column_order` except ``source_file`` (the caller adds
    that after parsing).
    """
    filepath_obj = Path(filepath)
    with filepath_obj.open("r", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()

    # Attempt to extract study/ID from filename as fallback
    filename_study, filename_id = _extract_study_and_id(filepath_obj.name)

    record = initialize_record()
    current_section = "header"

    for line in lines:
        stripped = line.strip()

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

    # Waveform blocks (T-SICF, A-SICI, A-SICF)
    _assign_waveform_values(
        record, "T_SICF",
        _extract_waveform_block_values(lines, TSICF_BLOCK_MARKER, TSICF_ISIS, float),
    )
    _assign_waveform_values(
        record, "A_SICI",
        _extract_waveform_block_values(
            lines, A_SICI_BLOCK_MARKER, A_SICI_ISIS, float,
        ),
    )
    _assign_waveform_values(
        record, "A_SICF",
        _extract_waveform_block_values(
            lines, ASICF_BLOCK_MARKER, ASICF_ISIS, float,
        ),
    )

    # Stimulus-response block (peripheral nerve-excitability files). The
    # reference Max CMAP amplitude is stored as a scalar; the full recruitment
    # curve is also persisted (as JSON) so the plot can be rebuilt from an
    # archived CSV without re-reading the source .MEM.
    sr_block = extract_sr_block(lines)
    record[SR_MAX_COLUMN] = sr_block["max_cmap_1ms"]
    record[SR_CURVE_COLUMN] = (
        json.dumps(sr_block["curve"]) if sr_block["curve"] else None
    )

    # Strength-duration block (same peripheral files). The two QtracP-derived
    # scalars (rheobase, strength-duration time constant) are stored, plus the
    # per-duration charge-duration points (as JSON) so the strength-duration
    # and charge-duration plots can likewise be rebuilt from an archived CSV.
    sd_block = extract_sd_block(lines)
    record[SD_RHEOBASE_COLUMN] = sd_block["rheobase_mA"]
    record[SD_TAU_COLUMN] = sd_block["tau_sd_ms"]
    record[SD_POINTS_COLUMN] = (
        json.dumps(sd_block["points"]) if sd_block["points"] else None
    )

    # Fallback Study from filename
    if record["Study"] is None and filename_study is not None:
        record["Study"] = filename_study

    # Fallback ID from filename
    if record["ID"] is None and filename_id is not None:
        record["ID"] = filename_id

    # Fallback Date from filename
    if record["Date"] is None:
        filename_date = _extract_date_from_filename(filepath_obj.name)
        if filename_date is not None:
            record["Date"] = filename_date

    # Per-record averages
    _compute_record_average(record, "T_SICI", TSICI_ISIS, "T_SICI_avg")
    _compute_record_average(record, "T_SICF", TSICF_ISIS, "T_SICF_avg")
    _compute_record_average(record, "A_SICI", A_SICI_ISIS, "A_SICI_avg")
    _compute_record_average(record, "A_SICF", ASICF_ISIS, "A_SICF_avg")

    # ISI-count classification (REDCap radio option codes)
    _assign_isi_counts(record)

    return record


def normalize_dirs(value) -> list[Path]:
    """Normalise a directory argument to a flat list of ``Path``.

    Accepts ``None``, a single ``str``/``Path``, or any (possibly nested)
    iterable of them, so callers can let the user pick files from several
    locations.  Empty/blank entries are dropped.
    """
    if value is None:
        return []
    if isinstance(value, (str, Path)):
        return [Path(value)] if str(value).strip() else []
    result: list[Path] = []
    for v in value:
        result.extend(normalize_dirs(v))
    return result


def _folder_key(path: str | Path) -> str:
    """Return the normalised absolute string used to recognise *path* twice.

    ``os.path.realpath`` is what collapses two spellings of the same folder —
    a junction, a second mapping of the share, an 8.3 short name — onto one
    key, and it is only ever called on the handful of *roots* (and excluded
    folders) a scan is given.  Resolving every discovered file instead is what
    made the old implementation spend 23s of a 25s scan inside
    ``nt._getfinalpathname`` on the lab's Y: share.
    """
    try:
        return os.path.normcase(os.path.realpath(path))
    except (OSError, ValueError):
        return os.path.normcase(os.path.abspath(path))


def _is_within(key: str, folder_keys: list[str]) -> bool:
    """True when *key* is one of *folder_keys* or sits inside one.

    Both sides are already normalised by :func:`_folder_key`, so this is the
    string form of the old ``resolved == ex or ex in resolved.parents`` test.
    The separator keeps ``CSP_extra`` from counting as inside ``CSP``.
    """
    for folder in folder_keys:
        if key == folder or key.startswith(folder.rstrip(os.sep) + os.sep):
            return True
    return False


def _same_file(first: str | Path, second: str | Path) -> bool:
    """True when two different paths are provably the same file on disk."""
    try:
        a = os.stat(first)
        b = os.stat(second)
    except OSError:
        return False
    if a.st_ino and b.st_ino and a.st_dev and b.st_dev:
        return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)
    # Network shares can report a zero inode; fall back to the expensive
    # comparison for that (rare) case alone.
    return _folder_key(first) == _folder_key(second)


def _scandir_entries(directory: Path) -> list[os.DirEntry]:
    """List *directory* via ``os.scandir``, sorted by name.

    Returns an empty list for a folder that is missing (a path the user typed
    wrong) or unreadable (a permission error on the share) rather than
    raising, which is how the previous ``glob``-based scan behaved.
    """
    try:
        with os.scandir(directory) as scan:
            entries = list(scan)
    except (OSError, ValueError):
        return []
    entries.sort(key=lambda e: e.name)
    return entries


def _name_matcher(pattern: str) -> Callable[[str], bool]:
    """Return a predicate matching a *filename* against *pattern*.

    ``fnmatch`` is case-insensitive on Windows and case-sensitive elsewhere,
    which is exactly what ``Path.glob`` did with the same pattern.
    """
    if pattern == "*":
        return lambda name: True
    return lambda name: fnmatch.fnmatch(name, pattern)


def _walk_candidates(root: Path, root_key: str, matches, recursive: bool,
                     exclude_keys: list[str]):
    """Yield ``(path, key, entry)`` for files under *root* matching the name test.

    A directory that is a link is not descended into, matching ``Path.rglob``
    (which skips symlinks/junctions) — so a junction pointing back into the
    tree cannot loop.  Excluded folders are pruned here rather than filtered
    afterwards, which keeps the whole CSP subtree off the wire during a MEM
    scan.
    """
    queue = deque([(root, root_key)])
    while queue:
        directory, dir_key = queue.popleft()
        for entry in _scandir_entries(directory):
            entry_key = os.path.join(dir_key, os.path.normcase(entry.name))
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                is_dir = False
            if is_dir:
                if recursive and not _is_within(entry_key, exclude_keys):
                    queue.append((directory / entry.name, entry_key))
                continue
            if not matches(entry.name) or _is_within(entry_key, exclude_keys):
                continue
            try:
                if not entry.is_file():
                    continue
            except OSError:
                continue
            yield directory / entry.name, entry_key, entry


def _glob_candidates(root: Path, pattern: str, recursive: bool,
                     exclude_keys: list[str]):
    """Yield ``(path, key, None)`` — fallback for patterns spanning folders.

    No caller passes one today (the app uses ``"*.MEM"`` and ``"*"``), but the
    *pattern* argument has always accepted e.g. ``"sub/*.MEM"``, which a
    filename test cannot express.  Correctness over speed here: this path
    resolves each hit, exactly as the whole function used to.
    """
    glob_iter = root.rglob(pattern) if recursive else root.glob(pattern)
    for path in sorted(glob_iter):
        if not path.is_file():
            continue
        key = _folder_key(path)
        if _is_within(key, exclude_keys):
            continue
        yield path, key, None


def _collect_files(
    input_dir: str | Path | list[str | Path] | None,
    pattern: str,
    recursive: bool,
    exclude_dirs: list[str | Path | None] | None = None,
) -> list[Path]:
    """Shared discovery engine behind :func:`iter_files` / :func:`iter_mem_files`."""
    exclude_keys = [_folder_key(d) for d in normalize_dirs(exclude_dirs)]
    matches = _name_matcher(pattern)
    spans_dirs = "**" in pattern or "/" in pattern or "\\" in pattern

    files: list[Path] = []
    seen_keys: set[str] = set()
    seen_attrs: dict[tuple, list[Path]] = {}

    for root in normalize_dirs(input_dir):
        root_key = _folder_key(root)
        if _is_within(root_key, exclude_keys) or not root.is_dir():
            continue
        if spans_dirs:
            candidates = _glob_candidates(root, pattern, recursive, exclude_keys)
        else:
            candidates = _walk_candidates(
                root, root_key, matches, recursive, exclude_keys,
            )
        for path, key, entry in candidates:
            if key in seen_keys:
                continue
            if _seen_as_another_path(path, entry, seen_attrs):
                continue
            seen_keys.add(key)
            files.append(path)
    return sorted(files, key=lambda p: str(p))


def _seen_as_another_path(path: Path, entry, seen_attrs: dict) -> bool:
    """True when *path* is a file already listed under a different name.

    ``Path.resolve()`` used to collapse those (a root reached through a
    junction, the same share mapped twice) at the cost of a round-trip per
    file.  The stand-in is the ``(name, size, mtime)`` the directory scan
    already carries for free; because that trio can also collide for two
    genuinely different recordings, a collision is confirmed against the
    file's identity before anything is dropped.
    """
    try:
        stat = entry.stat() if entry is not None else os.stat(path)
    except OSError:
        return False
    key = (os.path.normcase(path.name), stat.st_size, stat.st_mtime_ns)
    twins = seen_attrs.setdefault(key, [])
    if any(_same_file(path, other) for other in twins):
        return True
    twins.append(path)
    return False


def iter_files(
    input_dir: str | Path | list[str | Path] | None,
    pattern: str = "*.MEM",
    recursive: bool = True,
) -> list[Path]:
    """List files matching *pattern* across one or more dirs.

    *input_dir* may be a single directory or a (possibly nested) list of
    directories, so callers can collect files stored in several locations.
    When *recursive* is ``True`` (default), subfolders are searched too;
    when ``False``, only files directly inside each root are returned.
    Results are de-duplicated (overlapping/parent+child selections are not
    returned twice — the lab's CSP folder sits inside the MEM folder) and
    missing or unreadable directories are skipped.

    The walk is ``os.scandir``-based and de-duplicates on the normalised path
    instead of ``Path.resolve()``: this runs on every load, over a network
    share, and per-file resolution cost ~23s of a 25s scan there.
    """
    return _collect_files(input_dir, pattern, recursive)


def iter_mem_files(
    input_dir: str | Path | list[str | Path] | None,
    exclude_dirs: list[str | Path | None] | None = None,
    recursive: bool = True,
) -> list[Path]:
    """Return every ``*.MEM`` path under *input_dir*.

    *input_dir* may be a single directory or a list of directories — files
    are collected from all of them so the user can pull MEM files stored in
    different locations.  When *recursive* is ``True`` (default), subfolders
    are searched too; when ``False``, only files directly inside each root
    are returned.  Files are de-duplicated (overlapping selections won't be
    parsed twice), and any file inside one of *exclude_dirs* is skipped —
    used to keep the CSP directory (a subfolder of the MEM directory in
    typical lab layouts) out of the MEM parse, since CSP files use a
    different format handled by ``CSP_parser``.
    """
    return _collect_files(input_dir, "*.MEM", recursive, exclude_dirs=exclude_dirs)


def parse_mem_directory(
    input_dir: str | Path | list[str | Path] | None,
    exclude_dirs: list[str | Path | None] | None = None,
    recursive: bool = True,
) -> list[dict]:
    """Parse all .MEM files under *input_dir* and return record dicts.

    *input_dir* may be a single directory or a list of directories.  When
    *recursive* is ``True`` (default) subfolders are searched too; when
    ``False`` only files directly inside each root are parsed.  Each dict
    has a ``source_file`` key set to the filename (stem + extension).
    Pass *exclude_dirs* to skip subtrees such as the CSP directory.
    """
    roots = normalize_dirs(input_dir)
    if not roots:
        raise FileNotFoundError("No MEM directory was provided")

    mem_files = iter_mem_files(roots, exclude_dirs, recursive=recursive)
    if not mem_files:
        shown = ", ".join(str(r) for r in roots)
        raise FileNotFoundError(f"No .MEM files found in: {shown}")

    records: list[dict] = []
    for filepath in mem_files:
        record = parse_mem_file(filepath)
        record["source_file"] = filepath.name
        records.append(record)

    return records
