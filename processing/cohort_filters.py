"""Reference-cohort restriction: one study, one hemisphere.

Report graphs draw the selected participant against a reference cohort of ALS
patients and healthy controls. Two rules narrow which rows may enter that
cohort — both applied here, both leaving the selected participant's own rows
untouched so their traces still render in full (including a both-cortex
overlay).

**One study.**  A participant is compared only against their own study, because
the studies differ in protocol and recruitment.  The archive does not always
support that: ``NIALS`` and ``QUARTS`` hold patients but no controls at all, and
a quarter of rows carry no study name.  Rather than emit an empty comparison,
the restriction is *dropped* whenever it would leave either group without usable
rows, and the caller labels the plot with the cohort it actually got
(:func:`cohort_scope_label`).

**One hemisphere.**  Each cohort member contributes a single
``Stimulated_cortex``, so a participant tested on both sides does not count
twice.  The hemisphere chosen is the one **contralateral to the dominant hand**
— the one that drives it — read from the ``Handedness`` column
(``parser.handedness``).  When handedness is unknown or a subject's own files
disagree, the fallback is the hemisphere of the **earliest-collected file**,
pinned for every later visit: the Qtrac filename suffix runs alphabetically in
acquisition order, so sorting by visit date then filename recovers that order.

Rows carrying no cortex at all are always kept — the peripheral
(stimulus-response, strength-duration) and nerve-conduction rows belong to the
visit rather than to a hemisphere.

**Subject identity is ``(Study, ID)``, not ``ID``.**  Participant numbers restart
in each study, so 41 of the archive's 182 numeric IDs name several different
people (``SNBR-003`` and ``NIALS-003`` are unrelated).  Keying these rules on the
number alone would let one person's handedness decide another's hemisphere, and
would read two people's single-hemisphere recordings as one both-hemisphere
subject.  The cost of the pair key is that a participant whose study name is
misspelled on some files (``NIAL`` for ``NIALS``) splits into two subjects and
simply goes un-thinned, which is the behaviour that predates this module.

Public API
----------
resolve_subject_handedness(df)               -> dict[(study, id), str]
resolve_analysis_cortex(df)                  -> dict[(study, id), str]
analysis_cortex_for(df, participant_id)      -> str | None
restrict_cohort_to_analysis_cortex(df, ...)  -> pd.DataFrame
participant_study(df, participant_id)        -> str | None
restrict_cohort_to_study(df, study, ...)     -> tuple[pd.DataFrame, bool]
cohort_scope_label(study, study_applied)     -> str
cohort_label_bases(study, study_applied)     -> tuple[str, str]
"""

from __future__ import annotations

import pandas as pd

from parser.handedness import HANDEDNESS_COLUMN, contralateral_cortex

CORTEX_COLUMN = "Stimulated_cortex"
STUDY_COLUMN = "Study"
_SUBJECT_TYPE_COLUMN = "Subject_type"
_SOURCE_FILE_COLUMN = "source_file"

# Cohort label bases the plotting layer expects, kept in the historical shape
# ("<study> ALS" / "<study> Controls") so nothing downstream has to change.
_ALS_SUFFIX = "ALS"
_CONTROL_SUFFIX = "Controls"
_ALL_STUDIES_LABEL = "All studies"

# Sorts after every real filename, so a row with no source_file falls to the end
# of an acquisition-order sort instead of winning it.
_SORTS_LAST = "￿"


# ---------------------------------------------------------------------------
# Column and subject-key helpers
# ---------------------------------------------------------------------------

def _text_series(df: pd.DataFrame, column: str) -> pd.Series:
    """Return *column* as stripped strings, missing values becoming empty."""
    if column not in df.columns:
        return pd.Series([""] * len(df), index=df.index, dtype="object")
    return df[column].astype("string").fillna("").str.strip().astype("object")


