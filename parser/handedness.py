"""Hand dominance ("handedness") identification for .MEM files.

Which hemisphere a participant's cohort average is drawn from depends on their
dominant hand, so the value has to survive parsing into the DataFrame rather
than being read on demand: the rule applies to every *reference cohort* member,
not just the selected participant.

Qtrac wrote the field two different ways over the years and both are still
present in the lab's archive:

``L- or R-handed:``
    The current export format, e.g. ``L- or R-handed:    R``.

``Subject right-handed`` / ``Subject left-handed``
    An older format that occupies the same header slot but carries no field
    name at all, so it has to be recognised as a whole line.

Roughly a third of the archive's subjects have neither form, and a handful
carry both values across their own files (data-entry drift). Neither case is
resolved here — this module only reports what a single file says, and
``processing.cohort_filters`` decides what to do when a subject's files
disagree or say nothing.

Public API
----------
extract_handedness(stripped)   -> str | None
contralateral_cortex(hand)     -> str | None
"""

from __future__ import annotations

import re

# Column name added to the parsed-record schema.
HANDEDNESS_COLUMN = "Handedness"

# Current format: "L- or R-handed:    R". The trailing value is a bare letter.
_HANDED_FIELD_PATTERN = re.compile(
    r"L-\s*or\s*R-handed:?\s*([LR])\b", flags=re.IGNORECASE
)

# Older format: the whole header line is "Subject right-handed".
_HANDED_PROSE_PATTERN = re.compile(
    r"^Subject\s+(right|left)-handed\b", flags=re.IGNORECASE
)

# Header prefixes that may introduce a handedness value. Used by the parsers to
# decide whether a line is worth handing to extract_handedness().
HANDEDNESS_LINE_PREFIXES = ("L- or R-handed", "Subject right-handed", "Subject left-handed")


def extract_handedness(stripped: str) -> str | None:
    """Return ``"L"``/``"R"`` for a handedness header line, else ``None``.

    Accepts both export formats. Anything else — including a field that is
    present but blank, which happens in Qtrac exports where the operator left
    it empty — yields ``None`` rather than a guess.
    """
    match = _HANDED_FIELD_PATTERN.search(stripped)
    if match:
        return match.group(1).upper()
    match = _HANDED_PROSE_PATTERN.match(stripped)
    if match:
        return "R" if match.group(1).lower() == "right" else "L"
    return None


def contralateral_cortex(hand: str | None) -> str | None:
    """Return the hemisphere that drives *hand*, matching ``Stimulated_cortex``.

    A right-handed participant's dominant hand is driven by the **left**
    hemisphere, so that is the cortex reported for ``"R"``. This is the
    hemisphere the lab stimulates by convention (the archive holds 334 ``L``
    rows against 112 ``R``, with right-handers outnumbering left-handers ~12:1)
    and the one whose values feed cohort averages.
    """
    if hand is None:
        return None
    normalized = str(hand).strip().upper()
    if normalized == "R":
        return "L"
    if normalized == "L":
        return "R"
    return None
