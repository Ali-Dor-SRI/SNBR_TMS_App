"""dispatch/ledger.py -- append-only JSONL, replayed into state, no PHI."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from dispatch.identity import ParticipantKey
from dispatch.ledger import (
    STATUS_CLOSED, STATUS_REVISION, STATUS_SENT, STATUS_UNSENT, Ledger, new_run_id,
)
from dispatch.report_index import ReportFile


def _report(number=80, visit=date(2026, 8, 18), sha="a" * 64, mtime=None, study="SNBR"):
    return ReportFile(
        path=Path(f"report_{study}_{number:03d}.pdf"),
        key=ParticipantKey(study, number),
        visit_date=visit,
        sha256=sha,
        size=100,
        mtime=mtime or datetime(2026, 9, 8, 10, 0),
    )


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "share" / "dispatch_ledger.jsonl")


def test_fresh_ledger_is_uninitialised_and_everything_is_unsent(ledger):
    state = ledger.state()
    assert not state.initialised
    assert state.status(_report()) == STATUS_UNSENT
    assert not ledger.path.exists()


def test_mark_sent_then_status_and_record(ledger):
    report = _report()
    ok, msg = ledger.mark_sent(report, "run1", 1, 2, ["a@sunnybrook.ca"])
    assert ok and msg == "recorded"
    state = ledger.state()
    assert state.status(report) == STATUS_SENT
    rec = state.sent_record(report)
    assert (rec.run_id, rec.part, rec.parts) == ("run1", 1, 2)
    assert rec.source_file == "report_SNBR_080.pdf"
    assert rec.recipients == ["a@sunnybrook.ca"]
    assert rec.user and rec.at


def test_second_mark_is_refused_and_names_the_first(ledger):
    """The re-check before each send: a row already sent is never re-recorded."""
    report = _report()
    ledger.mark_sent(report, "run1", 1, 1, [])
    ok, msg = ledger.mark_sent(report, "run2", 1, 1, [])
    assert not ok
    assert "already marked sent" in msg and "run1" in msg
    events, _ = ledger.events()
    assert sum(1 for e in events if e["event"] == "sent") == 1


def test_a_changed_file_for_a_sent_visit_is_a_revision(ledger):
    sent = _report(sha="a" * 64)
    ledger.mark_sent(sent, "run1", 1, 1, [])
    revised = _report(sha="b" * 64)
    state = ledger.state()
    assert state.status(revised) == STATUS_REVISION
    assert state.status(sent) == STATUS_SENT
    # A different visit of the same participant is simply unsent.
    assert state.status(_report(visit=date(2026, 9, 1), sha="c" * 64)) == STATUS_UNSENT


def test_seed_closes_only_reports_exported_before_the_week(ledger):
    week = date(2026, 9, 7)   # a Monday
    old = _report(number=1, sha="1" * 64, mtime=datetime(2026, 9, 4, 9, 0))
    edge = _report(number=2, sha="2" * 64, mtime=datetime(2026, 9, 7, 0, 30))
    new = _report(number=3, sha="3" * 64, mtime=datetime(2026, 9, 8, 9, 0))
    assert ledger.seed([old, edge, new], week) == 1
    ledger.initialise(week)
    state = ledger.state()
    assert state.initialised and state.week_start == week
    assert state.status(old) == STATUS_CLOSED
    assert state.status(edge) == STATUS_UNSENT
    assert state.status(new) == STATUS_UNSENT


def test_close_by_hand(ledger):
    report = _report()
    ledger.close(report, "screening visit only")
    assert ledger.state().status(report) == STATUS_CLOSED


def test_run_events_are_kept_in_order(ledger):
    ledger.record_run("r1", 1, 3, "folder1")
    ledger.record_run("r2", 2, 5, "folder2")
    state = ledger.state()
    assert [r["run_id"] for r in state.runs] == ["r1", "r2"]
    assert state.last_run()["count"] == 5


def test_file_is_one_json_object_per_line_and_never_rewritten(ledger):
    report = _report()
    ledger.initialise(date(2026, 9, 7))
    ledger.mark_sent(report, "run1", 1, 1, [])
    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["event"] for line in lines] == ["initialised", "sent"]
    ledger.close(_report(number=81), "x")
    assert ledger.path.read_text(encoding="utf-8").splitlines()[:2] == lines


def test_ledger_holds_no_phi(ledger):
    """Only keys, hashes and send events -- never a name or an MRN.

    The identified attachment name (``John_Smith_1234567_...``) is exactly
    the thing that must not land on the share; the ledger records the
    report's own de-identified filename instead.
    """
    ledger.mark_sent(_report(), "run1", 1, 1, ["x@sunnybrook.ca"])
    text = ledger.path.read_text(encoding="utf-8")
    assert "John" not in text and "Smith" not in text and "1234567" not in text
    assert "report_SNBR_080.pdf" in text
    for ev in (json.loads(l) for l in text.splitlines()):
        assert set(ev) <= {
            "event", "key", "visit", "sha256", "run_id", "part", "parts",
            "source_file", "recipients", "at", "user", "declared",
        }


def test_corrupt_lines_are_counted_not_fatal(ledger):
    ledger.initialise(date(2026, 9, 7))
    with open(ledger.path, "a", encoding="utf-8") as fh:
        fh.write("{not json\n")
        fh.write('{"no_event_field": 1}\n')
    ledger.mark_sent(_report(), "run1", 1, 1, [])
    state = ledger.state()
    assert state.initialised
    assert state.bad_lines == 2
    assert state.status(_report()) == STATUS_SENT


def test_run_ids_are_unique_and_dated():
    when = datetime(2026, 9, 8, 14, 30, 5)
    a, b = new_run_id(when), new_run_id(when)
    assert a.startswith("20260908-143005-") and a != b
