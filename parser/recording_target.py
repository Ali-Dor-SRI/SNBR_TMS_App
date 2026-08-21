"""Recording target (muscle + recorded side) identification for .MEM files.

A single visit may hold several .MEM files that differ in *what was recorded*
rather than in *which measure was run*: the same T-SICI protocol repeated on
left FDI, right FDI, right TA and left TA.  Those files must stay on separate
DataFrame rows, whereas files that differ only in measure (T-SICI in one file,
CSP in another) still coalesce onto the same row.  The pair that decides this
is the **recording target**.

Both header fields are free text in Qtrac exports, so extraction is
deliberately conservative:

``Muscle:``
    Present in most cortical files (``FDI``, ``TA``, ``APB``, ``ADM``).  Qtrac
    truncates long values and marks the cut with a trailing ``.`` (``DI.``),
    which is stripped.  Unrecognised text is kept verbatim rather than guessed
    at — an honest odd label beats a wrong muscle in a clinical report.

``Stim/record:``
    Canonically ``L->R`` — stimulated hemisphere on the left of the arrow
    (already parsed as ``Stimulated_cortex``), recorded side on the right.
    Older files carry free-text variants (``L-R.``, ``L.FD``) with no arrow;
    those yield no side at all rather than a guess.  Side is therefore
    frequently unknown, and ``processing.df_builder`` absorbs side-less files
    into the visit's known side instead of splitting them off.

``S/R sites:``
    The peripheral nerve-excitability files (stimulus-response,
    strength-duration, M-SCAN) carry no ``Muscle:``/``Stim/record:`` line at
    all — they name the stimulation and recording sites together, as
    ``R CP-TA``, ``MEDIAN/APB``, ``L Uln Wr-ADM``.  Free text with a dozen
    spellings, so the muscle is taken as the last recognised muscle token
    anywhere in the value and the side only from a leading ``L``/``R`` word.
    Parsing this is what lets a visit's peripheral recording sit on the same
    row as the cortical recording of the same muscle and side.

``Comments:``
    The recent SR-SD exports name only the muscle in ``S/R sites:``
    (``Wrist-FDI``), and when the operator recorded the side anywhere it is
    here (``LEFT FDI``).  On every other kind of file the comment is protocol
    or clinical shorthand (``TSICI ASICI CSP``, ``Pt didnt tolrt <3ms``), so
    only two unmistakable spellings count: a spelled-out ``LEFT``/``RIGHT``
    word, or ``L``/``R`` joined directly to a known muscle token (``L FDI``,
    ``L-FDI``).  Callers apply it to SR-SD files only, and only to fill in
    what ``S/R sites:`` left blank.

Public API
----------
extract_muscle(stripped)            -> str | None
extract_recorded_side(stripped)     -> str | None
extract_sr_sites_target(stripped)   -> tuple[str | None, str | None]
extract_comment_target(stripped)    -> tuple[str | None, str | None]
target_key(muscle, side)            -> tuple[str, str]
target_label(muscle, side)          -> str
"""

from __future__ import annotations

import re

# Column names added to the parsed-record schema.
MUSCLE_COLUMN = "Muscle"
SIDE_COLUMN = "Recorded_side"

# Muscles recorded by the lab. Used only to canonicalise case/spacing; text
# that matches nothing here is passed through unchanged.
_KNOWN_MUSCLES = ("FDI", "APB", "ADM", "TA")

# Hand muscles, in preference order. The REDCap export and the "primary"
# target for single-target reporting pick from these first, since the study's
# historical records are all hand recordings.
HAND_MUSCLES = ("FDI", "APB", "ADM")

_SIDE_NAMES = {"L": "Left", "R": "Right"}

# "Stim/record: L->R" — the colon is absent in ~44% of files (older Qtrac
# export format), so it must be optional here. Only this canonical arrow form
# yields a recorded side.
_RECORDED_SIDE_PATTERN = re.compile(r"Stim/record:?\s*.*?->\s*([LR])\b", re.IGNORECASE)

_MUSCLE_PATTERN = re.compile(r"Muscle:\s*(.*)$")

_SR_SITES_PATTERN = re.compile(r"S/R sites:\s*(.*)$")
# Only whole-word muscle tokens, so stimulation sites (WR, CP, Uln, Median,
# Knee, Fib) can never be mistaken for one. The LAST match wins: every observed
# spelling puts the recording muscle after the stimulation site.
_SR_SITES_MUSCLE_PATTERN = re.compile(
    r"\b(" + "|".join(_KNOWN_MUSCLES) + r")\b", re.IGNORECASE
)
# A leading "L"/"R" word only — "Wrist-FDI" must not read as a right-side
# recording, and "A:rL->R.APB.PA" must not read as anything at all.
_SR_SITES_SIDE_PATTERN = re.compile(r"^\s*([LR])\b", re.IGNORECASE)

