"""Tests for the file-discovery helpers in ``parser.mem_parser``.

``iter_files`` / ``iter_mem_files`` walk the lab MEM folders on every load, so
they run on a network share where each extra round-trip is expensive. They are
built on ``os.scandir`` and de-duplicate on the *normalised* path rather than
on ``Path.resolve()``, which cost ~23s of a 25s scan on the real share.

These tests pin the behaviour de-duplication has to keep: overlapping roots,
excluded subfolders, recursive vs flat scans, arbitrary patterns, missing or
unreadable folders, and the same file reached by two different paths (a
junction) — while *not* collapsing two genuinely different files that happen
to share a name, size and timestamp.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser.mem_parser import iter_files, iter_mem_files


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _write(path: Path, text: str = "x") -> Path:
    """Create *path* (and parents) holding *text*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _names(paths) -> list[str]:
    return sorted(p.name for p in paths)


def _make_junction(link: Path, target: Path) -> bool:
    """Create a directory junction *link* -> *target*; False if unsupported.

    Junctions (unlike symlinks) need no elevation on Windows, but the call
    still fails on a filesystem without reparse-point support.
    """
    if os.name != "nt":
        try:
            link.symlink_to(target, target_is_directory=True)
            return True
        except (OSError, NotImplementedError):
            return False
    try:
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0 and link.exists()


# --------------------------------------------------------------------------
# Basic discovery
# --------------------------------------------------------------------------

def test_finds_files_recursively_and_flat(tmp_path):
    """``recursive=False`` returns only files directly inside each root."""
    _write(tmp_path / "top.MEM")
    _write(tmp_path / "sub" / "nested.MEM")
    _write(tmp_path / "sub" / "deeper" / "deep.MEM")

    assert _names(iter_files(tmp_path, "*.MEM")) == ["deep.MEM", "nested.MEM", "top.MEM"]
    assert _names(iter_files(tmp_path, "*.MEM", recursive=False)) == ["top.MEM"]


def test_pattern_filters_and_star_matches_everything(tmp_path):
    """The ``*`` pattern lists every file — cmap_parser filters PDF/DOCX itself."""
    _write(tmp_path / "a.MEM")
    _write(tmp_path / "b.pdf")
    _write(tmp_path / "sub" / "c.docx")

    assert _names(iter_files(tmp_path, "*.MEM")) == ["a.MEM"]
    assert _names(iter_files(tmp_path, "*")) == ["a.MEM", "b.pdf", "c.docx"]
    assert _names(iter_files(tmp_path, "*", recursive=False)) == ["a.MEM", "b.pdf"]
    assert _names(iter_files(tmp_path, "*.pdf")) == ["b.pdf"]


def test_pattern_spanning_folders_still_works(tmp_path):
    """A pattern with a separator has always been accepted — keep it working.

    Nothing in the app passes one (``*.MEM`` and ``*`` are the two patterns in
    use), and a filename test cannot express it, so those fall back to glob.
    """
    _write(tmp_path / "top.MEM")
    _write(tmp_path / "sub" / "a.MEM")
    _write(tmp_path / "sub" / "deeper" / "b.MEM")

    assert _names(iter_files(tmp_path, "sub/*.MEM", recursive=False)) == ["a.MEM"]
    assert _names(iter_files(tmp_path, "sub/*.MEM")) == ["a.MEM"]
    # "**" matches directories only, so it has always yielded no files.
    assert iter_files(tmp_path, "**") == []


def test_directories_are_not_returned_as_files(tmp_path):
    """A folder matching the pattern is a directory, not a result."""
    (tmp_path / "looks_like.MEM").mkdir()
    _write(tmp_path / "real.MEM")

    assert _names(iter_files(tmp_path, "*.MEM")) == ["real.MEM"]


def test_results_are_paths_sorted_by_string(tmp_path):
    """Discovery order feeds row coalescing, so the sort order is load-bearing."""
    _write(tmp_path / "b.MEM")
    _write(tmp_path / "a.MEM")
    _write(tmp_path / "sub" / "a.MEM")

    found = iter_files(tmp_path, "*.MEM")
    assert all(isinstance(p, Path) for p in found)
    assert [str(p) for p in found] == sorted(str(p) for p in found)


def test_multiple_roots_are_all_scanned(tmp_path):
    """A list of roots collects files from every one of them."""
    _write(tmp_path / "one" / "a.MEM")
    _write(tmp_path / "two" / "b.MEM")

    found = iter_files([tmp_path / "one", tmp_path / "two"], "*.MEM")
    assert _names(found) == ["a.MEM", "b.MEM"]


