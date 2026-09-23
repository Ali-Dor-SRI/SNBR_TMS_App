"""scripts/build_assets.py -- the marks are prepared and checked at build time.

Behavioural, and hermetic: no PyInstaller run happens here. What is tested is
the logic the specs and ``build_dispatch.bat`` depend on -- that a missing
mark is regenerated rather than shipped as a hole, that a wrong or absent
executable is rejected, and that the two apps' marks stay distinct.

The one thing these cannot cover is a real build; that is what the
``--verify-exe`` step in the build script is for, and it runs on every build.
"""

from __future__ import annotations

import sys

import pytest

from scripts.build_assets import (
    MARKS, BuildAssetError, ensure_icon, exe_embeds_icon, ico_frames, main,
    refresh_shell_icon, verify_exe,
)


@pytest.fixture()
def restore_icons():
    """Put every mark back exactly as it was, whatever a test does to it."""
    saved = {name: mark.ico.read_bytes() for name, mark in MARKS.items() if mark.ico.is_file()}
    yield
    for name, data in saved.items():
        MARKS[name].ico.parent.mkdir(parents=True, exist_ok=True)
        MARKS[name].ico.write_bytes(data)


def test_both_marks_are_registered_and_present():
    assert set(MARKS) == {"analysis", "dispatch"}
    for mark in MARKS.values():
        assert mark.ico.is_file(), f"{mark.ico} is missing -- run scripts/{mark.generator}.py"


def test_the_two_marks_are_different_files():
    """Two executables in one dist/; identical icons would be a build bug."""
    analysis, dispatch = MARKS["analysis"].ico, MARKS["dispatch"].ico
    assert analysis.resolve() != dispatch.resolve()
    assert analysis.read_bytes() != dispatch.read_bytes()


def test_ensure_icon_returns_the_existing_file_untouched():
    before = MARKS["dispatch"].ico.read_bytes()
    assert ensure_icon("dispatch") == MARKS["dispatch"].ico
    assert MARKS["dispatch"].ico.read_bytes() == before


@pytest.mark.parametrize("mark_name", sorted(MARKS))
def test_a_deleted_mark_is_regenerated_rather_than_missed(mark_name, restore_icons):
    """The point of the whole module.

    PyInstaller only notices a missing icon inside EXE.assemble -- after the
    executable is written -- so it exits 1 leaving an un-iconned binary in
    dist/. Regenerating up front means the spec never reaches that state.
    """
    ico = MARKS[mark_name].ico
    ico.unlink()
    assert not ico.is_file()

    returned = ensure_icon(mark_name)

    assert returned == ico and ico.is_file()
    assert len(ico_frames(ico)) >= 5, "the regenerated .ico lost its size frames"


def test_a_generator_that_runs_but_produces_nothing_fails_the_build(monkeypatch, tmp_path):
    """A silent skip here would ship an executable with no mark.

    ``Mark`` is frozen, so the whole entry is swapped rather than its field.
    """
    import dataclasses

    import scripts.build_assets as ba

    monkeypatch.setattr(ba, "_run_generator", lambda mark: None)
    monkeypatch.setitem(
        ba.MARKS, "dispatch",
        dataclasses.replace(ba.MARKS["dispatch"], ico=tmp_path / "never_written.ico"),
    )
    with pytest.raises(BuildAssetError, match="still missing"):
        ensure_icon("dispatch")


def test_generator_errors_are_wrapped_with_the_app_named(monkeypatch):
    import importlib

    import scripts.build_assets as ba

    def boom(name):
        raise ImportError("no matplotlib")

    monkeypatch.setattr(importlib, "import_module", boom)
    with pytest.raises(BuildAssetError, match="SNBR Report Dispatch"):
        ensure_icon("dispatch", regenerate=True)


# -- reading the .ico --------------------------------------------------------

def test_ico_frames_are_returned_largest_first():
    frames = ico_frames(MARKS["dispatch"].ico)
    assert len(frames) == 7, "the .ico should carry every size Windows asks for"
    assert frames == sorted(frames, key=len, reverse=True)
    assert all(frames)


def test_a_file_that_is_not_an_ico_is_rejected(tmp_path):
    for name, blob in (("short.ico", b"xx"), ("png.ico", b"\x89PNG\r\n\x1a\n" + b"0" * 64)):
        bad = tmp_path / name
        bad.write_bytes(blob)
        with pytest.raises(BuildAssetError):
            ico_frames(bad)


