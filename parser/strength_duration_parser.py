"""
Parse the strength-duration (charge-duration) block from a peripheral .MEM file.

These recordings live in the same folder as the TMS .MEM files and share a
visit with the stimulus-response block (:mod:`parser.sr_parser`).  Instead of
cortical RMT / T-SICI measures they carry a peripheral nerve-excitability
threshold-tracking study.  This module extracts two things from it:

* the ``CHARGE DURATION DATA`` table -- one ``QT.n`` row per stimulus duration,
  giving Duration (ms), Threshold (mA) and Threshold charge (mA*ms).  The
  ``QT.n`` labels are QtracP point identifiers and are ignored.  Threshold
  charge equals ``Threshold * Duration`` (recomputed when the file omits it).
* the two derived strength-duration scalars, which QtracP has already fitted
  and written into the ``DERIVED EXCITABILITY VARIABLES`` block.  Each derived
  line is keyed by a leading integer *slot* number: **slot 4 = Rheobase (mA)**
  and **slot 3 = Strength-duration time constant (ms)**.  We read them by slot
  key (robust to spacing) rather than refitting.

Only the two scalars (``Rheobase_mA`` and ``Tau_SD_ms``) are persisted into the
parsed DataFrame / exported CSV.  The per-duration points are returned here so
callers can draw the strength-duration and charge-duration (Weiss) plots on
demand without storing them per visit -- exactly as the stimulus-response curve
is re-parsed on demand.

Fit relationships (used only to draw / annotate the plots, never to overwrite
the QtracP-derived scalars):

* strength-duration curve : ``I = rheobase * (1 + tau / d)``
* Weiss's law (charge)    : ``Q = rheobase * (d + tau)``  -- a straight line in
  ``(d, Q)`` with slope = rheobase and x-intercept = -tau.

Public API
----------
SD_RHEOBASE_COLUMN                     -> str   (DataFrame column, mA)
SD_TAU_COLUMN                          -> str   (DataFrame column, ms)
extract_sd_block(lines)                -> dict  ({"rheobase_mA", "tau_sd_ms", "points"})
parse_strength_duration_file(filepath) -> dict  (reads the file, then extracts)
strength_duration_current(d, r, tau)   -> float (I = r*(1 + tau/d))
weiss_charge(d, r, tau)                -> float (Q = r*(d + tau))
charge_duration_r_squared(points, r, tau) -> float | None
"""

from __future__ import annotations

import re
from pathlib import Path

# DataFrame / CSV columns holding the two derived strength-duration scalars.
# These are the only strength-duration values stored on the parsed record --
# the per-duration points are re-parsed from the source file at plot time.
SD_RHEOBASE_COLUMN = "Rheobase_mA"
SD_TAU_COLUMN = "Tau_SD_ms"

# DataFrame / CSV column holding the per-duration charge-duration points as a
# JSON string (list of ``{"duration_ms", "threshold_mA", "charge_mA_ms"}``
# dicts). Persisting the points lets the strength-duration and charge-duration
# plots be rebuilt from an archived CSV alone -- without re-reading the source
# .MEM -- which also makes the plots load quickly.
SD_POINTS_COLUMN = "SD_points"

# Derived-variable slot numbers (QtracP DERIVED EXCITABILITY VARIABLES block).
_SLOT_RHEOBASE = 4
_SLOT_TAU_SD = 3

# Marker for the start of the charge-duration data table.
_SD_SECTION_MARKER = "CHARGE DURATION DATA"

# Marker for the derived-variable block that carries rheobase / tau.
_DERIVED_SECTION_MARKER = "DERIVED EXCITABILITY VARIABLES"

# Section headers used to bound a scan so we never read across block boundaries.
_SECTION_MARKERS = (
    "STIMULUS-RESPONSE DATA",
    "CHARGE DURATION DATA",
    "M-SCAN DATA",
    "DERIVED EXCITABILITY VARIABLES",
    "EXTRA VARIABLES",
    "EXTRA WAVEFORMS",
)

# Charge-duration data rows look like "QT.1 \t .2 \t 10.02212 \t 2.004424".
# The leading label is a QtracP point id (ignored).
_QT_ROW_PATTERN = re.compile(r"^QT\.\d+\b", re.IGNORECASE)

# A derived-variable line: leading integer slot, a dot, then the numeric value,
# e.g. " 4.                \t3.129               \tRheobase (mA)".
_DERIVED_ROW_PATTERN = re.compile(r"^\s*(\d+)\.\s+([-\d.]+)")


def _to_float(token: str) -> float | None:
    try:
        return float(token)
    except (TypeError, ValueError):
        return None


def _section_bounds(lines: list[str], marker: str) -> tuple[int, int] | None:
    """Return the ``[start, end)`` line span of the section headed by *marker*.

    ``end`` is the index of the next section header (any of
    :data:`_SECTION_MARKERS`) or the end of file.  Returns ``None`` when the
    section is absent.
    """
    start_index = None
    for index, line in enumerate(lines):
        if marker in line:
            start_index = index
            break
    if start_index is None:
        return None

    end_index = len(lines)
    for index in range(start_index + 1, len(lines)):
        if any(other in lines[index] for other in _SECTION_MARKERS):
            end_index = index
            break
    return start_index, end_index


