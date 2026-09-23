"""The one bridge between the dispatch window and the ``dispatch/`` backend.

Holds the session: settings, the loaded roster and report index, the ledger,
the current worklist and the batch being worked. Every method here is
synchronous; the window runs the slow ones (``load``, ``prepare_batch``) on a
thread and marshals results back with ``after(0, ...)``.
"""

from __future__ import annotations

from pathlib import Path

from dispatch import settings as ds
from dispatch.batch import Batch, Part, mailto_url, mark_part_sent, write_batch
from dispatch.ledger import Ledger
from dispatch.report_index import ReportIndex, scan_reports
from dispatch.roster import Roster, load_roster
from dispatch.worklist import Worklist, WorklistItem, build_worklist, ensure_initialised


class DispatchController:
    def __init__(self):
        self.settings: dict = ds.load_settings()
        self.roster: Roster | None = None
        self.index: ReportIndex | None = None
        self.ledger: Ledger | None = None
        self.worklist: Worklist | None = None
        self.batch: Batch | None = None
        self.seeded_on_first_run: int = 0

    # -- settings ------------------------------------------------------------

    def missing_configuration(self) -> list[str]:
        """Human-readable names of the required settings still blank."""
        labels = {
            ds.KEY_ROSTER_PATH: "Enrolment workbook",
            ds.KEY_REPORTS_DIR: "Exported reports folder",
            ds.KEY_IDENTIFIED_DIR: "Identified reports folder",
            ds.KEY_LEDGER_PATH: "Ledger file",
        }
        missing = [label for key, label in labels.items() if not str(self.settings.get(key, "")).strip()]
        if not self.settings.get(ds.KEY_RECIPIENTS):
            missing.append("Recipients")
        return missing

    def validate(self, values: dict) -> list[str]:
        """Problems that must be fixed before *values* can be saved."""
        problems = []
        recipients = values.get(ds.KEY_RECIPIENTS, [])
        problems += ds.validate_recipients(recipients, values.get(ds.KEY_ALLOWED_DOMAIN, "sunnybrook.ca"))
        try:
            cap = int(values.get(ds.KEY_SIZE_CAP_MB, 20))
            if cap <= 0:
                problems.append("Size cap must be a positive number of MB")
        except (TypeError, ValueError):
            problems.append("Size cap must be a whole number of MB")
        conflicts = ds.sync_source_conflicts(
            values.get(ds.KEY_IDENTIFIED_DIR, ""), ds.analysis_app_sync_pairs(),
        )
        for source in conflicts:
            problems.append(
                f"Identified reports folder is inside a backup/sync source ({source}); "
                f"stamped PDFs would be copied automatically. Choose a folder outside it."
            )
        roster = values.get(ds.KEY_ROSTER_PATH, "")
        if roster and not Path(roster).is_file():
            problems.append(f"Enrolment workbook not found: {roster}")
        reports = values.get(ds.KEY_REPORTS_DIR, "")
        if reports and not Path(reports).is_dir():
            problems.append(f"Exported reports folder not found: {reports}")
        return problems

    def save_settings(self, values: dict) -> list[str]:
        """Validate then persist; returns the problems (nothing saved if any)."""
        problems = self.validate(values)
        if problems:
            return problems
        ds.save_settings(**values)
        self.settings = ds.load_settings()
        return []

    # -- loading -------------------------------------------------------------

    def load(self) -> Worklist:
        """Read the roster, index the reports, replay the ledger. Slow: thread it."""
        s = self.settings
        self.roster = load_roster(
            s[ds.KEY_ROSTER_PATH], s[ds.KEY_ROSTER_SHEET],
            s[ds.KEY_COL_PATIENT_ID], s[ds.KEY_COL_PATIENT_NAME], s[ds.KEY_COL_MRN],
        )
        self.index = scan_reports(s[ds.KEY_REPORTS_DIR])
        self.ledger = Ledger(s[ds.KEY_LEDGER_PATH])
        self.seeded_on_first_run = ensure_initialised(self.ledger, self.index.reports)
        self.worklist = build_worklist(self.roster, self.index, self.ledger.state())
        self.batch = None
        return self.worklist

    def refresh_statuses(self) -> Worklist:
        """Re-read the ledger only (cheap) and rebuild the worklist."""
        if self.roster is None or self.index is None or self.ledger is None:
            return self.load()
        self.worklist = build_worklist(self.roster, self.index, self.ledger.state())
        return self.worklist

    # -- batch ---------------------------------------------------------------

    def prepare_batch(self, items: list[WorklistItem]) -> Batch:
        """Stamp and pack *items* into a batch folder. Slow: thread it."""
        s = self.settings
        self.batch = write_batch(
            items, s[ds.KEY_IDENTIFIED_DIR], list(s[ds.KEY_RECIPIENTS]),
            int(s[ds.KEY_SIZE_CAP_MB]), s[ds.KEY_SUBJECT_TEMPLATE], ledger=self.ledger,
        )
        return self.batch

    def mark_part_sent(self, part: Part) -> list[tuple]:
        results = mark_part_sent(self.ledger, self.batch, part)
        self.refresh_statuses()
        return results

    def close_report(self, item: WorklistItem, reason: str) -> None:
        self.ledger.close(item.report, reason)
        self.refresh_statuses()

    def mailto(self, part: Part) -> str:
        return mailto_url(self.batch.recipients, part.subject, part.body)

    # -- text for the issues panel -----------------------------------------------

    def issues_lines(self) -> list[str]:
        wl = self.worklist
        if wl is None:
            return []
        lines: list[str] = []
        if self.seeded_on_first_run:
            lines.append(
                f"First run: {self.seeded_on_first_run} report(s) exported before this week "
                f"were closed without sending."
            )
        if wl.ledger_bad_lines:
            lines.append(f"Ledger: {wl.ledger_bad_lines} unreadable line(s) were skipped.")
        for p in wl.roster_problems:
            lines.append(f"Roster row {p.row}: {p.message} ({p.patient_id_raw or 'blank'})")
        for ident in wl.coverage_missing:
            lines.append(f"No report exported for {ident.key.label()} ({ident.name or 'no name'})")
        for path in wl.unrecognised:
            lines.append(f"Not a report, ignored: {Path(path).name}")
        return lines
