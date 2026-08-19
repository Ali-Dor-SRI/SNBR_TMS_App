"""Tests for the reference-cohort restriction: one study, one hemisphere.

Two rules narrow which rows may enter a plot's reference cohort. Each cohort
member contributes a single ``Stimulated_cortex`` — the one contralateral to
their dominant hand, falling back to their earliest-collected file when the
.MEM archive does not say which hand that is — and the cohort is drawn from the
selected participant's own study whenever that study can actually supply both a
patient and a control group.

These tests cover the header parsing that recovers handedness (in both of the
formats Qtrac has written over the years), the hemisphere and study rules built
on it, the ``(Study, ID)`` subject identity those rules depend on, and the
labels that tell the reader which cohort a figure actually drew.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser.handedness import (
    HANDEDNESS_COLUMN,
    contralateral_cortex,
    extract_handedness,
)
from parser.mem_parser import output_column_order, parse_mem_file
from processing.cohort_filters import (
    analysis_cortex_for,
    cohort_label_bases,
    cohort_scope_label,
    participant_study,
    resolve_analysis_cortex,
    resolve_subject_handedness,
    restrict_cohort_to_analysis_cortex,
    restrict_cohort_to_study,
)

# --------------------------------------------------------------------------
# Fixtures — the real Qtrac header layout (leading space, tab before value).
# --------------------------------------------------------------------------

_HEADER = """\
 Name:              \tSNBR-{pid:03d}
 Protocol:          \tQTMSG18S
 Date:              \t{date}
 Age:               \t42
 Sex:               \tM
 TMS Coil:          \tMagStim D70^2
{handed_line}
 Stim/record:       \t{cortex}->{side}
 Muscle:            \tFDI
 Subject type:      \tPatient

  EXTRA VARIABLES
