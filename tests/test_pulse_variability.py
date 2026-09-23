"""The individual pulses behind the profile graphs, end to end.

Three pieces have to hold together: the Import Settings page takes the folder
of QtracP Excel exports (below the MEM folders, with the same subfolder and
save-as-default controls), the Visualization page offers the choice of drawing
the individual pulses and saves it with the rest of the page's defaults, and
the profile graphs honour it when the recording's export can be found --
falling back to the .MEM values, and saying so, when it cannot.

The widget tests walk the built tree on the session-wide Tk root (see
tests/conftest.py) rather than reading source. The export is synthetic (see
tests/_xlsx_fixtures.py); its token matches the fixture DataFrame's
``source_file`` so the controller's matching is exercised for real.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _xlsx_fixtures import TOKEN, write_tsici_workbook
from core.user_settings import (
    KEY_PLOT_PULSES,
    KEY_SELECTED_GRAPHS,
    KEY_XLSX_DIR,
    KEY_XLSX_RECURSIVE,
    load_defaults,
    save_defaults,
)
from gui.controller import AppController
from parser.mem_parser import initialize_record
from processing.df_builder import build_mem_dataframe
from processing.pulse_overlay import OVERLAY_GID

SUBJECT = 192
VISIT = "20/05/2026"
PROFILE_KEY = "profile__t_sici"
PROFILE_LABEL = "T-SICI Profile"
SAVE_BOX_TEXT = "Save as default"
MEM_LABEL = "MEM Files Directories *"
XLSX_LABEL = "Qtrac Excel Exports Directories"
CSP_LABEL = "CSP MEM Files Directories"


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

def _rec(pid, date, values: dict, *, source_file):
    r = initialize_record()
    r.update(
        Study="SNBR", ID=pid, Date=date, Subject_type="Patient",
        Stimulated_cortex="L", Muscle="FDI", Recorded_side="R",
        source_file=source_file,
    )
    for isi, value in values.items():
        r[f"T_SICI_{isi}"] = value
    return r


def _df():
    """One visit whose source file carries the fixture workbook's token, plus a cohort."""
    records = [
        _rec(SUBJECT, VISIT, {"1.0ms": 110.0, "1.5ms": 90.0}, source_file=f"SNBR-192-{TOKEN}.MEM"),
    ]
    for pid in (10, 11):
        records.append(_rec(pid, "01/01/2026", {"1.0ms": 100.0, "1.5ms": 95.0},
                            source_file=f"SNBR-{pid:03d}-TP3C6010{pid}A.MEM"))
    return build_mem_dataframe(records)


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


@pytest.fixture
def controller():
    c = AppController()
    c.set_dataframe(_df())
    dates = c.get_visit_dates(SUBJECT)
    c.set_selected_participant(SUBJECT, dates[-1])
    return c


@pytest.fixture
def xlsx_dir(tmp_path):
    folder = tmp_path / "xlsx"
    write_tsici_workbook(folder)
    return folder


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


def _labels(widget):
    import customtkinter as ctk

    return [w.cget("text") for w in _walk(widget) if isinstance(w, ctk.CTkLabel)]


def _checkboxes(widget, text):
    import customtkinter as ctk

    return [w for w in _walk(widget) if isinstance(w, ctk.CTkCheckBox) and w.cget("text") == text]


def _pulse_checkbox(widget):
    import customtkinter as ctk

    for w in _walk(widget):
        if isinstance(w, ctk.CTkCheckBox) and "individual pulses" in w.cget("text"):
            return w
    return None


def _overlay_artists(axis):
    return [a for a in list(axis.get_lines()) + list(axis.texts) if a.get_gid() == OVERLAY_GID]


# --------------------------------------------------------------------------
# Settings and controller plumbing
# --------------------------------------------------------------------------

def test_the_new_defaults_are_exposed_unset():
    defaults = load_defaults()
    assert defaults[KEY_XLSX_DIR] == ""
    assert defaults[KEY_XLSX_RECURSIVE] is False
    assert defaults[KEY_PLOT_PULSES] is False


