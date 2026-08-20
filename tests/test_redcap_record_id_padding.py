"""New REDCap records carry a zero-padded participant ID.

A record REDCap has never seen is created by the import, so this export decides
what its ``record_id`` will be forever. It is written zero-padded to three
digits -- ``001``, ``010``, ``100`` -- matching how the lab numbers participants
everywhere else: the ``.MEM`` filenames, the report titles, the export names.

An **existing** record is deliberately left alone. Its ``record_id`` is REDCap's
own primary key for a row that is already there, so rewriting ``7`` as ``007``
would stop naming the same record and the import would miss its target instead
of updating it. That asymmetry is the whole point of the rule and is what these
tests pin.

Only ``reports/redcap_exporter.py`` is affected. ``processing/redcap_mapper.py``
renames ``ID`` to ``record_id`` for new and existing rows alike, so padding
there would pad both; and ``scripts/generate_redcap_import.py`` skips any
participant with no REDCap match (``if len(rc_match) == 0: continue``), so it
never emits a new record at all.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser.mem_parser import TSICI_ISIS, initialize_record
from reports.redcap_exporter import (
    RECORD_ID_WIDTH,
    format_record_id,
    generate_redcap_import,
)

VISIT_DATE = "15/04/2026"
VISIT_DATE_ISO = "2026-04-15"


# ---------------------------------------------------------------------------
# The rule itself
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pid,expected", [
    (1, "001"),
    (10, "010"),
    (100, "100"),
    (7, "007"),
    (80, "080"),
    (999, "999"),
])
def test_a_new_record_id_is_padded_to_three_digits(pid, expected):
    assert format_record_id(pid, is_new=True) == expected


@pytest.mark.parametrize("pid", [1, 10, 100, 999])
def test_an_existing_record_id_is_left_as_an_integer(pid):
    """Padding an existing key would stop it naming the row it must update."""
    assert format_record_id(pid, is_new=False) == pid
    assert isinstance(format_record_id(pid, is_new=False), int)


def test_a_number_wider_than_the_pad_is_not_truncated():
    """Four digits stay four digits rather than losing the leading one."""
    assert format_record_id(1234, is_new=True) == "1234"


def test_the_pad_width_matches_the_rest_of_the_app():
    """The .MEM filenames and export names all use three digits."""
    assert RECORD_ID_WIDTH == 3
    assert format_record_id(5, is_new=True) == f"{5:0{RECORD_ID_WIDTH}d}"


# ---------------------------------------------------------------------------
# End to end, through the exporter
# ---------------------------------------------------------------------------

def _py_record(pid: int) -> dict:
    """One participant-visit with enough T-SICI data to produce a change."""
    r = initialize_record()
    r.update(
        Study="SNBR", ID=pid, Date=VISIT_DATE, Stimulated_cortex="L",
        Subject_type="Patient", Muscle="FDI", Recorded_side="R",
        source_file=f"SNBR-{pid:03d}-TP1C50415A.MEM",
    )
    for isi in TSICI_ISIS:
        r[f"T_SICI_{isi}"] = 55.0
    return r


def _write_redcap_export(path: Path, known_ids: list[int]):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "record_id", "redcap_event_name", "tt_test_date", "cortex",
            "t_sici_p_1_0_ms",
        ])
        for pid in known_ids:
            w.writerow([str(pid), "visit_1_arm_1", VISIT_DATE_ISO, "1", ""])


def _write_dictionary(path: Path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Variable / Field Name", "Form Name"])
        for field in ("t_sici_p_1_0_ms", "tms_values_complete"):
            w.writerow([field, "tms_values"])


def _write_template(path: Path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "record_id", "redcap_event_name", "t_sici_p_1_0_ms",
            "tms_values_complete",
        ])


@pytest.fixture
def redcap_files(tmp_path):
    """The three REDCap inputs, with participant 42 already registered."""
    export = tmp_path / "SNBR_DATA_2026.csv"
    dictionary = tmp_path / "SNBR_DataDictionary_2026.csv"
    template = tmp_path / "SNBR_ImportTemplate_2026.csv"
    _write_redcap_export(export, known_ids=[42])
    _write_dictionary(dictionary)
    _write_template(template)
    return export, dictionary, template


def _run(py_df, redcap_files, tmp_path, **kwargs):
    export, dictionary, template = redcap_files
    return generate_redcap_import(
        py_df, export, dictionary, template, tmp_path, **kwargs
    )


@pytest.mark.parametrize("pid,expected", [(1, "001"), (10, "010"), (100, "100")])
def test_a_new_participant_is_written_padded(pid, expected, redcap_files, tmp_path):
    py_df = pd.DataFrame([_py_record(pid)])

    import_df, output_path, stats = _run(
        py_df, redcap_files, tmp_path, include_new_ids=True,
    )

    assert stats["new_ids_added"] == [pid]
    assert list(import_df["record_id"]) == [expected]

    # And it reaches the file that way, not just the frame.
    written = output_path.read_text(encoding="utf-8-sig").splitlines()
    header = written[0].split(",")
    body = written[1].split(",")
    assert body[header.index("record_id")] == expected


def test_an_existing_participant_is_not_padded(redcap_files, tmp_path):
    """Participant 42 is already in REDCap; its key must stay 42."""
    py_df = pd.DataFrame([_py_record(42)])

    import_df, output_path, stats = _run(py_df, redcap_files, tmp_path)

    assert stats["new_ids_added"] == []
    assert list(import_df["record_id"]) == [42]

    written = output_path.read_text(encoding="utf-8-sig").splitlines()
    header = written[0].split(",")
    assert written[1].split(",")[header.index("record_id")] == "42"


def test_one_import_can_hold_both_kinds(redcap_files, tmp_path):
    """The asymmetry has to survive them being in the same file."""
    py_df = pd.DataFrame([_py_record(42), _py_record(7)])

    import_df, output_path, stats = _run(
        py_df, redcap_files, tmp_path, include_new_ids=True,
    )

    assert stats["new_ids_added"] == [7]
    assert set(import_df["record_id"]) == {42, "007"}

    written = output_path.read_text(encoding="utf-8-sig").splitlines()
    header = written[0].split(",")
    ids = {line.split(",")[header.index("record_id")] for line in written[1:] if line}
    assert ids == {"42", "007"}


def test_a_skipped_new_participant_writes_nothing_at_all(redcap_files, tmp_path):
    """Without include_new_ids a new participant is dropped, padded or not."""
    py_df = pd.DataFrame([_py_record(7)])

    import_df, _, stats = _run(py_df, redcap_files, tmp_path)

    assert stats["skipped_new_ids"] == [7]
    assert import_df.empty


def test_the_xlsx_change_report_shows_the_padded_id_too(redcap_files, tmp_path):
    """The report is the human-readable half of the same export.

    Its record_id column reads straight off the emitted rows, so it must show
    what the import will actually create rather than a different number.
    """
    pytest.importorskip("openpyxl")
    from openpyxl import load_workbook

    py_df = pd.DataFrame([_py_record(42), _py_record(7)])
    reports = tmp_path / "reports"

    _run(
        py_df, redcap_files, tmp_path,
        include_new_ids=True, xlsx_report_dir=str(reports),
    )

    written = sorted(reports.glob("*.xlsx"))
    assert written, "no xlsx change report was written"

    sheet = load_workbook(written[-1]).active
    ids = {
        str(sheet.cell(row, 1).value)
        for row in range(2, sheet.max_row + 1)
        if sheet.cell(row, 1).value is not None
    }
    assert ids == {"007", "42"}


def test_the_padded_id_is_a_string_so_the_zeros_survive_the_csv(
    redcap_files, tmp_path,
):
    """An int cannot carry a leading zero; the value must stay text.

    Guards the round trip specifically: reading the CSV back with the column
    forced to text must still show the padding.
    """
    py_df = pd.DataFrame([_py_record(1)])

    _, output_path, _ = _run(
        py_df, redcap_files, tmp_path, include_new_ids=True,
    )

    reread = pd.read_csv(output_path, dtype={"record_id": str})
    assert list(reread["record_id"]) == ["001"]
