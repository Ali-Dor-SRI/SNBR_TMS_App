"""Unit tests for the strength-duration (charge-duration) parser."""

import sys
from pathlib import Path

import pandas as pd
import pytest

# Allow imports from the SNBR_TMS_App package root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser.strength_duration_parser import (
    SD_POINTS_COLUMN,
    SD_RHEOBASE_COLUMN,
    SD_TAU_COLUMN,
    charge_duration_r_squared,
    extract_sd_block,
    parse_strength_duration_file,
    strength_duration_current,
    weiss_charge,
)
from parser.mem_parser import output_column_order, parse_mem_file
from processing.df_builder import build_mem_dataframe


# A trimmed charge-duration + derived block in the real Qtrac .MEM layout
# (tab-separated rows). Durations use QtracP's leading-zero-less style (".2")
# and a bare integer ("1"); the derived scalars are keyed by slot number
# (slot 3 = tau, slot 4 = rheobase) and are deliberately out of row order.
_SD_BLOCK_LINES = [
    "  CHARGE DURATION DATA (4.1-5m)",
    "",
    "                    \tDuration (ms)       \t Threshold (mA)     \t  Threshold charge (mA.mS)",
    "QT.1                \t .2                 \t 10.02212           \t 2.004424",
    "QT.2                \t .4                 \t 6.558791           \t 2.623517",
    "QT.3                \t .6                 \t 5.422698           \t 3.253619",
    "QT.4                \t .8                 \t 4.846163           \t 3.87693",
    "QT.5                \t 1                  \t 4.506972           \t 4.506972",
    "",
    "",
    "  DERIVED EXCITABILITY VARIABLES",
    "",
    " 1.                 \t5.267               \tStimulus (mA) for 50% max response",
    " 3.                 \t0.44                \tStrength-duration\\time constant (ms)",
    " 4.                 \t3.129               \tRheobase (mA)",
    " 5.                 \t2.297               \tStimulus-response\\slope",
    "",
    "  EXTRA VARIABLES (add here as required)",
]

# A minimal peripheral-excitability .MEM file (header + SD block).
_SD_MEM_FILE = "\n".join([
    " File:              \tc:\\Qtrac\\Data\\TP3C60429B.QZD",
    " Name:              \tSNBR-170 REGISTRY",
    " Protocol:",
    " Date:              \t29/4/26",
    " Age:               \t40",
    " Sex:               \tM",
    "",
    *_SD_BLOCK_LINES,
    "",
    "  EXTRA WAVEFORMS",
])

# A TMS-style .MEM file with no charge-duration block at all.
_TMS_MEM_FILE = "\n".join([
    "Name: SNBR-005",
    "Date: 01/01/2026",
    "Age: 40",
    "Sex: M",
    "Subject type: Patient",
    "Stim/record: L-APB -> APB",
    "",
    "DERIVED EXCITABILITY VARIABLES",
    "",
    "EXTRA VARIABLES",
    "RMT50 = 50",
    "",
    "EXTRA WAVEFORMS",
])


# ---------------------------------------------------------------------------
# Block extraction
# ---------------------------------------------------------------------------

def test_extract_sd_block_reads_derived_scalars_by_slot():
    block = extract_sd_block(_SD_BLOCK_LINES)
    # Slot 4 = rheobase, slot 3 = tau — read by key, not by row order.
    assert block["rheobase_mA"] == pytest.approx(3.129)
    assert block["tau_sd_ms"] == pytest.approx(0.44)


def test_extract_sd_block_parses_all_points():
    block = extract_sd_block(_SD_BLOCK_LINES)
    assert len(block["points"]) == 5
    # Leading-zero-less ".2" and bare-integer "1" both parse to floats.
    assert block["points"][0]["duration_ms"] == pytest.approx(0.2)
    assert block["points"][-1]["duration_ms"] == pytest.approx(1.0)
    assert block["points"][0]["threshold_mA"] == pytest.approx(10.02212)
    assert block["points"][0]["charge_mA_ms"] == pytest.approx(2.004424)