def test_the_controller_round_trips_the_excel_folders(controller, tmp_path):
    controller.set_paths(
        mem_path=[str(tmp_path)], xlsx_path=[str(tmp_path / "a"), str(tmp_path / "b")],
        xlsx_recursive=True,
    )
    paths = controller.get_paths()
    assert paths["xlsx_path"] == [str(tmp_path / "a"), str(tmp_path / "b")]
    assert paths["xlsx_recursive"] is True
    assert controller.has_xlsx_folders()


def test_a_missing_excel_folder_is_named_by_validation(controller, tmp_path):
    controller.set_paths(mem_path=[str(tmp_path)], xlsx_path=[str(tmp_path / "gone")])
    errors = controller.validate_paths()
    assert any("Excel" in e and "gone" in e for e in errors)


def test_the_excel_folder_is_optional(controller, tmp_path):
    controller.set_paths(mem_path=[str(tmp_path)])
    assert controller.validate_paths() == []
    assert not controller.has_xlsx_folders()


def test_saved_folders_are_applied_at_startup(tmp_path):
    save_defaults(**{KEY_XLSX_DIR: [str(tmp_path)], KEY_XLSX_RECURSIVE: True})
    c = AppController()
    assert c.get_paths()["xlsx_path"] == [str(tmp_path)]
    assert c.get_paths()["xlsx_recursive"] is True


# --------------------------------------------------------------------------
# The Import Settings page
# --------------------------------------------------------------------------

@pytest.fixture
def file_panel(tk_root, controller):
    from gui.file_panel import FilePanel

    panel = FilePanel(tk_root, controller, on_next=lambda: None, on_back=lambda: None)
    panel.update()
    yield panel
    panel.destroy()


def test_the_excel_field_sits_directly_below_the_mem_field(file_panel):
    labels = _labels(file_panel)
    assert XLSX_LABEL in labels
    assert labels.index(MEM_LABEL) < labels.index(XLSX_LABEL) < labels.index(CSP_LABEL)


def test_the_excel_field_has_the_same_controls_as_the_other_folder_fields(file_panel):
    # four folder fields, each with its own subfolder toggle; five save boxes with the archive's
    assert len(_checkboxes(file_panel, "Include subfolders")) == 4
    assert len(_checkboxes(file_panel, SAVE_BOX_TEXT)) == 5
    assert any("CSP waveform workbooks" in t for t in _labels(file_panel))


def test_the_archive_field_says_which_csv_it_is(file_panel):
    labels = _labels(file_panel)
    assert "Archive CSV File" not in labels
    assert any(t.startswith("Archive CSV") and "data frame" in t for t in labels)


def test_next_passes_the_excel_folder_to_the_controller_and_saves_it(file_panel, controller, tmp_path):
    xlsx = tmp_path / "xlsx"
    xlsx.mkdir()
    file_panel._dir_rows["mem"][0]["var"].set(str(tmp_path))
    file_panel._dir_rows["xlsx"][0]["var"].set(str(xlsx))
    file_panel._recursive_vars["xlsx"].set(True)
    file_panel._save_xlsx.set(True)

    file_panel._handle_next()

    assert controller.get_paths()["xlsx_path"] == [str(xlsx)]
    assert controller.get_paths()["xlsx_recursive"] is True
    saved = load_defaults()
    assert saved[KEY_XLSX_DIR] == [str(xlsx)]
    assert saved[KEY_XLSX_RECURSIVE] is True


def test_leaving_the_save_box_unticked_keeps_the_previous_default(file_panel, controller, tmp_path):
    save_defaults(**{KEY_XLSX_DIR: ["previous"]})
    file_panel._dir_rows["mem"][0]["var"].set(str(tmp_path))
    file_panel._dir_rows["xlsx"][0]["var"].set(str(tmp_path))

    file_panel._handle_next()

    assert load_defaults()[KEY_XLSX_DIR] == ["previous"]


