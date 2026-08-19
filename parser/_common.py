"""
Header-field extraction helpers shared by the .MEM/PDF/DOCX parsers.

Every function here was previously defined, byte-for-byte identically, in two
or three of ``parser.mem_parser`` / ``parser.CSP_parser`` / ``parser.cmap_parser``
/ ``parser.sr_parser`` / ``parser.strength_duration_parser``.  They are pure
string->value converters with no module state, so a single definition is the
same code the copies were.

Invariant to preserve: these feed ``parse_mem_file`` / ``parse_csp_file``, whose
output becomes the DataFrame's cell values.  Any change in what a helper returns
for a given header line silently changes archived data, so treat edits here as
edits to the schema.  ``parser.cmap_parser._to_float`` is deliberately NOT here:
it takes arbitrary pdfplumber cell objects (not just str) and handles ``None``
and blanks explicitly, so it is a different function that happens to share a name.

The legacy ``processing/_v1_parse_*`` modules keep their own copies on purpose —
they are frozen alongside the V1 plotting engine and must not follow changes made
here.

Public API
----------
extract_study_and_id(text)          -> (study, id)
extract_date(stripped)              -> "dd/mm/YYYY"
extract_int(pattern, stripped)      -> int
extract_match(pattern, stripped)    -> str
extract_subject_type(stripped)      -> "Control" | "Patient"
extract_stimulated_cortex(stripped) -> str
to_float(token)                     -> float
base_header_parsers()               -> prefix -> parser table
apply_header_prefix_table(stripped, record, parsers)
"""

from __future__ import annotations

import re
from datetime import datetime
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
)

STUDY_ID_PATTERN = re.compile(r"([A-Za-z]+)\d*-0*(\d+)", flags=re.IGNORECASE)


def extract_study_and_id(text: str | None) -> tuple[str | None, int | None]:
    """Extract (study_name, participant_id) from text like 'SNBR-005' or 'QUARTS-207'."""
    if text is None:
        return None, None
    match = STUDY_ID_PATTERN.search(str(text))
    if match:
        return match.group(1).upper(), int(match.group(2))
    return None, None


def extract_date(stripped: str) -> str | None:
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


def extract_int(pattern: str, stripped: str) -> int | None:
    match = re.search(pattern, stripped)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    return None


def extract_match(pattern: str, stripped: str) -> str | None:
    match = re.search(pattern, stripped)
    return match.group(1) if match else None


def extract_subject_type(stripped: str) -> str | None:
    match = re.search(
        r"Subject type:\s+(Control|Patient)\b", stripped, flags=re.IGNORECASE
    )
    return match.group(1).capitalize() if match else None


def extract_stimulated_cortex(stripped: str) -> str | None:
    # The colon after "Stim/record" is absent in ~44% of files (older Qtrac
    # export format), so it must be optional here.
    match = re.search(r"Stim/record:?\s*(.*?)\s*->", stripped)
    if match:
        cortex = match.group(1).strip()
        if cortex:
            return cortex
    return None


def to_float(token: str) -> float | None:
    try:
        return float(token)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Header prefix table
# ---------------------------------------------------------------------------

def base_header_parsers() -> dict[str, tuple[str, Callable] | Callable]:
    """Return the prefix -> parser table every Qtrac .MEM header shares.

    A fresh dict each call: ``mem_parser`` extends its copy with the fields only
    the TMS export carries, and the two tables must not alias one another.
    Insertion order is preserved because :func:`apply_header_prefix_table`
    returns on the first matching prefix.
    """
    return {
        "Name:": lambda s: extract_study_and_id(s),  # returns (study, id) — special-cased
        "Date:": ("Date", extract_date),
        "Age:": ("Age", lambda s: extract_int(r"Age:\s+(\d+)", s)),
        "Sex:": ("Sex", lambda s: extract_match(r"Sex:\s+([MF])", s)),
        "Subject type:": ("Subject_type", extract_subject_type),
        "Stim/record": ("Stimulated_cortex", extract_stimulated_cortex),
        "Muscle:": (MUSCLE_COLUMN, extract_muscle),
    }


def apply_header_prefix_table(
    stripped: str, record: dict, parsers: dict[str, tuple[str, Callable] | Callable]
) -> None:
    """Parse one header line into *record* using the *parsers* prefix table.

    Callers that recognise a line themselves must do so **before** delegating
    here, because this returns on the first prefix that matches.
    """
    # Matched on the whole line, not through the prefix table: the older export
    # format ("Subject right-handed") carries no field name to key on.
    if stripped.startswith(HANDEDNESS_LINE_PREFIXES):
        hand = extract_handedness(stripped)
        if hand is not None:
            record[HANDEDNESS_COLUMN] = hand
        return
    for prefix, entry in parsers.items():
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