def _parse_derived_scalars(lines: list[str]) -> dict[int, float]:
    """Parse the DERIVED EXCITABILITY VARIABLES block into ``{slot: value}``.

    Each line is keyed by its leading integer slot number, parsed robustly of
    spacing.  Returns an empty dict when the block is absent.
    """
    bounds = _section_bounds(lines, _DERIVED_SECTION_MARKER)
    if bounds is None:
        return {}
    start_index, end_index = bounds

    slots: dict[int, float] = {}
    for line in lines[start_index:end_index]:
        match = _DERIVED_ROW_PATTERN.match(line)
        if not match:
            continue
        slot = int(match.group(1))
        value = _to_float(match.group(2))
        if value is not None and slot not in slots:
            slots[slot] = value
    return slots


def extract_sd_block(lines: list[str]) -> dict:
    """Extract the strength-duration data from raw .MEM lines.

    Returns a dict with:

    * ``rheobase_mA`` : float | None
        QtracP-derived rheobase (mA) from derived-variable slot 4.
    * ``tau_sd_ms`` : float | None
        QtracP-derived strength-duration time constant (ms) from slot 3.
    * ``points`` : list[dict]
        One dict per ``QT.n`` row, in source order, each with ``duration_ms``
        (float), ``threshold_mA`` (float) and ``charge_mA_ms`` (float --
        the file's Threshold-charge column when present, else
        ``threshold_mA * duration_ms``).

    A file with no ``CHARGE DURATION DATA`` section and no derived scalars
    yields ``{"rheobase_mA": None, "tau_sd_ms": None, "points": []}``.
    """
    empty = {"rheobase_mA": None, "tau_sd_ms": None, "points": []}

    slots = _parse_derived_scalars(lines)
    rheobase = slots.get(_SLOT_RHEOBASE)
    tau_sd = slots.get(_SLOT_TAU_SD)

    bounds = _section_bounds(lines, _SD_SECTION_MARKER)
    if bounds is None:
        if rheobase is None and tau_sd is None:
            return empty
        return {"rheobase_mA": rheobase, "tau_sd_ms": tau_sd, "points": []}

    start_index, end_index = bounds
    points: list[dict] = []
    for line in lines[start_index:end_index]:
        stripped = line.strip()
        if not _QT_ROW_PATTERN.match(stripped):
            continue

        parts = re.split(r"\s+", stripped)
        # [label, duration, threshold, (optional) charge]
        if len(parts) < 3:
            continue
        duration = _to_float(parts[1])
        threshold = _to_float(parts[2])
        if duration is None or threshold is None:
            continue

        charge = _to_float(parts[3]) if len(parts) > 3 else None
        if charge is None:
            charge = threshold * duration

        points.append({
            "duration_ms": duration,
            "threshold_mA": threshold,
            "charge_mA_ms": charge,
        })

    return {"rheobase_mA": rheobase, "tau_sd_ms": tau_sd, "points": points}


def parse_strength_duration_file(filepath: str | Path) -> dict:
    """Read *filepath* and return its strength-duration block.

    Convenience wrapper around :func:`extract_sd_block` used by the plotting
    layer, which re-parses the per-duration points on demand from the visit's
    source file.
    """
    path = Path(filepath)
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    return extract_sd_block(lines)


# ---------------------------------------------------------------------------
# Fit / annotation helpers (pure -- drive the plots, never overwrite scalars)
# ---------------------------------------------------------------------------

def strength_duration_current(duration_ms: float, rheobase: float, tau_sd: float) -> float:
    """Fitted threshold current at *duration_ms*: ``I = rheobase*(1 + tau/d)``."""
    return rheobase * (1.0 + tau_sd / duration_ms)


def weiss_charge(duration_ms: float, rheobase: float, tau_sd: float) -> float:
    """Fitted threshold charge at *duration_ms*: ``Q = rheobase*(d + tau)``."""
    return rheobase * (duration_ms + tau_sd)


def charge_duration_r_squared(
    points: list[dict], rheobase: float | None, tau_sd: float | None,
) -> float | None:
    """Coefficient of determination of the measured charge points about the
    QtracP-derived Weiss line ``Q = rheobase*(d + tau)``.

    Returns ``None`` when it is undefined: fewer than two points, missing
    rheobase / tau, or zero total variance in the measured charges.
    """
    if rheobase is None or tau_sd is None:
        return None
    pairs = [
        (p["duration_ms"], p["charge_mA_ms"])
        for p in points
        if p.get("duration_ms") is not None and p.get("charge_mA_ms") is not None
    ]
    if len(pairs) < 2:
        return None

    observed = [q for _d, q in pairs]
    mean_q = sum(observed) / len(observed)
    ss_tot = sum((q - mean_q) ** 2 for q in observed)
    if ss_tot == 0:
        return None
    ss_res = sum(
        (q - weiss_charge(d, rheobase, tau_sd)) ** 2 for d, q in pairs
    )
    return 1.0 - ss_res / ss_tot
