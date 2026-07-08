"""Page 2 — lets the user choose how to build the DataFrame."""

import threading
import traceback

import customtkinter as ctk

from gui.theme import (
    FONT_TITLE, FONT_HEADING, FONT_BODY, FONT_SMALL, FONT_SUBTITLE, FONT_BUTTON,
    ACCENT_COLOR, ACCENT_HOVER, ERROR_COLOR, SUCCESS_COLOR, DISABLED_FG, SUBTITLE_COLOR,
    PAD_X, PAD_Y, SECTION_PAD_Y, BUTTON_HEIGHT, CORNER_RADIUS,
)

# Radio-button values
MODE_EXISTING_CSV = 1
MODE_PARSE_MEM = 2
# Fast path: load the chosen archive CSV as-is — no MEM-folder scan, no CMAP
# merge. Requires a CSV to have been selected on the Import Settings page.
MODE_EXISTING_CSV_FAST = 3


class DataModePanel(ctk.CTkFrame):
    """Data-import mode selection — page 2 of the workflow."""

    def __init__(self, parent, controller, on_next, on_back):
        super().__init__(parent, fg_color="transparent")
        self._controller = controller
        self._on_next = on_next
        self._on_back = on_back

        self._mode_var = ctk.IntVar(value=0)
        self._status_var = ctk.StringVar()
        self._info_var = ctk.StringVar()

        self._build_ui()

    # ── UI Construction ────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Title
        ctk.CTkLabel(
            self, text="Data Import", font=FONT_TITLE, anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=PAD_X, pady=(SECTION_PAD_Y, 4))

        ctk.CTkLabel(
            self,
            text="Choose how the application should prepare your data.",
            font=FONT_SUBTITLE,
            text_color=SUBTITLE_COLOR,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=PAD_X, pady=(0, SECTION_PAD_Y))

        # Options container
        options = ctk.CTkFrame(self, fg_color="transparent")
        options.grid(row=2, column=0, sticky="nsew", padx=PAD_X)
        options.grid_columnconfigure(0, weight=1)

        # Option 1 — fast: use the chosen archive CSV as-is
        self._radio_fast = ctk.CTkRadioButton(
            options,
            text="Create reports based on previous data frame (archive .csv)",
            variable=self._mode_var,
            value=MODE_EXISTING_CSV_FAST,
            font=FONT_HEADING,
        )
        self._radio_fast.grid(row=0, column=0, sticky="w", pady=(0, 2))

        self._fast_desc = ctk.CTkLabel(
            options,
            text="Use the selected archive .csv as-is. No parsing, no folder scan — fastest path to graphs.",
            font=FONT_SUBTITLE,
            text_color=SUBTITLE_COLOR,
            anchor="w",
            justify="left",
        )
        self._fast_desc.grid(row=1, column=0, sticky="w", padx=(26, 0), pady=(0, SECTION_PAD_Y))

        # Option 2 — existing CSV, also checking for newly added MEM files
        self._radio_csv = ctk.CTkRadioButton(
            options,
            text="Create report from existing data frame (check for new MEM files)",
            variable=self._mode_var,
            value=MODE_EXISTING_CSV,
            font=FONT_HEADING,
        )
        self._radio_csv.grid(row=2, column=0, sticky="w", pady=(0, 2))

        self._csv_desc = ctk.CTkLabel(
            options,
            text="Load the archive .csv, then scan the MEM folder for newly added .MEM files (no parsing).",
            font=FONT_SUBTITLE,
            text_color=SUBTITLE_COLOR,
            anchor="w",
            justify="left",
        )
        self._csv_desc.grid(row=3, column=0, sticky="w", padx=(26, 0), pady=(0, SECTION_PAD_Y))

        # Option 3 — parse MEM
        self._radio_mem = ctk.CTkRadioButton(
            options,
            text="Parse .MEM files and create new data frame",
            variable=self._mode_var,
            value=MODE_PARSE_MEM,
            font=FONT_HEADING,
        )
        self._radio_mem.grid(row=4, column=0, sticky="w", pady=(0, 2))

        ctk.CTkLabel(
            options,
            text="Scan the MEM directory for new files, parse them, and merge with any existing data.",
            font=FONT_SUBTITLE,
            text_color=SUBTITLE_COLOR,
            anchor="w",
        ).grid(row=5, column=0, sticky="w", padx=(26, 0), pady=(0, 2))

        ctk.CTkLabel(
            options,
            text="All .MEM files in the selected directory will be parsed.",
            font=FONT_BUTTON,
            text_color=SUBTITLE_COLOR,
            anchor="w",
        ).grid(row=6, column=0, sticky="w", padx=(26, 0), pady=(0, SECTION_PAD_Y))

        # Progress bar (hidden until import starts)
        self._progress = ctk.CTkProgressBar(
            self, mode="indeterminate", width=400,
        )
        self._progress.grid(row=3, column=0, padx=PAD_X, pady=(0, 4))
        self._progress.grid_remove()

        # Status / error label
        self._status_label = ctk.CTkLabel(
            self, textvariable=self._status_var, font=FONT_SMALL,
            text_color=DISABLED_FG, anchor="w", wraplength=600,
        )
        self._status_label.grid(row=4, column=0, sticky="w", padx=PAD_X, pady=(0, 2))

        # Info label (for "new MEM files" notice)
        self._info_label = ctk.CTkLabel(
            self, textvariable=self._info_var, font=FONT_SMALL,
            text_color=SUCCESS_COLOR, anchor="w", wraplength=600,
        )
        self._info_label.grid(row=5, column=0, sticky="w", padx=PAD_X, pady=(0, PAD_Y))

        # Navigation
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.grid(row=6, column=0, sticky="ew", padx=PAD_X, pady=(0, SECTION_PAD_Y))
        nav.grid_columnconfigure(0, weight=1)

        self._back_btn = ctk.CTkButton(
            nav, text="Back", width=100, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._handle_back,
        )
        self._back_btn.grid(row=0, column=0, sticky="w")

        self._next_btn = ctk.CTkButton(
            nav, text="Next", width=100, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._handle_next,
        )
        self._next_btn.grid(row=0, column=1, sticky="e")

    # ── Refresh state when page is shown ───────────────────

    def refresh(self):
        """Called each time this page is raised — sync radio state with paths."""
        csv_path = self._controller.get_paths()["csv_path"]
        has_csv = bool(csv_path)

        if has_csv:
            self._radio_fast.configure(state="normal")
            self._fast_desc.configure(
                text=(
                    "Use the selected archive .csv as-is. No parsing, no folder "
                    f"scan — fastest path to graphs.\n({csv_path})"
                ),
            )
            self._radio_csv.configure(state="normal")
            self._csv_desc.configure(
                text=(
                    "Load the archive .csv, then scan the MEM folder for newly "
                    f"added .MEM files (no parsing).\n({csv_path})"
                ),
            )
            # Default to the fast path when an archive is available.
            self._mode_var.set(MODE_EXISTING_CSV_FAST)
        else:
            self._radio_fast.configure(state="disabled")
            self._fast_desc.configure(
                text="No CSV archive was selected on the previous page.",
            )
            self._radio_csv.configure(state="disabled")
            self._csv_desc.configure(
                text="No CSV archive was selected on the previous page.",
            )
            self._mode_var.set(MODE_PARSE_MEM)

        # Clear any previous status
        self._status_var.set("")
        self._info_var.set("")
        self._status_label.configure(text_color=DISABLED_FG)

    # ── Navigation handlers ────────────────────────────────

    def _handle_back(self):
        self._on_back()

    def _handle_next(self):
        mode = self._mode_var.get()
        if mode == 0:
            self._status_var.set("Please select an option above.")
            self._status_label.configure(text_color=ERROR_COLOR)
            return

        self._set_busy(True)
        self._status_var.set("Loading data...")
        self._status_label.configure(text_color=DISABLED_FG)
        self._info_var.set("")

        thread = threading.Thread(target=self._run_import, args=(mode,), daemon=True)
        thread.start()

    # ── Background import ──────────────────────────────────

    def _run_import(self, mode: int):
        """Execute the chosen import in a background thread."""
        try:
            if mode == MODE_EXISTING_CSV_FAST:
                # Fast path: load the archive as-is, no folder access at all.
                df = self._controller.load_csv_dataframe(merge_cmap=False)
                self.after(0, self._on_fast_success, df)
            elif mode == MODE_EXISTING_CSV:
                df = self._controller.load_csv_dataframe()
                new_count = self._controller.count_new_mem_files(df)
                self.after(0, self._on_import_success, df, new_count)
            else:
                df = self._controller.parse_and_build()
                attrs = getattr(df, "attrs", {})
                new_parsed = attrs.get("new_files_parsed", "?")
                self.after(0, self._on_parse_success, df, new_parsed)
        except Exception:
            msg = traceback.format_exc()
            self.after(0, self._on_import_error, msg)

    def _on_fast_success(self, df):
        """Callback after the fast archive load — advance immediately."""
        self._set_busy(False)
        self._status_var.set(f"Loaded {len(df)} rows from archive CSV.")
        self._status_label.configure(text_color=SUCCESS_COLOR)
        self._on_next()

    def _on_import_success(self, df, new_count: int):
        """Callback on the main thread after CSV load completes."""
        self._set_busy(False)
        rows = len(df)
        self._status_var.set(f"Loaded {rows} rows from CSV.")
        self._status_label.configure(text_color=SUCCESS_COLOR)

        if new_count > 0:
            self._info_var.set(
                f"{new_count} new .MEM file(s) found that are not in this CSV."
            )
        self._on_next()

    def _on_parse_success(self, df, new_parsed):
        """Callback on the main thread after MEM parsing completes."""
        self._set_busy(False)
        rows = len(df)
        self._status_var.set(f"DataFrame ready — {rows} rows ({new_parsed} new files parsed).")
        self._status_label.configure(text_color=SUCCESS_COLOR)
        self._on_next()

    def _on_import_error(self, msg: str):
        """Callback on the main thread when import fails."""
        self._set_busy(False)
        self._status_var.set(f"Import failed:\n{msg}")
        self._status_label.configure(text_color=ERROR_COLOR)

    # ── Helpers ────────────────────────────────────────────

    def _set_busy(self, busy: bool):
        """Toggle progress bar and disable/enable navigation."""
        if busy:
            self._progress.grid()
            self._progress.start()
            self._next_btn.configure(state="disabled")
            self._back_btn.configure(state="disabled")
        else:
            self._progress.stop()
            self._progress.grid_remove()
            self._next_btn.configure(state="normal")
            self._back_btn.configure(state="normal")
