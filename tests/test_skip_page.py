"""Tests for the "Skip this page in future runs" feature.

Two layers:
* ``gui.nav`` — pure Next/Back computation that hops over skipped pages.
* ``AppController`` — the persisted, page-name-keyed skip API (gated to the
  optional pages so a required page can never be hidden).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import core.user_settings as user_settings
from core.user_settings import KEY_SKIPPED_PAGES
from gui.nav import next_visible_page, prev_visible_page

# Mirrors TMSApp._page_order.
PAGE_ORDER = [
    "welcome", "file_panel", "data_mode", "exclusion", "participant",
    "visualization", "export", "email", "redcap", "sync", "finish",
]


# ── Pure navigation ────────────────────────────────────────

def test_no_skips_is_plain_linear():
    assert next_visible_page(PAGE_ORDER, set(), "data_mode") == "exclusion"
    assert prev_visible_page(PAGE_ORDER, set(), "participant") == "exclusion"


def test_skipping_exclusion_bridges_data_mode_and_participant():
    skipped = {"exclusion"}
    assert next_visible_page(PAGE_ORDER, skipped, "data_mode") == "participant"
    assert prev_visible_page(PAGE_ORDER, skipped, "participant") == "data_mode"


def test_next_back_from_the_skipped_page_itself_land_on_neighbours():
    # Reached via the dropdown while skipped — Next/Back still bypass it.
    skipped = {"exclusion"}
    assert next_visible_page(PAGE_ORDER, skipped, "exclusion") == "participant"
    assert prev_visible_page(PAGE_ORDER, skipped, "exclusion") == "data_mode"


def test_multiple_consecutive_skips_are_hopped():
    skipped = {"email", "redcap", "sync"}
    assert next_visible_page(PAGE_ORDER, skipped, "export") == "finish"
    assert prev_visible_page(PAGE_ORDER, skipped, "finish") == "export"


def test_ends_and_unknown_pages_are_safe():
    assert next_visible_page(PAGE_ORDER, set(), "finish") == "finish"
    assert prev_visible_page(PAGE_ORDER, set(), "welcome") == "welcome"
    assert next_visible_page(PAGE_ORDER, set(), "settings") == "settings"


# ── Controller skip API (persisted) ────────────────────────

@pytest.fixture(autouse=True)
def temp_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(
        user_settings, "_SETTINGS_FILE", tmp_path / "saved_defaults.json",
    )


def _controller():
    from gui.controller import AppController
    return AppController()


def test_set_query_and_persist_skip():
    c = _controller()
    assert c.is_page_skipped("exclusion") is False

    c.set_page_skipped("exclusion", True)
    assert c.is_page_skipped("exclusion") is True
    assert c.get_skipped_pages() == {"exclusion"}

    # Persisted for future runs — a fresh controller re-reads it.
    assert _controller().is_page_skipped("exclusion") is True


def test_unskip_clears_the_persisted_flag():
    c = _controller()
    c.set_page_skipped("exclusion", True)
    c.set_page_skipped("exclusion", False)
    assert c.is_page_skipped("exclusion") is False
    # And the key is dropped from the settings file entirely.
    assert not user_settings.load_defaults().get(KEY_SKIPPED_PAGES)
    assert _controller().is_page_skipped("exclusion") is False


def test_required_pages_cannot_be_skipped():
    c = _controller()
    for required in ("participant", "visualization", "export", "welcome"):
        c.set_page_skipped(required, True)
        assert c.is_page_skipped(required) is False
    assert c.get_skipped_pages() == set()


def test_clear_all_defaults_resets_skips():
    c = _controller()
    c.set_page_skipped("exclusion", True)
    c.clear_all_defaults()
    assert c.get_skipped_pages() == set()


def test_startup_ignores_stale_non_skippable_saved_pages():
    # A settings file naming a now-required page must not resurrect a skip.
    user_settings.save_defaults(**{KEY_SKIPPED_PAGES: ["exclusion", "participant"]})
    c = _controller()
    assert c.get_skipped_pages() == {"exclusion"}