_COMMENT_PATTERN = re.compile(r"Comments:\s*(.*)$")
# A side + muscle pair joined by space or hyphen ("LEFT FDI", "L-FDI"). A bare
# L/R is accepted only in this joined form: "SR-SD" and "Only use 2nd trial RC"
# both contain the letter R and must read as nothing.
_COMMENT_SIDE_MUSCLE_PATTERN = re.compile(
    r"\b(L|R|LEFT|RIGHT)[-\s]+(" + "|".join(_KNOWN_MUSCLES) + r")\b",
    re.IGNORECASE,
)
# A spelled-out side word on its own ("LEFT") — unambiguous even without a
# muscle next to it.
_COMMENT_SIDE_WORD_PATTERN = re.compile(r"\b(LEFT|RIGHT)\b", re.IGNORECASE)


def extract_muscle(stripped: str) -> str | None:
    """Extract the recorded muscle from a ``Muscle:`` header line."""
    match = _MUSCLE_PATTERN.search(stripped)
    if not match:
        return None
    # Strip the trailing '.' Qtrac writes when it truncates the field.
    text = match.group(1).strip().rstrip(".").strip()
    if not text:
        return None
    upper = text.upper()
    for known in _KNOWN_MUSCLES:
        if upper == known:
            return known
    return upper


def extract_recorded_side(stripped: str) -> str | None:
    """Extract the recorded side (``"L"``/``"R"``) from ``Stim/record:``."""
    match = _RECORDED_SIDE_PATTERN.search(stripped)
    return match.group(1).upper() if match else None


def extract_sr_sites_target(stripped: str) -> tuple[str | None, str | None]:
    """Extract ``(muscle, side)`` from an ``S/R sites:`` header line.

    Either half may be ``None``: many values name only the muscle
    (``MEDIAN/APB``), and an unrecognised muscle yields ``None`` rather than a
    guess at which free-text token was meant to be the recording site.
    """
    match = _SR_SITES_PATTERN.search(stripped)
    if not match:
        return None, None
    text = match.group(1).strip()
    if not text:
        return None, None

    muscles = _SR_SITES_MUSCLE_PATTERN.findall(text)
    muscle = muscles[-1].upper() if muscles else None
    side_match = _SR_SITES_SIDE_PATTERN.search(text)
    side = side_match.group(1).upper() if side_match else None
    return muscle, side


def extract_comment_target(stripped: str) -> tuple[str | None, str | None]:
    """Extract ``(muscle, side)`` from a ``Comments:`` header line.

    Deliberately strict — the comment is free text used for protocol and
    clinical notes on most files, so only the two unmistakable spellings
    count (see the module docstring).  The muscle is never taken without a
    side next to it: ``S/R sites:`` names the muscle already, and a lone
    muscle token inside a protocol note would be a guess.
    """
    match = _COMMENT_PATTERN.search(stripped)
    if not match:
        return None, None
    text = match.group(1).strip()
    if not text:
        return None, None

    pair = _COMMENT_SIDE_MUSCLE_PATTERN.search(text)
    if pair:
        return pair.group(2).upper(), pair.group(1).upper()[0]
    side_word = _COMMENT_SIDE_WORD_PATTERN.search(text)
    if side_word:
        return None, side_word.group(1).upper()[0]
    return None, None


def _clean(value) -> str:
    """Normalise a possibly-missing muscle/side cell to a plain string."""
    if value is None:
        return ""
    text = str(value).strip()
    # pandas hands us the string "nan" for missing cells often enough to matter.
    if not text or text.lower() in ("nan", "none", "<na>"):
        return ""
    return text


def target_key(muscle, side) -> tuple[str, str]:
    """Return the hashable grouping key for a (muscle, side) pair."""
    return (_clean(muscle).upper(), _clean(side).upper())


def target_label(muscle, side) -> str:
    """Return the human-readable target label, e.g. ``"Right FDI"``.

    Falls back to whichever half is known, and to ``""`` when neither is —
    peripheral nerve-excitability files carry no muscle header at all.
    """
    muscle_text = _clean(muscle).upper()
    side_text = _SIDE_NAMES.get(_clean(side).upper(), "")
    if muscle_text and side_text:
        return f"{side_text} {muscle_text}"
    return muscle_text or side_text


def is_hand_muscle(muscle) -> bool:
    """Whether *muscle* is one of the hand muscles the study historically used."""
    return _clean(muscle).upper() in HAND_MUSCLES
