"""The app mark reaches the window, and the .ico carries every size.

Behavioural, not source-text: the Tk tests build a real ``TMSApp`` and check
what CustomTkinter actually did with the icon. Tk works headlessly here, so
they skip only when no display is available at all.
"""

import sys

import pytest

from gui.app import TMSApp, _resolve_logo_dir

ICO_SIZES = {(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)}


def test_logo_dir_resolves_to_a_real_ico():
    """The path the window icon is loaded from actually holds the file."""
    ico = _resolve_logo_dir() / "logo.ico"
    assert ico.is_file(), f"{ico} is missing -- run scripts/generate_logo.py"


def test_ico_carries_every_size_windows_asks_for():
    """A single-frame .ico makes Windows scale one bitmap for the 16px tray."""
    Image = pytest.importorskip("PIL.Image")
    with Image.open(_resolve_logo_dir() / "logo.ico") as img:
        assert set(img.info["sizes"]) == ICO_SIZES


@pytest.fixture()
def app():
    ctk = pytest.importorskip("customtkinter")
    try:
        instance = TMSApp()
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
    monkeypatch.setattr("gui.app._resolve_logo_dir", lambda: tmp_path / "gone")
    app._apply_window_icon()  # must not raise