# --------------------------------------------------------------------------
# De-duplication
# --------------------------------------------------------------------------

def test_nested_roots_return_each_file_once(tmp_path):
    """The live lab config nests the CSP folder inside the MEM folder."""
    mem = tmp_path / "MEM Data"
    csp = mem / "CSP"
    _write(mem / "top.MEM")
    _write(csp / "csp1.MEM")

    for roots in ([mem, csp], [csp, mem]):
        found = iter_files(roots, "*.MEM")
        assert len(found) == 2, roots
        assert _names(found) == ["csp1.MEM", "top.MEM"]


def test_same_root_listed_twice_is_deduplicated(tmp_path):
    """Different spellings of one root must not double the file list."""
    _write(tmp_path / "a.MEM")
    _write(tmp_path / "sub" / "b.MEM")
    spellings = [
        tmp_path,
        str(tmp_path),
        str(tmp_path) + os.sep,
        str(tmp_path / "sub" / ".."),
    ]

    assert _names(iter_files(spellings, "*.MEM")) == ["a.MEM", "b.MEM"]


def test_duplicate_reachable_two_ways_is_returned_once(tmp_path):
    """A junction to a scanned folder must not re-list its files."""
    real = tmp_path / "real"
    _write(real / "a.MEM")
    _write(real / "sub" / "b.MEM")
    link = tmp_path / "link"
    if not _make_junction(link, real):
        pytest.skip("filesystem does not support junctions/symlinks")

    assert _names(iter_files([real, link], "*.MEM")) == ["a.MEM", "b.MEM"]
    # ...and the junction alone still finds them (it is a valid path).
    assert _names(iter_files(link, "*.MEM")) == ["a.MEM", "b.MEM"]


def test_junction_inside_a_scanned_tree_is_not_followed(tmp_path):
    """Matches ``Path.rglob``, which does not descend into linked folders."""
    root = tmp_path / "root"
    _write(root / "a.MEM")
    _write(root / "data" / "b.MEM")
    if not _make_junction(root / "loop", root / "data"):
        pytest.skip("filesystem does not support junctions/symlinks")

    assert _names(iter_files(root, "*.MEM")) == ["a.MEM", "b.MEM"]


def test_distinct_files_sharing_name_size_and_time_are_both_kept(tmp_path):
    """The cheap (name, size, mtime) key must not collapse real files.

    Two different recordings can share a filename, byte count and timestamp
    across folders; only a genuine same-file identity may drop one.
    """
    first = _write(tmp_path / "one" / "same.MEM", "AAAA")
    second = _write(tmp_path / "two" / "same.MEM", "BBBB")
    stamp = (1_600_000_000, 1_600_000_000)
    os.utime(first, stamp)
    os.utime(second, stamp)

    found = iter_files(tmp_path, "*.MEM")
    assert len(found) == 2
    assert {p.parent.name for p in found} == {"one", "two"}


# --------------------------------------------------------------------------
# Missing / unreadable folders
# --------------------------------------------------------------------------

def test_missing_directory_is_skipped(tmp_path):
    """A path the user typed wrong must not raise mid-load."""
    _write(tmp_path / "a.MEM")

    assert iter_files(tmp_path / "nope", "*.MEM") == []
    assert _names(iter_files([tmp_path, tmp_path / "nope"], "*.MEM")) == ["a.MEM"]
    assert iter_files(None, "*.MEM") == []
    assert iter_files("", "*.MEM") == []
    assert iter_mem_files(tmp_path / "nope") == []


def test_file_passed_as_a_root_is_skipped(tmp_path):
    """Only directories are scanned."""
    target = _write(tmp_path / "a.MEM")

    assert iter_files(target, "*.MEM") == []


