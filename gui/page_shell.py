"""Page shell: scrolling content above a pinned action bar.

Every workflow page ends in the same set of controls — Back, Next, the page's
own action button, the progress bar and the status line. Those used to be the
last rows of the page itself, and the whole page sat inside one window-wide
scrollable frame, so on a tall page (the file picker asks for 1534px against a
700px window; the exclusion page asks for 1830px) the controls scrolled off the
bottom and had to be hunted for.

This splits a page in two. The content keeps scrolling as before, in
:attr:`PageShell.content`, while :attr:`PageShell.footer` is gridded beneath it
and never moves — so Back and Next sit at the bottom of the *window*, always
visible, whatever the page above is doing.

Panels stay in charge of their own controls: each is handed the footer at
construction and grids its own buttons into it. Nothing here knows what a
particular page's action button does.

Usage
-----
    shell = PageShell(container)
    shell.grid(row=0, column=0, sticky="nsew")
    panel = SomePanel(shell.content, footer=shell.footer, ...)
    panel.grid(row=0, column=0, sticky="nsew")
"""

from __future__ import annotations

import customtkinter as ctk


# The bar reads as a distinct strip rather than more page background. Both are
# (light, dark) pairs so they track the appearance-mode switch in the toolbar.
FOOTER_FG_COLOR = ("#DBDEE3", "#2A2D2E")
# A hairline above the bar: without it the content simply stops mid-row where
# the scroll viewport ends, which reads as a rendering glitch rather than an
# edge.
FOOTER_BORDER_COLOR = ("#B8BDC6", "#3E4245")


class PageShell(ctk.CTkFrame):
    """One workflow page: scrolling content, pinned footer.

    *scrolling* builds the content area as a scrollable frame, which is what
    every page needs bar one — the Visualization page sizes its graph canvas to
    the space it is given, so scrolling it would fight the canvas for height
    instead of fitting into the window.
    """

    def __init__(self, parent, scrolling: bool = True, **kwargs):
        super().__init__(parent, fg_color="transparent", corner_radius=0, **kwargs)

        self.grid_rowconfigure(0, weight=1)   # content takes the leftover height
        self.grid_rowconfigure(1, weight=0)   # separator hairline
        self.grid_rowconfigure(2, weight=0)   # footer keeps its natural height
        self.grid_columnconfigure(0, weight=1)

        if scrolling:
            self.content = ctk.CTkScrollableFrame(
                self, fg_color="transparent", corner_radius=0,
            )
        else:
            self.content = ctk.CTkFrame(
                self, fg_color="transparent", corner_radius=0,
            )
        self.content.grid(row=0, column=0, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        # height=1 rather than CTkFrame's 200px default: with children gridded
        # in, geometry propagation grows the bar to fit them; with none, it stays
        # a hairline until finalize() removes it.
        self.footer = ctk.CTkFrame(
            self, fg_color=FOOTER_FG_COLOR, corner_radius=0, height=1,
        )
        self.footer.grid(row=2, column=0, sticky="ew")
        # Column 0 absorbs the slack so a "Back" on the left and a "Next" on the
        # right push apart, matching how the nav rows were laid out before.
        self.footer.grid_columnconfigure(0, weight=1)

        self._separator = ctk.CTkFrame(
            self, height=1, fg_color=FOOTER_BORDER_COLOR, corner_radius=0,
        )
        self._separator.grid(row=1, column=0, sticky="ew")

    def finalize(self):
        """Drop the bar when the page put nothing in it.

        The Welcome and Finish pages are centred cards with their own buttons and
        no Back/Next row, so an empty strip along the bottom would just be a
        stray band of colour.
        """
        if not self.footer.winfo_children():
            self.footer.grid_remove()
            self._separator.grid_remove()


# Footer row order, shared by every panel that fills one in.
FOOTER_ROW_PROGRESS = 0
FOOTER_ROW_STATUS = 1
FOOTER_ROW_NAV = 2
