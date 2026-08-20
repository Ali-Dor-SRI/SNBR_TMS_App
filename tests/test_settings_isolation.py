"""The suite must not read or write the developer's real settings file.

``core/saved_defaults.json`` is gitignored dev state -- the machine's own MEM and
CSP paths, the operator's email address, their saved exclusions. It is also what
``core.user_settings`` resolves to in a development checkout, at import time.

So a test that calls ``save_defaults`` rewrites it, and a test that reads
defaults inherits whatever is in it. Three test modules already guarded
themselves with a local ``temp_settings`` fixture; the autouse fixture in
conftest makes that unconditional. These check the guard is actually in force,
because a guard nobody verifies is a guard that quietly stops working.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import user_settings
from core.user_settings import load_defaults, save_defaults

REAL_SETTINGS_FILE = (
    Path(__file__).resolve().parents[1] / "core" / "saved_defaults.json"
)


def test_the_settings_file_is_redirected_away_from_the_repo():
    """Whatever the tests write, it must not be the developer's own file."""
    active = Path(user_settings._SETTINGS_FILE).resolve()

    assert active != REAL_SETTINGS_FILE.resolve(), (
        "core.user_settings still points at the repo-local saved_defaults.json; "
        "the autouse fixture in conftest.py is not in force"
    )


def test_writing_a_default_does_not_touch_the_real_file():
    before = REAL_SETTINGS_FILE.read_bytes() if REAL_SETTINGS_FILE.exists() else None

    save_defaults(mem_dir=r"X:\not-a-real-path")

    after = REAL_SETTINGS_FILE.read_bytes() if REAL_SETTINGS_FILE.exists() else None
    assert after == before, (
        "saving a default rewrote the developer's core/saved_defaults.json"
    )


def test_each_test_starts_from_empty_settings():
    """Otherwise one test's saved value leaks into the next one's assertions.

    ``load_defaults`` always returns the full key set, filling in blanks for
    anything unsaved, so "empty" means every value is falsy rather than an
    empty dict.
    """
    populated = {k: v for k, v in load_defaults().items() if v}
    assert not populated, f"settings carried over from another test: {populated}"


def test_a_value_saved_in_this_test_is_visible_in_this_test():
    """The redirect must still behave like real settings, not swallow writes."""
    save_defaults(mem_dir=r"X:\somewhere")
    assert load_defaults().get("mem_dir") == r"X:\somewhere"