# --------------------------------------------------------------------------
# The Visualization page
# --------------------------------------------------------------------------

@pytest.fixture
def vis_panel(tk_root, controller):
    from gui.visualization_panel import VisualizationPanel

    panel = VisualizationPanel(tk_root, controller, on_next=lambda: None, on_back=lambda: None)
    panel.update()
    yield panel
    panel.destroy()


def _no_background_generation(panel, monkeypatch):
    monkeypatch.setattr(panel, "_generate_missing_worker", lambda *a, **k: None)


def test_the_page_offers_the_pulse_choice_at_the_top(vis_panel):
    box = _pulse_checkbox(vis_panel)
    assert box is not None, "no tick box for the individual pulses"
    assert "Excel" in box.cget("text")


def test_ticking_the_choice_updates_the_controller(vis_panel, controller):
    box = _pulse_checkbox(vis_panel)
    box.select()
    vis_panel._on_pulse_toggled()
    assert controller.get_pulse_variability() is True
    box.deselect()
    vis_panel._on_pulse_toggled()
    assert controller.get_pulse_variability() is False


def test_with_no_excel_folder_the_page_says_so(vis_panel, controller, monkeypatch):
    monkeypatch.setattr(vis_panel, "_show_current", lambda: None)
    save_defaults(**{KEY_PLOT_PULSES: True})

    vis_panel.refresh()

    assert vis_panel._pulse_var.get() is True
    assert controller.get_pulse_variability() is True
    assert "No Qtrac Excel export folder" in vis_panel._pulse_note_var.get()


def test_with_a_folder_set_the_note_is_clear(vis_panel, controller, xlsx_dir, monkeypatch):
    monkeypatch.setattr(vis_panel, "_show_current", lambda: None)
    controller.set_paths(mem_path=[str(xlsx_dir.parent)], xlsx_path=[str(xlsx_dir)])
    save_defaults(**{KEY_PLOT_PULSES: True})

    vis_panel.refresh()

    assert vis_panel._pulse_note_var.get() == ""


def test_save_as_default_records_the_pulse_choice(vis_panel, controller, monkeypatch):
    _no_background_generation(vis_panel, monkeypatch)
    vis_panel._check_vars[PROFILE_KEY].set(True)
    _checkboxes(vis_panel, SAVE_BOX_TEXT)[0].select()
    _pulse_checkbox(vis_panel).select()

    vis_panel._handle_next()

    assert load_defaults()[KEY_PLOT_PULSES] is True
    assert controller.get_pulse_variability_default() is True

    _pulse_checkbox(vis_panel).deselect()
    vis_panel._handle_next()

    assert controller.get_pulse_variability_default() is False


def test_leaving_save_unticked_keeps_the_saved_pulse_choice(vis_panel, controller, monkeypatch):
    _no_background_generation(vis_panel, monkeypatch)
    save_defaults(**{KEY_PLOT_PULSES: True})
    vis_panel._check_vars[PROFILE_KEY].set(True)

    vis_panel._handle_next()

    assert controller.get_pulse_variability_default() is True


# --------------------------------------------------------------------------
# The profile graph
# --------------------------------------------------------------------------

def _profile(controller):
    result = controller.generate_figure("profile", "t_sici")
    figure = result[0]
    return figure, figure.axes[0]


def test_the_profile_draws_the_pulses_when_the_export_matches(controller, xlsx_dir):
    controller.set_paths(mem_path=[str(xlsx_dir.parent)], xlsx_path=[str(xlsx_dir)])
    controller.set_pulse_variability(True)

    figure, axis = _profile(controller)

    artists = _overlay_artists(axis)
    assert artists, "no pulse overlay was drawn"
    # twelve pulses across the two ISIs, each with its tether, plus the footnote
    dots = [a for a in artists if getattr(a, "get_marker", lambda: None)() == "o"]
    assert len(dots) == 12
    legend = axis.get_legend()
    labels = [t.get_text() for t in legend.get_texts()]
    assert any("Paired pulse" in t for t in labels)
    assert any("Tether" in t for t in labels)
    note = legend.get_title().get_text()
    assert TOKEN in note and "6 pulses per ISI" in note and "RMT200" in note
    outcome = controller.get_last_pulse_overlay()
    assert outcome["drawn"] is True
    assert outcome["workbooks"] == [str(xlsx_dir / f"SNBR-192-{TOKEN}.xlsx")]


