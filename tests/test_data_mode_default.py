"""Tests for the Data Import page's "Save as default" tick box.

Every other page holding a setting that Quick Start reuses offers one; the Data
Import page did not, so the mode an automated run used was fixed in the
controller and could not be changed from the app at all.

Three things have to work: the tick box stores the chosen option, an automated
run replays it, and the page reopens on it. The widget-level tests walk the
built tree and drive the real checkbox rather than reading the panel's source,
so reformatting cannot break them and a box wired to nothing cannot pass.

The safety override is pinned here too: a saved "archive as-is" must still lose
to a schema-stale archive, or the fast path a user asked for would quietly cost
them the SR/SD figures.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gui.controller as controller_module
from core.user_settings import (
    DATA_MODE_ARCHIVE_AS_IS,
    DATA_MODE_ARCHIVE_PLUS_NEW,
    DATA_MODE_FULL_PARSE,
    KEY_CSV_FILE,
    KEY_DATA_MODE,
    KEY_EXPORT_CSV,
    KEY_MEM_DIR,
    save_defaults,
)
from gui.controller import AppController
from gui.data_mode_panel import (
    MODE_EXISTING_CSV,
    MODE_EXISTING_CSV_FAST,
    MODE_PARSE_MEM,
)

SAVE_BOX_TEXT = "Save as default"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


def _checkbox_labelled(widget, text):
    import customtkinter as ctk

    for w in _walk(widget):
        if isinstance(w, ctk.CTkCheckBox) and w.cget("text") == text:
            return w
    return None


def _label_texts(widget):
    import customtkinter as ctk

    return [
        w.cget("text") for w in _walk(widget)
        if isinstance(w, ctk.CTkLabel)
    ]


def _build_panel(tk_root, controller):
    """A DataModePanel on the session-wide root (see tests/conftest.py)."""
    import customtkinter as ctk

    from gui.data_mode_panel import DataModePanel

    holder = ctk.CTkFrame(tk_root)
    return DataModePanel(
        holder, controller, on_next=lambda: None, on_back=lambda: None,
    )


def _no_background_import(panel, monkeypatch):
    """Keep _handle_next's real save path but skip its worker thread.

    The worker marshals back with ``self.after``, which raises off the main
    thread when no Tk main loop is running; pytest then reports the failure
    against whichever test happens to run next. The save is on the main thread
    before the thread starts, so nothing under test is bypassed.
    """
    monkeypatch.setattr(panel, "_run_import", lambda *a, **k: None)


def _stub_loads(controller, monkeypatch):
    """Replace both load paths with recorders; return the call list.

    ``[("parse", {})]`` for a re-parse, ``[("load_csv", {"merge_cmap": ...})]``
    for an archive load, so a test can tell not just that data was loaded but
    which of the page's three options actually ran.
    """
    calls: list[tuple[str, dict]] = []
    df = pd.DataFrame([{"ID": 1, "Date": "18/08/2026"}])

    def fake_parse():
        calls.append(("parse", {}))
        controller._dataframe = df
        return df

    def fake_load(**kwargs):
        calls.append(("load_csv", kwargs))
        controller._dataframe = df
        return df

    monkeypatch.setattr(controller, "parse_and_build", fake_parse)
    monkeypatch.setattr(controller, "load_csv_dataframe", fake_load)
    return calls


def _controller_for_phase_two(monkeypatch, tmp_path, *, schema_current=True):
    """A controller with both import paths set and a known archive freshness."""
    c = AppController()
    c.set_paths(mem_path=[str(tmp_path)], csv_path=str(tmp_path / "archive.csv"))
    monkeypatch.setattr(
        controller_module, "csv_schema_is_current", lambda path: schema_current,
    )
    return c


# --------------------------------------------------------------------------
# The tick box itself
# --------------------------------------------------------------------------

def test_the_page_offers_a_save_as_default_tick_box(tk_root):
    panel = _build_panel(tk_root, AppController())

    assert _checkbox_labelled(panel, SAVE_BOX_TEXT) is not None, (
        "the Data Import page has no 'Save as default' checkbox"
    )


def test_ticking_it_stores_the_selected_mode(tk_root, monkeypatch):
    controller = AppController()
    panel = _build_panel(tk_root, controller)
    _no_background_import(panel, monkeypatch)
    panel._mode_var.set(MODE_PARSE_MEM)

    _checkbox_labelled(panel, SAVE_BOX_TEXT).select()
    panel._handle_next()

    assert controller.get_data_mode_default() == DATA_MODE_FULL_PARSE


def test_each_option_stores_its_own_mode(tk_root, monkeypatch):
    """The three radios must not all save the same slug."""
    saved = []
    for radio, expected in [
        (MODE_EXISTING_CSV_FAST, DATA_MODE_ARCHIVE_AS_IS),
        (MODE_EXISTING_CSV, DATA_MODE_ARCHIVE_PLUS_NEW),
        (MODE_PARSE_MEM, DATA_MODE_FULL_PARSE),
    ]:
        controller = AppController()
        panel = _build_panel(tk_root, controller)
        _no_background_import(panel, monkeypatch)
        panel._mode_var.set(radio)
        _checkbox_labelled(panel, SAVE_BOX_TEXT).select()
        panel._handle_next()
        saved.append((controller.get_data_mode_default(), expected))

    assert [got for got, _ in saved] == [want for _, want in saved]


def test_leaving_it_unticked_keeps_the_previous_default(tk_root, monkeypatch):
    """Unticked means "don't change it", never "clear it" — as on every page."""
    save_defaults(**{KEY_DATA_MODE: DATA_MODE_FULL_PARSE})
    controller = AppController()
    panel = _build_panel(tk_root, controller)
    _no_background_import(panel, monkeypatch)
    panel._mode_var.set(MODE_EXISTING_CSV_FAST)

    panel._handle_next()

    assert controller.get_data_mode_default() == DATA_MODE_FULL_PARSE


# --------------------------------------------------------------------------
# Reopening the page on the saved mode
# --------------------------------------------------------------------------

def test_the_page_reopens_on_the_saved_mode(tk_root):
    save_defaults(**{KEY_DATA_MODE: DATA_MODE_ARCHIVE_PLUS_NEW})
    controller = AppController()
    controller.set_paths(mem_path=[], csv_path="archive.csv")
    panel = _build_panel(tk_root, controller)

    panel.refresh()

    assert panel._mode_var.get() == MODE_EXISTING_CSV


def test_with_nothing_saved_the_page_still_opens_on_the_fast_path(tk_root):
    controller = AppController()
    controller.set_paths(mem_path=[], csv_path="archive.csv")
    panel = _build_panel(tk_root, controller)

    panel.refresh()

    assert panel._mode_var.get() == MODE_EXISTING_CSV_FAST


def test_a_saved_archive_mode_is_ignored_when_there_is_no_archive(tk_root):
    """Both archive radios are disabled without a CSV; don't preselect one."""
    save_defaults(**{KEY_DATA_MODE: DATA_MODE_ARCHIVE_AS_IS})
    controller = AppController()
    controller.set_paths(mem_path=[], csv_path="")
    panel = _build_panel(tk_root, controller)

    panel.refresh()

    assert panel._mode_var.get() == MODE_PARSE_MEM


