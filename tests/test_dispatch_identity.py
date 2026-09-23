"""dispatch/identity.py -- the key both apps agree on.

The roster's ``Patient ID`` cell is free text. The parser takes the trailing
digits and the letter token before them and ignores any prefix, so an
initials prefix, a bare ``SNBR-080``, or no separator at all resolve to the
same key. Anything that does not end that way must come back as ``None`` --
a guess here files a patient's report under someone else.
"""

from __future__ import annotations

import pytest

from dispatch.identity import Identity, ParticipantKey, keys_match, parse_patient_id


@pytest.mark.parametrize("text,expected", [
    ("AA-SNBR-001", ParticipantKey("SNBR", 1)),
    ("JS-SNBR-080", ParticipantKey("SNBR", 80)),
    ("SNBR-080", ParticipantKey("SNBR", 80)),
    ("snbr 080", ParticipantKey("SNBR", 80)),
    ("SNBR080", ParticipantKey("SNBR", 80)),
    ("  NIALS-12  ", ParticipantKey("NIALS", 12)),
    ("xx_quarts_007", ParticipantKey("QUARTS", 7)),
])
def test_prefix_is_ignored_and_study_plus_number_are_taken(text, expected):
    assert parse_patient_id(text) == expected


@pytest.mark.parametrize("text", ["", None, "080", "SNBR", "SNBR-080-FU", "080-SNBR"])
def test_cells_without_a_trailing_study_and_number_are_not_guessed(text):
    assert parse_patient_id(text) is None


def test_numeric_cell_is_not_a_key():
    """A bare number has no study, and numbers repeat across studies."""
    assert parse_patient_id(80) is None


def test_label_is_the_report_title_form():
    assert ParticipantKey("SNBR", 80).label() == "SNBR-080"
    assert ParticipantKey("", 80).label() == "080"


def test_json_round_trip():
    key = ParticipantKey("NIALS", 3)
    assert ParticipantKey.from_json(key.to_json()) == key


def test_keys_match_requires_same_study_when_the_report_names_one():
    assert keys_match(ParticipantKey("SNBR", 80), ParticipantKey("snbr", 80))
    assert not keys_match(ParticipantKey("SNBR", 80), ParticipantKey("NIALS", 80))
    assert not keys_match(ParticipantKey("SNBR", 80), ParticipantKey("SNBR", 81))


def test_a_report_without_a_study_matches_on_number_alone():
    assert keys_match(ParticipantKey("", 80), ParticipantKey("SNBR", 80))


def test_identity_completeness_names_what_is_missing():
    key = ParticipantKey("SNBR", 1)
    assert Identity(key, "AA-SNBR-001", "John Smith", "1234567").complete
    partial = Identity(key, "AA-SNBR-001", "John Smith", "  ")
    assert not partial.complete
    assert partial.missing_fields() == ["MRN"]
    assert Identity(key, "AA-SNBR-001", "", "").missing_fields() == ["name", "MRN"]


def test_one_field_present_still_identifies_the_patient():
    """The whole point: a blank MRN must not discard the name, or vice versa.

    Keying the stamp on ``complete`` threw away whichever field the enrolment
    log *did* have -- a report for a named patient went out anonymous because
    one cell was empty.
    """
    key = ParticipantKey("SNBR", 1)
    name_only = Identity(key, "AA-SNBR-001", "John Smith", "")
    mrn_only = Identity(key, "AA-SNBR-001", "   ", "1234567")

    for ident in (name_only, mrn_only):
        assert ident.identifying, "one field present is still an identity"
        assert ident.partial and not ident.complete

    both = Identity(key, "AA-SNBR-001", "John Smith", "1234567")
    assert both.identifying and both.complete and not both.partial


def test_neither_field_is_not_an_identity():
    key = ParticipantKey("SNBR", 1)
    for ident in (
        Identity(key, "AA-SNBR-001", "", ""),
        Identity(key, "AA-SNBR-001", "  ", "\t"),
    ):
        assert not ident.identifying
        assert not ident.partial and not ident.complete
