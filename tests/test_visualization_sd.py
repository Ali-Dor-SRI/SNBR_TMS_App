"""Tests for the mean ± SD whisker helper used on the cohort violin plots."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.container import ErrorbarContainer

from processing._v1_visualization import draw_group_sd_lines


def _errorbars(ax):
    return [c for c in ax.containers if isinstance(c, ErrorbarContainer)]


def test_draws_one_whisker_per_valid_group():
    fig, ax = plt.subplots()
    extents = draw_group_sd_lines(
        ax, [(0, 10.0, 2.0, "#000000"), (1, 20.0, 4.0, "#111111")],
    )
    assert len(_errorbars(ax)) == 2
    assert sorted(extents) == [8.0, 12.0, 16.0, 24.0]
    plt.close(fig)


def test_skips_undefined_or_zero_sd():
    fig, ax = plt.subplots()
    extents = draw_group_sd_lines(ax, [
        (0, 10.0, float("nan"), "#000"),   # undefined SD (group of one)
        (1, 20.0, 0.0, "#000"),            # zero SD
        (2, 30.0, 3.0, "#000"),            # valid
    ])
    assert len(_errorbars(ax)) == 1
    assert sorted(extents) == [27.0, 33.0]
    plt.close(fig)


def test_returns_empty_when_no_valid_groups():
    fig, ax = plt.subplots()
    assert draw_group_sd_lines(ax, [(0, float("nan"), 1.0, "#000")]) == []
    assert _errorbars(ax) == []
    plt.close(fig)
