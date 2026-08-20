"""Tests for the pinned page footer.

Every workflow page ends in Back/Next, its own action button, a progress bar and
a status line. Those used to be the last rows of the page itself, inside one
window-wide scrollable frame, so on a tall page — the file picker asks for
1534px against a 700px window, the exclusion page 1830px — they scrolled off the
bottom and had to be hunted for.

``gui.page_shell.PageShell`` splits each page into a scrolling content area and
a footer pinned beneath it. These tests check that arrangement in the built
widget tree: where each control's parent actually is, and which frame the app
raises when it changes page.

These were once source-text assertions — ``"nav = ctk.CTkFrame(self._footer" in
source`` and friends, over ten panel files. They read the property off the page
instead of off the program, so reformatting a call broke them while a genuinely
misparented widget could slip past. Walking the real tree costs a display but
answers the actual question.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

GUI_DIR = Path(__file__).resolve().parents[1] / "gui"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Pages that end in a Back/Next row. Welcome and Finish are centred cards with
# their own buttons and no nav row, so they have no footer to fill.
PAGES_WITH_NAV = [
    "file_panel", "data_mode", "exclusion", "participant", "visualization",
    "export", "email", "redcap", "sync", "settings",
]

PAGES_WITHOUT_NAV = ["welcome", "finish"]


# --------------------------------------------------------------------------
# A real app, or a skip
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


def test_every_page_of_the_app_is_covered_by_these_checks(app):
    """A page added later must not slip past the per-page checks above.

    The two lists are spelled out rather than derived from the app so that they
    assert something; this keeps them honest when a page is added or renamed.
    """
    listed = set(PAGES_WITH_NAV) | set(PAGES_WITHOUT_NAV)
    actual = set(app._pages)

    assert actual == listed, (
        f"page list drift -- add to PAGES_WITH_NAV/PAGES_WITHOUT_NAV: "
        f"{sorted(actual - listed)}; removed from the app: {sorted(listed - actual)}"
    )


def _descendants(widget):
    """Every widget below *widget*, itself excluded."""
    out = []
    stack = list(widget.winfo_children())
    while stack:
        node = stack.pop()
        out.append(node)
        stack.extend(node.winfo_children())
    return out


def _find_buttons(widget, *labels):
    """Descendant buttons of *widget* whose text is one of *labels*."""
    wanted = {label.casefold() for label in labels}
    found = []
    for node in _descendants(widget):
        try:
            text = node.cget("text")
        except Exception:
            continue
        if isinstance(text, str) and text.casefold() in wanted:
            found.append(node)
    return found


# --------------------------------------------------------------------------
# Where the controls actually live
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", PAGES_WITH_NAV)
def test_nav_buttons_live_in_the_pinned_footer(app, name):
    """A nav row parented to the page would scroll away with the content."""
    shell = app._shells[name]
    in_footer = _find_buttons(shell.footer, "Back", "Next")
    in_content = _find_buttons(shell.content, "Back", "Next")

    assert in_footer, f"{name}: no Back/Next button found in the pinned footer"
    assert not in_content, (
        f"{name}: {len(in_content)} nav button(s) are inside the scrolling "
        f"content and would scroll out of reach"
    )


@pytest.mark.parametrize("name", PAGES_WITH_NAV)
def test_progress_and_status_cannot_scroll_out_of_reach(app, name):
    """Whatever reports progress must not be somewhere it can scroll away.

    Stated as "not inside a scrolling area" rather than "inside the footer",
    because that is the property that actually matters and the Visualization
    page legitimately fails the stricter version: it is built ``scrolling=False``
    and parks its spinner on the graph canvas, where nothing can scroll at all.
    """
    import customtkinter as ctk

    shell = app._shells[name]
    panel = app._pages[name]

    if not isinstance(shell.content, ctk.CTkScrollableFrame):
        pytest.skip(f"{name} does not scroll, so nothing can scroll away")

    scrollable = set(map(id, _descendants(shell.content)))

    for attribute in ("_progress", "_status_label"):
        widget = getattr(panel, attribute, None)
        if widget is None:
            continue
        assert id(widget) not in scrollable, (
            f"{name}: {attribute} is inside the scrolling content and would "
            f"scroll out of reach on a tall page"
        )


@pytest.mark.parametrize("name", PAGES_WITH_NAV)
def test_the_footer_is_the_shell_footer_not_a_panel_fallback(app, name):
    """resolve_footer must hand back the injected bar when there is one.

    A panel that quietly built its own would grid it inside the scrolling page,
    which is the bug the shell exists to fix.
    """
    shell = app._shells[name]
    panel = app._pages[name]
    assert getattr(panel, "_footer", None) is shell.footer, (
        f"{name}: panel is filling in a footer of its own instead of the "
        f"shell's pinned one"
    )


def test_a_panel_built_without_a_footer_still_gets_one(app):
    """The fallback still has to work: a panel must stand alone in a test."""
    import customtkinter as ctk

    from gui.page_shell import resolve_footer

    standalone = ctk.CTkFrame(app)
    fallback = resolve_footer(standalone, None)

    assert fallback is not None
    assert fallback.winfo_parent() == standalone._w, (
        "the fallback bar must belong to the panel that asked for it"
    )
    # And an injected footer is handed straight back, untouched.
    injected = ctk.CTkFrame(app)
    assert resolve_footer(standalone, injected) is injected


# --------------------------------------------------------------------------
# Live geometry
# --------------------------------------------------------------------------

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
    for name in PAGES_WITHOUT_NAV:
        app._show_page(name)
        app.update()
        app.update_idletasks()
        shell = app._shells[name]
        assert not shell.footer.winfo_ismapped()
        assert not shell._separator.winfo_ismapped()


# --------------------------------------------------------------------------
# Changing page brings the bar with it
# --------------------------------------------------------------------------

def test_changing_page_raises_the_shell_so_the_footer_comes_along(app):
    """Raising the panel alone would leave the previous page's bar on top.

    All the pages are stacked in one container, so which page you see is purely
    stacking order. Tk reports ``winfo_children()`` lowest-first, so the shell of
    the page just shown must be the last child of the container. Raising the
    panel instead moves the panel within its own shell and leaves the shells
    where they were -- so the previous page's footer stays on top.
    """
    for name in ("file_panel", "export", "sync", "participant"):
        app._show_page(name)
        app.update()
        app.update_idletasks()

        shell = app._shells[name]
        stacking = app._container.winfo_children()
        top_most = stacking[-1]

        assert top_most is shell, (
            f"after showing {name!r} the top of the stack is "
            f"{top_most.winfo_name()}, not that page's shell -- the app is "
            f"probably raising the panel instead of the shell, which leaves "
            f"the previous page's footer on top"
        )


def test_the_page_container_holds_shells_not_bare_panels(app):
    """Each page is a PageShell; a bare panel would have no pinned bar at all."""
    from gui.page_shell import PageShell

    for name, shell in app._shells.items():
        assert isinstance(shell, PageShell), f"{name} is not wrapped in a PageShell"
        panel = app._pages[name]
        # The panel sits inside its shell's content area, not beside it.
        assert panel.winfo_parent() == shell.content._w, (
            f"{name}: panel is not parented to its shell's content area"
        )
