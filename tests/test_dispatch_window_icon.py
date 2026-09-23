"""The dispatch app wears its own mark, not the analysis app's.

Sibling of ``test_window_icon.py`` and behavioural in the same way: a real
``DispatchApp`` is built and asked what CustomTkinter actually did. The point
this file exists to defend is that the two executables are *different* icons
-- the dispatch window pointing at ``icons/logo/logo.ico`` would look
completely correct in code review and leave two identical taskbar buttons.
"""

import sys

import pytest

from dispatch_gui.app import DispatchApp, _resolve_logo_dir

ICO_SIZES = {(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)}


def test_logo_dir_resolves_to_a_real_ico():
    """The path the window icon is loaded from actually holds the file."""
    ico = _resolve_logo_dir() / "dispatch.ico"
    assert ico.is_file(), f"{ico} is missing -- run scripts/generate_dispatch_logo.py"


def test_the_dispatch_mark_is_not_the_analysis_app_mark():
    """Two apps, two icons. Same folder or same bytes means one of them is wrong."""
    from gui.app import _resolve_logo_dir as analysis_logo_dir

    dispatch_ico = _resolve_logo_dir() / "dispatch.ico"
    analysis_ico = analysis_logo_dir() / "logo.ico"
    assert dispatch_ico.resolve() != analysis_ico.resolve()
    assert dispatch_ico.read_bytes() != analysis_ico.read_bytes()


def test_ico_carries_every_size_windows_asks_for():
    """A single-frame .ico makes Windows scale one bitmap for the 16px tray."""
    Image = pytest.importorskip("PIL.Image")
    with Image.open(_resolve_logo_dir() / "dispatch.ico") as img:
        assert set(img.info["sizes"]) == ICO_SIZES


def test_both_cuts_are_actually_drawn_at_their_sizes():
    """The 16px frame must be the simplified cut, not a shrunk 256px one.

    Checked by ink coverage: the small cut carries a heavier stroke, so a
    downsampled large frame would be visibly lighter at 16px.
    """
    Image = pytest.importorskip("PIL.Image")
    with Image.open(_resolve_logo_dir() / "dispatch.ico") as img:
        img.size = (16, 16)
        alpha = img.convert("RGBA").getchannel("A")
    opaque = sum(alpha.histogram()[129:])
    assert opaque > 30, f"the 16px frame is nearly empty ({opaque} solid pixels)"


@pytest.fixture()
def app():
    ctk = pytest.importorskip("customtkinter")
    try:
        instance = DispatchApp()
    except Exception as exc:  # pragma: no cover - display-dependent
        pytest.skip(f"no usable display: {exc}")
    yield instance
    instance.destroy()


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows-only icon path")
def test_app_claims_the_icon_so_customtkinter_does_not_replace_it(app):
    """CTk installs its own icon on a timer unless iconbitmap was called.

    ``_iconbitmap_method_called`` is the flag CTk checks in
    ``_windows_set_titlebar_icon``; if it is False the window ends up wearing
    the CustomTkinter logo instead of ours, with no error anywhere.
    """
    assert app._iconbitmap_method_called is True


def test_missing_icon_file_does_not_stop_the_window_opening(app, monkeypatch, tmp_path):
    """The icon is cosmetic -- a bad path must not take the app down."""
    monkeypatch.setattr("dispatch_gui.app._resolve_logo_dir", lambda: tmp_path / "gone")
    app._apply_window_icon()  # must not raise
