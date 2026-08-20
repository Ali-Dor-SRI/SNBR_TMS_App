"""What the load pipeline does when the folders are wrong.

``tests/test_iter_files.py`` covers file discovery itself, which returns ``[]``
rather than raising for a missing folder, an unreadable one, or one swallowed by
an overlapping exclusion. What was untested is what the pipeline *above* it then
does with that empty list -- and that is where the failure a user actually hits
comes from: on another machine the import stopped with a message that named the
folder they had just picked and said their files were not there.

The distinction that matters is raise-versus-empty. All of these raise today. If
a refactor turned one into "return an empty DataFrame", the app would carry on
and produce an empty CSV and a blank report instead of stopping -- silent
failure, which is far worse than a wrong message. These tests pin that.

They characterise current behaviour rather than assert desired behaviour. Two
known-imperfect messages are pinned deliberately and marked as such; neither is
fixed here.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processing.df_builder import (
    build_combined_dataframe,
    build_combined_dataframe_incremental,
)

MEM_TEXT = "Name: SNBR-001\nDate: 1/2/26\n"


def _write_mem(path: Path, text: str = MEM_TEXT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Nothing to parse must stop, not sail on
# ---------------------------------------------------------------------------

def test_a_missing_mem_folder_stops_the_build(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_combined_dataframe(tmp_path / "does_not_exist")


def test_an_empty_mem_folder_stops_the_build(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        build_combined_dataframe(empty)


def test_an_unreadable_mem_folder_stops_the_build(tmp_path, monkeypatch):
    """is_dir() says yes while scandir raises -- the case from the field.

    The folder passes every existence check the app makes, so this cannot be
    caught by validating paths up front.
    """
    blocked = tmp_path / "blocked"
    _write_mem(blocked / "a.MEM")

    real_scandir = os.scandir

    def fake_scandir(path=".", *args, **kwargs):
        if Path(path).name == "blocked":
            raise PermissionError(13, "Access is denied", str(path))
        return real_scandir(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", fake_scandir)

    assert blocked.is_dir(), "guard: the folder must still look fine to is_dir()"
    with pytest.raises(FileNotFoundError):
        build_combined_dataframe(blocked)


def test_a_missing_mem_folder_stops_the_incremental_build(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_combined_dataframe_incremental(tmp_path / "does_not_exist")


# ---------------------------------------------------------------------------
# The messages, as they actually are
# ---------------------------------------------------------------------------

def test_the_two_builders_report_a_missing_folder_differently(tmp_path):
    """Characterisation, not endorsement.

    The incremental builder distinguishes "folder is not there" from "folder has
    no MEM files". The full-parse builder does not -- it reports both as "No
    .MEM files found in", which is what makes a permissions problem or a typo'd
    path read as "your data is missing". Known and deliberately not fixed here;
    pinned so the difference is visible rather than folklore.
    """
    missing = tmp_path / "does_not_exist"

    with pytest.raises(FileNotFoundError) as full:
        build_combined_dataframe(missing)
    with pytest.raises(FileNotFoundError) as incremental:
        build_combined_dataframe_incremental(missing)

    assert "No .MEM files found in" in str(full.value)
    assert "does not exist" in str(incremental.value)


def test_the_message_names_the_folder_the_user_chose(tmp_path):
    """Whatever it says, it has to point at something actionable."""
    empty = tmp_path / "chosen folder"
    empty.mkdir()

    with pytest.raises(FileNotFoundError) as exc:
        build_combined_dataframe(empty)

    assert str(empty) in str(exc.value)


# ---------------------------------------------------------------------------
# The exclusion that swallowed the scan
# ---------------------------------------------------------------------------

def test_one_folder_for_both_mem_and_csp_still_finds_the_mem_files(tmp_path):
    """The bug that shipped: the CSP folder is passed to the MEM scan as an
    exclusion, so selecting one folder for both excluded everything and the
    error named the folder the files were sitting in.
    """
    shared = tmp_path / "shared"
    _write_mem(shared / "a.MEM")

    df = build_combined_dataframe(shared, shared)

    assert len(df) == 1, "the MEM file was excluded by its own CSP selection"


def test_a_cmap_folder_containing_the_mem_folder_does_not_exclude_it(tmp_path):
    """Picking Y:\\ or a parent for CMAP must not wipe out the MEM scan."""
    root = tmp_path / "root"
    mem = root / "MEM Data"
    _write_mem(mem / "a.MEM")

    df = build_combined_dataframe(mem, None, root)

    assert len(df) == 1, "the MEM folder was excluded by an enclosing CMAP folder"


def test_a_real_csp_subfolder_is_still_excluded_from_the_mem_scan(tmp_path):
    """The nested layout must keep working: CSP files stay out of the MEM parse.

    A CSP export often carries its own RMT200 for the visit and sorts before the
    TMS file for the same session, so one reaching the MEM parser wins the
    first-non-null coalesce and silently replaces the recording's RMT.
    """
    mem = tmp_path / "MEM Data"
    csp = mem / "CSP"
    _write_mem(mem / "SNBR-001-TP1.MEM")
    _write_mem(csp / "SNBR-001-CSP-TP1.MEM", MEM_TEXT + "CSPs-80(ms)=12.0\nCSPe-80(ms)=90.0\n")

    df = build_combined_dataframe(mem, csp)

    # The CSP data is merged onto the visit, but the CSP file must not appear
    # as a parsed MEM source in its own right.
    parsed = {
        name.strip()
        for value in df["source_file"].dropna()
        for name in str(value).split(";")
    }
    assert parsed == {"SNBR-001-TP1.MEM"}, (
        f"a CSP recording reached the MEM parser: {sorted(parsed)}"
    )
