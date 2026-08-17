"""
Parse the STIMULUS-RESPONSE (peripheral nerve-excitability) block from a .MEM file.

These recordings live in the same folder as the TMS .MEM files but are a
different modality: instead of RMT / T-SICI cortical measures they carry a
peripheral recruitment curve (``STIMULUS-RESPONSE DATA``), a charge-duration
block, and an M-scan.  This module extracts only the stimulus-response
recruitment curve and its reference amplitude.

The block is read response-first: each ``SR.n`` row is a target response level
(``% Max`` column, 2 -> 98 %) and ``Stimulus(N)`` is the stimulus intensity (mA)
needed to reach it.  The ``Max CMAP 1 ms = nnnn`` line above the table is the
reference CMAP amplitude (mV); the absolute CMAP size for each row is
``percent_max / 100 * max_cmap_1ms``.  The ``SR.n`` labels are QtracP point
identifiers and are ignored.

Only the scalar ``SR_max_cmap_1ms`` is persisted into the parsed DataFrame /
exported CSV.  The full curve is returned here so callers can draw the plot on
demand without storing 49 points per visit.

Public API
----------
SR_MAX_COLUMN                          -> str   (the DataFrame column name)
extract_sr_block(lines)                -> dict  ({"max_cmap_1ms", "curve"})
parse_sr_file(filepath)                -> dict  (reads the file, then extracts)
"""

from __future__ import annotations

import re
from pathlib import Path

# DataFrame / CSV column holding the reference amplitude (mV).
SR_MAX_COLUMN = "SR_max_cmap_1ms"

# DataFrame / CSV column holding the full recruitment curve as a JSON string
# (list of ``{"percent_max", "stimulus_mA", "cmap_mV"}`` dicts). Persisting the
# curve lets the stimulus-response plot be rebuilt from an archived CSV alone —
# without re-reading the source .MEM — which also makes the plot load quickly.
SR_CURVE_COLUMN = "SR_curve"

# Marker for the start of the stimulus-response block.
_SR_SECTION_MARKER = "STIMULUS-RESPONSE DATA"

# Other section headers that terminate the stimulus-response block. Scanning is
# bounded by these so we never read charge-duration / M-scan / derived rows.
_OTHER_SECTION_MARKERS = (
    "CHARGE DURATION DATA",
    "M-SCAN DATA",
    "DERIVED EXCITABILITY VARIABLES",
    "EXTRA VARIABLES",
    "EXTRA WAVEFORMS",
)

# "Max CMAP  1 ms =  3.544922 mV" -> capture the first number after '='.
_SR_MAX_PATTERN = re.compile(r"Max\s*CMAP.*?=\s*([-\d.]+)", re.IGNORECASE)

# Data rows look like "SR.2 \t 2 \t 10.74938". The leading label is a QtracP
# point id (ignored); columns are % Max then Stimulus(N) in mA.
_SR_ROW_PATTERN = re.compile(r"^SR\.\d+\b", re.IGNORECASE)


def _to_float(token: str) -> float | None:
    try:
        return float(token)
    except (TypeError, ValueError):
        return None


def extract_sr_block(lines: list[str]) -> dict:
    """Extract the stimulus-response recruitment curve from raw .MEM lines.

    Returns a dict with:

    * ``max_cmap_1ms`` : float | None
        The reference "Max CMAP 1 ms" amplitude in mV, or ``None`` when the
        file has no stimulus-response block.
    * ``curve`` : list[dict]
        One dict per ``SR.n`` row, in source order, each with
        ``percent_max`` (float), ``stimulus_mA`` (float) and ``cmap_mV``
        (float | None — ``percent_max / 100 * max_cmap_1ms`` when the
        reference amplitude is known).

    A file with no ``STIMULUS-RESPONSE DATA`` section yields
    ``{"max_cmap_1ms": None, "curve": []}``.
    """
    empty = {"max_cmap_1ms": None, "curve": []}

    start_index = None
    for index, line in enumerate(lines):
        if _SR_SECTION_MARKER in line:
            start_index = index
            break
    if start_index is None:
        return empty

    # Bound the scan to the stimulus-response section only.
    end_index = len(lines)
    for index in range(start_index + 1, len(lines)):
        if any(marker in lines[index] for marker in _OTHER_SECTION_MARKERS):
            end_index = index
            break

    max_cmap_1ms: float | None = None
    curve: list[dict] = []

    for line in lines[start_index:end_index]:
        stripped = line.strip()
        if not stripped:
            continue

        if max_cmap_1ms is None:
            max_match = _SR_MAX_PATTERN.search(stripped)
            if max_match:
                max_cmap_1ms = _to_float(max_match.group(1))
                continue

        if not _SR_ROW_PATTERN.match(stripped):
            continue

        parts = re.split(r"\s+", stripped)
        # [label, percent_max, stimulus]
        if len(parts) < 3:
            continue
        percent_max = _to_float(parts[1])
        stimulus_ma = _to_float(parts[-1])
        if percent_max is None or stimulus_ma is None:
            continue

        cmap_mv = (
            percent_max / 100.0 * max_cmap_1ms
            if max_cmap_1ms is not None
            else None
        )
        curve.append({
            "percent_max": percent_max,
            "stimulus_mA": stimulus_ma,
            "cmap_mV": cmap_mv,
        })

    return {"max_cmap_1ms": max_cmap_1ms, "curve": curve}


def parse_sr_file(filepath: str | Path) -> dict:
    """Read *filepath* and return its stimulus-response block.

    Convenience wrapper around :func:`extract_sr_block` used by the plotting
    layer, which re-parses the curve on demand from the visit's source file.
    """
    path = Path(filepath)
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    return extract_sr_block(lines)
