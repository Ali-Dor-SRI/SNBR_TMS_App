"""Regression tests for ``build_combined_dataframe_incremental``.

Covers the case where a MEM file is present in the archive CSV but has since
been deleted from the MEM folder — the stale row must NOT survive a re-parse.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser.mem_parser import output_column_order
from processing.df_builder import build_combined_dataframe_incremental


_MIN_MEM = """\
Name: SNBR-999
Date: 01/01/2026
Age: 40
Sex: M
Subject type: Patient
Stim/record: L-APB -> APB

DERIVED EXCITABILITY VARIABLES

EXTRA VARIABLES
RMT50 = 50
RMT200 = 55
RMT1000 = 60
T-SICI(70%)1.0ms = -10.0

EXTRA WAVEFORMS
"""


def _write_mem(dirpath: Path, filename: str, pid: int) -> None:
    content = _MIN_MEM.replace("SNBR-999", f"SNBR-{pid:03d}")
    (dirpath / filename).write_text(content, encoding="utf-8")


_MIN_CSP = """\
Name: SNBR-999
Date: 13/02/2024
Age: 40
Sex: M
Subject type: Patient
Stim/record: R-APB -> APB

DERIVED EXCITABILITY VARIABLES

EXTRA VARIABLES
CSPs-100(ms) = 50
CSPe-100(ms) = 150

