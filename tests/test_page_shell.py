"""Tests for the pinned page footer.

Every workflow page ends in Back/Next, its own action button, a progress bar and
a status line. Those used to be the last rows of the page itself, inside one
window-wide scrollable frame, so on a tall page — the file picker asks for
1534px against a 700px window, the exclusion page 1830px — they scrolled off the
bottom and had to be hunted for.

``gui.page_shell.PageShell`` splits each page into a scrolling content area and
a footer pinned beneath it. These tests guard both halves of that: the source
level (panels must build their controls into the footer they are handed, and the
app must raise the shell rather than the panel) and, where a display is
available, the live geometry.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

GUI_DIR = Path(__file__).resolve().parents[1] / "gui"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Panels that end in a Back/Next row. Welcome and Finish are centred cards with
# their own buttons and no nav row, so they have no footer to fill.
PANELS_WITH_NAV = [
    "file_panel.py", "data_mode_panel.py", "exclusion_panel.py",
    "participant_panel.py", "visualization_panel.py", "export_panel.py",
    "email_panel.py", "redcap_panel.py", "sync_panel.py", "settings_panel.py",
]


def _source(name: str) -> str:
    return (GUI_DIR / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Source-level guards — no display needed
# --------------------------------------------------------------------------

@pytest.mark.parametrize("filename", PANELS_WITH_NAV)
def test_nav_row_is_built_in_the_footer_not_the_page(filename):
    """A nav row parented to the page would scroll away with the content."""
    source = _source(filename)
    assert "nav = ctk.CTkFrame(self._footer" in source, (
        f"{filename} must build its nav row in the pinned footer"
    )
    assert "nav = ctk.CTkFrame(self, " not in source


@pytest.mark.parametrize("filename", PANELS_WITH_NAV)
def test_panel_accepts_a_footer_and_falls_back_to_its_own(filename):
    """The footer is injected by the app, but a panel must still stand alone."""
    source = _source(filename)
    assert "footer=None" in source
    assert "self._footer = footer" in source


@pytest.mark.parametrize("filename", PANELS_WITH_NAV)
def test_progress_and_status_ride_with_the_buttons(filename):
    """Whatever reports progress belongs beside the controls, not above the fold."""
    source = _source(filename)
    for widget, pattern in (
        ("progress bar", r"self\._progress = ctk\.CTkProgressBar\(\s*self,"),
        ("status label", r"self\._status_label = ctk\.CTkLabel\(\s*self,"),
    ):
        assert not re.search(pattern, source), (
            f"{filename}: {widget} is still parented to the page"
        )


def test_app_raises_the_shell_so_the_footer_comes_with_the_page():
    """Raising the panel alone would leave the previous page's bar on top."""
    source = _source("app.py")
    assert "self._shells[name].tkraise()" in source
    assert "page.tkraise()" not in source


def test_pages_are_not_wrapped_in_one_window_wide_scroller():
    """That wrapper is what let the controls scroll out of reach."""
    source = _source("app.py")
    assert "CTkScrollableFrame" not in source
    assert "PageShell(self._container" in source


# --------------------------------------------------------------------------
# Live geometry — skipped where no display is available
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    """A real TMSApp, or a skip when Tk cannot open a display.

    Module-scoped: creating and tearing down a Tk root repeatedly in one process
    intermittently fails to re-initialise Tcl, which would skip these tests for
    a reason that has nothing to do with the layout they check.
    """
    import matplotlib
    matplotlib.use("Agg")
    try:
        from gui.app import TMSApp
        instance = TMSApp()
    except Exception as exc:  # pragma: no cover - headless CI
        pytest.skip(f"no display available: {exc}")
    instance.update()
    instance.update_idletasks()
    yield instance
    instance.destroy()


def test_every_page_pins_its_bar_to_the_bottom_of_the_window(app):
    window_bottom = app.winfo_height()
    root_y = app.winfo_rooty()
    for name in app._pages:
        app._show_page(name)
        app.update()
        app.update_idletasks()
        shell = app._shells[name]
        if not shell.footer.winfo_ismapped():
            continue  # centred card with no controls to pin
        top = shell.footer.winfo_rooty() - root_y
        bottom = top + shell.footer.winfo_height()
        assert abs(bottom - window_bottom) <= 2, (
            f"{name}: bar ends at {bottom}, window at {window_bottom}"
        )
        assert top >= 0, f"{name}: bar starts above the window"


def test_tall_pages_scroll_their_content_instead_of_their_controls(app):
    """The exclusion page wants ~1830px; the bar must not go with it."""
    import customtkinter as ctk

    app._show_page("exclusion")
    app.update()
    app.update_idletasks()
    shell = app._shells["exclusion"]
    assert isinstance(shell.content, ctk.CTkScrollableFrame)
    viewport = shell.content._parent_canvas.winfo_height()
    wanted = shell.content.winfo_reqheight()
    assert wanted > viewport, "expected this page to overflow its viewport"
    assert shell.footer.winfo_ismapped()


def test_pages_without_controls_show_no_empty_bar(app):
    """Welcome and Finish are centred cards; a bare strip would be noise."""
    for name in ("welcome", "finish"):
        app._show_page(name)
        app.update()
        app.update_idletasks()
        shell = app._shells[name]
        assert not shell.footer.winfo_ismapped()
        assert not shell._separator.winfo_ismapped()
