"""Controller tests for SR/SD graph availability and CSV-backed rendering.

Covers two fixes:

* Peripheral SR/SD data lives on cortex-less rows, so a single-cortex selection
  must NOT hide (grey out) those graphs — availability is cortex-independent.
* The SR curve and SD points are persisted in the DataFrame/CSV, so the plots
  render from the stored columns alone, without re-reading the source .MEM
  (fast, and works from an archived CSV even when the source files are gone).
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser.mem_parser import initialize_record
from parser.sr_parser import SR_CURVE_COLUMN, SR_MAX_COLUMN
from parser.strength_duration_parser import (
    SD_POINTS_COLUMN,
    SD_RHEOBASE_COLUMN,
    SD_TAU_COLUMN,
)
from processing.df_builder import build_mem_dataframe
from gui.controller import AppController
from gui.visualization_panel import GRAPH_REGISTRY

_SR_CURVE = [
    {"percent_max": 2.0, "stimulus_mA": 10.7, "cmap_mV": 0.07},
    {"percent_max": 50.0, "stimulus_mA": 27.9, "cmap_mV": 0.87},
    {"percent_max": 98.0, "stimulus_mA": 40.7, "cmap_mV": 1.71},
]
_SD_POINTS = [
    {"duration_ms": 0.2, "threshold_mA": 10.02212, "charge_mA_ms": 2.004424},
    {"duration_ms": 0.4, "threshold_mA": 6.558791, "charge_mA_ms": 2.623517},
    {"duration_ms": 0.6, "threshold_mA": 5.422698, "charge_mA_ms": 3.253619},
    {"duration_ms": 0.8, "threshold_mA": 4.846163, "charge_mA_ms": 3.87693},
    {"duration_ms": 1.0, "threshold_mA": 4.506972, "charge_mA_ms": 4.506972},
]


def _visit_df():
    """One visit: an 'L' cortical row + a cortex-less peripheral SR/SD row."""
    cortical = initialize_record()
    cortical.update(
        ID=999, Date="01/01/2026", Stimulated_cortex="L", RMT50=50.0,
        source_file="SNBR-999-BSL-A.MEM",
    )
    peripheral = initialize_record()
    peripheral.update({
        "ID": 999, "Date": "01/01/2026", "Stimulated_cortex": None,
        SR_MAX_COLUMN: 1.747233, SD_RHEOBASE_COLUMN: 3.129, SD_TAU_COLUMN: 0.44,
        SR_CURVE_COLUMN: json.dumps(_SR_CURVE),
        SD_POINTS_COLUMN: json.dumps(_SD_POINTS),
        "source_file": "SNBR-999-NET-B.MEM",
    })
    return build_mem_dataframe([cortical, peripheral])


def _controller(mem_paths):
    c = AppController()
    c.set_dataframe(_visit_df())
    c._mem_paths = mem_paths
    c._mem_recursive = False
    c.set_selected_participant(999, datetime(2026, 1, 1))
    return c


_SD_KEYS = ("stimulus_response", "strength_duration_curve", "charge_duration_weiss")


def test_single_cortex_selection_does_not_hide_peripheral_graphs():
    # The SR/SD data is on the cortex-less row; selecting the 'L' cortex (the
    # only cortical option) must not grey the peripheral graphs out.
    c = _controller(mem_paths=[])
    c.set_selected_cortex("L")
    avail = c.graph_availability_map(GRAPH_REGISTRY)
    for key in _SD_KEYS:
        assert bool(avail[key]), key
        assert bool(c.has_data_for_graph(key, None)), key


def test_cortex_filter_still_applies_to_cortical_graphs():
    # Sanity: cortex filtering still works for cortical graphs. Selecting a
    # cortex with no rows hides RMT (which lives only on the 'L' row).
    c = _controller(mem_paths=[])
    c.set_selected_cortex("R")  # no 'R' rows exist for this visit
    assert not c.has_data_for_graph("rmt_over_time", None)


def test_sr_sd_render_from_stored_columns_without_files():
    # No MEM paths configured at all — the figures must still build from the
    # SR_curve / SD_points columns (proves CSV-only rendering + no slow scan).
    c = _controller(mem_paths=[])
    c.set_selected_cortex("L")
    for key in _SD_KEYS:
        entry = next(e for e in GRAPH_REGISTRY if e.key == key)
        figs, _axes, plot_data = c.generate_figure(entry.graph_type, entry.measure)
        assert isinstance(figs, Figure), key
        assert isinstance(plot_data, dict)

    # The charge-duration plot's R^2 comes from the stored points + scalars.
    _f, _a, weiss = c.generate_figure("charge_duration_weiss", None)
    assert weiss["r_squared"] == pytest.approx(1.0, abs=1e-3)


_PERIPHERAL_MEM = """\
Name: SNBR-777
Date: 01/01/2026
Age: 45
Sex: F

 STIMULUS-RESPONSE DATA
 Max CMAP  1 ms =  3.5 mV