def test_a_truncated_ico_is_rejected(tmp_path):
    """A half-written .ico must fail loudly, not embed a broken icon."""
    good = MARKS["dispatch"].ico.read_bytes()
    bad = tmp_path / "truncated.ico"
    bad.write_bytes(good[: len(good) // 2])
    with pytest.raises(BuildAssetError, match="truncated"):
        ico_frames(bad)


# -- verifying a built executable --------------------------------------------

def _fake_exe(path, *, embed: bytes = b""):
    """Stand-in for a built binary: filler with the icon payload inside it."""
    path.write_bytes(b"MZ" + b"\x00" * 4096 + embed + b"\x00" * 4096)
    return path


def test_an_executable_carrying_the_mark_passes(tmp_path):
    largest = ico_frames(MARKS["dispatch"].ico)[0]
    exe = _fake_exe(tmp_path / "app.exe", embed=largest)
    assert exe_embeds_icon(exe, MARKS["dispatch"].ico)
    assert verify_exe(exe, "dispatch") == exe


def test_an_executable_carrying_the_other_app_mark_is_rejected(tmp_path):
    """The exact confusion worth catching: dispatch built with the coil icon."""
    exe = _fake_exe(tmp_path / "app.exe", embed=ico_frames(MARKS["analysis"].ico)[0])
    assert not exe_embeds_icon(exe, MARKS["dispatch"].ico)
    with pytest.raises(BuildAssetError, match="does not carry"):
        verify_exe(exe, "dispatch")


def test_an_executable_with_no_icon_at_all_is_rejected(tmp_path):
    """PyInstaller writes the exe *before* embedding the icon, so this is the
    shape of the file a failed build leaves behind."""
    exe = _fake_exe(tmp_path / "app.exe")
    with pytest.raises(BuildAssetError, match="does not carry"):
        verify_exe(exe, "dispatch")


def test_a_missing_executable_is_rejected(tmp_path):
    with pytest.raises(BuildAssetError, match="was not produced"):
        verify_exe(tmp_path / "never_built.exe", "dispatch")


# -- telling Explorer the executable changed ---------------------------------
#
# Embedding the icon is not the same as Explorer showing it: the shell caches
# icons per path, so a rebuilt .exe at the same path keeps the icon that
# filename had on its first build. The build notifies the shell; these check
# that the notification can never itself break a build.

@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows shell API")
def test_notifying_the_shell_about_a_real_executable_succeeds(tmp_path):
    exe = _fake_exe(tmp_path / "app.exe", embed=ico_frames(MARKS["dispatch"].ico)[0])
    assert refresh_shell_icon(exe) is True


def test_notifying_about_a_missing_file_does_not_raise(tmp_path):
    """Cosmetic step: it must never be the thing that fails a build."""
    assert refresh_shell_icon(tmp_path / "never_built.exe") in (True, False)


def test_it_is_a_silent_no_op_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert refresh_shell_icon("anything") is False


def test_a_shell_that_refuses_is_swallowed(monkeypatch, tmp_path):
    import ctypes

    if not sys.platform.startswith("win"):
        pytest.skip("Windows shell API")

    def boom(*args, **kwargs):
        raise OSError("shell32 unavailable")

    monkeypatch.setattr(ctypes, "WinDLL", boom)
    assert refresh_shell_icon(tmp_path / "app.exe") is False


# -- the CLI the build script calls ------------------------------------------

def test_cli_reports_success_and_failure_by_exit_code(tmp_path, capsys):
    assert main(["--ensure", "dispatch"]) == 0

    exe = _fake_exe(tmp_path / "app.exe", embed=ico_frames(MARKS["dispatch"].ico)[0])
    assert main(["--verify-exe", str(exe), "--mark", "dispatch"]) == 0

    assert main(["--verify-exe", str(tmp_path / "gone.exe"), "--mark", "dispatch"]) == 1
    assert "ERROR" in capsys.readouterr().err

    assert main(["--refresh-shell", str(exe)]) == 0


def test_cli_refuses_to_verify_without_being_told_which_mark(tmp_path):
    """--verify-exe alone would silently check nothing."""
    with pytest.raises(SystemExit):
        main(["--verify-exe", str(tmp_path / "app.exe")])


def test_cli_with_no_arguments_is_an_error_not_a_silent_pass():
    with pytest.raises(SystemExit):
        main([])


# -- the generated tree is only ever shipped assets --------------------------

def test_the_bundled_icons_tree_holds_no_scratch_or_preview_files():
    """Both specs bundle icons/ wholesale, so anything left there ships.

    The preview render therefore goes to the temp dir, not next to the assets.
    """
    strays = [
        p for p in (MARKS["dispatch"].ico.parent.parent).rglob("*")
        if p.is_file() and p.name.startswith("._")
    ]
    assert strays == [], f"scratch files would be bundled into the executables: {strays}"


def test_rendering_the_mark_twice_gives_identical_bytes():
    """What makes the spec's ``regenerate=True`` safe.

    The spec re-renders the mark on every build so the shipped icon always
    matches the current geometry. That is only tolerable because the render is
    deterministic -- otherwise every build would rewrite tracked assets and
    leave the working tree dirty. Checked at one small size to stay fast; the
    full render is the same code path.
    """
    from scripts.generate_dispatch_logo import LIGHT, render_at

    first, second = render_at(32, LIGHT), render_at(32, LIGHT)
    assert first.tobytes() == second.tobytes()


def test_every_bundled_icon_file_is_a_real_readable_asset():
    root = MARKS["dispatch"].ico.parent.parent
    files = [p for p in root.rglob("*") if p.is_file()]
    assert len(files) > 20, "the icons tree looks truncated"
    assert all(p.stat().st_size > 0 for p in files), "a zero-byte asset would bundle as a hole"