EXTRA WAVEFORMS
"""


def _write_csp(dirpath: Path, filename: str, pid: int, date: str) -> None:
    content = (
        _MIN_CSP.replace("SNBR-999", f"SNBR-{pid:03d}").replace("13/02/2024", date)
    )
    (dirpath / filename).write_text(content, encoding="utf-8")


def test_deleted_mem_file_does_not_persist_in_incremental_reparse(tmp_path):
    mem_dir = tmp_path / "mem"
    mem_dir.mkdir()

    # Two participants in the initial MEM folder.
    _write_mem(mem_dir, "SNBR-031-TP1C50101A.MEM", 31)
    _write_mem(mem_dir, "SNBR-032-TH2C30628A.MEM", 32)

    # First pass: full parse, export to CSV (simulating the archive).
    df1 = build_combined_dataframe_incremental(mem_dir=mem_dir)
    assert set(df1["ID"]) == {31, 32}

    csv_path = tmp_path / "SNBR_MEM_parsed_2026-01-02.csv"
    df1[output_column_order()].to_csv(csv_path, index=False)

    # Delete participant 32's MEM file.
    (mem_dir / "SNBR-032-TH2C30628A.MEM").unlink()

    # Second pass: reparse incrementally against the archive CSV. The stale
    # row for participant 32 must be dropped — before the fix it survived
    # because the fast-path "nothing changed" gate never detected deletions.
    df2 = build_combined_dataframe_incremental(
        mem_dir=mem_dir,
        existing_csv=csv_path,
    )
    assert 32 not in set(df2["ID"].dropna().astype(int)), (
        "Deleted MEM file's row leaked through the incremental fast path"
    )
    assert set(df2["ID"].dropna().astype(int)) == {31}


def test_no_changes_takes_fast_path(tmp_path):
    """Sanity check: when nothing on disk changed, the fast path still fires."""
    mem_dir = tmp_path / "mem"
    mem_dir.mkdir()
    _write_mem(mem_dir, "SNBR-031-TP1C50101A.MEM", 31)

    df1 = build_combined_dataframe_incremental(mem_dir=mem_dir)
    csv_path = tmp_path / "SNBR_MEM_parsed_2026-01-02.csv"
    df1[output_column_order()].to_csv(csv_path, index=False)

    df2 = build_combined_dataframe_incremental(
        mem_dir=mem_dir,
        existing_csv=csv_path,
    )
    assert df2.attrs.get("reused_existing") is True
    assert df2.attrs.get("new_files_parsed") == 0


# A peripheral (nerve-excitability) MEM carrying SR + charge-duration + derived
# blocks, so a re-parse populates the SR/SD columns.
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


def test_schema_stale_archive_triggers_full_reparse(tmp_path):
    """An archive predating the SR/SD columns must be fully re-parsed so those
    columns get populated — not kept NaN for already-archived participants."""
    from parser.sr_parser import SR_CURVE_COLUMN, SR_MAX_COLUMN
    from parser.strength_duration_parser import (
        SD_POINTS_COLUMN, SD_RHEOBASE_COLUMN, SD_TAU_COLUMN,
    )

    mem_dir = tmp_path / "mem"
    mem_dir.mkdir()
    (mem_dir / "SNBR-777-NET-A.MEM").write_text(_PERIPHERAL_MEM, encoding="utf-8")

    # A current-schema archive really does carry the SR/SD data.
    df1 = build_combined_dataframe_incremental(mem_dir=mem_dir)
    assert pd.to_numeric(df1[SR_MAX_COLUMN], errors="coerce").notna().any()

    # Simulate an archive exported before the SR/SD columns existed.
    stale_cols = [
        SR_MAX_COLUMN, SR_CURVE_COLUMN,
        SD_RHEOBASE_COLUMN, SD_TAU_COLUMN, SD_POINTS_COLUMN,
    ]
    stale_csv = tmp_path / "stale_archive.csv"
    df1.drop(columns=stale_cols).to_csv(stale_csv, index=False)

    # Reload against the stale archive: it must be rebuilt, repopulating SR/SD.
    df2 = build_combined_dataframe_incremental(mem_dir=mem_dir, existing_csv=stale_csv)
    assert df2.attrs.get("schema_rebuilt") is True
    assert df2.attrs.get("reused_existing") is False
    assert pd.to_numeric(df2[SR_MAX_COLUMN], errors="coerce").notna().any()
    assert pd.to_numeric(df2[SD_RHEOBASE_COLUMN], errors="coerce").notna().any()
    assert df2[SD_POINTS_COLUMN].notna().any()


def test_current_schema_archive_does_not_trigger_rebuild(tmp_path):
    """A current-schema archive with no disk changes reuses as-is — no costly
    full reparse (guards the schema-stale fix against over-triggering)."""
    mem_dir = tmp_path / "mem"
    mem_dir.mkdir()
    (mem_dir / "SNBR-777-NET-A.MEM").write_text(_PERIPHERAL_MEM, encoding="utf-8")

    df1 = build_combined_dataframe_incremental(mem_dir=mem_dir)
    csv_path = tmp_path / "current_archive.csv"
    df1[output_column_order()].to_csv(csv_path, index=False)

    df2 = build_combined_dataframe_incremental(mem_dir=mem_dir, existing_csv=csv_path)
    assert df2.attrs.get("reused_existing") is True
    assert not df2.attrs.get("schema_rebuilt")


def test_schema_rebuild_preserves_csp_when_folder_absent(tmp_path):
    """A schema rebuild must NOT drop archived CSP data even when the CSP folder
    is unavailable — CSP values are merged from a separate folder and are not
    reproduced by parse_mem_file, so a destructive rebuild would lose them."""
    from parser.CSP_parser import CSP_VALUE_COLUMNS
    from parser.sr_parser import SR_CURVE_COLUMN, SR_MAX_COLUMN
    from parser.strength_duration_parser import (
        SD_POINTS_COLUMN, SD_RHEOBASE_COLUMN, SD_TAU_COLUMN,
    )

    mem_dir = tmp_path / "mem"
    mem_dir.mkdir()
    csp_dir = tmp_path / "csp"
    csp_dir.mkdir()
    (mem_dir / "SNBR-777-NET-A.MEM").write_text(_PERIPHERAL_MEM, encoding="utf-8")
    _write_csp(csp_dir, "SNBR-777-CSP-A.MEM", 777, "01/01/2026")

    # Archive built WITH the CSP folder carries both CSP and SR/SD.
    full = build_combined_dataframe_incremental(mem_dir=mem_dir, csp_dir=csp_dir)
    csp_cols = [c for c in CSP_VALUE_COLUMNS if c in full.columns]
    csp_before = pd.to_numeric(full[csp_cols].stack(), errors="coerce").notna().sum()
    assert csp_before > 0

    # Simulate an archive predating SR/SD, then reload WITHOUT the CSP folder.
    stale_csv = tmp_path / "stale.csv"
    full.drop(columns=[
        SR_MAX_COLUMN, SR_CURVE_COLUMN, SD_RHEOBASE_COLUMN, SD_TAU_COLUMN, SD_POINTS_COLUMN,
    ]).to_csv(stale_csv, index=False)

    out = build_combined_dataframe_incremental(
        mem_dir=mem_dir, csp_dir=None, existing_csv=stale_csv,
    )
    assert out.attrs.get("schema_rebuilt") is True
    csp_after = pd.to_numeric(out[csp_cols].stack(), errors="coerce").notna().sum()
    assert csp_after == csp_before, "CSP data was lost during the schema rebuild"
    # SR/SD were still backfilled onto the archived rows.
    assert pd.to_numeric(out[SD_RHEOBASE_COLUMN], errors="coerce").notna().any()
    assert out[SD_POINTS_COLUMN].notna().any()


def test_csv_schema_is_current_helper(tmp_path):
    from processing.df_builder import csv_schema_is_current
    from parser.sr_parser import SR_MAX_COLUMN

    mem_dir = tmp_path / "mem"
    mem_dir.mkdir()
    (mem_dir / "SNBR-777-NET-A.MEM").write_text(_PERIPHERAL_MEM, encoding="utf-8")
    df = build_combined_dataframe_incremental(mem_dir=mem_dir)

    current = tmp_path / "current.csv"
    df[output_column_order()].to_csv(current, index=False)
    assert csv_schema_is_current(current) is True

    stale = tmp_path / "stale.csv"
    df.drop(columns=[SR_MAX_COLUMN]).to_csv(stale, index=False)
    assert csv_schema_is_current(stale) is False

    # Missing only "Study" is NOT stale — load_existing_csv synthesises it.
    no_study = tmp_path / "no_study.csv"
    df.drop(columns=["Study"]).to_csv(no_study, index=False)
    assert csv_schema_is_current(no_study) is True

    assert csv_schema_is_current(tmp_path / "does_not_exist.csv") is False
    assert csv_schema_is_current(None) is False


def test_new_csp_only_repeat_visit_is_detected_and_included(tmp_path):
    """A returning participant whose follow-up is a CSP-only recording (no new
    .MEM file) must still enter the DataFrame.

    Regression: the incremental fast path keyed only on .MEM filenames, so a
    new CSP file was treated as "nothing changed" and the CSP re-merge was
    skipped — the new visit silently vanished. This is the exact failure the
    "check for new files" mode hit for repeat visits.
    """
    mem_dir = tmp_path / "mem"
    mem_dir.mkdir()
    # CSP folder nested under the MEM folder, mirroring the real lab layout
    # (and therefore excluded from the MEM scan).
    csp_dir = mem_dir / "CSP"
    csp_dir.mkdir()

    # Visit 1: a normal MEM file (header date 01/01/2026).
    _write_mem(mem_dir, "SNBR-005-TP2C30426B.MEM", 5)
    df1 = build_combined_dataframe_incremental(mem_dir=mem_dir, csp_dir=csp_dir)
    assert (pd.to_numeric(df1["ID"], errors="coerce") == 5).sum() == 1

    csv_path = tmp_path / "SNBR_MEM_parsed_2026-01-02.csv"
    df1[output_column_order()].to_csv(csv_path, index=False)

    # Repeat visit 2 adds ONLY a CSP file, on a different date.
    _write_csp(csp_dir, "CSP-RAW-SNBR-005-TMSC40213A.MEM", 5, "13/02/2024")

    df2 = build_combined_dataframe_incremental(
        mem_dir=mem_dir, csp_dir=csp_dir, existing_csv=csv_path,
    )
    id5 = df2[pd.to_numeric(df2["ID"], errors="coerce") == 5]

    assert df2.attrs.get("reused_existing") is False, (
        "fast path swallowed a new CSP-only follow-up visit"
    )
    assert df2.attrs.get("new_csp_files_merged") == 1
    assert "13/02/2024" in set(id5["Date"]), (
        "new CSP-only repeat visit did not enter the DataFrame"
    )
    assert len(id5) == 2

    # And the visit is now persisted: re-parsing against a CSV that already
    # records the CSP file must return to the fast path (no perpetual re-merge).
    csv_path2 = tmp_path / "SNBR_MEM_parsed_2026-02-01.csv"
    df2[output_column_order()].to_csv(csv_path2, index=False)
    df3 = build_combined_dataframe_incremental(
        mem_dir=mem_dir, csp_dir=csp_dir, existing_csv=csv_path2,
    )
    assert df3.attrs.get("reused_existing") is True
    assert df3.attrs.get("new_csp_files_merged") == 0
