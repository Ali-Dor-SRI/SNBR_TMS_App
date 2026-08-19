"""Default filenames for exports the user did not name.

Naming an export is busywork: the participant, the visit and the graph are all
already known by the time the Export button is pressed. Leaving the name box
empty is therefore allowed everywhere, and these rules fill it in.

======================  ==========================================
Graph (PNG)             ``<Study>_<ID>_<graph type>_<visit date>``
Dataframe (CSV)         ``df_<export date>``
Report (PDF)            ``report_<Study>_<ID>``
======================  ==========================================

The participant number is zero-padded to three digits and the date is
``YYYYMMDD``, matching the lab's ``.MEM`` filenames (``SNBR-080-FU-RCX-…``) and
sorting chronologically. A graph carries the **visit** date because that is what
identifies the recording it was drawn from; the dataframe carries the **export**
date because it spans every participant and has no single visit.

These names already contain the study, participant and date, so they are used
verbatim — the ``_<Study>_ID<n>_<date>`` suffix that
``AppController.stamp_export_path`` appends to a name the user *typed* is not
applied on top (it would repeat all three).

Public API
----------
default_graph_stem(study, participant_id, graph_label, visit_date) -> str
default_dataframe_stem(export_date)                               -> str
default_report_stem(study, participant_id)                        -> str
unique_path(path)                                                 -> Path
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

DATE_FORMAT = "%Y%m%d"

# Characters Windows forbids in a filename, plus the separators we normalise to
# underscores. Hyphens survive: "T-SICI" must stay readable.
_ILLEGAL = r'<>:"/\\|?*'
_SEPARATORS = re.compile(r"[\s—–]+")   # whitespace, em dash, en dash


def sanitize_token(text) -> str:
    """Return *text* reduced to a filename-safe token.

    Spaces and the em dashes that separate a graph's sub-labels
    (``"RMT Comparison — RMT50 — Right FDI"``) become single underscores, and
    characters Windows rejects are dropped. Returns ``""`` for empty input, so
    callers can skip the part rather than emit a stray underscore.
    """
    if text is None:
        return ""
    cleaned = "".join(ch for ch in str(text) if ch not in _ILLEGAL)
    cleaned = _SEPARATORS.sub("_", cleaned.strip())
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned.strip("_.")


def format_participant(participant_id) -> str:
    """Return a participant number as a zero-padded 3-digit token."""
    try:
        return f"{int(participant_id):03d}"
    except (TypeError, ValueError):
        return sanitize_token(participant_id)


def _format_date(value) -> str:
    """Render a date as ``YYYYMMDD``, accepting the app's ``DD/MM/YYYY`` strings."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime(DATE_FORMAT)
    text = str(value).strip()
    if not text:
        return ""
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", DATE_FORMAT):
        try:
            return datetime.strptime(text, fmt).strftime(DATE_FORMAT)
        except ValueError:
            continue
    return sanitize_token(text)


def _join(*parts) -> str:
    """Join the parts that are actually present with underscores."""
    return "_".join(p for p in (str(x) for x in parts) if p)


def default_graph_stem(study, participant_id, graph_label, visit_date) -> str:
    """``SNBR_080_T-SICI_Profile_Right_FDI_20260818``.

    *graph_label* is the visualization page's own label for the figure, so a
    per-target or per-RMT-column figure keeps whatever distinguishes it and two
    graphs from one visit cannot collide.
    """
    return _join(
        sanitize_token(study),
        format_participant(participant_id),
        sanitize_token(graph_label),
        _format_date(visit_date),
    ) or "graph"


def default_dataframe_stem(export_date=None) -> str:
    """``df_20260818`` — the export date, since the frame spans every visit."""
    return _join("df", _format_date(export_date or datetime.now()))


def default_report_stem(study, participant_id) -> str:
    """``report_SNBR_080``."""
    return _join(
        "report", sanitize_token(study), format_participant(participant_id),
    )


def unique_path(path: str | Path) -> Path:
    """Return *path*, or the first free ``_2``/``_3``… variant beside it.

    An auto-named export must never quietly replace an earlier one: re-running a
    report for the same participant on the same day is a normal thing to do, and
    both versions should survive.
    """
    candidate = Path(path)
    if not candidate.exists():
        return candidate
    stem, suffix, parent = candidate.stem, candidate.suffix, candidate.parent
    counter = 2
    while True:
        nxt = parent / f"{stem}_{counter}{suffix}"
        if not nxt.exists():
            return nxt
        counter += 1
