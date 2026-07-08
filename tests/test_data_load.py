"""Tests for the archive-CSV loaders on AppController.

The fast "use the archive as-is" path must NOT touch the CMAP folder, while the
standard path still merges CMAP when one is configured. The heavy I/O is
monkeypatched out so the tests are hermetic and fast.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import pytest

import core.user_settings as user_settings
import gui.controller as controller_mod
from gui.controller import AppController


@pytest.fixture(autouse=True)
def temp_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(
        user_settings, "_SETTINGS_FILE", tmp_path / "saved_defaults.json",
    )


@pytest.fixture
def patched_loaders(monkeypatch):
    """Stub ``load_existing_csv`` and spy on the CMAP merge."""
    calls = {"cmap": 0}
    monkeypatch.setattr(
        controller_mod, "load_existing_csv",
        lambda path: pd.DataFrame({"ID": [1, 2], "T_SICI_avg": [0.5, 0.6]}),
    )

    def _cmap_spy(df, paths, recursive=False):
        calls["cmap"] += 1
        out = df.copy()
        out["CMAP_table"] = "x"
        return out

    monkeypatch.setattr(controller_mod, "_apply_cmap_merge", _cmap_spy)
    return calls


def _controller_with_cmap() -> AppController:
    c = AppController()
    c._csv_path = "archive.csv"
    c._cmap_paths = ["C:/some/cmap"]  # pretend a CMAP folder is configured
    return c


def test_fast_load_skips_cmap_merge(patched_loaders):
    c = _controller_with_cmap()
    df = c.load_csv_dataframe(merge_cmap=False)
    assert patched_loaders["cmap"] == 0
    assert "CMAP_table" not in df.columns
    assert c.get_dataframe() is df


def test_standard_load_applies_cmap_merge(patched_loaders):
    c = _controller_with_cmap()
    df = c.load_csv_dataframe()  # default merge_cmap=True
    assert patched_loaders["cmap"] == 1
    assert "CMAP_table" in df.columns


def test_fast_load_without_cmap_folder(patched_loaders):
    c = AppController()
    c._csv_path = "archive.csv"
    c._cmap_paths = []  # no CMAP configured
    df = c.load_csv_dataframe(merge_cmap=False)
    assert patched_loaders["cmap"] == 0
    assert len(df) == 2


def test_data_mode_has_fast_constant():
    # The fast-path radio value must be distinct from the other modes.
    from gui.data_mode_panel import (
        MODE_EXISTING_CSV, MODE_EXISTING_CSV_FAST, MODE_PARSE_MEM,
    )
    assert len({MODE_EXISTING_CSV, MODE_EXISTING_CSV_FAST, MODE_PARSE_MEM}) == 3
