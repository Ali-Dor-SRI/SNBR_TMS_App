"""Turning an optional Quick Start step off by saving an empty path field.

Four steps are optional — the CSV export, the PDF report, the email, the REDCap
export and the backup sync — and a lab that does not use one had no way to say
so: Quick Start refused to start without export paths and REDCap directories,
and then ran the export every time regardless.

Leaving the path empty and ticking that field's "save as default" now records
the step as turned off. The same control puts it back once a path is given, so
the setting is reachable from the page it belongs to and nowhere else.

The rule with teeth on the Export page is that an *empty* folder only means
"skip" when the export was not asked for: an empty folder with the export
ticked already means "use the default folder", and that had to keep working.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.user_settings import (
    KEY_EXPORT_CSV,
    KEY_EXPORT_PDF,
    KEY_CSV_FILE,
    KEY_MEM_DIR,
    KEY_REDCAP_DATA_DIR,
    KEY_REDCAP_DICT_DIR,
    KEY_REDCAP_EXPORT_DIR,
    KEY_REDCAP_TEMPLATE_DIR,
    KEY_SKIPPED_STEPS,
    STEP_EMAIL,
    STEP_EXPORT_CSV,
    STEP_EXPORT_PDF,
    STEP_REDCAP,
    STEP_SYNC,
    load_defaults,
    save_defaults,
)
from gui.controller import AppController


@pytest.fixture
def controller():
    return AppController()


# --------------------------------------------------------------------------
# The stored setting
# --------------------------------------------------------------------------

def test_a_step_starts_switched_on(controller):
    assert controller.get_skipped_steps() == set()
    assert not controller.is_step_skipped(STEP_REDCAP)


def test_turning_a_step_off_and_back_on(controller):
    controller.set_step_skipped(STEP_REDCAP, True)
    assert controller.is_step_skipped(STEP_REDCAP)

    controller.set_step_skipped(STEP_REDCAP, False)
    assert not controller.is_step_skipped(STEP_REDCAP)
    # Cleared, not left as an empty marker in the settings file.
    assert load_defaults().get(KEY_SKIPPED_STEPS) == []


def test_steps_are_independent(controller):
    controller.set_step_skipped(STEP_EXPORT_CSV, True)

    assert controller.is_step_skipped(STEP_EXPORT_CSV)
    assert not controller.is_step_skipped(STEP_EXPORT_PDF)


def test_a_required_step_cannot_be_turned_off(controller):
    """Only the optional five; the rest build the report."""
    with pytest.raises(ValueError):
        controller.set_step_skipped("participant", True)


def test_an_unknown_saved_step_is_ignored(controller):
    save_defaults(**{KEY_SKIPPED_STEPS: ["export_csv", "step_from_the_future"]})

    assert controller.get_skipped_steps() == {STEP_EXPORT_CSV}


def test_the_labels_name_the_steps_for_the_user(controller):
    controller.set_step_skipped(STEP_SYNC, True)
    controller.set_step_skipped(STEP_EXPORT_PDF, True)

    labels = controller.skipped_step_labels()
    assert any("PDF" in label for label in labels)
    assert any("sync" in label.lower() for label in labels)
    assert len(labels) == 2


# --------------------------------------------------------------------------
# The Export page
# --------------------------------------------------------------------------

@pytest.fixture
def export_panel(tk_root, controller):
    from gui.export_panel import ExportPanel

    panel = ExportPanel(
        tk_root, controller, on_next=lambda: None, on_back=lambda: None,
    )
    yield panel
    panel.destroy()


def test_saving_an_empty_export_folder_turns_that_export_off(
    export_panel, controller,
):
    export_panel._csv_check.set(False)
    export_panel._csv_dir.set("")
    export_panel._save_csv_default.set(True)

    export_panel._handle_next()

    assert controller.is_step_skipped(STEP_EXPORT_CSV)
    assert not controller.is_step_skipped(STEP_EXPORT_PDF)


def test_an_empty_folder_on_a_requested_export_still_means_default_folder(
    export_panel, controller,
):
    """The pre-existing meaning of an empty box must survive."""
    export_panel._csv_check.set(True)          # the user does want this export
    export_panel._csv_dir.set("")
    export_panel._save_csv_default.set(True)

    export_panel._handle_next()

    assert not controller.is_step_skipped(STEP_EXPORT_CSV)


def test_giving_a_folder_puts_the_export_back(export_panel, controller, tmp_path):
    controller.set_step_skipped(STEP_EXPORT_CSV, True)
    export_panel._csv_dir.set(str(tmp_path))
    export_panel._save_csv_default.set(True)

    export_panel._handle_next()

    assert not controller.is_step_skipped(STEP_EXPORT_CSV)


def test_without_the_save_box_nothing_changes(export_panel, controller, tmp_path):
    """Both directions: an unticked box neither turns an export off nor back on.

    Asserting only that a turned-off export stays off would pass even if the
    box were ignored entirely, since an empty folder turns it off anyway.
    """
    controller.set_step_skipped(STEP_EXPORT_CSV, True)
    export_panel._csv_dir.set(str(tmp_path))   # a folder, but not saved
    export_panel._save_csv_default.set(False)
    export_panel._pdf_dir.set("")              # empty, but not saved either
    export_panel._save_pdf_default.set(False)

    export_panel._handle_next()

    assert controller.is_step_skipped(STEP_EXPORT_CSV), "put back without asking"
    assert not controller.is_step_skipped(STEP_EXPORT_PDF), "turned off without asking"


def test_the_page_says_which_exports_are_turned_off(export_panel, controller):
    controller.set_step_skipped(STEP_EXPORT_PDF, True)

    export_panel.refresh()

    assert "PDF" in export_panel._status_var.get()


def test_ticking_save_on_an_empty_row_warns_before_next(export_panel):
    export_panel._csv_check.set(False)
    export_panel._csv_dir.set("")

    export_panel._save_csv_default.set(True)  # fires the trace

    assert "skipped" in export_panel._status_var.get().lower()


# --------------------------------------------------------------------------
# The REDCap page
# --------------------------------------------------------------------------

@pytest.fixture
def redcap_panel(tk_root, controller):
    from gui.redcap_panel import RedcapPanel

    panel = RedcapPanel(
        tk_root, controller, on_next=lambda: None, on_back=lambda: None,
    )
    yield panel
    panel.destroy()


def test_saving_an_empty_redcap_directory_turns_the_step_off(
    redcap_panel, controller,
):
    redcap_panel._data_var.set("")
    redcap_panel._save_data.set(True)

    redcap_panel._handle_next()

    assert controller.is_step_skipped(STEP_REDCAP)


def test_filling_the_redcap_directories_puts_the_step_back(
    redcap_panel, controller, tmp_path,
):
    controller.set_step_skipped(STEP_REDCAP, True)
    for var in (
        redcap_panel._data_var, redcap_panel._dict_var,
        redcap_panel._template_var, redcap_panel._export_var,
    ):
        var.set(str(tmp_path))
    redcap_panel._save_data.set(True)

    redcap_panel._handle_next()

    assert not controller.is_step_skipped(STEP_REDCAP)


def test_the_optional_xlsx_directory_cannot_turn_redcap_off(
    redcap_panel, controller, tmp_path,
):
    """The report is optional; the export runs without it."""
    for var in (
        redcap_panel._data_var, redcap_panel._dict_var,
        redcap_panel._template_var, redcap_panel._export_var,
    ):
        var.set(str(tmp_path))
    redcap_panel._xlsx_var.set("")
    redcap_panel._save_xlsx.set(True)

    redcap_panel._handle_next()

    assert not controller.is_step_skipped(STEP_REDCAP)


def test_redcap_without_any_save_box_changes_nothing(redcap_panel, controller):
    controller.set_step_skipped(STEP_REDCAP, True)
    redcap_panel._data_var.set("")

    redcap_panel._handle_next()

    assert controller.is_step_skipped(STEP_REDCAP)


# --------------------------------------------------------------------------
# The Backup & Sync page
# --------------------------------------------------------------------------

@pytest.fixture
def sync_panel(tk_root, controller):
    from gui.sync_panel import SyncPanel

    panel = SyncPanel(
        tk_root, controller, on_next=lambda: None, on_back=lambda: None,
    )
    panel.refresh()  # the pair rows are built when the page is shown
    yield panel
    panel.destroy()


def test_saving_with_no_pair_turns_sync_off(sync_panel, controller):
    sync_panel._save_default_var.set(True)

    sync_panel._handle_next()

    assert controller.is_step_skipped(STEP_SYNC)


def test_saving_a_complete_pair_puts_sync_back(sync_panel, controller, tmp_path):
    controller.set_step_skipped(STEP_SYNC, True)
    row = sync_panel._pair_rows[0]
    row["src_var"].set(str(tmp_path / "from"))
    row["dst_var"].set(str(tmp_path / "to"))
    sync_panel._save_default_var.set(True)

    sync_panel._handle_next()

    assert not controller.is_step_skipped(STEP_SYNC)


def test_a_half_filled_pair_does_not_count(sync_panel, controller, tmp_path):
    row = sync_panel._pair_rows[0]
    row["src_var"].set(str(tmp_path / "from"))
    sync_panel._save_default_var.set(True)

    sync_panel._handle_next()

    assert controller.is_step_skipped(STEP_SYNC)


# --------------------------------------------------------------------------
# The Email page
# --------------------------------------------------------------------------

@pytest.fixture
def email_panel(tk_root, controller):
    from gui.email_panel import EmailPanel

    panel = EmailPanel(
        tk_root, controller, on_next=lambda: None, on_back=lambda: None,
    )
    yield panel
    panel.destroy()


def _set_recipient(panel, value: str):
    panel._to_entry.delete(0, "end")
    panel._to_entry.insert(0, value)


def test_saving_email_defaults_with_no_recipient_turns_it_off(
    email_panel, controller,
):
    _set_recipient(email_panel, "")

    email_panel._on_save_defaults()

    assert controller.is_step_skipped(STEP_EMAIL)


def test_saving_a_recipient_puts_email_back(email_panel, controller):
    controller.set_step_skipped(STEP_EMAIL, True)
    _set_recipient(email_panel, "someone@sunnybrook.ca")

    email_panel._on_save_defaults()

    assert not controller.is_step_skipped(STEP_EMAIL)


# --------------------------------------------------------------------------
# What Quick Start then does
# --------------------------------------------------------------------------

def _export_ready(controller, out_dir, monkeypatch):
    """Point the exports at *out_dir* and stub the writing.

    A dedicated folder, not tmp_path itself: the settings file this test's
    defaults are written to lives there too, so "nothing was exported" could
    not be asserted by an empty directory.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    save_defaults(**{
        KEY_EXPORT_CSV: str(out_dir), KEY_EXPORT_PDF: str(out_dir),
    })
    written: list[str] = []
    monkeypatch.setattr(
        controller, "get_export_dataframe",
        lambda: pd.DataFrame([{"ID": 1}]),
    )
    import reports.pdf_renderer as renderer

    monkeypatch.setattr(
        renderer, "render_figures_to_pdf",
        lambda figs, path, **kw: written.append(str(path)),
    )
    return written


