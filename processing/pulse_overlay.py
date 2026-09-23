"""Draw the individual pulses of a QtracP export behind a profile graph.

The profile graphs plot one value per ISI from the ``.MEM``. When the matching
per-stimulus Excel export is available, each of those values can be shown with
the pulses it was computed from: a small dot per pulse, spread left to right in
delivery order, with a thin tether back to the ISI's value so membership is
never in doubt (chosen over jitter alone, shaded bands and range bars).

The readings come from :mod:`parser.xlsx_parser`; this module only draws.
"""

from __future__ import annotations

import numpy as np
from matplotlib.lines import Line2D

TETHER_COLOR = "#8C9AAF"
HOLLOW_FACE = "#FFFFFF"
TARGET_MV = 0.2
# Every artist the overlay adds carries this gid, so a test (or a later pass)
# can find them without knowing how they were drawn.
OVERLAY_GID = "pulse_overlay"

_THRESHOLD_MEASURES = ("t_sici", "t_sicf")


def is_threshold_measure(measure: str) -> bool:
    return str(measure).strip().lower().replace("-", "_") in _THRESHOLD_MEASURES


def draw_pulse_overlay(
    axis,
    profile_points: dict[float, float],
    block: dict,
    *,
    color: str,
    measure: str,
    half_width_fraction: float = 0.17,
) -> list[float]:
    """Draw the pulses behind each ISI of one profile trace.

    *profile_points* maps ISI (ms) to the value plotted for it; *block* is one
    measure's readings from :func:`parser.xlsx_parser.extract_pulse_readings`.
    Returns the y values drawn so the caller can widen its axis limits; an
    empty list means no ISI matched.
    """
    isis = sorted(profile_points)
    if not isis:
        return []
    spacing = float(min(np.diff(isis))) if len(isis) > 1 else 0.5
    jitter = half_width_fraction * spacing
    two_tone = is_threshold_measure(measure)
    drawn: list[float] = []
    for isi in isis:
        entry = (block.get("isis") or {}).get(round(float(isi), 2))
        pulses = (entry or {}).get("pulses") or []
        if not pulses:
            continue
        anchor = profile_points[isi]
        offsets = np.linspace(-jitter, jitter, len(pulses)) if len(pulses) > 1 else [0.0]
        for offset, pulse in zip(offsets, pulses):
            y = pulse.get("y")
            if y is None or not np.isfinite(y):
                continue
            axis.plot(
                [isi, isi + offset], [anchor, y],
                color=TETHER_COLOR, linewidth=0.7, alpha=0.55, zorder=1.5,
                gid=OVERLAY_GID,
            )
            filled = pulse.get("above_target", True) or not two_tone
            axis.plot(
                isi + offset, y, marker="o", markersize=4.4, linestyle="none",
                markerfacecolor=color if filled else HOLLOW_FACE,
                markeredgecolor=color, markeredgewidth=0.8, alpha=0.8, zorder=2.5,
                gid=OVERLAY_GID,
            )
            drawn.append(float(y))
    return drawn


def overlay_legend_handles(measure: str, label: str, color: str, block: dict) -> list[Line2D]:
    """Legend entries explaining the dots, the tether and the profile marker."""
    # Kept short: the app enlarges every font by 1.5x before display, and a
    # legend wider than the axes spills over the y-axis.
    handles = [
        Line2D(
            [], [], color=color, linewidth=1.2, marker="o", markersize=9,
            markerfacecolor="#ECE8E0", markeredgecolor=color, markeredgewidth=1.1,
            label=f"{label} value per ISI (.MEM)",
        ),
    ]
    if is_threshold_measure(measure):
        handles += [
            Line2D(
                [], [], linestyle="none", marker="o", markersize=5,
                markerfacecolor=color, markeredgecolor=color,
                label=f"Paired pulse, MEP ≥ {TARGET_MV:g} mV: test stimulus, % of parallel RMT200",
            ),
            Line2D(
                [], [], linestyle="none", marker="o", markersize=5,
                markerfacecolor=HOLLOW_FACE, markeredgecolor=color,
                label=f"Paired pulse, MEP < {TARGET_MV:g} mV (test pulse raised next cycle)",
            ),
        ]
    else:
        handles.append(
            Line2D(
                [], [], linestyle="none", marker="o", markersize=5,
                markerfacecolor=color, markeredgecolor=color,
                label="Paired pulse: MEP, % of the test-alone baseline",
            ),
        )
    handles.append(
        Line2D(
            [], [], color=TETHER_COLOR, linewidth=0.9, alpha=0.8,
            label="Tether: pulse → the ISI value it fed",
        ),
    )
    return handles


def overlay_note(measure: str, block: dict, source_name: str | None) -> str:
    """Two short lines for the legend title: the export the pulses came from,
    how many per ISI, and the reference they are scaled by."""
    n_pulses = sorted({len(e.get("pulses") or []) for e in (block.get("isis") or {}).values()})
    per_isi = "/".join(str(n) for n in n_pulses if n) or "?"
    lines = [
        f"{per_isi} pulses per ISI from {source_name or 'the Excel export'}, "
        "left→right in delivery order"
    ]
    reference = block.get("reference")
    n_ref = block.get("reference_n")
    if reference is not None:
        if is_threshold_measure(measure):
            lines.append(
                f"Reference RMT200 = {reference:.1f} %MSO (log regression over {n_ref} test-alone pulses)"
            )
        else:
            lines.append(
                f"Baseline = {reference:.2f} mV (geometric mean of {n_ref} test-alone pulses)"
            )
    if block.get("increment_mode"):
        lines.append("Test stimuli restored from exported increments")
    return "\n".join(lines)