RMT50 = 60
"""


def _write_mem(tmp_path, name, *, pid=1, date="1/2/26", cortex="L", side="R",
               handed_line=" L- or R-handed:    \tR"):
    path = tmp_path / name
    path.write_text(
        _HEADER.format(
            pid=pid, date=date, cortex=cortex, side=side, handed_line=handed_line,
        ),
        encoding="utf-8",
    )
    return path


def _rows(*specs) -> pd.DataFrame:
    """Build a minimal cohort frame from ``(id, study, type, cortex, hand, file)``."""
    records = []
    for pid, study, subject_type, cortex, hand, source in specs:
        records.append({
            "ID": pid,
            "Study": study,
            "Date": "01/02/2026",
            "Subject_type": subject_type,
            "Stimulated_cortex": cortex,
            HANDEDNESS_COLUMN: hand,
            "source_file": source,
            "T_SICI_avg": 50.0,
        })
    return pd.DataFrame(records)


# --------------------------------------------------------------------------
# Handedness parsing
# --------------------------------------------------------------------------

def test_extract_handedness_reads_the_current_field_format():
    assert extract_handedness("L- or R-handed:    \tR") == "R"
    assert extract_handedness("L- or R-handed:    \tL") == "L"


def test_extract_handedness_reads_the_older_prose_format():
    """Pre-2024 exports name no field at all — the whole line is the value."""
    assert extract_handedness("Subject right-handed") == "R"
    assert extract_handedness("Subject left-handed") == "L"


def test_extract_handedness_returns_none_rather_than_guessing():
    assert extract_handedness("L- or R-handed:") is None
    assert extract_handedness("Stim/record:       \tL->R") is None
    assert extract_handedness("Sex:               \tM") is None


def test_contralateral_cortex_maps_hand_to_the_hemisphere_driving_it():
    assert contralateral_cortex("R") == "L"
    assert contralateral_cortex("L") == "R"
    assert contralateral_cortex(None) is None


def test_handedness_is_parsed_into_the_record_schema(tmp_path):
    assert HANDEDNESS_COLUMN in output_column_order()
    record = parse_mem_file(_write_mem(tmp_path, "a.MEM"))
    assert record[HANDEDNESS_COLUMN] == "R"


def test_handedness_is_parsed_from_the_older_prose_header(tmp_path):
    record = parse_mem_file(
        _write_mem(tmp_path, "b.MEM", handed_line=" Subject left-handed")
    )
    assert record[HANDEDNESS_COLUMN] == "L"


def test_missing_handedness_header_leaves_the_column_empty(tmp_path):
    record = parse_mem_file(_write_mem(tmp_path, "c.MEM", handed_line=""))
    assert record[HANDEDNESS_COLUMN] is None
    # The line's absence must not disturb the fields around it.
    assert record["Stimulated_cortex"] == "L"
    assert record["Subject_type"] == "Patient"


# --------------------------------------------------------------------------
# Hemisphere selection
# --------------------------------------------------------------------------

def test_both_cortex_subject_keeps_the_hemisphere_driving_the_dominant_hand():
    df = _rows(
        (1, "SNBR", "Patient", "L", "R", "aA.MEM"),
        (1, "SNBR", "Patient", "R", "R", "aB.MEM"),
    )
    assert resolve_analysis_cortex(df) == {("SNBR", 1): "L"}
    kept = restrict_cohort_to_analysis_cortex(df)
    assert list(kept["Stimulated_cortex"]) == ["L"]


def test_left_handed_subject_keeps_the_right_hemisphere():
    df = _rows(
        (1, "SNBR", "Patient", "L", "L", "aA.MEM"),
        (1, "SNBR", "Patient", "R", "L", "aB.MEM"),
    )
    assert resolve_analysis_cortex(df) == {("SNBR", 1): "R"}


def test_single_cortex_subject_is_untouched_whatever_their_handedness():
    """Only a subject tested on both sides has anything to choose between."""
    df = _rows((1, "SNBR", "Patient", "R", "R", "aA.MEM"))
    assert resolve_analysis_cortex(df) == {("SNBR", 1): "R"}
    assert len(restrict_cohort_to_analysis_cortex(df)) == 1


def test_unknown_handedness_falls_back_to_the_earliest_collected_file():
    """The Qtrac filename suffix runs alphabetically in acquisition order."""
    df = _rows(
        (1, "SNBR", "Patient", "L", None, "TD2C60112B.MEM"),
        (1, "SNBR", "Patient", "R", None, "TD2C60112A.MEM"),
    )
    assert resolve_analysis_cortex(df) == {("SNBR", 1): "R"}


def test_earliest_file_choice_is_pinned_across_later_visits():
    df = pd.DataFrame([
        # First visit: R recorded first, so R is the subject's hemisphere.
        {"ID": 1, "Study": "SNBR", "Date": "01/02/2026", "Subject_type": "Patient",
         "Stimulated_cortex": "R", HANDEDNESS_COLUMN: None, "source_file": "TD2C60112A.MEM"},
        {"ID": 1, "Study": "SNBR", "Date": "01/02/2026", "Subject_type": "Patient",
         "Stimulated_cortex": "L", HANDEDNESS_COLUMN: None, "source_file": "TD2C60112B.MEM"},
        # A later visit whose first file is L must not flip the choice.
        {"ID": 1, "Study": "SNBR", "Date": "01/08/2026", "Subject_type": "Patient",
         "Stimulated_cortex": "L", HANDEDNESS_COLUMN: None, "source_file": "TD2C60801A.MEM"},
    ])
    assert resolve_analysis_cortex(df) == {("SNBR", 1): "R"}
    kept = restrict_cohort_to_analysis_cortex(df)
    assert set(kept["Stimulated_cortex"]) == {"R"}


def test_conflicting_handedness_falls_back_to_the_earliest_file():
    """A subject whose own files disagree gets no handedness rule applied."""
    df = _rows(
        (1, "SNBR", "Patient", "L", "R", "zB.MEM"),
        (1, "SNBR", "Patient", "R", "L", "aA.MEM"),
    )
    assert resolve_subject_handedness(df) == {}
    assert resolve_analysis_cortex(df) == {("SNBR", 1): "R"}


def test_rows_without_a_cortex_are_always_kept():
    """Peripheral SR/SD and nerve-conduction rows belong to the visit, not a side."""
    df = _rows(
        (1, "SNBR", "Patient", "L", "R", "aA.MEM"),
        (1, "SNBR", "Patient", "R", "R", "aB.MEM"),
        (1, "SNBR", "Patient", None, "R", "aSR.MEM"),
    )
    kept = restrict_cohort_to_analysis_cortex(df)
    assert sorted(kept["source_file"]) == ["aA.MEM", "aSR.MEM"]


def test_selected_participant_keeps_both_hemispheres():
    """Their own graphs overlay both sides; only the cohort is thinned."""
    df = _rows(
        (1, "SNBR", "Patient", "L", "R", "aA.MEM"),
        (1, "SNBR", "Patient", "R", "R", "aB.MEM"),
        (2, "SNBR", "Control", "L", "R", "bA.MEM"),
        (2, "SNBR", "Control", "R", "R", "bB.MEM"),
    )
    kept = restrict_cohort_to_analysis_cortex(df, exempt_id=1, exempt_study="SNBR")
    assert sorted(kept[kept["ID"] == 1]["Stimulated_cortex"]) == ["L", "R"]
    assert list(kept[kept["ID"] == 2]["Stimulated_cortex"]) == ["L"]


# --------------------------------------------------------------------------
# (Study, ID) subject identity
# --------------------------------------------------------------------------

def test_same_participant_number_in_two_studies_stays_two_subjects():
    """SNBR-003 and NIALS-003 are different people; 41 archive IDs collide."""
    df = _rows(
        (3, "SNBR", "Patient", "L", "R", "aA.MEM"),
        (3, "NIALS", "Patient", "R", "L", "bA.MEM"),
    )
    assert resolve_analysis_cortex(df) == {("SNBR", 3): "L", ("NIALS", 3): "R"}
    # Neither is tested on both sides, so nothing is dropped.
    assert len(restrict_cohort_to_analysis_cortex(df)) == 2


def test_a_colliding_id_does_not_borrow_the_other_subjects_handedness():
    df = _rows(
        # SNBR-003 tested on both sides and is right-handed -> keeps L.
        (3, "SNBR", "Patient", "L", "R", "aA.MEM"),
        (3, "SNBR", "Patient", "R", "R", "aB.MEM"),
        # NIALS-003 is a different, left-handed person.
        (3, "NIALS", "Patient", "R", "L", "bA.MEM"),
    )
    kept = restrict_cohort_to_analysis_cortex(df)
    assert sorted(kept["source_file"]) == ["aA.MEM", "bA.MEM"]


def test_exempting_by_number_alone_is_narrowed_by_the_study():
    df = _rows(
        (3, "SNBR", "Patient", "L", "R", "aA.MEM"),
        (3, "SNBR", "Patient", "R", "R", "aB.MEM"),
        (3, "NIALS", "Control", "L", "R", "bA.MEM"),
        (3, "NIALS", "Control", "R", "R", "bB.MEM"),
    )
    kept = restrict_cohort_to_analysis_cortex(df, exempt_id=3, exempt_study="SNBR")
    assert sorted(kept[kept["Study"] == "SNBR"]["Stimulated_cortex"]) == ["L", "R"]
    assert list(kept[kept["Study"] == "NIALS"]["Stimulated_cortex"]) == ["L"]


def test_participant_study_uses_the_visit_date_to_break_a_number_collision():
    df = pd.DataFrame([
        {"ID": 3, "Study": "SNBR", "Date": "01/02/2026"},
        {"ID": 3, "Study": "NIALS", "Date": "05/09/2022"},
    ])
    assert participant_study(df, 3, visit_date="05/09/2022") == "NIALS"
    assert participant_study(df, 3, visit_date="01/02/2026") == "SNBR"


def test_analysis_cortex_for_resolves_one_participants_hemisphere():
    df = _rows(
        (1, "SNBR", "Patient", "L", "R", "aA.MEM"),
        (1, "SNBR", "Patient", "R", "R", "aB.MEM"),
    )
    assert analysis_cortex_for(df, 1) == "L"
    assert analysis_cortex_for(df, 99) is None


# --------------------------------------------------------------------------
# Study restriction and its fallback
# --------------------------------------------------------------------------

def test_study_restriction_applies_when_the_study_has_both_groups():
    df = _rows(
        (1, "SNBR", "Patient", "L", "R", "aA.MEM"),
        (2, "SNBR", "Patient", "L", "R", "bA.MEM"),
        (3, "SNBR", "Control", "L", "R", "cA.MEM"),
        (4, "NIALS", "Patient", "L", "R", "dA.MEM"),
    )
    restricted, applied = restrict_cohort_to_study(df, "SNBR", exempt_id=1)
    assert applied is True
    assert set(restricted["Study"]) == {"SNBR"}


def test_study_restriction_falls_back_when_the_study_has_no_controls():
    """NIALS and QUARTS hold patients but no controls anywhere in the archive."""
    df = _rows(
        (1, "NIALS", "Patient", "L", "R", "aA.MEM"),
        (2, "NIALS", "Patient", "L", "R", "bA.MEM"),
        (3, "SNBR", "Control", "L", "R", "cA.MEM"),
    )
    restricted, applied = restrict_cohort_to_study(df, "NIALS", exempt_id=1)
    assert applied is False
    assert len(restricted) == len(df)


def test_study_restriction_falls_back_when_only_the_participant_supports_it():
    """A participant's own rows cannot vouch for the cohort they are drawn against."""
    df = _rows(
        (1, "SNBR", "Patient", "L", "R", "aA.MEM"),
        (2, "SNBR", "Control", "L", "R", "bA.MEM"),
        (3, "NIALS", "Patient", "L", "R", "cA.MEM"),
    )
    restricted, applied = restrict_cohort_to_study(df, "SNBR", exempt_id=1)
    assert applied is False