def test_a_turned_off_csv_export_is_not_written(controller, tmp_path, monkeypatch):
    out = tmp_path / "exports"
    _export_ready(controller, out, monkeypatch)
    controller.set_step_skipped(STEP_EXPORT_CSV, True)

    summary = controller.run_default_phases(6, 7)

    assert summary["csv_export"] == ""
    assert summary["pdf_export"]
    assert not list(out.glob("*.csv"))


def test_a_turned_off_pdf_report_is_not_rendered(controller, tmp_path, monkeypatch):
    written = _export_ready(controller, tmp_path / "exports", monkeypatch)
    controller.set_step_skipped(STEP_EXPORT_PDF, True)

    summary = controller.run_default_phases(6, 7)

    assert summary["pdf_export"] == ""
    assert written == []
    assert summary["csv_export"]


def test_turning_both_exports_off_writes_nothing(controller, tmp_path, monkeypatch):
    out = tmp_path / "exports"
    written = _export_ready(controller, out, monkeypatch)
    controller.set_step_skipped(STEP_EXPORT_CSV, True)
    controller.set_step_skipped(STEP_EXPORT_PDF, True)

    summary = controller.run_default_phases(6, 7)

    assert (summary["csv_export"], summary["pdf_export"]) == ("", "")
    assert written == []
    assert list(out.iterdir()) == []


