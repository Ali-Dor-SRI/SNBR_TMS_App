"""The send ledger: an append-only JSON Lines file, holding no PHI.

Why this shape
--------------
The ledger lives on a network share so several staff see one record. SQLite's
locking is unreliable over SMB and its WAL mode does not work there at all; a
file that is only ever *appended* -- one JSON object per line -- cannot be
half-written across a crash and needs no lock. State is derived by replaying
the events, and the replay *is* the audit trail.

What it stores
--------------
Only keys: study, participant number, visit date, the report's SHA-256, its
de-identified source filename, and send events (run id, part, Windows user,
timestamp, configured recipients). Never a name or an MRN -- those are looked
up from the workbook each run, so the share carries nothing the analysis
app's own archive does not. In particular the *attachment* name, which does
carry the name and MRN, is deliberately not recorded; it is reproducible
from the roster and the visit date at any time.

Events
------
``initialised``  first run; records the week the app started from
``seeded``       a report that predates the first run, closed without sending
``closed``       a report the operator closed by hand ("not to send")
``run``          a batch folder was written (parts, count)
``sent``         one report in one part was **declared** sent by the operator
                 (the app cannot verify a manual OWA send, and says so)
"""

from __future__ import annotations

import getpass
import json
import os
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from dispatch.identity import ParticipantKey
from dispatch.report_index import ReportFile

STATUS_UNSENT = "unsent"
STATUS_SENT = "sent"
STATUS_REVISION = "revision"    # a different version of this visit was sent
STATUS_CLOSED = "closed"        # seeded at first run or closed by hand


def current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USERNAME") or "unknown"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_run_id(when: datetime | None = None) -> str:
    stamp = (when or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{secrets.token_hex(3)}"


def _visit_key(report: ReportFile) -> tuple[ParticipantKey, str]:
    return report.key, report.visit_token


@dataclass
class SentRecord:
    run_id: str
    part: int
    parts: int
    user: str
    at: str
    source_file: str        # the de-identified report_<Study>_<ID>_<date>.pdf name
    recipients: list[str]


@dataclass
class VisitState:
    """Everything the ledger knows about one (participant, visit)."""

    sent: dict[str, SentRecord] = field(default_factory=dict)   # sha256 -> record
    closed: set[str] = field(default_factory=set)                 # sha256s

    def status_of(self, sha256: str) -> str:
        if sha256 in self.sent:
            return STATUS_SENT
        if sha256 in self.closed:
            return STATUS_CLOSED
        if self.sent:
            return STATUS_REVISION
        return STATUS_UNSENT


@dataclass
class LedgerState:
    initialised: bool = False
    week_start: date | None = None
    visits: dict[tuple[ParticipantKey, str], VisitState] = field(default_factory=dict)
    runs: list[dict] = field(default_factory=list)
    bad_lines: int = 0

    def status(self, report: ReportFile) -> str:
        visit = self.visits.get(_visit_key(report))
        return visit.status_of(report.sha256) if visit else STATUS_UNSENT

    def sent_record(self, report: ReportFile) -> SentRecord | None:
        visit = self.visits.get(_visit_key(report))
        return visit.sent.get(report.sha256) if visit else None

    def last_run(self) -> dict | None:
        return self.runs[-1] if self.runs else None


class Ledger:
    """Append-only JSONL at *path*. Every method re-reads the file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    # -- raw I/O -----------------------------------------------------------

    def append(self, event: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def events(self) -> tuple[list[dict], int]:
        """All events in order, plus the count of lines that failed to parse."""
        if not self.path.exists():
            return [], 0
        out, bad = [], 0
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    bad += 1
                    continue
                if isinstance(obj, dict) and "event" in obj:
                    out.append(obj)
                else:
                    bad += 1
        return out, bad

    # -- replay ------------------------------------------------------------

    def state(self) -> LedgerState:
        events, bad = self.events()
        state = LedgerState(bad_lines=bad)
        for ev in events:
            kind = ev.get("event")
            if kind == "initialised":
                state.initialised = True
                try:
                    state.week_start = date.fromisoformat(ev["week_start"])
                except (KeyError, ValueError):
                    pass
            elif kind in ("seeded", "closed"):
                visit = self._visit(state, ev)
                if visit is not None:
                    visit.closed.add(ev.get("sha256", ""))
            elif kind == "sent":
                visit = self._visit(state, ev)
                if visit is not None:
                    visit.sent[ev.get("sha256", "")] = SentRecord(
                        run_id=ev.get("run_id", ""),
                        part=int(ev.get("part", 1)),
                        parts=int(ev.get("parts", 1)),
                        user=ev.get("user", ""),
                        at=ev.get("at", ""),
                        source_file=ev.get("source_file", ""),
                        recipients=list(ev.get("recipients", [])),
                    )
            elif kind == "run":
                state.runs.append(ev)
        return state

    @staticmethod
    def _visit(state: LedgerState, ev: dict) -> VisitState | None:
        try:
            key = ParticipantKey.from_json(ev["key"])
        except (KeyError, TypeError, ValueError):
            return None
        visit_key = (key, str(ev.get("visit", "unknown")))
        return state.visits.setdefault(visit_key, VisitState())

    # -- writes ------------------------------------------------------------

    @staticmethod
    def _report_fields(report: ReportFile) -> dict:
        return {
            "key": report.key.to_json(),
            "visit": report.visit_token,
            "sha256": report.sha256,
        }

    def initialise(self, week_start: date) -> None:
        self.append({
            "event": "initialised", "week_start": week_start.isoformat(),
            "at": _now(), "user": current_user(),
        })

    def seed(self, reports: list[ReportFile], week_start: date) -> int:
        """First run: close every report exported before *week_start*.

        "Exported before" is judged on the file's modification time -- the
        moment the analysis app wrote it -- not the visit date.
        """
        count = 0
        for report in reports:
            if report.mtime.date() < week_start:
                self.append({
                    "event": "seeded", **self._report_fields(report),
                    "at": _now(), "user": current_user(),
                    "reason": f"predates first run (week of {week_start.isoformat()})",
                })
                count += 1
        return count

    def close(self, report: ReportFile, reason: str) -> None:
        self.append({
            "event": "closed", **self._report_fields(report),
            "at": _now(), "user": current_user(), "reason": reason,
        })

    def record_run(self, run_id: str, parts: int, count: int, folder: str) -> None:
        self.append({
            "event": "run", "run_id": run_id, "parts": parts, "count": count,
            "folder": folder, "at": _now(), "user": current_user(),
        })

    def mark_sent(
        self,
        report: ReportFile,
        run_id: str,
        part: int,
        parts: int,
        recipients: list[str],
    ) -> tuple[bool, str]:
        """Declare *report* sent. Re-reads the ledger first.

        Returns ``(recorded, message)``. If another user already marked this
        exact file sent in the meantime, nothing is written and the message
        says who did. Only the report's own (de-identified) filename is
        recorded -- never the identified attachment name.
        """
        existing = self.state().sent_record(report)
        if existing is not None:
            return False, (
                f"already marked sent by {existing.user or 'someone'} at "
                f"{existing.at} (run {existing.run_id}, part {existing.part})"
            )
        self.append({
            "event": "sent", **self._report_fields(report),
            "run_id": run_id, "part": part, "parts": parts,
            "source_file": report.path.name, "recipients": list(recipients),
            "at": _now(), "user": current_user(),
            "declared": True,   # a manual OWA send; the app cannot verify it
        })
        return True, "recorded"
