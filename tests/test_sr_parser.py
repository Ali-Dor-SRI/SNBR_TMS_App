"""Unit tests for the stimulus-response (peripheral recruitment) parser."""

import sys
from pathlib import Path

import pandas as pd
import pytest

# Allow imports from the SNBR_TMS_App package root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser.sr_parser import (
    SR_CURVE_COLUMN,
    SR_MAX_COLUMN,
    extract_sr_block,
    parse_sr_file,
)
from parser.mem_parser import output_column_order, parse_mem_file
from processing.df_builder import build_mem_dataframe


# A trimmed stimulus-response block in the real Qtrac .MEM layout (tab-separated
# rows, "Max CMAP 1 ms" reference line, followed by the next section).
_SR_BLOCK_LINES = [
    " STIMULUS-RESPONSE DATA (Repeat 2/2, 6.2-5.4m)",
    "",
    "Values are those recorded",
    "",
    " Max CMAP  1 ms =  3.544922 mV",
    "",
    "                    \t% Max               \tStimulus(2)",
    "SR.2                \t 2                  \t 10.74938",
    "SR.4                \t 4                  \t 15.99429",
    "SR.50               \t 50                 \t 27.94535",
    "SR.98               \t 98                 \t 40.70754",
    "",
    "",
    "  CHARGE DURATION DATA (3.7-4.7m)",
    "",
    "QT.1                \t .2                 \t 53.93436           \t 10.78687",
]

# A minimal peripheral-excitability .MEM file (header + SR block).
_SR_MEM_FILE = "\n".join([
    " File:              \tc:\\Qtrac\\Data\\TP3C60630A.QZD",
    " Name:              \tSNBR-164 REGISTRY",
    " Protocol:",
    " Date:              \t30/6/26",
    " Age:               \t54",
    " Sex:               \tF",
    *_SR_BLOCK_LINES,
    "",
    "",
    "  DERIVED EXCITABILITY VARIABLES",
    "",
    " 6.                 \t3.545               \tPeak response\\(mV)",
    "",
    "  EXTRA VARIABLES (add here as required)",
    "",
    "MScPeak(mV) = 2.98",
])

# A TMS-style .MEM file with no stimulus-response block at all.
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


def test_extract_sr_block_parses_reference_and_curve():
    block = extract_sr_block(_SR_BLOCK_LINES)
    assert block["max_cmap_1ms"] == pytest.approx(3.544922)
    # Four SR.n rows; the trailing QT.1 charge-duration row is excluded.
    assert len(block["curve"]) == 4
    assert [p["percent_max"] for p in block["curve"]] == [2.0, 4.0, 50.0, 98.0]
    assert block["curve"][0]["stimulus_mA"] == pytest.approx(10.74938)
    assert block["curve"][-1]["stimulus_mA"] == pytest.approx(40.70754)


def test_extract_sr_block_computes_absolute_cmap_in_mv():
    block = extract_sr_block(_SR_BLOCK_LINES)
    # CMAP size (mV) = percent_max / 100 * Max CMAP 1 ms.
    by_pct = {p["percent_max"]: p["cmap_mV"] for p in block["curve"]}
    assert by_pct[50.0] == pytest.approx(0.5 * 3.544922)
    assert by_pct[98.0] == pytest.approx(0.98 * 3.544922)


def test_extract_sr_block_without_section_returns_empty():
    block = extract_sr_block(["Name: SNBR-1", "Date: 1/1/26", "Age: 30"])
    assert block == {"max_cmap_1ms": None, "curve": []}


def test_parse_sr_file_round_trips(tmp_path):
    path = tmp_path / "SNBR-164-MT-FU1-TP3C60630A.MEM"
    path.write_text(_SR_MEM_FILE, encoding="utf-8")
    block = parse_sr_file(path)
    assert block["max_cmap_1ms"] == pytest.approx(3.544922)
    assert len(block["curve"]) == 4


def test_parse_mem_file_sets_sr_max_scalar(tmp_path):
    path = tmp_path / "SNBR-164-MT-FU1-TP3C60630A.MEM"
    path.write_text(_SR_MEM_FILE, encoding="utf-8")
    record = parse_mem_file(path)
    assert record["ID"] == 164
    assert record["Date"] == "30/06/2026"
    assert record[SR_MAX_COLUMN] == pytest.approx(3.544922)


def test_parse_mem_file_without_sr_block_leaves_scalar_none(tmp_path):
    path = tmp_path / "SNBR-005-TP2C30426B.MEM"
    path.write_text(_TMS_MEM_FILE, encoding="utf-8")
    record = parse_mem_file(path)
    assert record[SR_MAX_COLUMN] is None


def test_sr_column_in_output_schema():
    assert SR_MAX_COLUMN in output_column_order()
    assert SR_CURVE_COLUMN in output_column_order()


def test_parse_mem_file_stores_sr_curve_json(tmp_path):
    import json

    path = tmp_path / "SNBR-164-MT-FU1-TP3C60630A.MEM"
    path.write_text(_SR_MEM_FILE, encoding="utf-8")
    record = parse_mem_file(path)
    curve = json.loads(record[SR_CURVE_COLUMN])
    assert len(curve) == 4
    assert [p["percent_max"] for p in curve] == [2.0, 4.0, 50.0, 98.0]


def test_sr_scalar_survives_dataframe_build(tmp_path):
    path = tmp_path / "SNBR-164-MT-FU1-TP3C60630A.MEM"
    path.write_text(_SR_MEM_FILE, encoding="utf-8")
    record = parse_mem_file(path)
    record["source_file"] = path.name
    df = build_mem_dataframe([record])
    assert SR_MAX_COLUMN in df.columns
    value = pd.to_numeric(df[SR_MAX_COLUMN], errors="coerce").dropna()
    assert len(value) == 1
    assert float(value.iloc[0]) == pytest.approx(3.544922)