def test_a_turned_off_email_is_reported_as_a_choice(controller):
    controller.set_step_skipped(STEP_EMAIL, True)

    summary = controller.run_default_phases(7, 8)

    assert summary["email_sent"] is False
    assert "kipped" in summary["email_error"]
    assert "no saved email defaults" not in summary["email_error"]


def test_a_turned_off_redcap_export_does_not_run(controller, tmp_path, monkeypatch):
    save_defaults(**{
        KEY_REDCAP_DATA_DIR: str(tmp_path), KEY_REDCAP_DICT_DIR: str(tmp_path),
        KEY_REDCAP_TEMPLATE_DIR: str(tmp_path),
        KEY_REDCAP_EXPORT_DIR: str(tmp_path),
    })
    calls: list[dict] = []
    monkeypatch.setattr(
        controller, "run_redcap_export",
        lambda **kw: calls.append(kw) or {"rows_changed": 0},
    )
    controller.set_step_skipped(STEP_REDCAP, True)

    summary = controller.run_default_phases(8, 9)

    assert calls == []
    assert summary["redcap_summary"] is None


def test_redcap_still_runs_when_it_is_not_turned_off(
    controller, tmp_path, monkeypatch,
):
    """The premise: the test above is not passing for want of directories."""
    save_defaults(**{
        KEY_REDCAP_DATA_DIR: str(tmp_path), KEY_REDCAP_DICT_DIR: str(tmp_path),
        KEY_REDCAP_TEMPLATE_DIR: str(tmp_path),
        KEY_REDCAP_EXPORT_DIR: str(tmp_path),
    })
    calls: list[dict] = []
    monkeypatch.setattr(
        controller, "run_redcap_export",
        lambda **kw: calls.append(kw) or {"rows_changed": 0},
    )

    controller.run_default_phases(8, 9)

    assert len(calls) == 1


