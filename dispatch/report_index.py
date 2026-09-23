"""Index the folder the analysis app exports report PDFs into.

A report is identified by its filename, which the analysis app writes as
``report_<Study>_<ID>_<YYYYMMDD>.pdf`` (``reports.export_naming``), with a
``_2``/``_3`` counter when the same name is exported again. Files named before
the visit date was added (``report_SNBR_080.pdf``) are still indexed, with an
unknown visit date, so they show up rather than vanish; the cover page is a
rasterized image, so the date cannot be recovered from the PDF itself.

Each file's SHA-256 is the ledger's notion of *which* report was sent: a
re-export with different bytes is a revision, not the same document.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from dispatch.identity import ParticipantKey

_NAME_RE = re.compile(
    r"^report_"
    r"(?:(?P<study>[A-Za-z]+)_)?"
    r"(?P<number>\d{1,5})"
    r"(?:_(?P<date>\d{8}))?"
    r"(?:_(?P<dup>\d+))?"
    r"\.pdf$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ReportFile:
    path: Path
    key: ParticipantKey
    visit_date: date | None
    sha256: str
    size: int
    mtime: datetime

    @property
    def visit_token(self) -> str:
        """``YYYYMMDD`` for names and keys; ``unknown`` for a legacy filename."""
        return self.visit_date.strftime("%Y%m%d") if self.visit_date else "unknown"

    @property
    def visit_label(self) -> str:
        return self.visit_date.strftime("%d/%m/%Y") if self.visit_date else "unknown"


@dataclass
class ReportIndex:
    reports: list[ReportFile]
    unrecognised: list[Path]
    folder: Path


def parse_report_filename(name: str) -> tuple[ParticipantKey, date | None] | None:
    """Return ``(key, visit_date)`` for a report filename, or ``None``."""
    match = _NAME_RE.match(name)
    if not match:
        return None
    study = (match.group("study") or "").upper()
    number = int(match.group("number"))
    visit = None
    if match.group("date"):
        try:
            visit = datetime.strptime(match.group("date"), "%Y%m%d").date()
        except ValueError:
            return None
    return ParticipantKey(study, number), visit


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def scan_reports(folder: str | Path, recursive: bool = False) -> ReportIndex:
    """Index every ``report_*.pdf`` under *folder*.

    Sorted by path so the order is stable between runs. A missing folder
    raises ``FileNotFoundError`` rather than returning an empty index — the
    same contract the analysis app's loaders keep, so a typo'd path never
    reads as "nothing to send".
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"Reports folder does not exist: {folder}")
    pattern = "**/*.pdf" if recursive else "*.pdf"
    reports: list[ReportFile] = []
    unrecognised: list[Path] = []
    for path in sorted(folder.glob(pattern), key=lambda p: str(p).lower()):
        if not path.is_file():
            continue
        parsed = parse_report_filename(path.name)
        if parsed is None:
            unrecognised.append(path)
            continue
        key, visit = parsed
        stat = path.stat()
        reports.append(ReportFile(
            path=path,
            key=key,
            visit_date=visit,
            sha256=sha256_of(path),
            size=stat.st_size,
            mtime=datetime.fromtimestamp(stat.st_mtime),
        ))
    return ReportIndex(reports=reports, unrecognised=unrecognised, folder=folder)
