"""Tests for per-test participant exclusion (controller + persistence).

Excluding a test for a participant blanks that measure's columns in the
participant's rows, which removes them from that measure's cohort average and
blanks it in the exported CSV — while leaving their other tests intact.

A temporary settings file is patched in for every test so the real
``core/saved_defaults.json`` is never read or written.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow imports from the SNBR_TMS_App package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import pytest

import core.user_settings as user_settings
from core.user_settings import (
    KEY_EXCLUDED_MEASUREMENTS,
    KEY_EXCLUDED_PARTICIPANTS,
    load_defaults,
    save_defaults,
)
from gui.controller import AppController


@pytest.fixture(autouse=True)
def temp_settings(tmp_path, monkeypatch):
    """Redirect the settings file to a temp path for the whole test."""
    monkeypatch.setattr(
        user_settings, "_SETTINGS_FILE", tmp_path / "saved_defaults.json",
    )


def _make_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"ID": 1, "Date": "01/02/2026", "Study": "SNBR", "Subject_type": "Control",
         "Stimulated_cortex": "Left M1", "source_file": "a.MEM",
         "T_SICI_avg": 0.50, "T_SICF_avg": 1.10, "RMT50": 40},
        {"ID": 1, "Date": "08/03/2026", "Study": "SNBR", "Subject_type": "Control",
         "Stimulated_cortex": "Right M1", "source_file": "b.MEM",
         "T_SICI_avg": 0.60, "T_SICF_avg": 1.20, "RMT50": 42},
        {"ID": 2, "Date": "02/02/2026", "Study": "SNBR", "Subject_type": "Patient",
         "Stimulated_cortex": "Left M1", "source_file": "c.MEM",
         "T_SICI_avg": 0.90, "T_SICF_avg": 1.90, "RMT50": 55},
        {"ID": 3, "Date": "03/02/2026", "Study": "ALS", "Subject_type": "Patient",
         "Stimulated_cortex": "Left M1", "source_file": "d.MEM",
         "T_SICI_avg": 0.70, "T_SICF_avg": 1.70, "RMT50": 50},
    ])


def _controller() -> AppController:
    c = AppController()
    c.clear_excluded_tests()  # start clean regardless of any default
    c.set_dataframe(_make_df())
    return c


def _rows_for(df: pd.DataFrame, pid: int) -> pd.DataFrame:
    return df[pd.to_numeric(df["ID"], errors="coerce") == pid]


# ── Test registry ──────────────────────────────────────

def test_expected_test_keys_available():
    keys = AppController.EXCLUDABLE_TEST_KEYS
    for k in ("t_sici", "t_sicf", "a_sici", "a_sicf", "csp", "rmt"):
        assert k in keys


# ── Overviews & available tests ────────────────────────

def test_overviews_carry_excluded_count():
    c = _controller()
    c.set_test_excluded(2, "t_sicf", True)
    overviews = {o["id"]: o for o in c.get_participant_overviews()}
    assert overviews[1]["excluded_count"] == 0
    assert overviews[2]["excluded_count"] == 1
    assert overviews[1]["visit_count"] == 2


def test_participant_tests_lists_only_present_tests():
    c = _controller()
    keys = {t["key"] for t in c.get_participant_tests(1)}
    # Only T-SICI, T-SICF and RMT have data in the fixture.
    assert keys == {"t_sici", "t_sicf", "rmt"}
    assert all(t["excluded"] is False for t in c.get_participant_tests(1))


def test_participant_tests_reflect_exclusion():
    c = _controller()
    c.set_test_excluded(1, "t_sicf", True)
    by_key = {t["key"]: t for t in c.get_participant_tests(1)}
    assert by_key["t_sicf"]["excluded"] is True
    assert by_key["t_sici"]["excluded"] is False


# ── Toggling ───────────────────────────────────────────

def test_toggle_single_test():
    c = _controller()
    c.set_test_excluded(2, "t_sicf", True)
    assert c.is_test_excluded(2, "t_sicf") is True
    assert c.is_test_excluded(2, "t_sici") is False
    assert c.is_participant_excluded(2) is True
    assert c.get_excluded_test_count(2) == 1

    c.set_test_excluded(2, "t_sicf", False)
    assert c.is_test_excluded(2, "t_sicf") is False
    assert c.is_participant_excluded(2) is False


def test_unknown_test_key_is_ignored():
    c = _controller()
    c.set_test_excluded(2, "bogus", True)
    assert c.is_participant_excluded(2) is False


def test_excluded_entries_are_flattened_and_ordered():
    c = _controller()
    c.set_test_excluded(3, "rmt", True)
    c.set_test_excluded(2, "t_sicf", True)
    c.set_test_excluded(2, "t_sici", True)
    entries = c.get_excluded_entries()
    # Ordered by participant id, then by canonical test order.
    assert [(e["id"], e["test_key"]) for e in entries] == [
        (2, "t_sici"), (2, "t_sicf"), (3, "rmt"),
    ]


# ── Export blanking ────────────────────────────────────

def test_export_blanks_only_excluded_test_for_that_participant():
    c = _controller()
    c.set_test_excluded(2, "t_sicf", True)
    exported = c.get_export_dataframe()

    p2 = _rows_for(exported, 2)
    assert p2["T_SICF_avg"].isna().all()      # excluded test blanked
    assert p2["T_SICI_avg"].notna().all()     # other test kept
    assert p2["RMT50"].notna().all()          # other test kept

    # Other participants are untouched.
    assert _rows_for(exported, 1)["T_SICF_avg"].notna().all()
    assert _rows_for(exported, 3)["T_SICF_avg"].notna().all()


def test_export_blanks_rmt_when_excluded():
    c = _controller()
    c.set_test_excluded(3, "rmt", True)
    exported = c.get_export_dataframe()
    assert _rows_for(exported, 3)["RMT50"].isna().all()
    assert _rows_for(exported, 3)["T_SICI_avg"].notna().all()


def test_export_does_not_mutate_in_memory_df():
    c = _controller()
    c.set_test_excluded(2, "t_sicf", True)
    c.get_export_dataframe()
    assert _rows_for(c.get_dataframe(), 2)["T_SICF_avg"].notna().all()


def test_export_unchanged_when_nothing_excluded():
    c = _controller()
    exported = c.get_export_dataframe()
    assert exported["T_SICF_avg"].notna().all()


def test_export_none_without_data():
    c = AppController()
    c.clear_excluded_tests()
    c.set_dataframe(None)
    assert c.get_export_dataframe() is None


# ── Plotting exemption ─────────────────────────────────

def test_plot_filter_exempts_selected_participant():
    c = _controller()
    c.set_test_excluded(2, "t_sicf", True)
    c.set_test_excluded(3, "rmt", True)

    base = c._measure_excluded_df(c.get_dataframe(), exempt_id=2)
    # Selected participant 2 keeps their excluded test...
    assert _rows_for(base, 2)["T_SICF_avg"].notna().all()
    # ...but the other excluded participant (3) still gets RMT blanked.
    assert _rows_for(base, 3)["RMT50"].isna().all()


def test_plot_filter_blanks_excluded_without_exemption():
    c = _controller()
    c.set_test_excluded(2, "t_sicf", True)
    base = c._measure_excluded_df(c.get_dataframe())
    assert _rows_for(base, 2)["T_SICF_avg"].isna().all()


# ── Clear ──────────────────────────────────────────────

def test_clear_removes_all_exclusions():
    c = _controller()
    c.set_test_excluded(1, "t_sici", True)
    c.set_test_excluded(2, "t_sicf", True)
    c.clear_excluded_tests()
    assert c.get_excluded_entries() == []
    assert c.is_participant_excluded(1) is False


# ── Persistence ────────────────────────────────────────

def test_save_persists_and_reloads_on_new_controller():
    c = _controller()
    c.set_test_excluded(2, "t_sicf", True)
    c.set_test_excluded(3, "rmt", True)
    c.save_excluded_tests()

    assert load_defaults()[KEY_EXCLUDED_MEASUREMENTS] == {"2": ["t_sicf"], "3": ["rmt"]}
    assert c.get_saved_excluded_map() == {2: ["t_sicf"], 3: ["rmt"]}

    fresh = AppController()
    assert fresh.is_test_excluded(2, "t_sicf") is True
    assert fresh.is_test_excluded(3, "rmt") is True
    assert fresh.get_excluded_test_count(2) == 1


def test_save_empty_clears_saved_default():
    c = _controller()
    c.set_test_excluded(2, "t_sicf", True)
    c.save_excluded_tests()
    assert c.get_saved_excluded_map() == {2: ["t_sicf"]}

    c.clear_excluded_tests()
    c.save_excluded_tests()
    assert c.get_saved_excluded_map() == {}


def test_session_change_does_not_persist_until_saved():
    c = _controller()
    c.set_test_excluded(2, "t_sicf", True)
    assert c.get_saved_excluded_map() == {}
    fresh = AppController()
    assert fresh.is_participant_excluded(2) is False


def test_saved_map_coerces_keys_and_drops_invalid_tests():
    save_defaults(**{KEY_EXCLUDED_MEASUREMENTS: {"2": ["t_sicf", "bogus"], "x": ["rmt"]}})
    c = AppController()
    assert c.is_test_excluded(2, "t_sicf") is True
    assert c.is_test_excluded(2, "bogus") is False
    # Non-integer participant key is ignored.
    assert c.get_excluded_entries() == [{"id": 2, "test_key": "t_sicf",
                                          "test_label": AppController._test_label("t_sicf")}]


def test_legacy_whole_participant_list_migrates_to_all_tests():
    # Old format: a plain list of participant IDs means "exclude every test".
    save_defaults(**{KEY_EXCLUDED_PARTICIPANTS: [2, 3]})
    c = AppController()
    assert c.is_participant_excluded(2) is True
    assert c.get_excluded_test_count(2) == len(AppController.EXCLUDABLE_TEST_KEYS)
    assert c.is_test_excluded(2, "t_sicf") is True
    assert c.is_test_excluded(3, "rmt") is True
