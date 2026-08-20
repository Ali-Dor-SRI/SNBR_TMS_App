"""Tests for naming exports the user did not name.

Leaving the name box empty is accepted everywhere an export is written, and the
filename is filled in from what the app already knows — the study, the
participant, the graph and the date. Typing a name keeps the old behaviour
untouched, including the ``_<Study>_ID<n>_<date>`` suffix stamped onto it, so
the two schemes never both apply and repeat the same facts twice.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui.controller import AppController
from reports.export_naming import (
    default_dataframe_stem,
    default_graph_stem,
    default_report_stem,
    format_participant,
    sanitize_token,
    unique_path,
)


@pytest.fixture
def controller():
    """A controller holding one participant-visit, with export folders set."""
    df = pd.DataFrame([{
        "ID": 80, "Study": "SNBR", "Date": "18/08/2026",
        "Subject_type": "Patient", "Stimulated_cortex": "L",
        "Muscle": "FDI", "Recorded_side": "R", "source_file": "a.MEM",
    }])
    c = AppController()
    c.set_dataframe(df)
    c.set_selected_participant(80, datetime(2026, 8, 18))
    return c


# --------------------------------------------------------------------------
# The naming rules themselves
# --------------------------------------------------------------------------

def test_graph_name_carries_study_participant_graph_and_visit_date():
    assert default_graph_stem(
        "SNBR", 80, "T-SICI Profile — Right FDI", "18/08/2026",
    ) == "SNBR_080_T-SICI_Profile_Right_FDI_20260818"


def test_graph_name_keeps_whatever_distinguishes_one_figure_from_another():
    """Two figures from one visit must not collide on the same name."""
    a = default_graph_stem("SNBR", 80, "RMT Comparison — RMT50", "18/08/2026")
    b = default_graph_stem("SNBR", 80, "RMT Comparison — RMT200", "18/08/2026")
    assert a != b
    assert a == "SNBR_080_RMT_Comparison_RMT50_20260818"


def test_dataframe_name_is_the_export_date():
    """A frame spans every participant, so no single visit date applies."""
    assert default_dataframe_stem(datetime(2026, 8, 19)) == "df_20260819"


def test_report_name_is_study_and_participant():
    assert default_report_stem("SNBR", 80) == "report_SNBR_080"
    assert default_report_stem("NIALS", 3) == "report_NIALS_003"


def test_participant_number_is_padded_to_match_the_mem_filenames():
    assert format_participant(80) == "080"
    assert format_participant(3) == "003"
    assert format_participant(213) == "213"


def test_missing_parts_do_not_leave_stray_underscores():
    """A participant with no study recorded still gets a usable name."""
    assert default_graph_stem(None, 213, "Visit Timeline", None) == "213_Visit_Timeline"
    assert default_report_stem("", 80) == "report_080"


def test_characters_windows_rejects_are_dropped():
    assert sanitize_token('CSP: 80%/RMT <x>') == "CSP_80%RMT_x"
    assert sanitize_token("  spaced   out  ") == "spaced_out"
    assert sanitize_token(None) == ""


# --------------------------------------------------------------------------
# Collisions
# --------------------------------------------------------------------------

def test_an_auto_named_export_never_overwrites_an_earlier_one(tmp_path):
    """Re-running a report for the same participant on the same day is normal."""
    first = tmp_path / "report_SNBR_080.pdf"
    assert unique_path(first) == first
    first.write_text("x")

    second = unique_path(first)
    assert second.name == "report_SNBR_080_2.pdf"
    second.write_text("x")

    assert unique_path(first).name == "report_SNBR_080_3.pdf"


def test_unique_path_leaves_a_free_name_alone(tmp_path):
    target = tmp_path / "nothing_here.csv"
    assert unique_path(target) == target


# --------------------------------------------------------------------------
# Controller wiring
# --------------------------------------------------------------------------

def test_blank_name_is_filled_in(controller, tmp_path):
    controller._default_export_csv = str(tmp_path / "df" / "df.csv")
    controller._default_export_pdf = str(tmp_path / "reports" / "report")

    csv_out = Path(controller.resolve_export_path("csv"))
    pdf_out = Path(controller.resolve_export_path("pdf"))

    assert csv_out.name == f"{default_dataframe_stem()}.csv"
    assert pdf_out.name == "report_SNBR_080.pdf"
    # ...into the folder the user's saved defaults already point at.
    assert csv_out.parent == tmp_path / "df"
    assert pdf_out.parent == tmp_path / "reports"


def test_a_typed_name_keeps_the_behaviour_it_always_had(controller, tmp_path):
    """Including the stamp — the defaults are what skip it, not the other way."""
    out = Path(controller.resolve_export_path("pdf", str(tmp_path / "myreport.pdf")))
    assert out.name == "myreport_SNBR_ID80_20260818.pdf"


def test_default_names_are_not_stamped_on_top(controller, tmp_path):
    """They already carry the study and participant; stamping would repeat them."""
    controller._default_export_pdf = str(tmp_path / "report")
    out = Path(controller.resolve_export_path("pdf"))
    assert out.name == "report_SNBR_080.pdf"
    assert "ID80" not in out.name


def test_a_box_holding_only_a_folder_gets_the_default_name(controller, tmp_path):
    folder = tmp_path / "picked"
    folder.mkdir()
    out = Path(controller.resolve_export_path("pdf", str(folder)))
    assert out == folder / "report_SNBR_080.pdf"


def test_export_folder_falls_back_to_the_loaded_archive(controller, tmp_path):
    """With no saved default, exports land beside the data they came from."""
    controller._default_export_csv = ""
    controller._csv_path = str(tmp_path / "archive" / "df_old.csv")
    assert controller.default_export_folder("csv") == str(tmp_path / "archive")


def test_graph_filename_offered_for_a_saved_figure(controller):
    name = controller.default_graph_filename("T-SICI Profile — Right FDI")
    assert name == "SNBR_080_T-SICI_Profile_Right_FDI_20260818.png"


def test_study_is_resolved_by_visit_date_not_number_alone():
    """41 archive IDs are shared by different people in different studies."""
    df = pd.DataFrame([
        {"ID": 3, "Study": "NIALS", "Date": "05/09/2022", "source_file": "a.MEM"},
        {"ID": 3, "Study": "SNBR", "Date": "18/08/2026", "source_file": "b.MEM"},
    ])
    c = AppController()
    c.set_dataframe(df)

    c.set_selected_participant(3, datetime(2022, 9, 5))
    assert c.default_export_filename("pdf") == "report_NIALS_003.pdf"

    c.set_selected_participant(3, datetime(2026, 8, 18))
    assert c.default_export_filename("pdf") == "report_SNBR_003.pdf"


# --------------------------------------------------------------------------
# The Export page no longer refuses an empty box
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tk_root():
    """One Tk root for the whole module, or a skip without a display.

    Module-scoped deliberately. Creating and tearing down a Tk root once per
    test intermittently fails to re-initialise Tcl ("Tcl wasn't installed
    properly"), which turned one or two of these into random skips -- a test
    that sometimes does not run is a test that sometimes does not protect.
    """
    import matplotlib
    matplotlib.use("Agg")
    try:
        import customtkinter as ctk
        root = ctk.CTk()
        root.withdraw()
    except Exception as exc:  # pragma: no cover - headless CI
        pytest.skip(f"no display available: {exc}")
    yield root
    root.destroy()


@pytest.fixture
def export_panel(tk_root, controller):
    """A real ExportPanel wired to *controller*.

    Driving the page is the point: these used to be assertions on the text of
    export_panel.py -- 'no path is set' not in source, and a match on
    'resolve_export_target(\\n                    "csv"' including its exact
    indentation. That second one made reformatting the call, and nothing else,
    turn the suite red.
    """
    from gui.export_panel import ExportPanel

    panel = ExportPanel(
        tk_root, controller, on_next=lambda: None, on_back=lambda: None,
    )
    yield panel
    panel.destroy()


def test_an_empty_box_exports_to_the_default_name(export_panel, controller, tmp_path):
    """An empty box means "name it for me", and the export must actually land."""
    controller.set_dataframe(controller.get_dataframe())

    export_panel._csv_check.set(True)
    export_panel._csv_dir.set(str(tmp_path))
    export_panel._csv_name.set("")

    # Called directly rather than through _handle_export's worker thread, so the
    # assertion does not race the export.
    export_panel._export_worker(
        str(tmp_path), "", "", "", csv_wanted=True, pdf_wanted=False,
    )

    written = list(tmp_path.glob("*.csv"))
    assert len(written) == 1, f"expected exactly one CSV, got {written}"
    assert written[0].name == f"{default_dataframe_stem()}.csv"


def test_the_page_does_not_refuse_an_empty_box(export_panel):
    """It used to answer "no path is set" and do nothing."""
    export_panel._csv_check.set(True)
    export_panel._csv_dir.set("")
    export_panel._csv_name.set("")
    export_panel._pdf_check.set(False)

    export_panel._handle_export()
    export_panel.update()

    status = export_panel._status_var.get().casefold()
    assert "no path" not in status, f"the page refused an empty box: {status!r}"
    assert "nothing selected" not in status


def test_clearing_the_box_does_not_untick_the_export(export_panel):
    """The tick is the request now; an empty path only means "name it for me"."""
    for name_var, check_var in (
        (export_panel._csv_name, export_panel._csv_check),
        (export_panel._pdf_name, export_panel._pdf_check),
    ):
        name_var.set("something.csv")
        assert check_var.get(), "typing a name should tick the export"

        name_var.set("")
        assert check_var.get(), (
            "clearing the box unticked the export -- an empty box means "
            "'name it for me', not 'skip this'"
        )


def test_typing_or_browsing_still_ticks_the_export(export_panel):
    """The auto-tick is how a filled box announces itself."""
    export_panel._csv_check.set(False)
    export_panel._csv_dir.set(r"C:\somewhere")
    assert export_panel._csv_check.get()

    export_panel._pdf_check.set(False)
    export_panel._pdf_name.set("report.pdf")
    assert export_panel._pdf_check.get()


# --------------------------------------------------------------------------
# Choosing a folder, with or without a name of your own
# --------------------------------------------------------------------------

def test_a_chosen_folder_alone_gets_the_default_name(controller, tmp_path):
    """The point of the folder box: pick where, let the app decide what."""
    assert Path(controller.resolve_export_target("csv", str(tmp_path))) == (
        tmp_path / f"{default_dataframe_stem()}.csv"
    )
    assert Path(controller.resolve_export_target("pdf", str(tmp_path))) == (
        tmp_path / "report_SNBR_080.pdf"
    )


def test_a_chosen_folder_plus_a_name_keeps_the_suffix(controller, tmp_path):
    out = Path(controller.resolve_export_target("pdf", str(tmp_path), "myreport"))
    assert out == tmp_path / "myreport_SNBR_ID80_20260818.pdf"


def test_a_typed_name_gets_the_extension_it_omitted(controller, tmp_path):
    """There is no save dialog to add it now that the name is a plain box."""
    for kind, ext in (("csv", ".csv"), ("pdf", ".pdf")):
        out = Path(controller.resolve_export_target(kind, str(tmp_path), "mine"))
        assert out.suffix == ext
    # An extension the user did type is not doubled.
    out = Path(controller.resolve_export_target("csv", str(tmp_path), "mine.csv"))
    assert out.name == "mine_SNBR_ID80_20260818.csv"


def test_a_name_without_a_folder_uses_the_default_folder(controller, tmp_path):
    (tmp_path / "df").mkdir()
    controller._default_export_csv = str(tmp_path / "df")
    out = Path(controller.resolve_export_target("csv", "", "mine"))
    assert out.parent == tmp_path / "df"


def test_an_auto_named_export_into_a_chosen_folder_is_uniquified(controller, tmp_path):
    first = Path(controller.resolve_export_target("pdf", str(tmp_path)))
    first.write_text("x", encoding="utf-8")
    second = Path(controller.resolve_export_target("pdf", str(tmp_path)))
    assert second.name == "report_SNBR_080_2.pdf"


def test_graphs_follow_the_same_rules_as_the_other_exports(controller, tmp_path):
    auto = Path(controller.resolve_export_target(
        "graph", str(tmp_path), "", "T-SICI Profile — Right FDI",
    ))
    assert auto == tmp_path / "SNBR_080_T-SICI_Profile_Right_FDI_20260818.png"

    named = Path(controller.resolve_export_target(
        "graph", str(tmp_path), "figure one", "T-SICI Profile",
    ))
    assert named == tmp_path / "figure one_SNBR_ID80_20260818.png"


def test_graphs_borrow_the_reports_default_folder(controller, tmp_path):
    """There is no saved-default key of its own for figures."""
    (tmp_path / "reports").mkdir()
    controller._default_export_pdf = str(tmp_path / "reports")
    assert controller.default_export_folder("graph") == str(tmp_path / "reports")


def test_saved_default_holding_an_old_full_path_shows_only_its_folder():
    """Defaults saved before the split hold a filename; the Folder box drops it."""
    from gui.export_panel import ExportPanel
    assert ExportPanel._folder_of("") == ""
    assert ExportPanel._folder_of(str(Path("C:/out/df/df_20260101.csv"))) == str(
        Path("C:/out/df")
    )
