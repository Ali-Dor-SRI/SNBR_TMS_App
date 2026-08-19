"""Small widget builders shared by more than one panel.

Distinct from ``gui.skip_control`` (one self-contained interactive widget) and
``gui.page_shell`` (page layout): these are plain builder functions that grid
widgets into a parent a panel already owns.

Public API
----------
add_summary_section(parent, row, title, lines) -> int
"""

from __future__ import annotations

import customtkinter as ctk

from gui.theme import FONT_HEADING, FONT_SMALL, PAD_Y


def add_summary_section(parent, row: int, title: str, lines: list[str]) -> int:
    """Add a titled section with lines to the scrollable frame.

    Used for the saved-defaults summary, which the Settings page and the
    Welcome page's summary popup both render. Returns the next free grid row so
    callers can chain sections down a single column.
    """
    ctk.CTkLabel(
        parent, text=title, font=FONT_HEADING, anchor="w",
    ).grid(row=row, column=0, sticky="w", pady=(PAD_Y, 2))
    row += 1

    for line in lines:
        ctk.CTkLabel(
            parent, text=line, font=FONT_SMALL, anchor="w",
            wraplength=480, justify="left",
        ).grid(row=row, column=0, sticky="w", padx=(12, 0), pady=1)
        row += 1

    return row
