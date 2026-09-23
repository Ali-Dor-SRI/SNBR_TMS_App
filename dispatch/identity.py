"""Participant keys and patient identity.

The two data sources name a participant differently: a report filename says
``report_SNBR_080_20260818``, the enrolment workbook says ``AA-SNBR-080``. Both
reduce to the same :class:`ParticipantKey` — the study token and the number —
which is the only thing the two apps ever agree on.

Parsing is deliberately narrow. The number is the trailing run of digits and
the study is the letter token immediately before it; anything in front of
that (initials, a site code, nothing at all) is ignored. A cell that does not
end that way is not guessed at: it is reported as a roster problem instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A letter token immediately before a trailing run of digits, allowing a
# single separator (or none) between them: "SNBR-080", "SNBR 080", "SNBR080",
# "AA-SNBR-001". The prefix is whatever came before and is discarded.
_KEY_RE = re.compile(r"([A-Za-z]+)\s*[-_ ]?\s*(\d+)\s*$")


@dataclass(frozen=True, order=True)
class ParticipantKey:
    """``(study, number)`` — the identity shared by both apps.

    ``study`` is upper-cased and may be ``""`` for a report whose filename
    carried no study; see :func:`keys_match` for how that is compared.
    """

    study: str
    number: int

    def label(self) -> str:
        """``SNBR-080`` — the form used in report titles and the worklist."""
        return f"{self.study}-{self.number:03d}" if self.study else f"{self.number:03d}"

    def to_json(self) -> dict:
        return {"study": self.study, "number": self.number}

    @classmethod
    def from_json(cls, data: dict) -> "ParticipantKey":
        return cls(str(data.get("study") or ""), int(data["number"]))


def parse_patient_id(text) -> ParticipantKey | None:
    """Return the key in a roster ``Patient ID`` cell, or ``None`` if it has none.

    >>> parse_patient_id("AA-SNBR-001")
    ParticipantKey(study='SNBR', number=1)
    >>> parse_patient_id("snbr 080")
    ParticipantKey(study='SNBR', number=80)
    >>> parse_patient_id("080") is None
    True
    """
    if text is None:
        return None
    match = _KEY_RE.search(str(text).strip())
    if not match:
        return None
    return ParticipantKey(match.group(1).upper(), int(match.group(2)))


def keys_match(report_key: ParticipantKey, roster_key: ParticipantKey) -> bool:
    """Whether a report's key and a roster key name the same participant.

    Study tokens are compared case-insensitively. A report with **no** study
    token matches on the number alone — the caller must then ensure the match
    is unique across the roster, since numbers repeat between studies.
    """
    if report_key.number != roster_key.number:
        return False
    if not report_key.study:
        return True
    return report_key.study.upper() == roster_key.study.upper()


@dataclass(frozen=True)
class Identity:
    """One roster row: what the stamped report and the attachment name carry."""

    key: ParticipantKey
    patient_id_raw: str
    name: str
    mrn: str

    @property
    def complete(self) -> bool:
        """Both the name and the MRN are present."""
        return bool(self.name.strip()) and bool(self.mrn.strip())

    @property
    def identifying(self) -> bool:
        """At least one of the name and the MRN is present.

        This -- not :attr:`complete` -- is what decides whether the report can
        be stamped. A roster row that gives a name but no MRN still identifies
        the patient, and discarding the name because the MRN is blank throws
        away the very thing the clinician needs.
        """
        return bool(self.name.strip()) or bool(self.mrn.strip())

    @property
    def partial(self) -> bool:
        """Exactly one of the two is present, so the stamp carries a caveat."""
        return self.identifying and not self.complete

    def missing_fields(self) -> list[str]:
        missing = []
        if not self.name.strip():
            missing.append("name")
        if not self.mrn.strip():
            missing.append("MRN")
        return missing
