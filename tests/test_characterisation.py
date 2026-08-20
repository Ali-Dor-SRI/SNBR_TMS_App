"""Characterisation tests against the real lab share. Opt-in: ``--realdata``.

The point of this file is that the *next* refactor does not have to rebuild the
harness the last one used. That one lived in scratch scripts and is gone, so the
work of proving 8 commits changed nothing was thrown away with it.

What it does
------------
Builds the three load modes against the real folders, fingerprints each, and
compares that fingerprint against the one recorded on a previous run. The usual
sequence is:

    pytest tests/ -q --realdata          # before your change: records a baseline
    ...refactor...
    pytest tests/ -q --realdata          # after: fails on any cell that moved

The fingerprint covers the frame shape, the column list, the dtypes and a hash
per column, so a change to any cell in any column is caught -- not just a change
to the row count. It also covers file-discovery *order*, which is load-bearing
rather than cosmetic: it feeds the record list ``_coalesce_same_session_rows``
merges, where the first non-null value per column wins, so a reordering can
change cell values without changing the row count.

Why the baseline is not committed
---------------------------------
It is written to ``tests/output/``, which is gitignored. The hashes are derived
from patient data and this repository has two public remotes; and the share
grows as the lab collects, so a committed baseline would go stale and start
failing for the right reason at the wrong time. A baseline recorded on your own
machine, minutes before your change, is what actually answers "did I change
anything".

The first run records and passes with a note. Delete the file to re-baseline.

What it deliberately does not do
--------------------------------
No PDF byte comparison. ``reports.pdf_layout.generation_date_string`` stamps the
report, so a baseline captured yesterday differs from an identical build today
(~105 bytes). A date rollover mid-refactor would read as a regression.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser.mem_parser import iter_files, iter_mem_files, output_column_order
from processing.df_builder import (
    build_combined_dataframe,
    build_combined_dataframe_incremental,
    load_existing_csv,
)

pytestmark = pytest.mark.realdata

# The lab's live configuration. Missing pieces skip rather than fail: this file
# is opt-in, but a machine that opts in may still not have the share mounted.
MEM_DIR = Path(r"Y:\Merged Data\MEM Data")
CSP_DIR = Path(r"Y:\Merged Data\MEM Data\CSP")
CMAP_DIR = Path(r"Y:\Merged Data\Viking")
ARCHIVE_CSV = Path(
    r"C:\Users\Ali D\Desktop\Projects\TMS_out\df\df_SNBR_ID151_20260709.csv"
)

BASELINE = Path(__file__).resolve().parent / "output" / "realdata_fingerprint.json"


def _require(*paths: Path):
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        pytest.skip(f"not available on this machine: {', '.join(missing)}")


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------

def _column_hash(series: pd.Series) -> str:
    """A stable digest of one column's values, NaNs included."""
    # to_json normalises NaN/None and keeps float repr stable across runs.
    payload = series.to_json(orient="values", date_format="iso", default_handler=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def fingerprint(df: pd.DataFrame) -> dict:
    """Shape, columns, dtypes and a per-column digest.

    Sorted by source_file first so a change in row *order* does not masquerade
    as a change in row *content* -- discovery order is checked separately and
    on its own terms.
    """
    ordered = df.sort_values(
        by=[c for c in ("source_file", "ID", "Date") if c in df.columns],
        kind="stable",
    ).reset_index(drop=True)

    return {
        "shape": list(ordered.shape),
        "columns": list(ordered.columns),
        "dtypes": {c: str(t) for c, t in ordered.dtypes.items()},
        "column_hashes": {c: _column_hash(ordered[c]) for c in ordered.columns},
    }


def _diff(old: dict, new: dict) -> list[str]:
    """Human-readable differences between two fingerprints.

    Two kinds are stored: a DataFrame fingerprint (shape/columns/dtypes/hashes)
    and the plain nested dict recorded for file discovery. Anything without a
    "shape" key gets the generic key-by-key comparison.
    """
    if "shape" not in old or "shape" not in new:
        return _generic_diff(old, new)

    problems = []
    if old["shape"] != new["shape"]:
        problems.append(f"shape {old['shape']} -> {new['shape']}")

    lost = [c for c in old["columns"] if c not in new["columns"]]
    gained = [c for c in new["columns"] if c not in old["columns"]]
    if lost:
        problems.append(f"columns lost: {lost}")
    if gained:
        problems.append(f"columns gained: {gained}")

    for column in old["columns"]:
        if column not in new["column_hashes"]:
            continue
        if old["column_hashes"][column] != new["column_hashes"][column]:
            problems.append(f"values changed in column {column!r}")
        elif old["dtypes"].get(column) != new["dtypes"].get(column):
            problems.append(
                f"dtype of {column!r}: {old['dtypes'].get(column)} -> "
                f"{new['dtypes'].get(column)}"
            )
    return problems


def _generic_diff(old, new, path: str = "") -> list[str]:
    """Key-by-key comparison of two plain nested dicts."""
    if isinstance(old, dict) and isinstance(new, dict):
        problems = []
        for key in sorted(set(old) | set(new)):
            here = f"{path}.{key}" if path else str(key)
            if key not in old:
                problems.append(f"{here}: added ({new[key]!r})")
            elif key not in new:
                problems.append(f"{here}: removed (was {old[key]!r})")
            else:
                problems.extend(_generic_diff(old[key], new[key], here))
        return problems
    if old != new:
        return [f"{path}: {old!r} -> {new!r}"]
    return []


def _load_baseline() -> dict:
    if not BASELINE.exists():
        return {}
    try:
        return json.loads(BASELINE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_baseline(data: dict):
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps(data, indent=1), encoding="utf-8")


def _check_against_baseline(key: str, current: dict):
    """Compare *current* to the recorded fingerprint for *key*, or record it."""
    baseline = _load_baseline()
    previous = baseline.get(key)

    if previous is None:
        baseline[key] = current
        _save_baseline(baseline)
        pytest.skip(
            f"recorded a new baseline for {key!r} in {BASELINE.name}; "
            f"re-run --realdata after your change to compare against it"
        )

    problems = _diff(previous, current)
    assert not problems, (
        f"{key} differs from the recorded baseline:\n  "
        + "\n  ".join(problems)
        + f"\n\nIf the change is intended, delete {BASELINE} and re-run to "
          f"re-baseline."
    )


# ---------------------------------------------------------------------------
# The three load modes
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def full_parse():
    _require(MEM_DIR, CSP_DIR)
    return build_combined_dataframe(MEM_DIR, CSP_DIR, CMAP_DIR)


@pytest.fixture(scope="module")
def archive_as_is():
    _require(ARCHIVE_CSV)
    return load_existing_csv(ARCHIVE_CSV)


@pytest.fixture(scope="module")
def archive_plus_new():
    _require(MEM_DIR, CSP_DIR, ARCHIVE_CSV)
    return build_combined_dataframe_incremental(
        MEM_DIR, CSP_DIR, ARCHIVE_CSV, CMAP_DIR,
    )


def test_full_parse_matches_the_recorded_baseline(full_parse):
    _check_against_baseline("full_parse", fingerprint(full_parse))


def test_archive_as_is_matches_the_recorded_baseline(archive_as_is):
    _check_against_baseline("archive_as_is", fingerprint(archive_as_is))


def test_archive_plus_new_matches_the_recorded_baseline(archive_plus_new):
    _check_against_baseline("archive_plus_new", fingerprint(archive_plus_new))


# ---------------------------------------------------------------------------
# Facts that hold whatever the share currently contains
# ---------------------------------------------------------------------------

def test_every_load_mode_produces_the_same_schema(
    full_parse, archive_as_is, archive_plus_new,
):
    """A mode that quietly drops a column would give a differently-shaped CSV."""
    schemas = {
        "full_parse": list(full_parse.columns),
        "archive_as_is": list(archive_as_is.columns),
        "archive_plus_new": list(archive_plus_new.columns),
    }
    reference = schemas["full_parse"]
    for name, columns in schemas.items():
        assert columns == reference, (
            f"{name} has a different column list from full_parse: "
            f"missing {[c for c in reference if c not in columns]}, "
            f"extra {[c for c in columns if c not in reference]}"
        )


def test_the_canonical_columns_are_all_present(full_parse):
    """output_column_order() is the schema every downstream module depends on."""
    missing = [c for c in output_column_order() if c not in full_parse.columns]
    assert not missing, f"columns missing from a full parse: {missing}"


def test_a_full_parse_finds_more_than_the_archive_holds(full_parse, archive_as_is):
    """Guard against a fingerprint recorded from an empty or truncated parse."""
    assert len(full_parse) > 0
    assert len(archive_as_is) > 0
    assert len(full_parse) >= len(archive_as_is)


# ---------------------------------------------------------------------------
# Discovery order
# ---------------------------------------------------------------------------

def test_file_discovery_order_matches_the_recorded_baseline():
    """Order feeds _coalesce_same_session_rows, where first-non-null wins.

    A reordering can therefore change cell values without changing the row
    count -- which is exactly the kind of change a shape check would miss.
    """
    _require(MEM_DIR, CSP_DIR)

    discovered = {
        "iter_files": [str(p) for p in iter_files(MEM_DIR, "*.MEM", recursive=True)],
        "iter_mem_files": [
            str(p) for p in iter_mem_files(
                MEM_DIR, recursive=True, exclude_dirs=[CSP_DIR],
            )
        ],
    }

    current = {
        name: {
            "count": len(paths),
            "digest": hashlib.sha256(
                "\n".join(paths).encode("utf-8")
            ).hexdigest()[:16],
        }
        for name, paths in discovered.items()
    }

    assert current["iter_files"]["count"] > 0, "no MEM files discovered at all"
    _check_against_baseline("discovery", current)


def test_discovery_returns_each_file_once():
    """The CSP folder sits inside the MEM folder; nothing may be listed twice."""
    _require(MEM_DIR)
    found = iter_files(MEM_DIR, "*.MEM", recursive=True)
    seen = [str(p).lower() for p in found]
    assert len(seen) == len(set(seen)), (
        f"{len(seen) - len(set(seen))} duplicate path(s) returned"
    )
