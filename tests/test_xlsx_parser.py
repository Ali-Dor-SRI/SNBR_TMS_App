"""Tests for parser/xlsx_parser.py: the QtracP per-stimulus Excel exports.

The recordings are synthetic (see tests/_xlsx_fixtures.py) and built so that
Qtrac's estimators return exact numbers: every MEP is placed on a perfect
log-linear stimulus-response curve, so the weighted regression has nothing to
average and the thresholds come back to the decimal. A real workbook from the
share is checked too, behind ``--realdata``.
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _xlsx_fixtures import (
    ASICF_VALUES,
    REF_THRESHOLD,
    TOKEN,
    TSICI_THRESHOLDS,
    tsici_recording,
    write_tsici_workbook,
    write_waveform_workbook,
    write_workbook,
)
from parser import xlsx_parser as xp


# --------------------------------------------------------------------------
# Tokens and matching
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name, token", [
    ("SNBR-196-TP3C60922B.xlsx", "TP3C60922B"),
    ("snbr-157-FU2-TP3C60715B.xlsx", "TP3C60715B"),
    ("SNBR-080-FU-LCX-TP3C60818A.MEM", "TP3C60818A"),
    ("TP3C60608B.xlsx", "TP3C60608B"),
    ("SNBR-212-RCX_LTA-TP3C60813A.xlsx", "TP3C60813A"),
    ("notes.xlsx", None),
    ("SNBR-045-CSP-RAW-TH2C30816A.MEM", "TH2C30816A"),
])
def test_the_token_is_read_off_the_end_of_the_stem(name, token):
    assert xp.acquisition_token(name) == token


def test_tokens_of_a_coalesced_source_file_cell():
    cell = "SNBR-213-L-FDI-TP3C60821A.MEM; SNBR-213-R-FDI-TP2C60821A.MEM"
    assert xp.tokens_in(cell) == {"TP3C60821A", "TP2C60821A"}
    assert xp.tokens_in(None) == set()
    assert xp.tokens_in(float("nan")) == set()


def test_workbook_for_source_files_matches_by_token(tmp_path):
    path = write_tsici_workbook(tmp_path)
    index = {TOKEN: path}
    assert xp.workbook_for_source_files(index, f"SNBR-192-{TOKEN}.MEM") == path
    assert xp.workbook_for_source_files(index, ["other.MEM", f"x-{TOKEN}.MEM"]) == path
    assert xp.workbook_for_source_files(index, "SNBR-192-TP3C60999Z.MEM") is None


# --------------------------------------------------------------------------
# Telling the export kinds apart
# --------------------------------------------------------------------------

def test_a_per_stimulus_export_is_recognised(tmp_path):
    path = write_tsici_workbook(tmp_path)
    assert xp.workbook_kind(path) == xp.KIND_STIMULI


def test_an_export_without_the_stimulus_sheet_is_amplitude_only(tmp_path):
    path = write_workbook(tmp_path / "x.xlsx", tsici_recording(), sheets=("D", "P", "M1-1"))
    assert xp.workbook_kind(path) == xp.KIND_STIMULI_NO_T


def test_a_csp_waveform_export_is_recognised_and_not_parsed(tmp_path):
    path = write_waveform_workbook(tmp_path / f"SNBR-001-CSP-{TOKEN}.xlsx")
    assert xp.workbook_kind(path) == xp.KIND_WAVEFORMS
    readings = xp.extract_pulse_readings(path)
    assert readings["measures"] == {}
    assert readings["warnings"]


def test_the_index_prefers_the_stimulus_export_over_a_csp_workbook_of_the_same_token(tmp_path):
    """The CSP folder sits next to the others and shares tokens with them."""
    csp = write_waveform_workbook(tmp_path / f"SNBR-001-CSP-{TOKEN}.xlsx")
    full = write_tsici_workbook(tmp_path, name=f"SNBR-001-{TOKEN}.xlsx")
    index = xp.index_workbooks(tmp_path)
    assert index == {TOKEN: full}
    assert csp not in index.values()


def test_the_index_prefers_a_full_export_then_the_newest(tmp_path):
    partial = write_workbook(tmp_path / "SNBR-002-TP3C60102A.xlsx", tsici_recording(), sheets=("D", "P", "M1-1"))
    full = write_workbook(tmp_path / "SNBR-002-test-TP3C60102A.xlsx", tsici_recording())
    older = write_workbook(tmp_path / "SNBR-003-TP3C60103A.xlsx", tsici_recording())
    newer = write_workbook(tmp_path / "SNBR-003-again-TP3C60103A.xlsx", tsici_recording())
    past = time.time() - 3600
    import os
    os.utime(older, (past, past))
    index = xp.index_workbooks(tmp_path)
    assert index["TP3C60102A"] == full, "the export with the stimulus column wins"
    assert index["TP3C60103A"] == newer, "otherwise the newest file wins"
    assert partial not in index.values()


def test_subfolders_are_only_searched_when_asked(tmp_path):
    write_tsici_workbook(tmp_path / "sub", name=f"SNBR-003-{TOKEN}.xlsx")
    assert xp.index_workbooks(tmp_path, recursive=False) == {}
    assert TOKEN in xp.index_workbooks(tmp_path, recursive=True)


def test_a_missing_folder_yields_an_empty_index(tmp_path):
    assert xp.index_workbooks(tmp_path / "nowhere") == {}
    assert xp.index_workbooks([]) == {}


# --------------------------------------------------------------------------
# Qtrac's estimators
# --------------------------------------------------------------------------

def test_the_log_regression_recovers_an_exact_threshold():
    stimuli = [36, 38, 40, 42, 44]
    responses = [0.2 * math.exp(0.5 * (T - 40)) for T in stimuli]
    threshold, se = xp.qtrac_log_regression(stimuli, responses)
    assert threshold == pytest.approx(40.0, abs=1e-9)
    assert se == pytest.approx(0.0, abs=1e-6)


def test_responses_outside_the_usable_range_carry_no_weight():
    """A 5 mV MEP (25x target) and a 0.001 mV one are ignored, as Qtrac does."""
    stimuli = [36, 38, 40, 42, 44, 60, 10]
    responses = [0.2 * math.exp(0.5 * (T - 40)) for T in stimuli[:5]] + [5.0, 0.001]
    threshold, _ = xp.qtrac_log_regression(stimuli, responses)
    assert threshold == pytest.approx(40.0, abs=1e-9)


def test_fewer_than_two_weighted_pulses_gives_nan():
    threshold, se = xp.qtrac_log_regression([40], [0.2])
    assert math.isnan(threshold) and math.isnan(se)


def test_the_geometric_mean_ignores_non_positive_values():
    assert xp.geometric_mean([1.0, 4.0]) == pytest.approx(2.0)
    assert xp.geometric_mean([1.0, 4.0, 0.0, None, float("nan")]) == pytest.approx(2.0)
    assert math.isnan(xp.geometric_mean([]))


# --------------------------------------------------------------------------
# The readings of a recording
# --------------------------------------------------------------------------

@pytest.fixture
def readings(tmp_path):
    return xp.extract_pulse_readings(write_tsici_workbook(tmp_path))


def test_the_recording_is_split_into_its_two_measures(readings):
    assert readings["token"] == TOKEN
    assert readings["kind"] == xp.KIND_STIMULI
    assert set(readings["measures"]) == {"t_sici", "a_sicf"}
    assert readings["warnings"] == []


def test_tsici_values_are_the_regression_thresholds_as_percent_of_the_parallel_rmt(readings):
    block = readings["measures"]["t_sici"]
    assert block["reference"] == pytest.approx(REF_THRESHOLD, abs=1e-9)
    assert block["reference_kind"] == "parallel_rmt200"
    assert block["increment_mode"] is False
    assert set(block["isis"]) == set(TSICI_THRESHOLDS)
    for isi, threshold in TSICI_THRESHOLDS.items():
        assert block["isis"][isi]["value"] == pytest.approx(threshold / REF_THRESHOLD * 100, abs=1e-9)


def test_each_pulse_is_its_test_stimulus_on_the_same_scale(readings):
    pulses = readings["measures"]["t_sici"]["isis"][1.0]["pulses"]
    assert [p["stimulus"] for p in pulses] == [42, 43, 44, 45, 46, 44]
    assert [p["y"] for p in pulses] == pytest.approx([T / REF_THRESHOLD * 100 for T in (42, 43, 44, 45, 46, 44)])
    assert [p["above_target"] for p in pulses] == [False, False, True, True, True, True]
    assert [p["time"] for p in pulses] == sorted(p["time"] for p in pulses), "delivery order"


def test_rejected_traces_are_counted_but_never_used(readings):
    assert readings["skipped_traces"] == {"emg": 3, "artefact": 0, "missing": 0}
    stimuli = [p["stimulus"] for isi in readings["measures"]["t_sici"]["isis"].values() for p in isi["pulses"]]
    assert 99 not in stimuli


def test_asicf_values_are_geometric_means_over_the_test_alone_baseline(readings):
    block = readings["measures"]["a_sicf"]
    assert block["reference"] == pytest.approx(1.0, abs=1e-9), "baseline: the pulses from the one just before the first pair to the last pair"
    assert block["reference_n"] == 3
    assert block["reference_kind"] == "test_alone_baseline"
    for isi, value in ASICF_VALUES.items():
        assert block["isis"][isi]["value"] == pytest.approx(value, abs=1e-9)
    pulses = block["isis"][1.0]["pulses"]
    assert [p["mep"] for p in pulses] == [2.0, 4.0, 8.0]
    assert [p["y"] for p in pulses] == pytest.approx([200.0, 400.0, 800.0])


def test_the_pulse_before_the_phase_is_not_in_the_baseline(tmp_path):
    """Drop the 8 mV outlier that precedes the phase and the baseline must not move."""
    chans = tsici_recording()
    chans[5] = [p for p in chans[5] if p[0] != 12.0]
    readings = xp.extract_pulse_readings(write_workbook(tmp_path / f"a-{TOKEN}.xlsx", chans))
    assert readings["measures"]["a_sicf"]["reference"] == pytest.approx(1.0, abs=1e-9)


def test_stimuli_exported_as_increments_are_restored(tmp_path):
    """Two recordings on the share export the paired T as the increment above the conditioning pulse."""
    path = write_tsici_workbook(tmp_path, increment_mode=True)
    readings = xp.extract_pulse_readings(path)
    block = readings["measures"]["t_sici"]
    assert block["increment_mode"] is True
    assert any("increment" in w for w in readings["warnings"])
    for isi, threshold in TSICI_THRESHOLDS.items():
        assert block["isis"][isi]["value"] == pytest.approx(threshold / REF_THRESHOLD * 100, abs=1e-9)


def test_an_export_without_the_stimulus_sheet_keeps_the_amplitudes_only(tmp_path):
    path = write_workbook(tmp_path / f"b-{TOKEN}.xlsx", tsici_recording(), sheets=("D", "P", "M1-1"))
    readings = xp.extract_pulse_readings(path)
    assert readings["kind"] == xp.KIND_STIMULI_NO_T
    assert readings["measures"]["t_sici"] is None
    assert any("no test-stimulus" in w for w in readings["warnings"])
    assert readings["measures"]["a_sicf"]["isis"][1.0]["value"] == pytest.approx(400.0)


def test_readings_for_source_file_looks_the_token_up(readings):
    by_token = {TOKEN: readings}
    assert xp.readings_for_source_file(by_token, f"SNBR-192-{TOKEN}.MEM") is readings
    assert xp.readings_for_source_file(by_token, "SNBR-192-TP3C60999Z.MEM") is None


# --------------------------------------------------------------------------
# A real workbook from the share
# --------------------------------------------------------------------------

REAL_XLSX = Path(r"Y:\Merged Data\xlsx Data\SNBR-196-TP3C60922B.xlsx")
REAL_MEM_TSICI = {1.0: 97.0, 1.5: 92.4, 2.0: 98.3, 2.5: 97.4, 3.0: 102.5, 3.5: 80.6}
REAL_MEM_ASICF = {1.0: 307.4, 1.3: 529.5, 1.6: 754.4, 1.9: 252.1, 2.2: 122.2, 2.5: 83.5, 2.8: 122.3,
                  3.1: 199.4, 3.4: 281.8, 3.7: 182.8, 4.0: 134.5, 4.3: 91.5, 4.6: 133.3, 4.9: 132.8}


@pytest.mark.realdata
def test_snbr_196_reproduces_its_mem_values():
    if not REAL_XLSX.is_file():
        pytest.skip("share not mounted")
    readings = xp.extract_pulse_readings(REAL_XLSX)
    tsici = readings["measures"]["t_sici"]["isis"]
    for isi, mem in REAL_MEM_TSICI.items():
        assert tsici[isi]["value"] == pytest.approx(mem, abs=0.5)
    asicf = readings["measures"]["a_sicf"]["isis"]
    for isi, mem in REAL_MEM_ASICF.items():
        assert asicf[isi]["value"] == pytest.approx(mem, abs=0.1)
    assert readings["skipped_traces"]["emg"] >= 100
