"""Reusable "skip this step in future runs" toggle button.

Optional workflow pages (Exclude Participants, and later Email / REDCap /
Backup & Sync) can drop this button in to let the user hide the page from the
linear Next/Back flow. A skipped page stays reachable from the toolbar
page-jump dropdown. The choice is persisted immediately through the controller,
so it also takes effect on future launches.

Usage
-----
    from gui.skip_control import SkipStepButton

    self._skip_btn = SkipStepButton(
        parent, controller, "exclusion", on_toggle=self._on_skip_toggled,
    )
    ...
    def refresh(self):
        self._skip_btn.refresh()   # keep the label in sync with saved state
"""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from gui.theme import (
    FONT_BUTTON, ACCENT_COLOR, ACCENT_HOVER, CORNER_RADIUS, BUTTON_HEIGHT,
)


class SkipStepButton(ctk.CTkButton):
    """Toggle button that skips / restores its page in the workflow flow.

    The controller owns the persisted state; this widget only reflects and
    flips it. Pass *on_toggle* to react to a change (e.g. show a status line);
    it receives the new ``skipped`` boolean.
    """

    def __init__(
        self,
        parent,
        controller,
        page_name: str,
        *,
        on_toggle: Callable[[bool], None] | None = None,
        **kwargs,
    ):
        self._controller = controller
        self._page_name = page_name
        self._on_toggle = on_toggle

        kwargs.setdefault("width", 220)
        kwargs.setdefault("height", BUTTON_HEIGHT)
        kwargs.setdefault("corner_radius", CORNER_RADIUS)
        kwargs.setdefault("font", FONT_BUTTON)

        super().__init__(parent, command=self._toggle, **kwargs)
        self.refresh()

    def _toggle(self):
        new_state = not self._controller.is_page_skipped(self._page_name)
        self._controller.set_page_skipped(self._page_name, new_state)
        self.refresh()
        if self._on_toggle is not None:
            self._on_toggle(new_state)

    def refresh(self):
        """Sync the button's label and styling with the persisted skip state."""
        if self._controller.is_page_skipped(self._page_name):
            # Currently skipped — offer to put it back in the flow.
            self.configure(
                text="Show this page in future runs",
                fg_color="transparent",
                hover_color=ACCENT_COLOR,
                border_width=1,
                border_color=ACCENT_COLOR,
                text_color=ACCENT_COLOR,
            )
        else:
            self.configure(
                text="Skip this page in future runs",
                fg_color=ACCENT_COLOR,
                hover_color=ACCENT_HOVER,
                border_width=0,
                text_color="white",
            )
