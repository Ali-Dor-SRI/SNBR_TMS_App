"""Page 6 — final page with options to restart or close."""

import customtkinter as ctk

from gui.theme import (
    FONT_TITLE, FONT_SUBTITLE, FONT_BUTTON,
    ACCENT_COLOR, ACCENT_HOVER, SUBTITLE_COLOR,
    BUTTON_HEIGHT, CORNER_RADIUS,
)


class FinishPanel(ctk.CTkFrame):
    """Final page — restart with same data or close the app."""

    def __init__(self, parent, controller, on_restart, on_back, footer=None):
        super().__init__(parent, fg_color="transparent")
        # The pinned bar at the bottom of the window (gui.page_shell.PageShell).
        # Panels grid their Back/Next, action buttons, progress bar and status
        # line into it so those never scroll away with the content. Falling back
        # to a row of its own keeps a panel constructible standalone.
        self._footer = footer
        if self._footer is None:
            self._footer = ctk.CTkFrame(self, fg_color="transparent")
            self._footer.grid(row=99, column=0, sticky="ew")
        self._controller = controller
        self._on_restart = on_restart
        self._on_back = on_back

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.grid(row=0, column=0)

        ctk.CTkLabel(
            inner, text="All Done", font=FONT_TITLE,
        ).pack(pady=(0, 8))

        ctk.CTkLabel(
            inner,
            text="Your exports are complete. What would you like to do next?",
            font=FONT_SUBTITLE,
            text_color=SUBTITLE_COLOR,
        ).pack(pady=(0, 30))

        ctk.CTkButton(
            inner,
            text="Create more graphs using the same data frame",
            width=380,
            height=BUTTON_HEIGHT + 4,
            corner_radius=CORNER_RADIUS,
            font=FONT_BUTTON,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER,
            command=self._on_restart,
        ).pack(pady=(0, 12))

        ctk.CTkButton(
            inner,
            text="Close SNBR TMS Reports app",
            width=380,
            height=BUTTON_HEIGHT + 4,
            corner_radius=CORNER_RADIUS,
            font=FONT_BUTTON,
            fg_color="#E74C3C",
            hover_color="#C0392B",
            command=self._close_app,
        ).pack(pady=(0, 20))

        ctk.CTkButton(
            inner,
            text="Back",
            width=100,
            height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS,
            font=FONT_BUTTON,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER,
            command=self._on_back,
        ).pack(anchor="w")

    def _close_app(self):
        self.winfo_toplevel().destroy()