SR.2                 2                  10.7
SR.98                98                 40.7

  CHARGE DURATION DATA
QT.1                 .2                 10.0               2.0
QT.2                 1                  4.5                4.5

  DERIVED EXCITABILITY VARIABLES

 3.                  0.44               Strength-duration
 4.                  3.1                Rheobase

  EXTRA VARIABLES
"""


def test_fast_load_of_stale_archive_then_export_does_not_poison_schema(tmp_path):
    """A fast 'archive as-is' load of a stale CSV, then export, must NOT yield a
    CSV that looks schema-current. Otherwise the staleness check would never
    fire again and SR/SD would stay silently unavailable forever. The empty,
    newly-synthesised columns are dropped on export so it re-parses next load."""
    from processing.df_builder import (
        build_combined_dataframe_incremental,
        csv_schema_is_current,
    )

    mem_dir = tmp_path / "mem"
    mem_dir.mkdir()
    (mem_dir / "SNBR-777-NET-A.MEM").write_text(_PERIPHERAL_MEM, encoding="utf-8")

    full = build_combined_dataframe_incremental(mem_dir=mem_dir)
    stale = tmp_path / "stale.csv"
    full.drop(columns=[
        SR_MAX_COLUMN, SR_CURVE_COLUMN,
        SD_RHEOBASE_COLUMN, SD_TAU_COLUMN, SD_POINTS_COLUMN,
    ]).to_csv(stale, index=False)
    assert csv_schema_is_current(stale) is False

    c = AppController()
    c._csv_path = str(stale)
    c._cmap_paths = []
    c.load_csv_dataframe(merge_cmap=False)
    assert c._schema_stale is True

    exported = tmp_path / "exported.csv"
    c.get_export_dataframe().to_csv(exported, index=False)
    # Poison prevented: the re-exported archive is still recognised as stale.
    assert csv_schema_is_current(exported) is False


def test_export_poison_prevention_survives_csv_path_change(tmp_path):
    """The export drop uses a load-time snapshot of the archive header, so
    repointing the CSV path (or the file being replaced) after a stale fast-load
    cannot reintroduce the poison."""
    from processing.df_builder import (
        build_combined_dataframe_incremental,
        csv_schema_is_current,
    )
    from parser.mem_parser import output_column_order

    mem_dir = tmp_path / "mem"
    mem_dir.mkdir()
    (mem_dir / "SNBR-777-NET-A.MEM").write_text(_PERIPHERAL_MEM, encoding="utf-8")
    full = build_combined_dataframe_incremental(mem_dir=mem_dir)
    stale = tmp_path / "stale.csv"
    full.drop(columns=[
        SR_MAX_COLUMN, SR_CURVE_COLUMN,
        SD_RHEOBASE_COLUMN, SD_TAU_COLUMN, SD_POINTS_COLUMN,
    ]).to_csv(stale, index=False)
    current = tmp_path / "current.csv"
    full[output_column_order()].to_csv(current, index=False)

    c = AppController()
    c._csv_path = str(stale)
    c._cmap_paths = []
    c.load_csv_dataframe(merge_cmap=False)
    assert c._schema_stale is True

    # Repoint the CSV path to a schema-current archive WITHOUT reloading the
    # frame (mirrors a back-navigate + re-select + forward page-jump).
    c._csv_path = str(current)
    exported = tmp_path / "exported.csv"
    c.get_export_dataframe().to_csv(exported, index=False)
    assert csv_schema_is_current(exported) is False
