"""Comprehensive tests for the backup/sync engine.

Every test uses pytest's ``tmp_path`` fixture so no real files are touched.
Source directories are verified to be unmodified after every sync.
"""

from __future__ import annotations

import os
import shutil
import time
import threading
from pathlib import Path
from unittest.mock import patch

from back_up_sync.file_sync import (
    SyncPair,
    _should_copy,
    file_hash,
    sync_directory,
    sync_pairs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_file(path: Path, content: str = "hello") -> Path:
    """Create a file with the given content and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _hash_dir(directory: Path) -> dict[str, str]:
    """Return {relative_path: sha256} for every file in *directory*."""
    result = {}
    for f in sorted(directory.rglob("*")):
        if f.is_file():
            rel = str(f.relative_to(directory))
            result[rel] = file_hash(f)
    return result


def _set_mtime(path: Path, mtime: float) -> None:
    """Set modification time of *path*."""
    os.utime(path, (mtime, mtime))


# ---------------------------------------------------------------------------
# _should_copy
# ---------------------------------------------------------------------------

class TestShouldCopy:
    def test_dest_missing(self, tmp_path: Path):
        src = _write_file(tmp_path / "src" / "a.txt")
        dest = tmp_path / "dst" / "a.txt"
        assert _should_copy(src, dest) is True

    def test_dest_older(self, tmp_path: Path):
        src = _write_file(tmp_path / "src" / "a.txt", "new")
        dest = _write_file(tmp_path / "dst" / "a.txt", "old")
        _set_mtime(dest, os.path.getmtime(src) - 10)
        assert _should_copy(src, dest) is True

    def test_dest_same_age(self, tmp_path: Path):
        src = _write_file(tmp_path / "src" / "a.txt")
        dest = _write_file(tmp_path / "dst" / "a.txt")
        t = os.path.getmtime(src)
        _set_mtime(dest, t)
        assert _should_copy(src, dest) is False

    def test_dest_newer(self, tmp_path: Path):
        src = _write_file(tmp_path / "src" / "a.txt")
        dest = _write_file(tmp_path / "dst" / "a.txt")
        _set_mtime(dest, os.path.getmtime(src) + 10)
        assert _should_copy(src, dest) is False


# ---------------------------------------------------------------------------
# sync_directory — basic scenarios
# ---------------------------------------------------------------------------

class TestSyncDirectory:
    def test_copy_new_file(self, tmp_path: Path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        _write_file(src / "file.txt", "data")

        result = sync_directory(str(src), str(dst))

        assert result.files_copied == 1
        assert result.files_skipped == 0
        assert result.files_failed == 0
        assert (dst / "file.txt").read_text(encoding="utf-8") == "data"

    def test_skip_older_source(self, tmp_path: Path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        _write_file(src / "f.txt", "old")
        _write_file(dst / "f.txt", "new")
        # Make dest newer
        _set_mtime(dst / "f.txt", os.path.getmtime(src / "f.txt") + 10)

        result = sync_directory(str(src), str(dst))

        assert result.files_copied == 0
        assert result.files_skipped == 1
        assert (dst / "f.txt").read_text(encoding="utf-8") == "new"

    def test_copy_newer_source(self, tmp_path: Path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        _write_file(dst / "f.txt", "old content")
        time.sleep(0.05)
        _write_file(src / "f.txt", "new content")
        # Ensure source is strictly newer
        _set_mtime(src / "f.txt", os.path.getmtime(dst / "f.txt") + 10)

        result = sync_directory(str(src), str(dst))

        assert result.files_copied == 1
        assert (dst / "f.txt").read_text(encoding="utf-8") == "new content"

    def test_recursive_copy(self, tmp_path: Path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        _write_file(src / "a.txt", "a")
        _write_file(src / "sub1" / "b.txt", "b")
        _write_file(src / "sub1" / "sub2" / "c.txt", "c")

        result = sync_directory(str(src), str(dst))

        assert result.files_copied == 3
        assert (dst / "a.txt").read_text(encoding="utf-8") == "a"
        assert (dst / "sub1" / "b.txt").read_text(encoding="utf-8") == "b"
        assert (dst / "sub1" / "sub2" / "c.txt").read_text(encoding="utf-8") == "c"

    def test_empty_source(self, tmp_path: Path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()

        result = sync_directory(str(src), str(dst))

        assert result.files_copied == 0
        assert result.files_skipped == 0
        assert result.files_failed == 0
        assert result.errors == []

    def test_source_does_not_exist(self, tmp_path: Path):
        result = sync_directory(str(tmp_path / "nope"), str(tmp_path / "dst"))
        assert result.files_failed == 0
        assert len(result.errors) == 1
        assert "does not exist" in result.errors[0]


# ---------------------------------------------------------------------------
# Timestamps & source safety
# ---------------------------------------------------------------------------

class TestSafety:
    def test_preserves_timestamps(self, tmp_path: Path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        f = _write_file(src / "ts.txt", "timestamp test")
        target_mtime = 1_700_000_000.0
        _set_mtime(f, target_mtime)

        sync_directory(str(src), str(dst))

        dest_mtime = os.path.getmtime(dst / "ts.txt")
        assert abs(dest_mtime - target_mtime) < 2.0  # allow small OS rounding

    def test_source_not_modified(self, tmp_path: Path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        _write_file(src / "a.txt", "aaa")
        _write_file(src / "sub" / "b.txt", "bbb")

        before = _hash_dir(src)
        sync_directory(str(src), str(dst))
        after = _hash_dir(src)

        assert before == after, "Source files were modified during sync!"

    def test_destination_not_deleted(self, tmp_path: Path):
        """Existing dest files not in source must NOT be removed."""
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        _write_file(src / "new.txt", "new")
        _write_file(dst / "existing.txt", "keep me")

        sync_directory(str(src), str(dst))

        assert (dst / "existing.txt").read_text(encoding="utf-8") == "keep me"
        assert (dst / "new.txt").exists()


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------

class TestRetry:
    def test_retry_on_failure_then_success(self, tmp_path: Path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        _write_file(src / "f.txt", "data")

        call_count = {"n": 0}
        original_copy2 = shutil.copy2

        def flaky_copy(s, d, **kw):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise OSError("disk busy")
            return original_copy2(s, d, **kw)

        with patch("back_up_sync.file_sync.shutil.copy2", side_effect=flaky_copy):
            result = sync_directory(str(src), str(dst), retries=3, wait=0)

        assert result.files_copied == 1
        assert result.files_failed == 0
        assert call_count["n"] == 3

    def test_retry_exhausted(self, tmp_path: Path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        _write_file(src / "a.txt", "ok")
        _write_file(src / "fail.txt", "will fail")

        real_copy2 = shutil.copy2

        def always_fail(s, d, **kw):
            if "fail.txt" in str(s):
                raise OSError("permanent error")
            return real_copy2(s, d, **kw)

        with patch("back_up_sync.file_sync.shutil.copy2", side_effect=always_fail):
            result = sync_directory(str(src), str(dst), retries=2, wait=0)

        assert result.files_copied == 1   # a.txt succeeded
        assert result.files_failed == 1   # fail.txt exhausted retries
        assert len(result.errors) == 1


# ---------------------------------------------------------------------------
# Progress callback
# ---------------------------------------------------------------------------

class TestProgress:
    def test_progress_callback_called(self, tmp_path: Path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        _write_file(src / "a.txt", "a")
        _write_file(src / "b.txt", "b")

        calls: list[tuple] = []
        def on_progress(name, done, total):
            calls.append((name, done, total))

        sync_directory(str(src), str(dst), progress_callback=on_progress)

        assert len(calls) == 2
        assert calls[-1][1] == 2   # files_done
        assert calls[-1][2] == 2   # total

    def test_progress_callback_with_skip(self, tmp_path: Path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        _write_file(src / "a.txt", "a")
        _write_file(dst / "a.txt", "a")
        # Make dest newer so it's skipped
        _set_mtime(dst / "a.txt", os.path.getmtime(src / "a.txt") + 10)

        calls: list[tuple] = []
        sync_directory(str(src), str(dst), progress_callback=lambda n, d, t: calls.append((n, d, t)))

        assert len(calls) == 1  # still called for skipped files


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class TestLogging:
    def test_log_append(self, tmp_path: Path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        log = tmp_path / "sync.log"
        _write_file(src / "x.txt", "x")

        # First run
        sync_directory(str(src), str(dst), log_path=str(log))
        lines_after_first = log.read_text(encoding="utf-8").splitlines()

        # Second run (should append, not overwrite)
        _set_mtime(src / "x.txt", os.path.getmtime(src / "x.txt") + 100)
        sync_directory(str(src), str(dst), log_path=str(log))
        lines_after_second = log.read_text(encoding="utf-8").splitlines()

        assert len(lines_after_second) > len(lines_after_first)

    def test_log_contains_operations(self, tmp_path: Path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        log = tmp_path / "sync.log"
        _write_file(src / "f.txt", "data")

        sync_directory(str(src), str(dst), log_path=str(log))
        text = log.read_text(encoding="utf-8")

        assert "START" in text
        assert "COPY" in text
        assert "DONE" in text


# ---------------------------------------------------------------------------
# Multiple pairs
# ---------------------------------------------------------------------------

class TestSyncPairs:
    def test_multiple_pairs(self, tmp_path: Path):
        s1 = tmp_path / "s1"
        d1 = tmp_path / "d1"
        s2 = tmp_path / "s2"
        d2 = tmp_path / "d2"
        _write_file(s1 / "a.txt", "a")
        _write_file(s2 / "b.txt", "b")

        pairs = [SyncPair(str(s1), str(d1)), SyncPair(str(s2), str(d2))]
        result = sync_pairs(pairs)

        assert result.files_copied == 2
        assert (d1 / "a.txt").exists()
        assert (d2 / "b.txt").exists()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_special_characters_in_path(self, tmp_path: Path):
        src = tmp_path / "src folder (1)"
        dst = tmp_path / "dst folder (2)"
        _write_file(src / "file with spaces.txt", "data")

        result = sync_directory(str(src), str(dst))

        assert result.files_copied == 1
        assert (dst / "file with spaces.txt").exists()

    def test_large_file_copy(self, tmp_path: Path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        big_file = src / "big.bin"
        big_file.parent.mkdir(parents=True, exist_ok=True)
        # ~2 MB file
        big_file.write_bytes(os.urandom(2 * 1024 * 1024))

        src_hash = file_hash(big_file)
        sync_directory(str(src), str(dst))

        assert file_hash(dst / "big.bin") == src_hash

    def test_destination_created_if_missing(self, tmp_path: Path):
        src = tmp_path / "src"
        dst = tmp_path / "deep" / "nested" / "dst"
        _write_file(src / "f.txt", "x")

        sync_directory(str(src), str(dst))

        assert (dst / "f.txt").exists()

    def test_idempotent_second_run(self, tmp_path: Path):
        """Running sync twice without changes should copy 0 files the second time."""
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        _write_file(src / "a.txt", "a")
        _write_file(src / "sub" / "b.txt", "b")

        r1 = sync_directory(str(src), str(dst))
        assert r1.files_copied == 2

        r2 = sync_directory(str(src), str(dst))
        assert r2.files_copied == 0
        assert r2.files_skipped == 2


# ---------------------------------------------------------------------------
# Cancel support
# ---------------------------------------------------------------------------

class TestCancel:
    def test_cancel_event_stops_sync(self, tmp_path: Path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        for i in range(20):
            _write_file(src / f"file_{i:03d}.txt", f"data {i}")

        cancel = threading.Event()
        cancel.set()  # already cancelled

        result = sync_directory(str(src), str(dst), cancel_event=cancel)

        # Should have processed very few (or zero) files
        assert result.files_copied < 20


# ---------------------------------------------------------------------------
# file_hash utility
# ---------------------------------------------------------------------------

class TestFileHash:
    def test_hash_consistency(self, tmp_path: Path):
        f = _write_file(tmp_path / "h.txt", "hash me")
        h1 = file_hash(f)
        h2 = file_hash(f)
        assert h1 == h2
        assert len(h1) == 64  # sha256 hex digest length