def _numeric_ids(df: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(df.get("ID"), errors="coerce")


def subject_key(study, participant_id) -> tuple[str, int] | None:
    """Return the ``(study, id)`` identity of one participant, or ``None``.

    The study is upper-cased so the archive's casing drift does not split a
    subject in two.  ``None`` when there is no usable participant number, since
    a row with no ID cannot be attributed to anyone.
    """
    if participant_id is None or pd.isna(participant_id):
        return None
    study_text = "" if study is None or pd.isna(study) else str(study).strip().upper()
    return (study_text, int(participant_id))


def _subject_keys(df: pd.DataFrame) -> pd.Series:
    """Return each row's ``(study, id)`` subject key, ``None`` where unknown."""
    studies = _text_series(df, STUDY_COLUMN).str.upper()
    ids = _numeric_ids(df)
    return pd.Series(
        [
            None if pd.isna(pid) else (str(study), int(pid))
            for study, pid in zip(studies, ids)
        ],
        index=df.index,
        dtype="object",
    )


def _earliest_file_sort_key(value) -> str:
    """Sort key for a row's ``source_file``, which may hold several names.

    ``df_builder`` joins the files that coalesced onto one row with ``"; "``.
    A row's position in acquisition order is set by its *earliest* file, so the
    smallest name is the key.  Compared case-insensitively because the archive
    mixes ``.MEM`` and ``.mem``.
    """
    names = [n.strip().lower() for n in str(value or "").split(";") if n.strip()]
    return min(names) if names else _SORTS_LAST


# ---------------------------------------------------------------------------
# Handedness -> analysis cortex
# ---------------------------------------------------------------------------

def resolve_subject_handedness(df: pd.DataFrame) -> dict:
    """Return the settled dominant hand per ``(study, id)`` subject.

    A subject appears only when every one of their files that states a
    handedness states the *same* one.  Subjects whose files disagree (a handful
    of data-entry inconsistencies in the archive) are left out entirely, as are
    those with no handedness recorded, so the caller falls back rather than
    picking one of two contradictory values.
    """
    if df is None or df.empty or HANDEDNESS_COLUMN not in df.columns:
        return {}

    frame = pd.DataFrame({
        "key": _subject_keys(df),
        "hand": _text_series(df, HANDEDNESS_COLUMN).str.upper(),
    })
    frame = frame[frame["key"].notna() & frame["hand"].isin(["L", "R"])]

    resolved: dict = {}
    for key, group in frame.groupby("key", sort=False):
        values = set(group["hand"])
        if len(values) == 1:
            resolved[key] = values.pop()
    return resolved


def resolve_analysis_cortex(df: pd.DataFrame) -> dict:
    """Return the hemisphere used for averages, per ``(study, id)`` subject.

    Only subjects that actually recorded a hemisphere appear.  A subject tested
    on one side gets that side, so the rules below decide only the ~20% of
    subjects tested on both.
    """
    if df is None or df.empty or CORTEX_COLUMN not in df.columns:
        return {}

    frame = pd.DataFrame({
        "key": _subject_keys(df),
        "cortex": _text_series(df, CORTEX_COLUMN).str.upper(),
        "date": pd.to_datetime(df.get("Date"), dayfirst=True, errors="coerce"),
        "file": _text_series(df, _SOURCE_FILE_COLUMN).map(_earliest_file_sort_key),
    })
    frame = frame[frame["key"].notna() & (frame["cortex"] != "")]
    if frame.empty:
        return {}

    handedness = resolve_subject_handedness(df)
    chosen: dict = {}
    for key, group in frame.groupby("key", sort=False):
        available = set(group["cortex"])
        if len(available) == 1:
            chosen[key] = next(iter(available))
            continue

        # Both hemispheres tested: prefer the one driving the dominant hand.
        preferred = contralateral_cortex(handedness.get(key))
        if preferred in available:
            chosen[key] = preferred
            continue

        # Handedness unknown or contradictory — pin the hemisphere of the
        # earliest-collected file and keep it for every later visit.
        ordered = group.sort_values(["date", "file"], na_position="last")
        chosen[key] = str(ordered["cortex"].iloc[0])
    return chosen


def analysis_cortex_for(
    df: pd.DataFrame, participant_id, study=None, visit_date=None,
) -> str | None:
    """Return the hemisphere one participant contributes to cohort averages.

    Resolves the participant's study when it is not supplied.  ``None`` when the
    participant has no hemisphere recorded at all.
    """
    if study is None:
        study = participant_study(df, participant_id, visit_date=visit_date)
    key = subject_key(study, participant_id)
    if key is None:
        return None
    return resolve_analysis_cortex(df).get(key)


def restrict_cohort_to_analysis_cortex(
    df: pd.DataFrame, exempt_id=None, exempt_study=None,
) -> pd.DataFrame:
    """Drop cohort rows recorded from a subject's non-analysis hemisphere.

    The selected participant — ``exempt_id``, narrowed to one subject by
    ``exempt_study`` when the caller knows it — passes through whole, so a visit
    tested on both sides still overlays both traces on their own graphs while
    contributing only one hemisphere to everyone else's averages.
    """
    if df is None or df.empty or CORTEX_COLUMN not in df.columns:
        return df

    chosen = resolve_analysis_cortex(df)
    if not chosen:
        return df

    keys = _subject_keys(df)
    cortex = _text_series(df, CORTEX_COLUMN).str.upper()
    expected = keys.map(lambda k: chosen.get(k) if k is not None else None)

    keep = (
        cortex.eq("")            # visit-level / peripheral rows carry no cortex
        | expected.isna()        # subject with no resolvable hemisphere
        | cortex.eq(expected)
    )
    keep = keep | _exempt_mask(df, exempt_id, exempt_study)
    return df[keep]


def _exempt_mask(df: pd.DataFrame, exempt_id, exempt_study) -> pd.Series:
    """Rows belonging to the participant a restriction must not touch.

    With *exempt_study* the match is the full subject key, so a same-numbered
    participant from another study is still restricted.  Without it the number
    alone is used — wider than ideal, but the caller has nothing better.
    """
    if exempt_id is None:
        return pd.Series(False, index=df.index)
    if exempt_study is None:
        return _numeric_ids(df).eq(exempt_id)
    key = subject_key(exempt_study, exempt_id)
    # Compared element by element: a tuple on the right of Series.eq would be
    # read as a list-like to align against, not as one value.
    return _subject_keys(df).map(lambda k: k == key).astype(bool)


# ---------------------------------------------------------------------------
# Study restriction
# ---------------------------------------------------------------------------

def participant_study(df: pd.DataFrame, participant_id, visit_date=None) -> str | None:
    """Return the study name recorded for *participant_id*, else ``None``.

    Participant numbers repeat across studies, so *visit_date* is used when
    given to pick the right one — a date narrows an ID to a single real person
    everywhere in the archive.  ``None`` covers both a missing participant and
    one whose rows carry no study name: neither can drive a study-restricted
    cohort.
    """
    if df is None or df.empty or participant_id is None:
        return None
    rows = df[_numeric_ids(df) == participant_id]
    if visit_date is not None and "Date" in rows.columns:
        dated = rows[rows["Date"].astype("string").str.strip() == str(visit_date).strip()]
        if not dated.empty:
            rows = dated
    if rows.empty:
        return None
    names = _text_series(rows, STUDY_COLUMN)
    names = names[names != ""]
    if names.empty:
        return None
    return str(names.iloc[0])


def _has_usable_rows(
    df: pd.DataFrame, subject_type: str, value_columns=None,
) -> bool:
    """Whether *df* holds at least one row of *subject_type* worth plotting.

    With *value_columns* the test is per-measure — a study whose controls exist
    but recorded nothing for this measure counts as unusable, which is what
    decides whether the study restriction can stand.  Without them it falls back
    to mere row presence.
    """
    types = _text_series(df, _SUBJECT_TYPE_COLUMN).str.capitalize()
    rows = df[types == subject_type]
    if rows.empty:
        return False
    if not value_columns:
        return True
    present = [c for c in value_columns if c in rows.columns]
    if not present:
        return True
    values = rows[present].apply(pd.to_numeric, errors="coerce")
    return bool(values.notna().any(axis=1).any())


def restrict_cohort_to_study(
    df: pd.DataFrame,
    study: str | None,
    exempt_id=None,
    value_columns=None,
) -> tuple[pd.DataFrame, bool]:
    """Restrict the reference cohort to one study where that is possible.

    Returns ``(dataframe, applied)``.  ``applied`` is ``False`` — and the frame
    comes back unfiltered — when *study* is unknown, or when restricting to it
    would leave either the patient or the control group with nothing to plot.
    That fallback is why the caller must label the plot from the returned flag
    rather than from the requested study.
    """
    if df is None or df.empty or not study or STUDY_COLUMN not in df.columns:
        return df, False

    names = _text_series(df, STUDY_COLUMN).str.upper()
    in_study = names == str(study).strip().upper()

    # The participant's own rows cannot vouch for their cohort, so they are held
    # out of the usability test even though they survive the filter.
    cohort = df[in_study & ~_exempt_mask(df, exempt_id, study)]
    if not (
        _has_usable_rows(cohort, "Patient", value_columns)
        and _has_usable_rows(cohort, "Control", value_columns)
    ):
        return df, False

    return df[in_study | _exempt_mask(df, exempt_id, study)], True


def cohort_scope_label(study: str | None, study_applied: bool) -> str:
    """Return the name of the cohort a plot actually drew from.

    Either the study name, when the restriction held, or a plain statement that
    it did not, so a pooled comparison can never be mistaken for a within-study
    one.
    """
    return str(study).strip() if (study_applied and study) else _ALL_STUDIES_LABEL


def cohort_label_bases(study: str | None, study_applied: bool) -> tuple[str, str]:
    """Return the patient/control legend label bases for a cohort."""
    base = cohort_scope_label(study, study_applied)
    return f"{base} {_ALS_SUFFIX}", f"{base} {_CONTROL_SUFFIX}"