def test_extract_sd_block_recomputes_missing_charge():
    # A charge-duration table without the third (charge) column: charge should
    # be recomputed as threshold * duration.
    lines = [
        "  CHARGE DURATION DATA",
        "QT.1                \t .5                 \t 4.0",
        "QT.2                \t 1                  \t 3.0",
        "  DERIVED EXCITABILITY VARIABLES",
        " 4.                 \t2.0                 \tRheobase (mA)",
    ]
    block = extract_sd_block(lines)
    assert [p["charge_mA_ms"] for p in block["points"]] == pytest.approx([2.0, 3.0])


def test_extract_sd_block_without_section_returns_empty():
    block = extract_sd_block(["Name: SNBR-1", "Date: 1/1/26", "Age: 30"])
    assert block == {"rheobase_mA": None, "tau_sd_ms": None, "points": []}


def test_extract_sd_block_derived_only_yields_scalars_without_points():
    # Some acquisitions carry the derived scalars but no charge-duration table.
    lines = [
        "  DERIVED EXCITABILITY VARIABLES",
        " 3.                 \t0.5                 \tStrength-duration\\time constant (ms)",
        " 4.                 \t2.5                 \tRheobase (mA)",
        "  EXTRA VARIABLES",
    ]
    block = extract_sd_block(lines)
    assert block["rheobase_mA"] == pytest.approx(2.5)
    assert block["tau_sd_ms"] == pytest.approx(0.5)
    assert block["points"] == []


def test_parse_strength_duration_file_round_trips(tmp_path):
    path = tmp_path / "SNBR-170-NET-PLS-FU1-TP3C60429B.MEM"
    path.write_text(_SD_MEM_FILE, encoding="utf-8")
    block = parse_strength_duration_file(path)
    assert block["rheobase_mA"] == pytest.approx(3.129)
    assert block["tau_sd_ms"] == pytest.approx(0.44)
    assert len(block["points"]) == 5


# ---------------------------------------------------------------------------
# Fit / annotation helpers
# ---------------------------------------------------------------------------

def test_fit_helpers_match_qtrac_relationships():
    # Strength-duration curve: I = rheobase*(1 + tau/d).
    assert strength_duration_current(0.2, 3.129, 0.44) == pytest.approx(10.0128)
    # Weiss's law: Q = rheobase*(d + tau).
    assert weiss_charge(0.2, 3.129, 0.44) == pytest.approx(2.00256)


def test_charge_duration_r_squared_perfect_line_is_one():
    # Points placed exactly on Q = rheobase*(d + tau) → R^2 == 1.
    r, tau = 2.0, 0.5
    points = [
        {"duration_ms": d, "threshold_mA": None, "charge_mA_ms": weiss_charge(d, r, tau)}
        for d in (0.2, 0.5, 1.0)
    ]
    assert charge_duration_r_squared(points, r, tau) == pytest.approx(1.0)


def test_charge_duration_r_squared_on_real_points_is_high():
    block = extract_sd_block(_SD_BLOCK_LINES)
    r2 = charge_duration_r_squared(
        block["points"], block["rheobase_mA"], block["tau_sd_ms"],
    )
    assert r2 is not None and r2 > 0.999


def test_charge_duration_r_squared_undefined_cases_return_none():
    one_point = [{"duration_ms": 0.5, "threshold_mA": 2.0, "charge_mA_ms": 1.0}]
    assert charge_duration_r_squared(one_point, 2.0, 0.5) is None  # < 2 points
    two_points = [
        {"duration_ms": 0.5, "threshold_mA": 2.0, "charge_mA_ms": 1.0},
        {"duration_ms": 1.0, "threshold_mA": 2.0, "charge_mA_ms": 2.0},
    ]
    assert charge_duration_r_squared(two_points, None, 0.5) is None  # no rheobase
    assert charge_duration_r_squared(two_points, 2.0, None) is None  # no tau


