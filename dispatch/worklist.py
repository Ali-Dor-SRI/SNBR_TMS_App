"""Join roster, report index and ledger into the rows the operator works from.

This is the headless "controller" of the dispatch app: everything the GUI
shows is computed here from the three sources, so it can be tested without
a window and reused from a script.

A :class:`WorklistItem` is one exported report: who it belongs to (if the
roster knows), what the ledger says about it, and why it will go out
de-identified if it will. Coverage -- roster rows with no report at all --
is reported separately, since it is a gap in the analysis, not in dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from dispatch.identity import Identity
from dispatch.ledger import (
    STATUS_CLOSED, STATUS_REVISION, STATUS_SENT, STATUS_UNSENT, Ledger, LedgerState,
    SentRecord,
)
from dispatch.report_index import ReportFile, ReportIndex
from dispatch.roster import Roster


@dataclass
class WorklistItem:
    report: ReportFile
    identity: Identity | None
    status: str
    unresolved_reason: str = ""      # "" when the identity is complete
    sent: SentRecord | None = None

    @property
    def identified(self) -> bool:
        """Both name and MRN -- the stamp carries no caveat."""
        return self.identity is not None and self.identity.complete

    @property
    def identifying(self) -> bool:
        """Something to stamp: a name, an MRN, or both."""
        return self.identity is not None and self.identity.identifying

    @property
    def partially_identified(self) -> bool:
        """One field present, the other blank in the enrolment log."""
        return self.identity is not None and self.identity.partial

    @property
    def unidentified(self) -> bool:
        """No roster row, or a row with neither a name nor an MRN."""
        return not self.identifying

    @property
    def proposed(self) -> bool:
        """Whether the app ticks this row for the next batch by default."""
        return self.status in (STATUS_UNSENT, STATUS_REVISION)

    @property
    def is_revision(self) -> bool:
        return self.status == STATUS_REVISION

    @property
    def display_name(self) -> str:
        return self.identity.name if self.identity and self.identity.name else "-"

    @property
    def display_mrn(self) -> str:
        return self.identity.mrn if self.identity and self.identity.mrn else "-"


@dataclass
class Worklist:
    items: list[WorklistItem] = field(default_factory=list)
    coverage_missing: list[Identity] = field(default_factory=list)   # roster rows with no report
    unrecognised: list = field(default_factory=list)                 # PDFs that are not reports
    roster_problems: list = field(default_factory=list)
    ledger_bad_lines: int = 0

    def proposed(self) -> list[WorklistItem]:
        return [item for item in self.items if item.proposed]

    def counts(self) -> dict[str, int]:
        out = {STATUS_UNSENT: 0, STATUS_REVISION: 0, STATUS_SENT: 0, STATUS_CLOSED: 0}
        for item in self.items:
            out[item.status] = out.get(item.status, 0) + 1
        return out


def week_start_of(today: date | None = None) -> date:
    """Monday of the ISO week containing *today*."""
    today = today or date.today()
    return today - timedelta(days=today.weekday())


def ensure_initialised(ledger: Ledger, reports: list[ReportFile], today: date | None = None) -> int:
    """First run: seed the back-catalogue as closed. Returns how many were seeded.

    Idempotent -- a ledger that already carries an ``initialised`` event is
    left alone, so a second machine opening the same ledger does not re-seed.
    """
    if ledger.state().initialised:
        return 0
    week_start = week_start_of(today)
    seeded = ledger.seed(reports, week_start)
    ledger.initialise(week_start)
    return seeded


def build_worklist(roster: Roster, index: ReportIndex, state: LedgerState) -> Worklist:
    worklist = Worklist(
        unrecognised=list(index.unrecognised),
        roster_problems=list(roster.problems),
        ledger_bad_lines=state.bad_lines,
    )
    seen_keys = set()
    for report in index.reports:
        identity, reason = roster.lookup(report.key)
        if identity is not None:
            seen_keys.add(identity.key)
            if not identity.complete:
                reason = f"roster row lacks {' and '.join(identity.missing_fields())}"
        worklist.items.append(WorklistItem(
            report=report,
            identity=identity,
            status=state.status(report),
            unresolved_reason=reason,
            sent=state.sent_record(report),
        ))
    worklist.coverage_missing = [
        ident for key, ident in sorted(roster.entries.items()) if key not in seen_keys
    ]
    return worklist