# --------------------------------------------------------------------------
# What Quick Start / Complete All then does (phase 2)
# --------------------------------------------------------------------------

def test_with_nothing_saved_quick_start_loads_the_archive_as_before(
    monkeypatch, tmp_path,
):
    c = _controller_for_phase_two(monkeypatch, tmp_path)
    calls = _stub_loads(c, monkeypatch)

    c.run_default_phases(2, 3)

    assert calls == [("load_csv", {"merge_cmap": True})]


def test_a_saved_fast_mode_touches_no_folders_at_all(monkeypatch, tmp_path):
    """"Archive as-is" is the page's fast path: no CMAP scan either."""
    save_defaults(**{KEY_DATA_MODE: DATA_MODE_ARCHIVE_AS_IS})
    c = _controller_for_phase_two(monkeypatch, tmp_path)
    calls = _stub_loads(c, monkeypatch)

    c.run_default_phases(2, 3)

    assert calls == [("load_csv", {"merge_cmap": False})]


@pytest.mark.parametrize(
    "mode", [DATA_MODE_ARCHIVE_PLUS_NEW, DATA_MODE_FULL_PARSE],
)
def test_a_saved_parse_mode_re_parses_instead_of_loading(
    mode, monkeypatch, tmp_path,
):
    save_defaults(**{KEY_DATA_MODE: mode})
    c = _controller_for_phase_two(monkeypatch, tmp_path)
    calls = _stub_loads(c, monkeypatch)

    c.run_default_phases(2, 3)

    assert calls == [("parse", {})]


