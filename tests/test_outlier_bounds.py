"""Tests for cohort-wide outlier bounds (controller + persistence).

An outlier bound is a per-measure ``[lower, upper]`` cutoff applied to every
participant. The value tested is each participant-visit's *average* for the
measure (the stored ``*_avg`` for SICI/SICF, the mean across sub-columns for
CSP/RMT). A visit whose average falls outside the range has that measure's
columns blanked in *just that row* — removing it from the measure's cohort
average and blanking it in the exported CSV — on top of the per-participant
exclusions.

A temporary settings file is patched in for every test so the real
``core/saved_defaults.json`` is never read or written.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow imports from the SNBR_TMS_App package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import pytest

import core.user_settings as user_settings
from core.user_settings import KEY_OUTLIER_BOUNDS, load_defaults, save_defaults
from gui.controller import AppController


@pytest.fixture(autouse=True)
def temp_settings(tmp_path, monkeypatch):
    """Redirect the settings file to a temp path for the whole test."""
    monkeypatch.setattr(
        user_settings, "_SETTINGS_FILE", tmp_path / "saved_defaults.json",
    )


def _make_df() -> pd.DataFrame:
    """Four participant-visits with SICI-avg, RMT and CSP columns.

    RMT means: id1-A 44, id1-B 46, id2 55, id3 200 (id3 a high outlier).
    T_SICI_avg: 0.50, 0.60, 0.90, 5.00 (id3 a high outlier).
    """
    return pd.DataFrame([
        {"ID": 1, "Date": "01/02/2026", "Study": "SNBR", "Subject_type": "Control",
         "Stimulated_cortex": "Left M1", "source_file": "a.MEM",
         "T_SICI_avg": 0.50, "RMT50": 40, "RMT200": 44, "RMT1000": 48,
         "CSP_80": 100, "CSP_100": 110, "CSP_120": 120, "CSP_140": 130, "CSP_160": 140},
        {"ID": 1, "Date": "08/03/2026", "Study": "SNBR", "Subject_type": "Control",
         "Stimulated_cortex": "Right M1", "source_file": "b.MEM",
         "T_SICI_avg": 0.60, "RMT50": 44, "RMT200": 46, "RMT1000": 48,
         "CSP_80": 102, "CSP_100": 112, "CSP_120": 122, "CSP_140": 132, "CSP_160": 142},
        {"ID": 2, "Date": "02/02/2026", "Study": "SNBR", "Subject_type": "Patient",
         "Stimulated_cortex": "Left M1", "source_file": "c.MEM",
         "T_SICI_avg": 0.90, "RMT50": 54, "RMT200": 55, "RMT1000": 56,
         "CSP_80": 150, "CSP_100": 160, "CSP_120": 170, "CSP_140": 180, "CSP_160": 190},
        {"ID": 3, "Date": "03/02/2026", "Study": "ALS", "Subject_type": "Patient",
         "Stimulated_cortex": "Left M1", "source_file": "d.MEM",
         "T_SICI_avg": 5.00, "RMT50": 190, "RMT200": 200, "RMT1000": 210,
         "CSP_80": 300, "CSP_100": 310, "CSP_120": 320, "CSP_140": 330, "CSP_160": 340},
    ])


def _controller() -> AppController:
    c = AppController()
    c.clear_excluded_tests()   # start clean regardless of any default
    c.clear_outlier_bounds()
    c.set_dataframe(_make_df())
    return c


def _rows_for(df: pd.DataFrame, pid: int) -> pd.DataFrame:
    return df[pd.to_numeric(df["ID"], errors="coerce") == pid]


def _row_at(df: pd.DataFrame, pid: int, date: str) -> pd.Series:
    sub = df[(pd.to_numeric(df["ID"], errors="coerce") == pid) & (df["Date"] == date)]
    return sub.iloc[0]


# ── Aggregate value used for the check ─────────────────

def test_aggregate_uses_stored_sici_avg():
    c = _controller()
    agg = AppController._measure_aggregate_series(c.get_dataframe(), "t_sici")
    assert list(agg) == [0.50, 0.60, 0.90, 5.00]


def test_aggregate_means_rmt_subcolumns():
    c = _controller()
    agg = AppController._measure_aggregate_series(c.get_dataframe(), "rmt")
    assert list(agg) == [44.0, 46.0, 55.0, 200.0]


def test_aggregate_means_csp_subcolumns():
    c = _controller()
    agg = AppController._measure_aggregate_series(c.get_dataframe(), "csp")
    # id1-A CSP 100..140 → mean 120.
    assert agg.iloc[0] == 120.0


# ── Bound blanking ─────────────────────────────────────

def test_upper_bound_blanks_out_of_range_visit_only():
    c = _controller()
    c.set_outlier_bound("t_sici", None, 2.0)
    exported = c.get_export_dataframe()
    # id3 (avg 5.0) is out of range → blanked; everyone else kept.
    assert _rows_for(exported, 3)["T_SICI_avg"].isna().all()
    assert _rows_for(exported, 1)["T_SICI_avg"].notna().all()
    assert _rows_for(exported, 2)["T_SICI_avg"].notna().all()
    # A different measure on id3 is untouched.
    assert _rows_for(exported, 3)["RMT50"].notna().all()


def test_lower_bound_blanks_below_cutoff():
    c = _controller()
    c.set_outlier_bound("rmt", 60, None)  # RMT mean < 60 excluded
    exported = c.get_export_dataframe()
    for pid in (1, 2):  # means 44/46/55 all < 60
        assert _rows_for(exported, pid)[["RMT50", "RMT200", "RMT1000"]].isna().all().all()
    assert _rows_for(exported, 3)[["RMT50", "RMT200", "RMT1000"]].notna().all().all()


def test_bound_is_per_visit_not_per_participant():
    c = _controller()
    # id1 visit-A avg 0.50 (kept), visit-B avg 0.60 (excluded).
    c.set_outlier_bound("t_sici", None, 0.55)
    exported = c.get_export_dataframe()
    assert pd.notna(_row_at(exported, 1, "01/02/2026")["T_SICI_avg"])
    assert pd.isna(_row_at(exported, 1, "08/03/2026")["T_SICI_avg"])


def test_bounds_additive_with_manual_exclusion():
    c = _controller()
    c.set_test_excluded(2, "t_sici", True)      # manual: whole participant 2
    c.set_outlier_bound("rmt", None, 100)       # outlier: id3 (mean 200)
    exported = c.get_export_dataframe()
    assert _rows_for(exported, 2)["T_SICI_avg"].isna().all()          # manual
    assert _rows_for(exported, 3)[["RMT50", "RMT1000"]].isna().all().all()  # outlier
    # Manual exclusion on id2 leaves id2's RMT alone; id2 RMT mean 55 < 100 so kept.
    assert _rows_for(exported, 2)["RMT50"].notna().all()


def test_out_of_range_when_no_bounds_changes_nothing():
    c = _controller()
    exported = c.get_export_dataframe()
    assert exported["T_SICI_avg"].notna().all()
    assert exported["RMT50"].notna().all()


# ── Plotting exemption ─────────────────────────────────

def test_exempt_participant_keeps_own_out_of_range_value():
    c = _controller()
    c.set_outlier_bound("t_sici", None, 2.0)
    base = c._measure_excluded_df(c.get_dataframe(), exempt_id=3)
    # id3 keeps its own out-of-range value when it is the report subject...
    assert _rows_for(base, 3)["T_SICI_avg"].notna().all()
    # ...but without the exemption it is blanked.
    plain = c._measure_excluded_df(c.get_dataframe())
    assert _rows_for(plain, 3)["T_SICI_avg"].isna().all()


def test_export_does_not_mutate_in_memory_df():
    c = _controller()
    c.set_outlier_bound("t_sici", None, 2.0)
    c.get_export_dataframe()
    assert _rows_for(c.get_dataframe(), 3)["T_SICI_avg"].notna().all()


# ── Suggest (mean ± 2 SD) ──────────────────────────────

def test_suggest_mean_2sd_matches_numpy():
    c = _controller()
    values = np.array([0.50, 0.60, 0.90, 5.00])
    mean, std = values.mean(), values.std(ddof=1)
    lower, upper = c.suggest_outlier_bounds("t_sici")
    assert lower == pytest.approx(mean - 2 * std)
    assert upper == pytest.approx(mean + 2 * std)


def test_suggest_needs_two_values():
    c = AppController()
    c.clear_outlier_bounds()
    c.set_dataframe(_make_df().iloc[[0]].copy())
    assert c.suggest_outlier_bounds("t_sici") == (None, None)


def test_suggest_none_without_data():
    c = AppController()
    c.clear_outlier_bounds()
    c.set_dataframe(None)
    assert c.suggest_outlier_bounds("rmt") == (None, None)


# ── Counts & table rows ────────────────────────────────

def test_outlier_excluded_count():
    c = _controller()
    c.set_outlier_bound("rmt", None, 100)  # only id3 (mean 200)
    assert c.get_outlier_excluded_count("rmt") == 1
    c.set_outlier_bound("t_sici", None, 0.55)  # id1-B (0.60), id2 (0.90), id3 (5.0)
    assert c.get_outlier_excluded_count("t_sici") == 3


def test_bound_rows_report_presence_and_values():
    c = _controller()
    c.set_outlier_bound("rmt", 30, 100)
    rows = {r["key"]: r for r in c.get_outlier_bound_rows()}
    assert rows["rmt"]["lower"] == 30 and rows["rmt"]["upper"] == 100
    assert rows["rmt"]["present"] is True
    assert rows["t_sici"]["present"] is True
    assert rows["csp"]["present"] is True
    # Measures with no data in the fixture are flagged absent.
    assert rows["t_sicf"]["present"] is False
    assert rows["a_sici"]["present"] is False


# ── Set / clear semantics ──────────────────────────────

def test_set_bound_none_clears_measure():
    c = _controller()
    c.set_outlier_bound("rmt", 30, 90)
    assert c.has_outlier_bounds() is True
    c.set_outlier_bound("rmt", None, None)
    assert c.has_outlier_bounds() is False
    assert c.get_outlier_bound("rmt") == (None, None)


def test_lower_only_and_upper_only():
    c = _controller()
    c.set_outlier_bound("rmt", 30, None)
    assert c.get_outlier_bound("rmt") == (30.0, None)
    c.set_outlier_bound("t_sici", None, 2.5)
    assert c.get_outlier_bound("t_sici") == (None, 2.5)


def test_numeric_strings_are_coerced():
    c = _controller()
    c.set_outlier_bound("rmt", "30", "90.5")
    assert c.get_outlier_bound("rmt") == (30.0, 90.5)


def test_unknown_measure_is_ignored():
    c = _controller()
    c.set_outlier_bound("bogus", 1, 2)
    assert c.has_outlier_bounds() is False


def test_unparseable_bound_is_dropped():
    c = _controller()
    c.set_outlier_bound("rmt", "abc", 90)
    assert c.get_outlier_bound("rmt") == (None, 90.0)


def test_clear_removes_all_bounds():
    c = _controller()
    c.set_outlier_bound("rmt", 30, 90)
    c.set_outlier_bound("t_sici", None, 2.0)
    c.clear_outlier_bounds()
    assert c.has_outlier_bounds() is False


# ── Persistence ────────────────────────────────────────

def test_save_persists_and_reloads_on_new_controller():
    c = _controller()
    c.set_outlier_bound("rmt", 30, 90)
    c.set_outlier_bound("t_sici", None, 2.0)
    c.save_outlier_bounds()

    assert load_defaults()[KEY_OUTLIER_BOUNDS] == {
        "rmt": {"lower": 30.0, "upper": 90.0},
        "t_sici": {"lower": None, "upper": 2.0},
    }

    fresh = AppController()
    assert fresh.get_outlier_bound("rmt") == (30.0, 90.0)
    assert fresh.get_outlier_bound("t_sici") == (None, 2.0)
    assert fresh.has_outlier_bounds() is True


def test_save_empty_clears_saved_default():
    c = _controller()
    c.set_outlier_bound("rmt", 30, 90)
    c.save_outlier_bounds()
    assert c.get_saved_outlier_bounds() == {"rmt": {"lower": 30.0, "upper": 90.0}}

    c.clear_outlier_bounds()
    c.save_outlier_bounds()
    assert c.get_saved_outlier_bounds() == {}


def test_session_change_does_not_persist_until_saved():
    c = _controller()
    c.set_outlier_bound("rmt", 30, 90)
    assert c.get_saved_outlier_bounds() == {}
    fresh = AppController()
    assert fresh.has_outlier_bounds() is False


def test_saved_bounds_coerce_and_drop_invalid():
    save_defaults(**{KEY_OUTLIER_BOUNDS: {
        "rmt": {"lower": "30", "upper": "abc"},   # upper unparseable → None
        "bogus": {"lower": 1, "upper": 2},        # unknown measure → dropped
        "csp": {"lower": None, "upper": None},    # both empty → dropped
    }})
    c = AppController()
    assert c.get_outlier_bound("rmt") == (30.0, None)
    assert c.get_outlier_bound("csp") == (None, None)
    # Only rmt survived coercion — the bogus/both-empty entries were dropped.
    active = [
        k for k in AppController.EXCLUDABLE_TEST_KEYS
        if c.get_outlier_bound(k) != (None, None)
    ]
    assert active == ["rmt"]
