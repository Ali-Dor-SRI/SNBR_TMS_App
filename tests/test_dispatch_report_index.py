"""dispatch/report_index.py -- filenames in, keyed reports out."""

from __future__ import annotations

import os
import time
from datetime import date

import pytest

from dispatch.identity import ParticipantKey
from dispatch.report_index import parse_report_filename, scan_reports, sha256_of


@pytest.mark.parametrize("name,key,visit", [
    ("report_SNBR_080_20260818.pdf", ParticipantKey("SNBR", 80), date(2026, 8, 18)),
    ("report_SNBR_080_20260818_2.pdf", ParticipantKey("SNBR", 80), date(2026, 8, 18)),
    ("report_nials_003_20240422.pdf", ParticipantKey("NIALS", 3), date(2024, 4, 22)),
    ("report_080_20260818.pdf", ParticipantKey("", 80), date(2026, 8, 18)),
    ("report_SNBR_080.pdf", ParticipantKey("SNBR", 80), None),      # legacy name
    ("report_SNBR_080_3.pdf", ParticipantKey("SNBR", 80), None),    # legacy duplicate
    ("REPORT_SNBR_080_20260818.PDF", ParticipantKey("SNBR", 80), date(2026, 8, 18)),
])
def test_report_filenames_parse(name, key, visit):
    assert parse_report_filename(name) == (key, visit)


@pytest.mark.parametrize("name", [
    "SNBR-107_MEM_report_202604161509.pdf",   # the old timestamped name
    "SNBR_080_T-SICI_Profile_20260818.pdf",    # a graph export
    "df_20260818.csv",
    "report_SNBR_080_20261345.pdf",            # impossible date
    "report.pdf",
])
def test_other_files_are_not_reports(name):
    assert parse_report_filename(name) is None


def _touch(path, content=b"%PDF-1.4 fake", mtime=None):
    path.write_bytes(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_scan_indexes_reports_and_lists_the_rest(tmp_path):
    a = _touch(tmp_path / "report_SNBR_080_20260818.pdf", b"aaa")
    _touch(tmp_path / "report_SNBR_081_20260819.pdf", b"bbb")
    _touch(tmp_path / "SNBR_080_T-SICI_20260818.pdf", b"png-ish")
    _touch(tmp_path / "notes.txt", b"text")
    (tmp_path / "sub").mkdir()
    _touch(tmp_path / "sub" / "report_SNBR_082_20260820.pdf", b"ccc")

    index = scan_reports(tmp_path)
    assert [r.key.number for r in index.reports] == [80, 81]
    assert [p.name for p in index.unrecognised] == ["SNBR_080_T-SICI_20260818.pdf"]
    first = index.reports[0]
    assert first.path == a
    assert first.sha256 == sha256_of(a)
    assert first.size == 3
    assert first.visit_token == "20260818"
    assert first.visit_label == "18/08/2026"

    assert [r.key.number for r in scan_reports(tmp_path, recursive=True).reports] == [80, 81, 82]


def test_scan_order_is_stable_and_case_insensitive(tmp_path):
    for name in ("report_SNBR_090_20260101.pdf", "report_snbr_010_20260101.pdf", "report_SNBR_050_20260101.pdf"):
        _touch(tmp_path / name)
    assert [r.key.number for r in scan_reports(tmp_path).reports] == [10, 50, 90]


def test_missing_folder_raises_rather_than_returning_empty(tmp_path):
    """A typo'd path must never read as 'nothing to send'."""
    with pytest.raises(FileNotFoundError):
        scan_reports(tmp_path / "missing")


def test_hash_changes_with_content_and_mtime_is_recorded(tmp_path):
    old = time.time() - 30 * 86400
    path = _touch(tmp_path / "report_SNBR_080_20260818.pdf", b"v1", mtime=old)
    first = scan_reports(tmp_path).reports[0]
    assert abs(first.mtime.timestamp() - old) < 2
    _touch(path, b"v2")
    second = scan_reports(tmp_path).reports[0]
    assert second.sha256 != first.sha256


def test_legacy_name_has_unknown_visit(tmp_path):
    _touch(tmp_path / "report_SNBR_080.pdf")
    report = scan_reports(tmp_path).reports[0]
    assert report.visit_date is None
    assert report.visit_token == "unknown"
    assert report.visit_label == "unknown"
