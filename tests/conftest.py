"""Shared pytest configuration for the SNBR TMS App test suite.

Two things live here.

**The realdata opt-in.** Some tests read the lab's Y: share and take tens of
seconds. They are marked ``@pytest.mark.realdata`` and are deselected unless
``--realdata`` is passed, so the everyday suite stays hermetic and fast::

    .venv312\\Scripts\\python.exe -m pytest tests/ -q                # hermetic
    .venv312\\Scripts\\python.exe -m pytest tests/ -q --realdata     # + the share

The flag and the marker are registered here rather than in a pytest.ini because
CLAUDE.md asks that nothing new be created in the project root.

**Settings isolation.** ``core.user_settings`` resolves its file at import time
and, in development, that is the repo-local ``core/saved_defaults.json`` -- the
developer's real machine paths, email address and exclusions. Any test that
calls ``save_defaults`` would rewrite it, and any test that reads defaults would
depend on whatever happens to be in it. Three test modules already defended
themselves with a local ``temp_settings`` fixture; this makes that automatic and
unconditional, so a new test cannot forget.

It also removes a known trap: the GUI widget tree depends on the saved defaults,
so a comparison checkout without that gitignored file renders the Settings page
differently for reasons that have nothing to do with the code under test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------------
# The realdata opt-in
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption(
        "--realdata",
        action="store_true",
        default=False,
        help="also run tests that read the lab's Y: share (slow, machine-specific)",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "realdata: reads the lab's Y: share; deselected unless --realdata is given",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--realdata"):
        return
    skip = pytest.mark.skip(reason="needs --realdata (reads the lab's Y: share)")
    for item in items:
        if "realdata" in item.keywords:
            item.add_marker(skip)


# ---------------------------------------------------------------------------
# Settings isolation
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_user_settings(tmp_path, monkeypatch):
    """Point core.user_settings at a throwaway file for every test.

    Autouse and unconditional. The real file is the developer's own
    core/saved_defaults.json, which is gitignored dev state: tests must neither
    read it nor write it.
    """
    from core import user_settings

    monkeypatch.setattr(
        user_settings, "_SETTINGS_FILE", tmp_path / "saved_defaults.json",
    )
    yield