# ---------------------------------------------------------------------------
# Schema threading (parser → record → DataFrame)
# ---------------------------------------------------------------------------

def test_parse_mem_file_sets_sd_scalars(tmp_path):
    path = tmp_path / "SNBR-170-NET-PLS-FU1-TP3C60429B.MEM"
    path.write_text(_SD_MEM_FILE, encoding="utf-8")
    record = parse_mem_file(path)
    assert record["ID"] == 170
    assert record[SD_RHEOBASE_COLUMN] == pytest.approx(3.129)
    assert record[SD_TAU_COLUMN] == pytest.approx(0.44)


def test_parse_mem_file_without_sd_block_leaves_scalars_none(tmp_path):
    path = tmp_path / "SNBR-005-TP2C30426B.MEM"
    path.write_text(_TMS_MEM_FILE, encoding="utf-8")
    record = parse_mem_file(path)
    assert record[SD_RHEOBASE_COLUMN] is None
    assert record[SD_TAU_COLUMN] is None


def test_sd_columns_in_output_schema():
    cols = output_column_order()
    assert SD_RHEOBASE_COLUMN in cols
    assert SD_TAU_COLUMN in cols
    assert SD_POINTS_COLUMN in cols


def test_parse_mem_file_stores_sd_points_json(tmp_path):
    import json

    path = tmp_path / "SNBR-170-NET-PLS-FU1-TP3C60429B.MEM"
    path.write_text(_SD_MEM_FILE, encoding="utf-8")
    record = parse_mem_file(path)
    stored = json.loads(record[SD_POINTS_COLUMN])
    assert len(stored) == 5
    assert stored[0]["duration_ms"] == pytest.approx(0.2)
    assert stored[0]["charge_mA_ms"] == pytest.approx(2.004424)


def test_parse_mem_file_without_sd_block_leaves_points_none(tmp_path):
    path = tmp_path / "SNBR-005-TP2C30426B.MEM"
    path.write_text(_TMS_MEM_FILE, encoding="utf-8")
    record = parse_mem_file(path)
    assert record[SD_POINTS_COLUMN] is None


def test_sd_points_survive_dataframe_build_and_csv_roundtrip(tmp_path):
    import json

    mem = tmp_path / "SNBR-170-NET-PLS-FU1-TP3C60429B.MEM"
    mem.write_text(_SD_MEM_FILE, encoding="utf-8")
    record = parse_mem_file(mem)
    record["source_file"] = mem.name
    df = build_mem_dataframe([record])

    # Points survive a CSV round-trip so the plots can be rebuilt from the
    # archived CSV alone (no source .MEM needed).
    csv = tmp_path / "archive.csv"
    df.to_csv(csv, index=False)
    reloaded = pd.read_csv(csv)
    cell = reloaded.loc[reloaded[SD_POINTS_COLUMN].notna(), SD_POINTS_COLUMN].iloc[0]
    points = json.loads(cell)
    assert len(points) == 5
    assert points[-1]["duration_ms"] == pytest.approx(1.0)


def test_sd_scalars_survive_dataframe_build(tmp_path):
    path = tmp_path / "SNBR-170-NET-PLS-FU1-TP3C60429B.MEM"
    path.write_text(_SD_MEM_FILE, encoding="utf-8")
    record = parse_mem_file(path)
    record["source_file"] = path.name
    df = build_mem_dataframe([record])

    assert SD_RHEOBASE_COLUMN in df.columns
    assert SD_TAU_COLUMN in df.columns
    rheobase = pd.to_numeric(df[SD_RHEOBASE_COLUMN], errors="coerce").dropna()
    tau = pd.to_numeric(df[SD_TAU_COLUMN], errors="coerce").dropna()
    assert float(rheobase.iloc[0]) == pytest.approx(3.129)
    assert float(tau.iloc[0]) == pytest.approx(0.44)
