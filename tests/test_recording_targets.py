"""Tests for per-muscle recording targets.

A visit can hold several .MEM files that differ in *what was recorded* rather
than in *which measure was run* — the same T-SICI protocol on left FDI, right
FDI and right TA. Those must stay on separate DataFrame rows, while files that
differ only in measure still coalesce onto one row. These tests cover the
header parsing that identifies a target, the coalescing rules that follow from
it (including the absorption rules for the very common case of a missing side),
and the downstream consequences for the visualization panel and REDCap.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser.mem_parser import output_column_order, parse_mem_file
from parser.recording_target import (
    MUSCLE_COLUMN,
    SIDE_COLUMN,
    extract_sr_sites_target,
    target_label,
)
from processing.df_builder import (
    archive_predates_recording_targets,
    build_combined_dataframe,
    build_combined_dataframe_incremental,
    restrict_participant_to_target,
    target_labels_in,
)


# --------------------------------------------------------------------------
# Fixtures — minimal files in the real Qtrac header layout (leading space and
# a tab before each value, which is what the parsers must cope with).
# --------------------------------------------------------------------------

_CORTICAL = """\
 Name:              \tSNBR-{pid:03d}
 Protocol:          \tQTMSG18S
 Date:              \t{date}
 Age:               \t42
 Sex:               \tM
 TMS Coil:          \tMagStim D70^2
 Stim/record:       \t{stim}
 Muscle:            \t{muscle}
 Subject type:      \tPatient

  DERIVED EXCITABILITY VARIABLES

  EXTRA VARIABLES
{values}

  EXTRA WAVEFORMS
"""

_PERIPHERAL = """\
 Name:              \tSNBR-{pid:03d}
 Protocol:          \tTRONDNF
 Date:              \t{date}
 Age:               \t42
 Sex:               \tM
 S/R sites:         \t{sites}

 STIMULUS-RESPONSE DATA
 Max CMAP  1 ms =  {max_cmap} mV
SR.2                 2                  10.7
SR.98                98                 40.7

  DERIVED EXCITABILITY VARIABLES

  EXTRA VARIABLES