def test_the_profile_falls_back_when_no_export_matches(controller, tmp_path):
    other = tmp_path / "xlsx"
    write_tsici_workbook(other, name="SNBR-999-TP3C60999Z.xlsx")
    controller.set_paths(mem_path=[str(tmp_path)], xlsx_path=[str(other)])
    controller.set_pulse_variability(True)

    figure, axis = _profile(controller)

    assert _overlay_artists(axis) == []
    assert axis.get_legend() is None
    outcome = controller.get_last_pulse_overlay()
    assert outcome["drawn"] is False
    assert "no Excel export matches" in outcome["reason"]


def test_the_profile_falls_back_when_no_folder_is_set(controller):
    controller.set_pulse_variability(True)

    figure, axis = _profile(controller)

    assert _overlay_artists(axis) == []
    assert controller.get_last_pulse_overlay()["reason"] == "no Excel export folder selected"


def test_the_profile_falls_back_when_the_folder_holds_only_csp_workbooks(controller, tmp_path):
    from _xlsx_fixtures import write_waveform_workbook

    folder = tmp_path / "xlsx"
    folder.mkdir()
    write_waveform_workbook(folder / f"SNBR-192-CSP-{TOKEN}.xlsx")
    controller.set_paths(mem_path=[str(tmp_path)], xlsx_path=[str(folder)])
    controller.set_pulse_variability(True)

    figure, axis = _profile(controller)

    assert _overlay_artists(axis) == []
    assert controller.get_last_pulse_overlay()["reason"] == "no per-stimulus Excel exports found"


def test_with_the_choice_off_the_export_is_not_used(controller, xlsx_dir):
    controller.set_paths(mem_path=[str(xlsx_dir.parent)], xlsx_path=[str(xlsx_dir)])
    controller.set_pulse_variability(False)

    figure, axis = _profile(controller)

    assert _overlay_artists(axis) == []
    assert controller.get_last_pulse_overlay() is None


def test_the_pulses_sit_at_the_values_the_workbook_implies(controller, xlsx_dir):
    """Dots are the test stimuli as % of the parallel RMT: 42..46 of 40 -> 105..115."""
    controller.set_paths(mem_path=[str(xlsx_dir.parent)], xlsx_path=[str(xlsx_dir)])
    controller.set_pulse_variability(True)

    figure, axis = _profile(controller)

    dots = [a for a in axis.get_lines() if a.get_gid() == OVERLAY_GID and a.get_marker() == "o"]
    ys = sorted(round(float(a.get_ydata()[0]), 6) for a in dots if 0.8 < float(a.get_xdata()[0]) < 1.2)
    assert ys == pytest.approx(sorted([T / 40 * 100 for T in (42, 43, 44, 45, 46, 44)]))
    lo, hi = axis.get_ylim()
    assert lo <= min(ys) and hi >= max(ys), "the axis must widen to fit the pulses"


# --------------------------------------------------------------------------
# Quick Start
# --------------------------------------------------------------------------

def test_quick_start_honours_the_saved_choice_and_names_the_fallbacks(controller):
    save_defaults(**{KEY_PLOT_PULSES: True, KEY_SELECTED_GRAPHS: [PROFILE_KEY]})

    summary = controller.run_default_phases(5, 6)

    assert summary["pulse_variability"] is True
    assert summary["graphs"] == [PROFILE_LABEL]
    assert summary["pulse_overlay_missing"] == [PROFILE_LABEL]
    assert summary["pulse_overlay_drawn"] == []
    assert summary["figure_count"] >= 1, "the profile is still built from the .MEM values"