def test_study_restriction_falls_back_when_the_measure_has_no_control_values():
    """Controls exist, but none recorded this measure — same as having none."""
    df = _rows(
        (1, "SNBR", "Patient", "L", "R", "aA.MEM"),
        (2, "SNBR", "Patient", "L", "R", "bA.MEM"),
        (3, "SNBR", "Control", "L", "R", "cA.MEM"),
        (4, "NIALS", "Control", "L", "R", "dA.MEM"),
    )
    df["CSP_120"] = [220.0, 210.0, None, 205.0]
    _, applied = restrict_cohort_to_study(
        df, "SNBR", exempt_id=1, value_columns=["CSP_120"],
    )
    assert applied is False
    # The same cohort is fine for a measure the controls did record.
    _, applied_tsici = restrict_cohort_to_study(
        df, "SNBR", exempt_id=1, value_columns=["T_SICI_avg"],
    )
    assert applied_tsici is True


def test_unknown_study_never_restricts():
    df = _rows(
        (1, None, "Patient", "L", "R", "aA.MEM"),
        (2, "SNBR", "Control", "L", "R", "bA.MEM"),
    )
    restricted, applied = restrict_cohort_to_study(df, None, exempt_id=1)
    assert applied is False
    assert len(restricted) == len(df)


def test_restricted_participant_rows_survive_the_study_filter():
    df = _rows(
        (1, "SNBR", "Patient", "L", "R", "aA.MEM"),
        (2, "SNBR", "Patient", "L", "R", "bA.MEM"),
        (3, "SNBR", "Control", "L", "R", "cA.MEM"),
    )
    restricted, applied = restrict_cohort_to_study(df, "SNBR", exempt_id=1)
    assert applied is True
    assert 1 in set(restricted["ID"])