"""

_RMT = "RMT50 = {v}\nRMT200 = 55\nRMT1000 = 60"
_TSICI = "T-SICI(70%)1.0ms = {v}\nT-SICI(70%)2ms = -8.0"


def _cortical(dirpath: Path, name: str, *, pid=1, date="12/1/26", stim="L->R",
              muscle="FDI", values=_RMT.format(v=50)) -> Path:
    path = dirpath / name
    path.write_text(
        _CORTICAL.format(pid=pid, date=date, stim=stim, muscle=muscle, values=values),
        encoding="utf-8",
    )
    return path


def _peripheral(dirpath: Path, name: str, *, pid=1, date="12/1/26",
                sites="R WR-APB", max_cmap="7.5") -> Path:
    path = dirpath / name
    path.write_text(
        _PERIPHERAL.format(pid=pid, date=date, sites=sites, max_cmap=max_cmap),
        encoding="utf-8",
    )
    return path


def _visit_rows(df: pd.DataFrame, pid: int) -> pd.DataFrame:
    return df[pd.to_numeric(df["ID"], errors="coerce") == pid]


# --------------------------------------------------------------------------
# Header parsing
# --------------------------------------------------------------------------

def test_muscle_and_recorded_side_parsed_from_headers(tmp_path):
    path = _cortical(tmp_path, "SNBR-001-TP1C60112A.MEM", stim="L->R", muscle="FDI")
    record = parse_mem_file(path)
    # "L->R" means stimulate the left cortex and record the right side.
    assert record["Stimulated_cortex"] == "L"
    assert record[SIDE_COLUMN] == "R"
    assert record[MUSCLE_COLUMN] == "FDI"


def test_truncated_muscle_value_keeps_its_text(tmp_path):
    # Qtrac marks a truncated field with a trailing '.' ("DI."). Guessing which
    # muscle was meant would be worse than reporting what the file says.
    path = _cortical(tmp_path, "SNBR-001-TP1C60112A.MEM", muscle="DI.")
    assert parse_mem_file(path)[MUSCLE_COLUMN] == "DI"


def test_free_text_stim_record_yields_no_side(tmp_path):
    # Older files write "L-R." with no arrow; that must not be read as a side.
    path = _cortical(tmp_path, "SNBR-001-TP1C60112A.MEM", stim="L-R.")
    assert parse_mem_file(path)[SIDE_COLUMN] is None


@pytest.mark.parametrize("value, expected", [
    ("R CP-TA", ("TA", "R")),
    ("L WR-APB", ("APB", "L")),
    ("MEDIAN/APB", ("APB", None)),
    ("Wrist-FDI", ("FDI", None)),         # leading "Wrist" is not a side
    ("R Uln Wr-ADM", ("ADM", "R")),
    ("Wrist?-APB?", ("APB", None)),
    ("A:rL->R.APB.PA", ("APB", None)),    # trailing "PA" is not a muscle
    ("Knee CP-TA", ("TA", None)),
])
def test_sr_sites_variants(value, expected):
    assert extract_sr_sites_target(f"S/R sites: {value}") == expected


def test_peripheral_file_gets_its_target_from_sr_sites(tmp_path):
    path = _peripheral(tmp_path, "NRVC60112A.MEM", sites="R WR-APB")
    record = parse_mem_file(path)
    assert record[MUSCLE_COLUMN] == "APB"
    assert record[SIDE_COLUMN] == "R"


# --------------------------------------------------------------------------
# Coalescing
# --------------------------------------------------------------------------

def test_same_target_different_measures_coalesce(tmp_path):
    """Scenario 2: one measure per file, same recording — combine into one row."""
    _cortical(tmp_path, "SNBR-001-A-TP1C60112A.MEM", values=_RMT.format(v=50))
    _cortical(tmp_path, "SNBR-001-B-TP1C60112B.MEM", values=_TSICI.format(v=-10.0))

    rows = _visit_rows(build_combined_dataframe(tmp_path), 1)
    assert len(rows) == 1
    row = rows.iloc[0]
    assert row["RMT50"] == 50
    assert row["T_SICI_1.0ms"] == 90.0
    assert row[MUSCLE_COLUMN] == "FDI" and row[SIDE_COLUMN] == "R"


def test_same_measure_different_muscles_stay_separate(tmp_path):
    """Scenario 1: same measure on two muscles — one row each, no overwriting."""
    _cortical(tmp_path, "SNBR-001-A-TP1C60112A.MEM",
              muscle="FDI", values=_RMT.format(v=50))
    _cortical(tmp_path, "SNBR-001-B-TP1C60112B.MEM",
              muscle="TA", values=_RMT.format(v=70))

    rows = _visit_rows(build_combined_dataframe(tmp_path), 1)
    assert len(rows) == 2
    by_muscle = dict(zip(rows[MUSCLE_COLUMN], rows["RMT50"]))
    assert by_muscle == {"FDI": 50, "TA": 70}


def test_same_muscle_both_sides_stay_separate(tmp_path):
    _cortical(tmp_path, "SNBR-001-A-TP1C60112A.MEM",
              stim="L->R", values=_RMT.format(v=50))
    _cortical(tmp_path, "SNBR-001-B-TP1C60112B.MEM",
              stim="R->L", values=_RMT.format(v=70))

    rows = _visit_rows(build_combined_dataframe(tmp_path), 1)
    assert len(rows) == 2
    assert dict(zip(rows[SIDE_COLUMN], rows["RMT50"])) == {"R": 50, "L": 70}


def test_sideless_file_absorbs_into_the_visits_known_side(tmp_path):
    """Most cortical files carry a muscle but no Stim/record line at all."""
    _cortical(tmp_path, "SNBR-001-A-TP1C60112A.MEM",
              stim="L->R", values=_RMT.format(v=50))
    _cortical(tmp_path, "SNBR-001-B-TP1C60112B.MEM",
              stim="", values=_TSICI.format(v=-10.0))

    rows = _visit_rows(build_combined_dataframe(tmp_path), 1)
    assert len(rows) == 1, "a side-less file must not fragment the visit"
    row = rows.iloc[0]
    assert row[SIDE_COLUMN] == "R"
    assert row["RMT50"] == 50 and row["T_SICI_1.0ms"] == 90.0


def test_unattributable_sideless_file_becomes_its_own_target(tmp_path):
    """With two sides recorded, a side-less file cannot be attributed to either."""
    _cortical(tmp_path, "SNBR-001-A-TP1C60112A.MEM",
              stim="L->R", values=_RMT.format(v=50))
    _cortical(tmp_path, "SNBR-001-B-TP1C60112B.MEM",
              stim="R->L", values=_RMT.format(v=70))
    _cortical(tmp_path, "SNBR-001-C-TP1C60112C.MEM",
              stim="", values=_RMT.format(v=90))

    rows = _visit_rows(build_combined_dataframe(tmp_path), 1)
    assert len(rows) == 3
    orphan = rows[rows[SIDE_COLUMN].isna()]
    assert len(orphan) == 1
    assert orphan.iloc[0]["RMT50"] == 90, "its data must survive, not be dropped"


def test_peripheral_row_joins_the_cortical_row_of_the_same_target(tmp_path):
    """The peripheral recording of a muscle belongs with its cortical one."""
    _cortical(tmp_path, "SNBR-001-A-TP1C60112A.MEM",
              stim="L->R", muscle="APB", values=_RMT.format(v=50))
    _cortical(tmp_path, "SNBR-001-B-TP1C60112B.MEM",
              stim="L->R", muscle="TA", values=_RMT.format(v=70))
    _peripheral(tmp_path, "NRVC60112A.MEM", sites="R WR-APB", max_cmap="7.5")
    _peripheral(tmp_path, "NRVC60112B.MEM", sites="R CP-TA", max_cmap="3.2")

    rows = _visit_rows(build_combined_dataframe(tmp_path), 1)
    assert len(rows) == 2
    pairs = dict(zip(rows[MUSCLE_COLUMN], rows["SR_max_cmap_1ms"]))
    assert pairs == pytest.approx({"APB": 7.5, "TA": 3.2})


def test_single_target_visit_absorbs_an_unidentified_peripheral_row(tmp_path):
    """One recording in the visit — everything collapses, as it always has."""
    _cortical(tmp_path, "SNBR-001-A-TP1C60112A.MEM", values=_RMT.format(v=50))
    _peripheral(tmp_path, "NRVC60112A.MEM", sites="Unknown site", max_cmap="7.5")

    rows = _visit_rows(build_combined_dataframe(tmp_path), 1)
    assert len(rows) == 1
    assert rows.iloc[0]["SR_max_cmap_1ms"] == pytest.approx(7.5)
    assert rows.iloc[0]["RMT50"] == 50


def test_different_dates_never_coalesce(tmp_path):
    _cortical(tmp_path, "SNBR-001-A-TP1C60112A.MEM", date="12/1/26")
    _cortical(tmp_path, "SNBR-001-B-TP1C60113A.MEM", date="13/1/26")
    assert len(_visit_rows(build_combined_dataframe(tmp_path), 1)) == 2


# --------------------------------------------------------------------------
# Target helpers
# --------------------------------------------------------------------------

def test_target_labels_are_ordered_hand_muscles_first():
    rows = pd.DataFrame({
        MUSCLE_COLUMN: ["TA", "FDI", "FDI", "APB", None],
        SIDE_COLUMN: ["R", "R", "L", "L", None],
    })
    assert target_labels_in(rows) == [
        "Left APB", "Left FDI", "Right FDI", "Right TA",
    ]


def test_target_label_falls_back_to_whichever_half_is_known():
    assert target_label("FDI", "R") == "Right FDI"
    assert target_label("FDI", None) == "FDI"
    assert target_label(None, "R") == "Right"
    assert target_label(None, None) == ""


def test_restricting_to_a_target_leaves_the_cohort_pooled():
    """Reference groups stay pooled across muscles — only the participant is cut."""
    df = pd.DataFrame({
        "ID": [1, 1, 2, 3],
        MUSCLE_COLUMN: ["FDI", "TA", "TA", None],
        SIDE_COLUMN: ["R", "R", "R", None],
    })
    out = restrict_participant_to_target(df, 1, "Right FDI")
    assert sorted(out["ID"].tolist()) == [1, 2, 3]
    assert out[out["ID"] == 1][MUSCLE_COLUMN].tolist() == ["FDI"]


def test_restricting_keeps_the_participants_visit_level_rows():
    # A row with no muscle holds visit-level data (CMAP/MUNIX), not a muscle's.
    df = pd.DataFrame({
        "ID": [1, 1, 1],
        MUSCLE_COLUMN: ["FDI", "TA", None],
        SIDE_COLUMN: ["R", "R", None],
    })
    out = restrict_participant_to_target(df, 1, "Right FDI")
    assert len(out) == 2
    assert out[MUSCLE_COLUMN].isna().sum() == 1


# --------------------------------------------------------------------------
# Archive staleness
# --------------------------------------------------------------------------

def test_archive_without_muscle_columns_is_flagged():
    assert archive_predates_recording_targets({"ID", "Date", "source_file"}) is True
    assert archive_predates_recording_targets(
        {"ID", "Date", "source_file", MUSCLE_COLUMN, SIDE_COLUMN}
    ) is False
    # No archive at all is not "stale" — there is nothing to rebuild.
    assert archive_predates_recording_targets(set()) is False


def test_stale_archive_is_rebuilt_rather_than_backfilled(tmp_path):
    """Row identity cannot be backfilled: the merged values are already gone."""
    mem_dir = tmp_path / "mem"
    mem_dir.mkdir()
    _cortical(mem_dir, "SNBR-001-A-TP1C60112A.MEM",
              muscle="FDI", values=_RMT.format(v=50))
    _cortical(mem_dir, "SNBR-001-B-TP1C60112B.MEM",
              muscle="TA", values=_RMT.format(v=70))

    # An archive from before recording targets: one merged row, no muscle columns.
    archive = tmp_path / "SNBR_MEM_parsed_2026-01-02.csv"
    legacy = pd.DataFrame([{
        **{c: None for c in output_column_order()},
        "Study": "SNBR", "ID": 1, "Date": "12/01/2026", "RMT50": 50,
        "source_file": "SNBR-001-A-TP1C60112A.MEM; SNBR-001-B-TP1C60112B.MEM",
    }]).drop(columns=[MUSCLE_COLUMN, SIDE_COLUMN])
    legacy.to_csv(archive, index=False)

    df = build_combined_dataframe_incremental(mem_dir=mem_dir, existing_csv=archive)
    assert df.attrs["target_rebuild"] is True
    rows = _visit_rows(df, 1)
    assert len(rows) == 2, "the merged legacy row must be split, not kept"
    assert dict(zip(rows[MUSCLE_COLUMN], rows["RMT50"])) == {"FDI": 50, "TA": 70}


def test_current_archive_still_takes_the_incremental_path(tmp_path):
    """Sanity: an up-to-date archive is not force-rebuilt."""
    mem_dir = tmp_path / "mem"
    mem_dir.mkdir()
    _cortical(mem_dir, "SNBR-001-A-TP1C60112A.MEM", values=_RMT.format(v=50))

    first = build_combined_dataframe_incremental(mem_dir=mem_dir)
    archive = tmp_path / "SNBR_MEM_parsed_2026-01-02.csv"
    first[output_column_order()].to_csv(archive, index=False)

    second = build_combined_dataframe_incremental(
        mem_dir=mem_dir, existing_csv=archive,
    )
    assert second.attrs["target_rebuild"] is False
    assert second.attrs["reused_existing"] is True


# --------------------------------------------------------------------------
# Controller — selection, availability, per-target figures, titles
# --------------------------------------------------------------------------

def _multi_target_controller(tmp_path):
    """A visit recorded from two cortical targets plus one peripheral muscle."""
    from gui.controller import AppController

    _cortical(tmp_path, "SNBR-001-A-TP1C60112A.MEM",
              stim="L->R", muscle="FDI", values=_RMT.format(v=50))
    _cortical(tmp_path, "SNBR-001-B-TP1C60112B.MEM",
              stim="R->L", muscle="FDI", values=_RMT.format(v=70))
    _peripheral(tmp_path, "NRVC60112A.MEM", sites="R CP-TA", max_cmap="3.2")

    controller = AppController()
    controller.set_dataframe(build_combined_dataframe(tmp_path))
    controller._mem_paths = []
    controller.set_selected_participant(1, datetime(2026, 1, 12))
    return controller


def test_controller_lists_the_visits_targets(tmp_path):
    controller = _multi_target_controller(tmp_path)
    assert controller.get_target_options(1, datetime(2026, 1, 12)) == [
        "Left FDI", "Right FDI", "Right TA",
    ]


def test_one_figure_per_selected_target(tmp_path):
    controller = _multi_target_controller(tmp_path)
    controller.set_selected_targets(["Left FDI", "Right FDI"])
    figures, _axes, data = controller.generate_figure("rmt_over_time", None)
    assert isinstance(figures, list)
    assert data["figure_targets"] == ["Left FDI"] * len(
        [t for t in data["figure_targets"] if t == "Left FDI"]
    ) + ["Right FDI"] * len(
        [t for t in data["figure_targets"] if t == "Right FDI"]
    )
    assert set(data["figure_targets"]) == {"Left FDI", "Right FDI"}
    assert len(data["figure_data"]) == len(figures)


def test_targets_without_data_are_skipped_not_fatal(tmp_path):
    """The leg here has only a peripheral recording — no RMT to draw."""
    controller = _multi_target_controller(tmp_path)
    controller.set_selected_targets(["Left FDI", "Right FDI", "Right TA"])
    _figs, _axes, data = controller.generate_figure("rmt_over_time", None)
    assert "Right TA" not in set(data["figure_targets"])


def test_visit_level_graphs_render_once_for_all_targets(tmp_path):
    controller = _multi_target_controller(tmp_path)
    controller.set_selected_targets(["Left FDI", "Right FDI"])
    figs, _axes, _data = controller.generate_figure("visit_table", None)
    assert not isinstance(figs, list) or len(figs) == 1


def test_availability_holds_when_any_selected_target_has_data(tmp_path):
    from gui.visualization_panel import GRAPH_REGISTRY

    controller = _multi_target_controller(tmp_path)
    # Right TA alone carries the stimulus-response curve and no RMT.
    controller.set_selected_targets(["Right TA"])
    assert controller.has_data_for_graph("stimulus_response", None)
    assert not controller.has_data_for_graph("rmt_over_time", None)

    controller.set_selected_targets(["Left FDI", "Right TA"])
    availability = controller.graph_availability_map(GRAPH_REGISTRY)
    assert availability["stimulus_response"]
    assert availability["rmt_over_time"], "the FDI target still has RMT data"


def test_title_names_the_target_only_when_the_visit_has_several(tmp_path):
    controller = _multi_target_controller(tmp_path)
    controller.set_selected_targets(["Right FDI"])
    assert controller._build_graph_title("profile", "t_sici").endswith("Right FDI")


def test_title_omits_the_target_for_a_single_recording(tmp_path):
    from gui.controller import AppController

    _cortical(tmp_path, "SNBR-001-A-TP1C60112A.MEM", values=_RMT.format(v=50))
    controller = AppController()
    controller.set_dataframe(build_combined_dataframe(tmp_path))
    controller.set_selected_participant(1, datetime(2026, 1, 12))
    controller.set_selected_targets(["Right FDI"])
    # One recording in the visit: the muscle belongs on the report's title
    # page, not repeated on every plot.
    assert controller._target_suffix() == ""
    assert not controller._build_graph_title("profile", "t_sici").endswith("Right FDI")


def test_report_title_page_names_every_recorded_muscle(tmp_path):
    from reports.report_builder import _recording_targets_text

    df = build_combined_dataframe(_prepared_two_muscle_dir(tmp_path))
    assert _recording_targets_text(_visit_rows(df, 1)) == "Right FDI, Right TA"


def _prepared_two_muscle_dir(tmp_path) -> Path:
    _cortical(tmp_path, "SNBR-001-A-TP1C60112A.MEM",
              muscle="FDI", values=_RMT.format(v=50))
    _cortical(tmp_path, "SNBR-001-B-TP1C60112B.MEM",
              muscle="TA", values=_RMT.format(v=70))
    return tmp_path


# --------------------------------------------------------------------------
# REDCap — one record per participant-visit
# --------------------------------------------------------------------------

def test_redcap_dedup_prefers_the_hand_recording():
    from reports.redcap_exporter import _non_exported_targets

    py_snbr = pd.DataFrame({
        "ID": [1, 1],
        "date_iso": ["2026-01-12", "2026-01-12"],
        MUSCLE_COLUMN: ["TA", "FDI"],
        SIDE_COLUMN: ["R", "R"],
        "_target_rank": [1, 0],
    })
    assert _non_exported_targets(py_snbr) == ["Right TA"]

    kept = (
        py_snbr.sort_values(["_target_rank"])
        .drop_duplicates(subset=["ID", "date_iso"], keep="first")
    )
    assert kept[MUSCLE_COLUMN].tolist() == ["FDI"]
