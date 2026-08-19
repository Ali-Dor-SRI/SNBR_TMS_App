"""Settings page — read-only display of Quick Start defaults."""

from __future__ import annotations

import customtkinter as ctk

from core.user_settings import (
    KEY_MEM_DIR, KEY_CSP_DIR, KEY_CMAP_DIR, KEY_CSV_FILE,
    KEY_EXPORT_CSV, KEY_EXPORT_PDF, KEY_SYNC_PAIRS,
    KEY_REDCAP_DATA_DIR, KEY_REDCAP_DICT_DIR,
    KEY_REDCAP_TEMPLATE_DIR, KEY_REDCAP_EXPORT_DIR,
)
from gui.theme import (
    FONT_TITLE, FONT_HEADING, FONT_BODY, FONT_SMALL, FONT_SUBTITLE, FONT_BUTTON,
    ACCENT_COLOR, ACCENT_HOVER, DISABLED_FG, ERROR_COLOR, SUCCESS_COLOR,
    SUBTITLE_COLOR,
    PAD_X, PAD_Y, SECTION_PAD_Y, BUTTON_HEIGHT, CORNER_RADIUS,
)


class SettingsPanel(ctk.CTkFrame):
    """Read-only settings page showing Quick Start defaults."""

    def __init__(self, parent, controller, on_back, footer=None):
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
        self._on_back = on_back

        self._build_ui()

    # ── UI ─────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)  # scrollable area expands

        # Title
        ctk.CTkLabel(
            self, text="Settings", font=FONT_TITLE, anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=PAD_X, pady=(SECTION_PAD_Y, 4))

        ctk.CTkLabel(
            self,
            text=(
                "These are the current default settings for Quick Start.\n"
                "To change them, run a Custom Workflow and save new defaults."
            ),
            font=FONT_SUBTITLE,
            text_color=SUBTITLE_COLOR,
            anchor="w",
            justify="left",
        ).grid(row=1, column=0, sticky="w", padx=PAD_X, pady=(0, SECTION_PAD_Y))

        # Scrollable content area
        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._scroll.grid(row=2, column=0, sticky="nsew", padx=PAD_X, pady=(0, PAD_Y))
        self._scroll.grid_columnconfigure(0, weight=1)

        # Navigation (pinned; see gui.page_shell)
        nav = ctk.CTkFrame(self._footer, fg_color="transparent")
        nav.grid(row=2, column=0, sticky="ew", padx=PAD_X, pady=(PAD_Y, PAD_Y))
        nav.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            nav, text="Back", width=100, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._on_back,
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            nav, text="Clear All Defaults", width=160, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ERROR_COLOR, hover_color="#C0392B",
            command=self._confirm_clear_defaults,
        ).grid(row=0, column=2, sticky="e")

    # ── Refresh ────────────────────────────────────────────

    def refresh(self):
        """Rebuild the scrollable content with current saved defaults."""
        # Clear existing content
        for widget in self._scroll.winfo_children():
            widget.destroy()

        defaults = self._controller.get_saved_defaults()
        row = 0

        # Participant
        row = self._add_section(self._scroll, row, "Participant", [
            "Most recent visit (auto-selected)",
        ])

        # Cortex
        row = self._add_section(self._scroll, row, "Cortex", [
            "Both hemispheres when available",
        ])

        # Import Paths
        def _fmt(value):
            if isinstance(value, (list, tuple)):
                value = "; ".join(str(p) for p in value if str(p).strip())
            return value or "(not set)"

        import_lines = [
            f"MEM Dir: {_fmt(defaults.get(KEY_MEM_DIR))}",
            f"CSP Dir: {_fmt(defaults.get(KEY_CSP_DIR))}",
            f"CMAP Dir: {_fmt(defaults.get(KEY_CMAP_DIR))}",
            f"CSV File: {_fmt(defaults.get(KEY_CSV_FILE))}",
        ]
        row = self._add_section(self._scroll, row, "Import Paths", import_lines)

        # Export Paths
        export_lines = [
            f"CSV Export: {defaults.get(KEY_EXPORT_CSV) or '(not set)'}",
            f"PDF Export: {defaults.get(KEY_EXPORT_PDF) or '(not set)'}",
        ]
        row = self._add_section(self._scroll, row, "Export Paths", export_lines)

        # REDCap Export Paths
        redcap_lines = [
            f"Data Dir: {defaults.get(KEY_REDCAP_DATA_DIR) or '(not set)'}",
            f"Dictionary Dir: {defaults.get(KEY_REDCAP_DICT_DIR) or '(not set)'}",
            f"Template Dir: {defaults.get(KEY_REDCAP_TEMPLATE_DIR) or '(not set)'}",
            f"Export Dir: {defaults.get(KEY_REDCAP_EXPORT_DIR) or '(not set)'}",
        ]
        row = self._add_section(self._scroll, row, "REDCap Export", redcap_lines)

        # Graphs
        from gui.visualization_panel import GRAPH_REGISTRY
        graph_lines = [f"{i+1}. {entry.label}" for i, entry in enumerate(GRAPH_REGISTRY)]
        graph_lines.append(f"Total: {len(GRAPH_REGISTRY)} graphs (all available)")
        row = self._add_section(self._scroll, row, "Graphs in Report", graph_lines)

        # Sync Pairs
        sync_pairs = defaults.get(KEY_SYNC_PAIRS, [])
        if sync_pairs:
            sync_lines = [
                f"Pair {i+1}: {p.get('source', '')} -> {p.get('destination', '')}"
                for i, p in enumerate(sync_pairs)
            ]
        else:
            sync_lines = ["No sync pairs configured."]
        row = self._add_section(self._scroll, row, "Backup & Sync", sync_lines)

    # ── Clear defaults ────────────────────────────────────

    def _confirm_clear_defaults(self):
        """Show a confirmation dialog before clearing all saved defaults."""
        popup = ctk.CTkToplevel(self)
        popup.title("Clear All Defaults")
        popup.geometry("400x160")
        popup.resizable(False, False)
        popup.grab_set()
        popup.after(100, popup.focus_force)

        popup.grid_columnconfigure(0, weight=1)
        popup.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            popup,
            text="Are you sure you want to clear all saved defaults?",
            font=FONT_BODY,
            wraplength=360,
        ).grid(row=0, column=0, columnspan=2, padx=PAD_X, pady=(PAD_Y, 4))

        ctk.CTkLabel(
            popup,
            text="This cannot be undone.",
            font=FONT_SMALL,
            text_color=ERROR_COLOR,
        ).grid(row=1, column=0, columnspan=2, padx=PAD_X, pady=(0, PAD_Y))

        ctk.CTkButton(
            popup, text="Cancel", width=120, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color="transparent", border_width=2,
            border_color=ACCENT_COLOR, text_color=ACCENT_COLOR,
            hover_color=("gray90", "gray25"),
            command=popup.destroy,
        ).grid(row=2, column=0, padx=(PAD_X, 4), pady=(0, PAD_Y), sticky="e")

        ctk.CTkButton(
            popup, text="Clear All", width=120, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ERROR_COLOR, hover_color="#C0392B",
            command=lambda: self._do_clear(popup),
        ).grid(row=2, column=1, padx=(4, PAD_X), pady=(0, PAD_Y), sticky="w")

    def _do_clear(self, popup):
        popup.destroy()
        self._controller.clear_all_defaults()
        self.refresh()

    # ── Helpers ────────────────────────────────────────────

    def _add_section(self, parent, row: int, title: str, lines: list[str]) -> int:
        """Add a titled section with lines to the scrollable frame."""
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