# --------------------------------------------------------------------------
# Labels
# --------------------------------------------------------------------------

def test_labels_name_the_study_when_the_restriction_held():
    assert cohort_label_bases("SNBR", True) == ("SNBR ALS", "SNBR Controls")
    assert cohort_scope_label("SNBR", True) == "SNBR"


def test_labels_say_so_when_the_cohort_was_pooled_instead():
    """A pooled comparison must never read as a within-study one."""
    assert cohort_label_bases("NIALS", False) == (
        "All studies ALS", "All studies Controls",
    )
    assert cohort_scope_label(None, False) == "All studies"


# --------------------------------------------------------------------------
# Empty / degenerate input
# --------------------------------------------------------------------------

@pytest.mark.parametrize("df", [
    pd.DataFrame(),
    pd.DataFrame({"ID": [], "Study": [], "Stimulated_cortex": []}),
])
def test_empty_frames_pass_through_unchanged(df):
    assert resolve_analysis_cortex(df) == {}
    assert resolve_subject_handedness(df) == {}
    assert len(restrict_cohort_to_analysis_cortex(df)) == 0
    restricted, applied = restrict_cohort_to_study(df, "SNBR")
    assert applied is False


def test_frame_without_the_handedness_column_still_resolves_a_hemisphere():
    """An archive predating the column falls back to the earliest file."""
    df = _rows(
        (1, "SNBR", "Patient", "L", None, "aB.MEM"),
        (1, "SNBR", "Patient", "R", None, "aA.MEM"),
    ).drop(columns=[HANDEDNESS_COLUMN])
    assert resolve_analysis_cortex(df) == {("SNBR", 1): "R"}