def test_a_turned_off_sync_does_not_run(controller, tmp_path, monkeypatch):
    controller.save_sync_defaults([
        {"source": str(tmp_path / "a"), "destination": str(tmp_path / "b")},
    ])
    calls: list = []
    import back_up_sync.file_sync as file_sync

    monkeypatch.setattr(
        file_sync, "sync_pairs", lambda pairs, **kw: calls.append(pairs),
    )
    controller.set_step_skipped(STEP_SYNC, True)

    summary = controller.run_default_phases(9, 10)

    assert calls == []
    assert summary["sync_result"] is None


def test_the_summary_names_the_steps_that_were_turned_off(controller):
    controller.set_step_skipped(STEP_SYNC, True)

    summary = controller.run_default_phases(9, 10)

    assert any("sync" in s.lower() for s in summary["skipped_steps"])


# --------------------------------------------------------------------------
# The readiness gate stops demanding what it will not use
# --------------------------------------------------------------------------

def _import_defaults_saved(tmp_path):
    """The MEM folder and archive the gate demands before anything optional."""
    archive = tmp_path / "archive.csv"
    archive.write_text("ID,Date\n", encoding="utf-8")
    save_defaults(**{
        KEY_MEM_DIR: [str(tmp_path)], KEY_CSV_FILE: str(archive),
    })


def test_turning_both_exports_off_removes_the_export_requirement(
    controller, tmp_path,
):
    _import_defaults_saved(tmp_path)
    save_defaults(**{
        KEY_REDCAP_DATA_DIR: str(tmp_path), KEY_REDCAP_DICT_DIR: str(tmp_path),
        KEY_REDCAP_TEMPLATE_DIR: str(tmp_path),
        KEY_REDCAP_EXPORT_DIR: str(tmp_path),
    })
    controller.set_step_skipped(STEP_EXPORT_CSV, True)
    controller.set_step_skipped(STEP_EXPORT_PDF, True)

    assert controller.check_quick_start_readiness() != "export"
    assert not [m for m in controller.check_defaults_for_range(6, 7) if "Export" in m]


def test_one_export_left_on_still_needs_a_path(controller, tmp_path):
    _import_defaults_saved(tmp_path)
    controller.set_step_skipped(STEP_EXPORT_CSV, True)

    assert controller.check_quick_start_readiness() == "export"


def test_turning_redcap_off_removes_the_redcap_requirement(controller, tmp_path):
    _import_defaults_saved(tmp_path)
    save_defaults(**{KEY_EXPORT_PDF: str(tmp_path)})
    controller.set_step_skipped(STEP_REDCAP, True)

    assert controller.check_quick_start_readiness() is None
    assert controller.check_defaults_for_range(8, 9) == []


def test_redcap_is_still_required_when_it_is_on(controller, tmp_path):
    _import_defaults_saved(tmp_path)
    save_defaults(**{KEY_EXPORT_PDF: str(tmp_path)})

    assert controller.check_quick_start_readiness() == "redcap"


# --------------------------------------------------------------------------
# Where the user can see it
# --------------------------------------------------------------------------

def test_the_settings_page_lists_the_turned_off_steps(tk_root, controller):
    import customtkinter as ctk

    from gui.settings_panel import SettingsPanel

    controller.set_step_skipped(STEP_SYNC, True)
    panel = SettingsPanel(tk_root, controller, on_back=lambda: None)
    try:
        panel.refresh()

        texts = []
        stack = [panel]
        while stack:
            w = stack.pop()
            stack.extend(w.winfo_children())
            if isinstance(w, ctk.CTkLabel):
                texts.append(w.cget("text"))

        assert "Skipped in Quick Start" in texts
        assert any("sync" in t.lower() for t in texts)
    finally:
        panel.destroy()
