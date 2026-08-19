"""Page 6 — REDCap Export panel.

Lets the user point at directories containing REDCap CSV files
(data export, data dictionary, import template) and an output directory,
then generates a REDCap import CSV containing only the TMS values that
differ from the current REDCap data.
"""

from __future__ import annotations

import threading
from pathlib import Path
from tkinter import filedialog, StringVar, BooleanVar

import customtkinter as ctk

from gui.theme import (
    ACCENT_COLOR, ACCENT_HOVER, DISABLED_FG, ERROR_COLOR,
    FONT_BODY, FONT_BUTTON, FONT_HEADING, FONT_SMALL,
    FONT_SUBTITLE, FONT_TITLE, SUBTITLE_COLOR, SUCCESS_COLOR,
    BUTTON_HEIGHT, CORNER_RADIUS, ENTRY_HEIGHT, PAD_X, PAD_Y,
    SECTION_PAD_Y,
)


class RedcapPanel(ctk.CTkFrame):
    """GUI frame for generating a REDCap import CSV."""

    def __init__(
        self,
        parent,
        controller,
        on_next=None,
        on_back=None,
        footer=None,
    ):
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
        self._on_next = on_next
        self._on_back = on_back

        # Path variables
        self._data_var = StringVar(value="")
        self._dict_var = StringVar(value="")
        self._template_var = StringVar(value="")
        self._export_var = StringVar(value="")
        self._xlsx_var = StringVar(value="")

        # Save-default checkboxes
        self._save_data = BooleanVar(value=False)
        self._save_dict = BooleanVar(value=False)
        self._save_template = BooleanVar(value=False)
        self._save_export = BooleanVar(value=False)
        self._save_xlsx = BooleanVar(value=False)

        # Option: include new participants not yet in the REDCap export
        self._include_new_ids = BooleanVar(value=False)

        # State
        self._status_var = StringVar(value="")
        self._exporting = False

        self._build_ui()

    # ── UI construction ───────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        row = 0

        # Title
        ctk.CTkLabel(
            self, text="REDCap Export", font=FONT_TITLE, anchor="w",
        ).grid(row=row, column=0, sticky="w", padx=PAD_X, pady=(SECTION_PAD_Y, 0))
        row += 1

        ctk.CTkLabel(
            self,
            text="Generate an import file for REDCap TMS values",
            font=FONT_SUBTITLE,
            text_color=SUBTITLE_COLOR,
            anchor="w",
        ).grid(row=row, column=0, sticky="w", padx=PAD_X, pady=(0, SECTION_PAD_Y))
        row += 1

        # Scrollable content for the 4 path rows
        self._fields = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._fields.grid(
            row=row, column=0, sticky="nsew", padx=PAD_X, pady=(0, PAD_Y),
        )
        self._fields.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(row, weight=1)
        row += 1

        frow = 0
        frow = self._add_path_row(
            self._fields, frow,
            "REDCap Data Directory *",
            "Folder containing SNBR_DATA_*.csv",
            self._data_var,
            self._save_data,
        )
        frow = self._add_path_row(
            self._fields, frow,
            "Data Dictionary Directory *",
            "Folder containing SNBR_DataDictionary_*.csv",
            self._dict_var,
            self._save_dict,
        )
        frow = self._add_path_row(
            self._fields, frow,
            "Import Template Directory *",
            "Folder containing SNBR_ImportTemplate_*.csv",
            self._template_var,
            self._save_template,
        )
        frow = self._add_path_row(
            self._fields, frow,
            "Export Directory *",
            "Where the timestamped import CSV will be saved",
            self._export_var,
            self._save_export,
        )
        frow = self._add_path_row(
            self._fields, frow,
            "Change Report Directory (optional)",
            "Where the human-readable .xlsx diff will be saved. "
            "Leave blank to skip the change report.",
            self._xlsx_var,
            self._save_xlsx,
        )

        # Toggle: include new participants (not yet in REDCap)
        options = ctk.CTkFrame(self, fg_color="transparent")
        options.grid(row=row, column=0, sticky="ew", padx=PAD_X, pady=(0, PAD_Y))
        options.grid_columnconfigure(1, weight=1)

        ctk.CTkSwitch(
            options,
            text="Include new participants (not yet in REDCap)",
            variable=self._include_new_ids,
            font=FONT_BODY,
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            options,
            text=(
                "Off: only update IDs already in REDCap. "
                "On: also add rows for new IDs (event name left blank)."
            ),
            font=FONT_SMALL,
            text_color=DISABLED_FG,
            anchor="w",
            wraplength=600,
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        row += 1

        # Progress bar (hidden)
        self._progress = ctk.CTkProgressBar(self._footer, mode="indeterminate")
        self._progress.grid(
            row=0, column=0, sticky="ew", padx=PAD_X, pady=(PAD_Y, 0),
        )
        self._progress.grid_remove()

        # Status
        self._status_label = ctk.CTkLabel(
            self._footer,
            textvariable=self._status_var,
            font=FONT_SMALL,
            text_color=DISABLED_FG,
            anchor="w",
            wraplength=600,
        )
        self._status_label.grid(row=1, column=0, sticky="w", padx=PAD_X, pady=(2, 0))

        # Navigation (pinned; see gui.page_shell)
        nav = ctk.CTkFrame(self._footer, fg_color="transparent")
        nav.grid(row=2, column=0, sticky="ew", padx=PAD_X, pady=(PAD_Y, PAD_Y))
        nav.grid_columnconfigure(1, weight=1)

        self._back_btn = ctk.CTkButton(
            nav, text="Back", width=100, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color="transparent", border_width=2,
            border_color=ACCENT_COLOR, text_color=ACCENT_COLOR,
            hover_color=("gray90", "gray25"),
            command=self._on_back,
        )
        self._back_btn.grid(row=0, column=0, sticky="w")

        self._gen_btn = ctk.CTkButton(
            nav, text="Generate", width=160, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._handle_generate,
        )
        self._gen_btn.grid(row=0, column=1)

        self._next_btn = ctk.CTkButton(
            nav, text="Next", width=100, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._on_next,
        )
        self._next_btn.grid(row=0, column=2, sticky="e")

    def _add_path_row(
        self,
        parent,
        row: int,
        label: str,
        helper: str,
        var: StringVar,
        save_var: BooleanVar,
    ) -> int:
        """Add a labeled directory path row with Browse and Save checkbox."""
        ctk.CTkLabel(
            parent, text=label, font=FONT_HEADING, anchor="w",
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(PAD_Y, 2))
        row += 1

        entry = ctk.CTkEntry(
            parent, textvariable=var, height=ENTRY_HEIGHT,
            font=FONT_BODY, corner_radius=CORNER_RADIUS,
        )
        entry.grid(row=row, column=0, columnspan=2, sticky="ew", padx=(0, 8))

        ctk.CTkButton(
            parent, text="Browse", width=80, height=ENTRY_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BODY,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=lambda v=var: self._browse_dir(v),
        ).grid(row=row, column=2, sticky="e")
        row += 1

        bottom = ctk.CTkFrame(parent, fg_color="transparent")
        bottom.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(2, 0))

        ctk.CTkLabel(
            bottom, text=helper, font=FONT_SMALL,
            text_color=DISABLED_FG, anchor="w",
        ).pack(side="left")

        ctk.CTkCheckBox(
            bottom, text="Save as default", font=FONT_SMALL,
            variable=save_var, checkbox_width=18, checkbox_height=18,
        ).pack(side="right")
        row += 1

        return row

    # ── Browse ────────────────────────────────────────────

    def _browse_dir(self, var: StringVar):
        initial = var.get().strip() or None
        chosen = filedialog.askdirectory(
            title="Select Directory",
            initialdir=initial,
        )
        if chosen:
            var.set(chosen)

    # ── Refresh ───────────────────────────────────────────

    def refresh(self):
        """Reload saved defaults into the path entries."""
        defaults = self._controller.get_redcap_defaults()
        if defaults["data_dir"] and not self._data_var.get().strip():
            self._data_var.set(defaults["data_dir"])
        if defaults["dict_dir"] and not self._dict_var.get().strip():
            self._dict_var.set(defaults["dict_dir"])
        if defaults["template_dir"] and not self._template_var.get().strip():
            self._template_var.set(defaults["template_dir"])
        if defaults["export_dir"] and not self._export_var.get().strip():
            self._export_var.set(defaults["export_dir"])
        if defaults.get("xlsx_dir") and not self._xlsx_var.get().strip():
            self._xlsx_var.set(defaults["xlsx_dir"])

        self._status_var.set("")
        self._status_label.configure(text_color=DISABLED_FG)

        # Consume any redirect message from Quick Start
        msg = self._controller.consume_quick_start_message()
        if msg:
            self._status_var.set(msg)
            self._status_label.configure(text_color=ERROR_COLOR)

    # ── Generate ──────────────────────────────────────────

    def _handle_generate(self):
        if self._exporting:
            return

        # Validate all paths provided
        data_dir = self._data_var.get().strip()
        dict_dir = self._dict_var.get().strip()
        template_dir = self._template_var.get().strip()
        export_dir = self._export_var.get().strip()

        missing = []
        if not data_dir:
            missing.append("REDCap Data Directory")
        if not dict_dir:
            missing.append("Data Dictionary Directory")
        if not template_dir:
            missing.append("Import Template Directory")
        if not export_dir:
            missing.append("Export Directory")

        if missing:
            self._status_var.set(
                f"Missing required paths: {', '.join(missing)}"
            )
            self._status_label.configure(text_color=ERROR_COLOR)
            return

        # Validate directories exist
        for label, path in [
            ("REDCap Data", data_dir),
            ("Dictionary", dict_dir),
            ("Template", template_dir),
        ]:
            if not Path(path).is_dir():
                self._status_var.set(f"{label} directory not found: {path}")
                self._status_label.configure(text_color=ERROR_COLOR)
                return

        self._set_busy(True)
        self._status_var.set("Generating REDCap import...")
        self._status_label.configure(text_color=DISABLED_FG)

        include_new_ids = bool(self._include_new_ids.get())
        xlsx_dir = self._xlsx_var.get().strip() or None
        thread = threading.Thread(
            target=self._generate_worker,
            args=(
                data_dir, dict_dir, template_dir, export_dir,
                include_new_ids, xlsx_dir,
            ),
            daemon=True,
        )
        thread.start()

    def _generate_worker(
        self, data_dir, dict_dir, template_dir, export_dir,
        include_new_ids, xlsx_dir,
    ):
        try:
            summary = self._controller.run_redcap_export(
                data_dir=data_dir,
                dict_dir=dict_dir,
                template_dir=template_dir,
                export_dir=export_dir,
                include_new_ids=include_new_ids,
                xlsx_report_dir=xlsx_dir,
            )
            self.after(0, self._on_success, summary)
        except Exception as exc:
            self.after(0, self._on_error, str(exc))

    def _on_success(self, summary: dict):
        self._set_busy(False)

        # Save defaults if checked
        to_save = {}
        if self._save_data.get():
            to_save["data_dir"] = self._data_var.get().strip()
        if self._save_dict.get():
            to_save["dict_dir"] = self._dict_var.get().strip()
        if self._save_template.get():
            to_save["template_dir"] = self._template_var.get().strip()
        if self._save_export.get():
            to_save["export_dir"] = self._export_var.get().strip()
        if self._save_xlsx.get():
            to_save["xlsx_dir"] = self._xlsx_var.get().strip()
        if to_save:
            self._controller.save_redcap_defaults(**to_save)

        rows = summary.get("rows_changed", 0)
        cells_changed = summary.get("cells_changed", 0)
        cells_filled = summary.get("cells_filled", 0)
        total = cells_changed + cells_filled
        output = summary.get("output_path", "")
        qc = summary.get("quality_checks", {})

        if rows == 0:
            msg = "No differences found. REDCap data matches Python data."
            self._status_label.configure(text_color=SUCCESS_COLOR)
        else:
            msg = (
                f"Generated: {rows} rows, {total} cells "
                f"({cells_changed} changed, {cells_filled} filled blanks)"
            )
            if output:
                msg += f"\nSaved to: {Path(output).name}"
            xlsx_path = summary.get("xlsx_report_path")
            if xlsx_path:
                msg += f"\nChange report: {Path(xlsx_path).name}"
            if qc.get("warnings"):
                msg += f"\nWarnings: {len(qc['warnings'])}"
            self._status_label.configure(text_color=SUCCESS_COLOR)

        # REDCap holds one record per participant-visit, so only the hand
        # recording is exported. Name what that left out.
        skipped_targets = summary.get("skipped_targets") or []
        if skipped_targets:
            msg += (
                "\nNot exported (REDCap keeps one record per visit): "
                + ", ".join(skipped_targets)
            )

        self._status_var.set(msg)

    def _on_error(self, msg: str):
        self._set_busy(False)
        self._status_var.set(f"Error: {msg}")
        self._status_label.configure(text_color=ERROR_COLOR)

    def _set_busy(self, busy: bool):
        self._exporting = busy
        if busy:
            self._progress.grid()
            self._progress.start()
            self._gen_btn.configure(state="disabled")
            self._back_btn.configure(state="disabled")
            self._next_btn.configure(state="disabled")
        else:
            self._progress.stop()
            self._progress.grid_remove()
            self._gen_btn.configure(state="normal")
            self._back_btn.configure(state="normal")
            self._next_btn.configure(state="normal")