def test_quick_start_draws_the_pulses_when_the_export_is_there(controller, xlsx_dir):
    save_defaults(**{KEY_PLOT_PULSES: True, KEY_SELECTED_GRAPHS: [PROFILE_KEY]})
    controller.set_paths(mem_path=[str(xlsx_dir.parent)], xlsx_path=[str(xlsx_dir)])

    summary = controller.run_default_phases(5, 6)

    assert summary["pulse_overlay_drawn"] == [PROFILE_LABEL]
    assert summary["pulse_overlay_missing"] == []


def test_quick_start_with_the_choice_unset_asks_for_no_pulses(controller, xlsx_dir):
    save_defaults(**{KEY_SELECTED_GRAPHS: [PROFILE_KEY]})
    controller.set_paths(mem_path=[str(xlsx_dir.parent)], xlsx_path=[str(xlsx_dir)])

    summary = controller.run_default_phases(5, 6)

    assert summary["pulse_variability"] is False
    assert summary["pulse_overlay_drawn"] == []
    assert summary["pulse_overlay_missing"] == []


def test_quick_start_phase_one_applies_the_saved_excel_folder(xlsx_dir):
    save_defaults(**{"mem_dir": [str(xlsx_dir.parent)], KEY_XLSX_DIR: [str(xlsx_dir)]})
    c = AppController()

    summary = c.run_default_phases(1, 2)

    assert c.get_paths()["xlsx_path"] == [str(xlsx_dir)]
    assert summary["xlsx_dir"] == str(xlsx_dir)


def test_the_summary_names_what_was_drawn_and_what_fell_back():
    from gui.welcome_panel import graph_summary_lines

    lines = graph_summary_lines({
        "graphs": ["A"], "figure_count": 2, "pulse_variability": True,
        "pulse_overlay_drawn": ["T-SICI Profile"], "pulse_overlay_missing": ["A-SICF Profile"],
    })
    assert any("drawn on: T-SICI Profile" in line for line in lines)
    assert any("A-SICF Profile" in line and ".MEM" in line for line in lines)


def test_the_summary_stays_quiet_when_pulses_were_not_asked_for():
    from gui.welcome_panel import graph_summary_lines

    assert graph_summary_lines({"graphs": ["A"], "figure_count": 2}) == ["1. A", "Total figures: 2"]


# --------------------------------------------------------------------------
# Smoke: the report still renders with the pulses in it
# --------------------------------------------------------------------------

def test_the_pdf_report_renders_a_profile_with_pulses(controller, xlsx_dir, tmp_path):
    from reports.pdf_layout import ReportItem
    from reports.pdf_renderer import render_figures_to_pdf

    controller.set_paths(mem_path=[str(xlsx_dir.parent)], xlsx_path=[str(xlsx_dir)])
    controller.set_pulse_variability(True)
    figure, axis = _profile(controller)
    assert _overlay_artists(axis)

    out = render_figures_to_pdf(
        [ReportItem(figure=figure, caption="T-SICI", section_key=PROFILE_KEY)],
        tmp_path / "report.pdf",
    )

    assert Path(out).is_file() and Path(out).stat().st_size > 1000


def test_the_settings_page_shows_the_new_defaults(tk_root, controller, tmp_path):
    import customtkinter as ctk

    from gui.settings_panel import SettingsPanel

    save_defaults(**{KEY_XLSX_DIR: [str(tmp_path)], KEY_PLOT_PULSES: True})
    panel = SettingsPanel(tk_root, controller, on_back=lambda: None)
    try:
        panel.refresh()
        texts = [w.cget("text") for w in _walk(panel) if isinstance(w, ctk.CTkLabel)]
        assert any("Excel" in t and str(tmp_path) in t for t in texts)
        assert any("Individual pulses" in t and t.endswith("on") for t in texts)
        assert any(t.startswith("Archive CSV") for t in texts)
    finally:
        panel.destroy()