def test_a_stale_archive_is_re_parsed_even_when_fast_mode_is_saved(
    monkeypatch, tmp_path,
):
    """The user asked for speed, not for a report missing its SR/SD figures."""
    save_defaults(**{KEY_DATA_MODE: DATA_MODE_ARCHIVE_AS_IS})
    c = _controller_for_phase_two(monkeypatch, tmp_path, schema_current=False)
    calls = _stub_loads(c, monkeypatch)

    summary = c.run_default_phases(2, 3)

    assert calls == [("parse", {})]
    assert summary.get("schema_rebuilt") is True


# --------------------------------------------------------------------------
# The readiness gate
# --------------------------------------------------------------------------

def test_a_saved_full_parse_does_not_require_an_archive(tmp_path):
    save_defaults(**{
        KEY_MEM_DIR: [str(tmp_path)],
        KEY_DATA_MODE: DATA_MODE_FULL_PARSE,
        KEY_EXPORT_CSV: str(tmp_path),
    })
    c = AppController()

    assert c.check_quick_start_readiness() != "file_panel"
    assert not [
        m for m in c.check_defaults_for_range(1, 2) if "CSV" in m
    ]


def test_an_archive_mode_still_requires_an_archive(tmp_path):
    save_defaults(**{
        KEY_MEM_DIR: [str(tmp_path)],
        KEY_DATA_MODE: DATA_MODE_ARCHIVE_AS_IS,
        KEY_EXPORT_CSV: str(tmp_path),
    })
    c = AppController()

    assert c.check_quick_start_readiness() == "file_panel"
    assert [m for m in c.check_defaults_for_range(1, 2) if "CSV" in m]


def test_a_saved_archive_that_is_gone_is_still_an_error(tmp_path):
    """Full parse passes the archive through, so a dead path must not pass."""
    save_defaults(**{
        KEY_MEM_DIR: [str(tmp_path)],
        KEY_CSV_FILE: str(tmp_path / "missing.csv"),
        KEY_DATA_MODE: DATA_MODE_FULL_PARSE,
        KEY_EXPORT_CSV: str(tmp_path),
    })
    c = AppController()

    assert c.check_quick_start_readiness() == "file_panel"
    assert [m for m in c.check_defaults_for_range(1, 2) if "not found" in m]


# --------------------------------------------------------------------------
# Where the user can see what is saved
# --------------------------------------------------------------------------

def test_the_settings_page_names_the_saved_mode(tk_root):
    import customtkinter as ctk

    from gui.settings_panel import SettingsPanel

    save_defaults(**{KEY_DATA_MODE: DATA_MODE_FULL_PARSE})
    panel = SettingsPanel(
        ctk.CTkFrame(tk_root), AppController(), on_back=lambda: None,
    )

    panel.refresh()

    texts = _label_texts(panel)
    assert "Data Import" in texts
    assert any("Parse .MEM files" in t for t in texts)


def test_the_settings_page_says_so_when_no_mode_is_saved(tk_root):
    import customtkinter as ctk

    from gui.settings_panel import SettingsPanel

    panel = SettingsPanel(
        ctk.CTkFrame(tk_root), AppController(), on_back=lambda: None,
    )

    panel.refresh()

    # Not merely "some label says (not set)" — the unset Import Paths lines say
    # that too, which would pass with no Data Import section at all.
    assert any(
        t.startswith("(not set") and "archive .csv" in t
        for t in _label_texts(panel)
    )