def test_unreadable_directory_is_skipped(tmp_path, monkeypatch):
    """A permission error deep in the tree must not abort the whole scan."""
    _write(tmp_path / "ok.MEM")
    _write(tmp_path / "blocked" / "hidden.MEM")

    real_scandir = os.scandir

    def fake_scandir(path=".", *args, **kwargs):
        if Path(path).name == "blocked":
            raise PermissionError(13, "Access is denied", str(path))
        return real_scandir(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", fake_scandir)

    assert _names(iter_files(tmp_path, "*.MEM")) == ["ok.MEM"]


# --------------------------------------------------------------------------
# iter_mem_files — exclusions
# --------------------------------------------------------------------------

def test_exclude_dirs_drops_the_csp_subfolder(tmp_path):
    """CSP files use a different format and are parsed by CSP_parser."""
    mem = tmp_path / "MEM Data"
    csp = mem / "CSP"
    cmap = tmp_path / "Viking"
    _write(mem / "top.MEM")
    _write(mem / "sub" / "nested.MEM")
    _write(csp / "csp1.MEM")
    _write(csp / "deeper" / "csp2.MEM")
    _write(cmap / "vik.MEM")

    assert _names(iter_mem_files(mem)) == [
        "csp1.MEM", "csp2.MEM", "nested.MEM", "top.MEM",
    ]
    assert _names(iter_mem_files(mem, exclude_dirs=[csp])) == ["nested.MEM", "top.MEM"]
    assert _names(iter_mem_files([mem, cmap], exclude_dirs=[csp, cmap])) == [
        "nested.MEM", "top.MEM",
    ]
    # An excluded folder that is also a root yields nothing from that root.
    assert _names(iter_mem_files([mem, csp], exclude_dirs=[csp])) == [
        "nested.MEM", "top.MEM",
    ]


def test_exclude_dirs_tolerates_none_and_missing_entries(tmp_path):
    """The GUI passes ``[csp_dir, cmap_dir]`` with either possibly unset."""
    mem = tmp_path / "MEM Data"
    _write(mem / "top.MEM")

    assert _names(iter_mem_files(mem, exclude_dirs=None)) == ["top.MEM"]
    assert _names(iter_mem_files(mem, exclude_dirs=[None, ""])) == ["top.MEM"]
    assert _names(iter_mem_files(mem, exclude_dirs=[tmp_path / "gone"])) == ["top.MEM"]


def test_exclude_dirs_matches_only_whole_folder_names(tmp_path):
    """``CSP_extra`` is not inside ``CSP`` — a prefix test must not eat it."""
    mem = tmp_path / "MEM Data"
    _write(mem / "CSP" / "csp1.MEM")
    _write(mem / "CSP_extra" / "other.MEM")

    assert _names(iter_mem_files(mem, exclude_dirs=[mem / "CSP"])) == ["other.MEM"]


def test_exclude_dirs_recursive_flag(tmp_path):
    """Flat scans keep honouring exclusions."""
    mem = tmp_path / "MEM Data"
    _write(mem / "top.MEM")
    _write(mem / "CSP" / "csp1.MEM")

    assert _names(iter_mem_files(mem, exclude_dirs=[mem / "CSP"], recursive=False)) == ["top.MEM"]
    assert _names(iter_mem_files(mem, recursive=False)) == ["top.MEM"]


def test_exclude_dirs_reached_through_a_junction(tmp_path):
    """Excluding the real folder also excludes its junction spelling."""
    mem = tmp_path / "MEM Data"
    csp = mem / "CSP"
    _write(mem / "top.MEM")
    _write(csp / "csp1.MEM")
    link = tmp_path / "csp_link"
    if not _make_junction(link, csp):
        pytest.skip("filesystem does not support junctions/symlinks")

    assert _names(iter_mem_files([mem, link], exclude_dirs=[csp])) == ["top.MEM"]
    assert _names(iter_mem_files([mem, link], exclude_dirs=[link])) == ["top.MEM"]


@pytest.mark.skipif(os.name != "nt", reason="Windows path matching is case-insensitive")
def test_windows_matching_is_case_insensitive(tmp_path):
    """``*.MEM`` has always matched ``.mem`` on the lab Windows machines."""
    mem = tmp_path / "MEM Data"
    _write(mem / "lower.mem")
    _write(mem / "CSP" / "c.mem")

    assert _names(iter_files(mem, "*.MEM")) == ["c.mem", "lower.mem"]
    # Exclusions compare case-insensitively too.
    assert _names(iter_mem_files(mem, exclude_dirs=[str(mem / "csp").upper()])) == ["lower.mem"]


# --------------------------------------------------------------------------
# CSP and MEM sharing one folder
#
# Selecting the same folder for both is a supported layout: some sites keep the
# silent-period recordings beside the TMS ones. The folder-based exclusion
# cannot express that — excluding the CSP folder would exclude every MEM file —
# so the split is made by file content instead.
# --------------------------------------------------------------------------

CSP_BODY = """Name:\tSNBR-005
Date:\t13/02/2024
 EXTRA VARIABLES
CSPs-80(ms) = 12.5
CSPe-80(ms) = 45.0
"""

TMS_BODY = """Name:\tSNBR-005
Date:\t13/02/2024
 EXTRA VARIABLES
RMT200 = 45.2
"""


def _mixed_folder(tmp_path):
    d = tmp_path / "All MEM"
    d.mkdir()
    (d / "SNBR-005-TP2C40213A.MEM").write_text(TMS_BODY, encoding="utf-8")
    (d / "SNBR-005-CSP-TP2C40213A.MEM").write_text(CSP_BODY, encoding="utf-8")
    (d / "SNBR-006-TP2C40214A.MEM").write_text(TMS_BODY, encoding="utf-8")
    return d


def test_a_csp_recording_is_recognised_by_content_not_by_name(tmp_path):
    from parser.mem_parser import is_csp_recording

    d = _mixed_folder(tmp_path)
    # Named like a CSP file but holding no CSP values -> not a CSP recording.
    decoy = d / "SNBR-007-CSP-TP2C40215A.MEM"
    decoy.write_text(TMS_BODY, encoding="utf-8")
    # Named like a TMS file but holding CSP values -> is a CSP recording.
    hidden = d / "SNBR-008-TP2C40216A.MEM"
    hidden.write_text(CSP_BODY, encoding="utf-8")

    assert is_csp_recording(d / "SNBR-005-CSP-TP2C40213A.MEM") is True
    assert is_csp_recording(d / "SNBR-005-TP2C40213A.MEM") is False
    assert is_csp_recording(decoy) is False
    assert is_csp_recording(hidden) is True
    assert is_csp_recording(d / "nothing-here.MEM") is False


def test_the_same_folder_for_mem_and_csp_still_finds_the_mem_files(tmp_path):
    """The reported bug: identical folders excluded every file."""
    from processing.df_builder import mem_scan_exclusions

    d = _mixed_folder(tmp_path)
    # The CSP folder is dropped from the exclusion list because it IS the MEM
    # folder; excluding it would leave nothing to scan.
    assert mem_scan_exclusions(d, d, None) == []
    assert len(iter_mem_files(d, mem_scan_exclusions(d, d, None))) == 3


def test_a_csp_or_cmap_folder_above_the_mem_folder_is_not_excluded(tmp_path):
    from processing.df_builder import mem_scan_exclusions

    mem = tmp_path / "Merged" / "MEM Data"
    mem.mkdir(parents=True)
    (mem / "a.MEM").write_text(TMS_BODY, encoding="utf-8")

    # A parent folder chosen for CMAP would otherwise swallow the MEM tree.
    assert mem_scan_exclusions(mem, None, tmp_path / "Merged") == []
    assert len(iter_mem_files(mem, mem_scan_exclusions(mem, None, tmp_path / "Merged"))) == 1

    # A genuine sibling/subfolder exclusion is still honoured.
    csp = mem / "CSP"
    csp.mkdir()
    (csp / "b.MEM").write_text(CSP_BODY, encoding="utf-8")
    assert mem_scan_exclusions(mem, csp, None) == [csp]
    assert len(iter_mem_files(mem, mem_scan_exclusions(mem, csp, None))) == 1


def test_a_shared_folder_is_split_into_tms_and_csp_by_content(tmp_path):
    from processing.df_builder import split_shared_mem_csp_folder

    d = _mixed_folder(tmp_path)
    tms, csp = split_shared_mem_csp_folder(iter_mem_files(d, []))
    assert [f.name for f in csp] == ["SNBR-005-CSP-TP2C40213A.MEM"]
    assert sorted(f.name for f in tms) == [
        "SNBR-005-TP2C40213A.MEM", "SNBR-006-TP2C40214A.MEM",
    ]


def test_csp_recordings_do_not_reach_the_mem_parser_in_a_shared_folder(tmp_path):
    """A CSP export carries its own RMT; letting it through would win the
    coalesce and replace the TMS recording's value for that visit."""
    from processing.df_builder import build_combined_dataframe

    d = tmp_path / "All MEM"
    d.mkdir()
    (d / "SNBR-005-TP2C40213A.MEM").write_text(TMS_BODY, encoding="utf-8")
    (d / "SNBR-005-CSP-TP2C40213A.MEM").write_text(
        CSP_BODY.replace("CSPs-80(ms) = 12.5", "RMT200 = 40.8\nCSPs-80(ms) = 12.5"),
        encoding="utf-8",
    )

    df = build_combined_dataframe(d, d, None, mem_recursive=False, csp_recursive=False)
    row = df[df["ID"] == 5].iloc[0]
    assert row["RMT200"] == 45.2          # the TMS recording's value, not 40.8
    assert row["CSPs_80"] == 12.5         # and the CSP values still merged
