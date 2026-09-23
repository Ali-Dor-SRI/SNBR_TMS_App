"""dispatch/worklist.py -- roster x reports x ledger, and first-run seeding."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from dispatch.identity import Identity, ParticipantKey
from dispatch.ledger import STATUS_CLOSED, STATUS_REVISION, STATUS_SENT, STATUS_UNSENT, Ledger
from dispatch.report_index import ReportFile, ReportIndex
from dispatch.roster import Roster, RosterProblem
from dispatch.worklist import build_worklist, ensure_initialised, week_start_of


def _report(number, sha, visit=date(2026, 8, 18), mtime=datetime(2026, 9, 8, 9), study="SNBR"):
    return ReportFile(
        path=Path(f"report_{study}_{number:03d}_{visit:%Y%m%d}.pdf"),
        key=ParticipantKey(study, number), visit_date=visit,
        sha256=sha * 64, size=10, mtime=mtime,
    )


def _roster(*rows):
    roster = Roster()
    for number, name, mrn in rows:
        key = ParticipantKey("SNBR", number)
        roster.entries[key] = Identity(key, f"AA-SNBR-{number:03d}", name, mrn)
    return roster


def test_week_start_is_monday():
    assert week_start_of(date(2026, 9, 8)) == date(2026, 9, 7)    # Tuesday -> Monday
    assert week_start_of(date(2026, 9, 7)) == date(2026, 9, 7)
    assert week_start_of(date(2026, 9, 13)) == date(2026, 9, 7)   # Sunday


def test_worklist_joins_identity_status_and_reasons(tmp_path):
    roster = _roster((80, "John Smith", "1"), (81, "Jane Doe", ""), (99, "Never Tested", "9"))
    reports = [_report(80, "a"), _report(81, "b"), _report(82, "c")]
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.mark_sent(reports[0], "r", 1, 1, [])

    wl = build_worklist(roster, ReportIndex(reports, [Path("odd.pdf")], tmp_path), ledger.state())

    by_number = {item.report.key.number: item for item in wl.items}
    assert by_number[80].identified and by_number[80].status == STATUS_SENT
    assert by_number[80].sent.run_id == "r"
    assert not by_number[80].proposed

    # 81 has a name but no MRN: incompletely identified, not anonymous.
    assert not by_number[81].identified
    assert by_number[81].identifying and by_number[81].partially_identified
    assert not by_number[81].unidentified
    assert by_number[81].display_name == "Jane Doe" and by_number[81].display_mrn == "-"
    assert by_number[81].unresolved_reason == "roster row lacks MRN"
    assert by_number[81].status == STATUS_UNSENT and by_number[81].proposed

    assert by_number[82].identity is None
    assert by_number[82].unidentified and not by_number[82].identifying
    assert not by_number[82].partially_identified
    assert "not in the roster" in by_number[82].unresolved_reason
    assert by_number[82].display_name == "-" and by_number[82].display_mrn == "-"

    assert [i.name for i in wl.coverage_missing] == ["Never Tested"]
    assert wl.unrecognised == [Path("odd.pdf")]
    assert wl.counts() == {STATUS_UNSENT: 2, STATUS_REVISION: 0, STATUS_SENT: 1, STATUS_CLOSED: 0}
    assert [i.report.key.number for i in wl.proposed()] == [81, 82]


def test_a_roster_row_with_neither_field_is_unidentified(tmp_path):
    roster = _roster((80, "", ""))
    wl = build_worklist(roster, ReportIndex([_report(80, "a")], [], tmp_path), Ledger(tmp_path / "l.jsonl").state())
    item = wl.items[0]
    assert item.unidentified and not item.partially_identified
    assert item.unresolved_reason == "roster row lacks name and MRN"


def test_revision_is_proposed_and_flagged(tmp_path):
    roster = _roster((80, "John Smith", "1"))
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.mark_sent(_report(80, "a"), "r", 1, 1, [])
    wl = build_worklist(roster, ReportIndex([_report(80, "b")], [], tmp_path), ledger.state())
    item = wl.items[0]
    assert item.status == STATUS_REVISION and item.is_revision and item.proposed


def test_roster_problems_and_bad_lines_surface(tmp_path):
    roster = _roster()
    roster.problems.append(RosterProblem(4, "??", "bad"))
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append({"event": "initialised", "week_start": "2026-09-07"})
    ledger.path.open("a").write("garbage\n")
    wl = build_worklist(roster, ReportIndex([], [], tmp_path), ledger.state())
    assert wl.roster_problems[0].row == 4
    assert wl.ledger_bad_lines == 1


def test_first_run_seeds_the_back_catalogue_once(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    old = _report(1, "1", mtime=datetime(2026, 8, 30, 9))
    new = _report(2, "2", mtime=datetime(2026, 9, 8, 9))
    assert ensure_initialised(ledger, [old, new], today=date(2026, 9, 8)) == 1
    state = ledger.state()
    assert state.initialised and state.week_start == date(2026, 9, 7)
    assert state.status(old) == STATUS_CLOSED
    assert state.status(new) == STATUS_UNSENT
    # A second machine opening the same ledger must not re-seed.
    assert ensure_initialised(ledger, [old, new, _report(3, "3", mtime=datetime(2026, 1, 1))], today=date(2026, 9, 9)) == 0
    assert ledger.state().status(_report(3, "3")) == STATUS_UNSENT
