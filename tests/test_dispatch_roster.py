"""dispatch/roster.py against a synthetic workbook.

Never a real enrolment log: the workbook is built in ``tmp_path`` with
openpyxl, with the lab's real headers (``Patient ID`` / ``Patient Name`` /
``MRN``) and invented rows.
"""

from __future__ import annotations

import pytest

openpyxl = pytest.importorskip("openpyxl")

from dispatch.identity import ParticipantKey
from dispatch.roster import RosterError, load_roster

SHEET = "SNBR enrolment log"
HEADERS = ("Patient ID", "Patient Name", "MRN")


def _workbook(tmp_path, rows, sheet=SHEET, headers=HEADERS, preamble=0, extra_sheet=None):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    for _ in range(preamble):
        ws.append(["Enrolment log -- confidential", None, None])
    ws.append(list(headers))
    for row in rows:
        ws.append(list(row))
    if extra_sheet:
        wb.create_sheet(extra_sheet).append(["unrelated"])
    path = tmp_path / "roster.xlsx"
    wb.save(path)
    return path


def _load(path, sheet=SHEET):
    return load_roster(path, sheet, "Patient ID", "Patient Name", "MRN")


def test_rows_become_identities_keyed_by_study_and_number(tmp_path):
    path = _workbook(tmp_path, [
        ("AA-SNBR-001", "John Smith", "1234567"),
        ("BB-SNBR-002", "Jane Doe", 7654321),      # numeric MRN cell
    ])
    roster = _load(path)
    assert len(roster) == 2
    assert roster.problems == []
    ident = roster.entries[ParticipantKey("SNBR", 1)]
    assert (ident.name, ident.mrn, ident.patient_id_raw) == ("John Smith", "1234567", "AA-SNBR-001")
    assert roster.entries[ParticipantKey("SNBR", 2)].mrn == "7654321"


def test_header_row_is_found_below_a_preamble_and_matched_loosely(tmp_path):
    path = _workbook(
        tmp_path, [("AA-SNBR-001", "John Smith", "1")],
        headers=("  patient id ", "PATIENT NAME", "Mrn"), preamble=3,
    )
    assert len(_load(path)) == 1


def test_sheet_name_is_matched_case_insensitively(tmp_path):
    path = _workbook(tmp_path, [("AA-SNBR-001", "J S", "1")], sheet="snbr Enrolment Log")
    assert len(_load(path)) == 1


def test_missing_sheet_names_the_sheets_present(tmp_path):
    path = _workbook(tmp_path, [], sheet="Other", extra_sheet="More")
    with pytest.raises(RosterError, match="Other, More"):
        _load(path)


def test_missing_column_is_named(tmp_path):
    path = _workbook(tmp_path, [], headers=("Patient ID", "Patient Name", "Hospital no"))
    with pytest.raises(RosterError, match="'MRN'"):
        _load(path)


def test_missing_workbook_raises(tmp_path):
    with pytest.raises(RosterError, match="not found"):
        _load(tmp_path / "nope.xlsx")


def test_unparseable_and_duplicate_ids_are_problems_not_guesses(tmp_path):
    path = _workbook(tmp_path, [
        ("AA-SNBR-001", "John Smith", "1"),
        ("not an id", "Someone", "2"),
        ("", "Blank id", "3"),
        ("AA-SNBR-001", "John Smith again", "4"),
        (None, None, None),                         # fully blank row: ignored
    ])
    roster = _load(path)
    assert len(roster) == 1
    assert roster.entries[ParticipantKey("SNBR", 1)].name == "John Smith"
    messages = [(p.row, p.message) for p in roster.problems]
    assert (3, "Patient ID does not end in a study token and number") in messages
    assert (4, "Patient ID is blank") in messages
    assert any(row == 5 and "duplicate" in msg for row, msg in messages)


def test_blank_mrn_is_kept_but_incomplete(tmp_path):
    """The lab chose to send such reports de-identified; the row must survive."""
    path = _workbook(tmp_path, [("AA-SNBR-001", "John Smith", None)])
    ident = _load(path).entries[ParticipantKey("SNBR", 1)]
    assert not ident.complete
    assert ident.missing_fields() == ["MRN"]


def test_lookup_by_study_and_by_number_alone(tmp_path):
    path = _workbook(tmp_path, [
        ("AA-SNBR-005", "A", "1"),
        ("BB-NIALS-005", "B", "2"),
        ("CC-SNBR-009", "C", "3"),
    ])
    roster = _load(path)
    ident, reason = roster.lookup(ParticipantKey("SNBR", 5))
    assert ident.name == "A" and reason == ""
    ident, reason = roster.lookup(ParticipantKey("", 9))
    assert ident.name == "C" and reason == ""
    ident, reason = roster.lookup(ParticipantKey("", 5))
    assert ident is None and "several studies" in reason
    ident, reason = roster.lookup(ParticipantKey("QUARTS", 5))
    assert ident is None and "not in the roster" in reason


def test_the_workbook_is_never_written(tmp_path):
    path = _workbook(tmp_path, [("AA-SNBR-001", "J S", "1")])
    before = path.read_bytes()
    _load(path)
    assert path.read_bytes() == before
