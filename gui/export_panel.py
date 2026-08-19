"""Page 5 — export DataFrame to CSV and/or report to PDF."""

from __future__ import annotations

import threading
import traceback
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from core.user_settings import save_defaults, KEY_EXPORT_CSV, KEY_EXPORT_PDF
from gui.theme import (
    FONT_TITLE, FONT_HEADING, FONT_BODY, FONT_SMALL, FONT_SUBTITLE, FONT_BUTTON,
    ACCENT_COLOR, ACCENT_HOVER, ERROR_COLOR, SUCCESS_COLOR, DISABLED_FG, SUBTITLE_COLOR,
    PAD_X, PAD_Y, SECTION_PAD_Y, ENTRY_HEIGHT, BUTTON_HEIGHT, CORNER_RADIUS,
)
from gui.page_shell import resolve_footer


class ExportPanel(ctk.CTkFrame):
    """Export page — page 5 (final) of the workflow."""

    def __init__(self, parent, controller, on_next, on_back, footer=None):
        super().__init__(parent, fg_color="transparent")
        # The pinned bar at the bottom of the window; see gui.page_shell.
        self._footer = resolve_footer(self, footer)
        self._controller = controller
        self._on_next = on_next
        self._on_back = on_back

        # Checkbox + path state. Folder and file name are separate: a folder on
        # its own is enough, and the name box is what overrides the automatic
        # name (see AppController.resolve_export_target).
        self._csv_check = ctk.BooleanVar(value=False)
        self._csv_dir = ctk.StringVar()
        self._csv_name = ctk.StringVar()
        self._pdf_check = ctk.BooleanVar(value=False)
        self._pdf_dir = ctk.StringVar()
        self._pdf_name = ctk.StringVar()

        self._save_csv_default = ctk.BooleanVar(value=False)
        self._save_pdf_default = ctk.BooleanVar(value=False)

        self._status_var = ctk.StringVar()
        self._exporting = False

        self._build_ui()

        # Auto-check when either box is filled in
        self._csv_dir.trace_add("write", self._auto_check_csv)
        self._csv_name.trace_add("write", self._auto_check_csv)
        self._pdf_dir.trace_add("write", self._auto_check_pdf)
        self._pdf_name.trace_add("write", self._auto_check_pdf)

    # ── UI ─────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)

        # Title
        ctk.CTkLabel(
            self, text="Export", font=FONT_TITLE, anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=PAD_X, pady=(SECTION_PAD_Y, 4))

        ctk.CTkLabel(
            self,
            text="Choose export formats and destinations.",
            font=FONT_SUBTITLE,
            text_color=SUBTITLE_COLOR,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=PAD_X, pady=(0, SECTION_PAD_Y))

        # ── Export rows ────────────────────────────────────
        rows_frame = ctk.CTkFrame(self, fg_color="transparent")
        rows_frame.grid(row=2, column=0, sticky="ew", padx=PAD_X)
        rows_frame.grid_columnconfigure(0, weight=1)

        self._csv_dir_entry = self._build_export_row(
            rows_frame, row=0,
            label="Export DataFrame to CSV",
            helper=(
                "Saves the working data frame as a .csv file for future use. "
                "Leave the file name empty to name it automatically (df_<date>); "
                "a name you type gets the _<study>_ID<n>_<date> suffix."
            ),
            check_var=self._csv_check,
            dir_var=self._csv_dir,
            name_var=self._csv_name,
            browse_cmd=self._browse_csv,
            save_var=self._save_csv_default,
        )

        self._pdf_dir_entry = self._build_export_row(
            rows_frame, row=1,
            label="Export Report to PDF",
            helper=(
                "Appends the selected graphs into a single PDF report. "
                "Leave the file name empty to name it automatically "
                "(report_<study>_<participant>); a name you type gets the "
                "_<study>_ID<n>_<date> suffix."
            ),
            check_var=self._pdf_check,
            dir_var=self._pdf_dir,
            name_var=self._pdf_name,
            browse_cmd=self._browse_pdf,
            save_var=self._save_pdf_default,
        )

        # ── Progress bar (hidden) ──────────────────────────
        self._progress = ctk.CTkProgressBar(
            self._footer, mode="indeterminate", width=400,
        )
        self._progress.grid(row=0, column=0, padx=PAD_X, pady=(PAD_Y, 0))
        self._progress.grid_remove()

        # ── Status label ───────────────────────────────────
        self._status_label = ctk.CTkLabel(
            self._footer,
            textvariable=self._status_var,
            font=FONT_SMALL,
            text_color=DISABLED_FG,
            anchor="w",
            wraplength=700,
        )
        self._status_label.grid(row=1, column=0, sticky="w", padx=PAD_X, pady=(2, 0))

        # ── Navigation (pinned; see gui.page_shell) ────────
        nav = ctk.CTkFrame(self._footer, fg_color="transparent")
        nav.grid(row=2, column=0, sticky="ew", padx=PAD_X, pady=(PAD_Y, PAD_Y))
        nav.grid_columnconfigure(0, weight=1)

        self._back_btn = ctk.CTkButton(
            nav, text="Back", width=100, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._on_back,
        )
        self._back_btn.grid(row=0, column=0, sticky="w")

        self._export_btn = ctk.CTkButton(
            nav, text="Export All", width=120, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._handle_export,
        )
        self._export_btn.grid(row=0, column=1)

        self._next_btn = ctk.CTkButton(
            nav, text="Next", width=100, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._on_next,
        )
        self._next_btn.grid(row=0, column=2, sticky="e")

    def _build_export_row(
        self, parent, row: int, label: str, helper: str,
        check_var: ctk.BooleanVar, dir_var: ctk.StringVar,
        name_var: ctk.StringVar, browse_cmd,
        save_var: ctk.BooleanVar | None = None,
    ):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", pady=(0, SECTION_PAD_Y))
        frame.grid_columnconfigure(1, weight=1)

        cb = ctk.CTkCheckBox(
            frame, text=label, variable=check_var, font=FONT_HEADING,
        )
        cb.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))

        # Folder + Browse
        ctk.CTkLabel(
            frame, text="Folder", font=FONT_SMALL, text_color=SUBTITLE_COLOR,
            anchor="w", width=64,
        ).grid(row=1, column=0, sticky="w", padx=(26, 4))

        dir_entry = ctk.CTkEntry(
            frame, textvariable=dir_var,
            height=ENTRY_HEIGHT, corner_radius=CORNER_RADIUS, font=FONT_BODY,
        )
        dir_entry.grid(row=1, column=1, sticky="ew", padx=(0, 8))

        ctk.CTkButton(
            frame, text="Browse", width=90, height=ENTRY_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BODY,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=browse_cmd,
        ).grid(row=1, column=2, sticky="e")

        # Optional file name
        ctk.CTkLabel(
            frame, text="File name", font=FONT_SMALL, text_color=SUBTITLE_COLOR,
            anchor="w", width=64,
        ).grid(row=2, column=0, sticky="w", padx=(26, 4), pady=(4, 0))

        ctk.CTkEntry(
            frame, textvariable=name_var, placeholder_text="optional",
            height=ENTRY_HEIGHT, corner_radius=CORNER_RADIUS, font=FONT_BODY,
        ).grid(row=2, column=1, sticky="ew", padx=(0, 8), pady=(4, 0))

        ctk.CTkLabel(
            frame, text=helper, font=FONT_SUBTITLE, text_color=SUBTITLE_COLOR,
            anchor="w", justify="left", wraplength=620,
        ).grid(row=3, column=0, columnspan=3, sticky="w", padx=(26, 0), pady=(2, 0))

        if save_var is not None:
            ctk.CTkCheckBox(
                frame, text="Save folder as default", variable=save_var, font=FONT_SMALL,
            ).grid(row=4, column=0, columnspan=3, sticky="w", padx=(26, 0), pady=(4, 0))

        return dir_entry

    # ── Browse dialogs ─────────────────────────────────────

    def _browse_folder_into(self, var, title: str):
        """Ask for a directory and, if the user picked one, store it in *var*."""
        initial = var.get().strip()
        chosen = filedialog.askdirectory(
            title=title, initialdir=initial or None, mustexist=False,
        )
        if chosen:
            var.set(chosen)

    def _browse_csv(self):
        self._browse_folder_into(self._csv_dir, "Choose a folder for the CSV")

    def _browse_pdf(self):
        self._browse_folder_into(self._pdf_dir, "Choose a folder for the report")

    # ── Auto-check ─────────────────────────────────────────

    # Filling in either box still ticks the export. Clearing them does not
    # untick it: empty boxes mean "put it in the default folder and name it for
    # me" rather than "skip this export", so the tick is the only thing that
    # says what the user wants. Unticking by hand is how you skip one.
    def _auto_check_csv(self, *_args):
        if self._csv_dir.get().strip() or self._csv_name.get().strip():
            self._csv_check.set(True)

    def _auto_check_pdf(self, *_args):
        if self._pdf_dir.get().strip() or self._pdf_name.get().strip():
            self._pdf_check.set(True)

    # ── Refresh ────────────────────────────────────────────

    @staticmethod
    def _folder_of(saved: str) -> str:
        """The folder half of a saved default.

        Defaults saved before the folder/name split hold a full file path, so
        the filename is dropped rather than shown in the Folder box.
        """
        saved = (saved or "").strip()
        if not saved:
            return ""
        candidate = Path(saved)
        return str(candidate if candidate.is_dir() else candidate.parent)

    def refresh(self):
        # Pre-populate the folder from saved defaults (auto-check ticks via
        # trace). Start from unticked so a page with no saved defaults does not
        # silently request exports the user never asked for — which is also why
        # the fallback folder is shown as placeholder text rather than filled
        # in: it would tick both exports on every visit.
        defaults = self._controller.get_default_export_paths()
        self._csv_check.set(False)
        self._pdf_check.set(False)
        self._csv_dir.set(self._folder_of(defaults.get("csv", "")))
        self._pdf_dir.set(self._folder_of(defaults.get("pdf", "")))
        self._csv_name.set("")
        self._pdf_name.set("")
        for entry, kind in (
            (self._csv_dir_entry, "csv"), (self._pdf_dir_entry, "pdf"),
        ):
            try:
                entry.configure(
                    placeholder_text=self._controller.default_export_folder(kind)
                )
            except Exception:
                pass
        self._save_csv_default.set(False)
        self._save_pdf_default.set(False)
        self._status_var.set("")
        self._status_label.configure(text_color=DISABLED_FG)

        msg = self._controller.consume_quick_start_message()
        if msg:
            self._status_var.set(msg)
            self._status_label.configure(text_color="#F39C12")

    # ── Export logic ───────────────────────────────────────

    def _handle_export(self):
        if self._exporting:
            return

        csv_checked = self._csv_check.get()
        pdf_checked = self._pdf_check.get()

        if not csv_checked and not pdf_checked:
            self._status_var.set("Nothing selected for export.")
            self._status_label.configure(text_color=ERROR_COLOR)
            return

        errors: list[str] = []
        csv_dir = self._csv_dir.get().strip() if csv_checked else ""
        csv_name = self._csv_name.get().strip() if csv_checked else ""
        pdf_dir = self._pdf_dir.get().strip() if pdf_checked else ""
        pdf_name = self._pdf_name.get().strip() if pdf_checked else ""

        # Empty boxes are fine: the controller picks the folder and names the
        # file from the participant and date (see reports.export_naming).
        if pdf_checked and not self._controller.get_report_figures():
            errors.append("No figures available for PDF export.")

        if errors:
            self._status_var.set("\n".join(errors))
            self._status_label.configure(text_color=ERROR_COLOR)
            return

        self._set_busy(True)
        self._status_var.set("Exporting...")
        self._status_label.configure(text_color=DISABLED_FG)

        thread = threading.Thread(
            target=self._export_worker,
            args=(csv_dir, csv_name, pdf_dir, pdf_name, csv_checked, pdf_checked),
            daemon=True,
        )
        thread.start()

    def _export_worker(
        self, csv_dir: str, csv_name: str, pdf_dir: str, pdf_name: str,
        csv_wanted: bool = True, pdf_wanted: bool = True,
    ):
        """Write the checked exports.

        The *wanted* flags carry the checkbox state, because empty boxes no
        longer mean "not requested" — they mean "default folder, name it for me".
        """
        results: list[str] = []
        try:
            if csv_wanted:
                df = self._controller.get_export_dataframe()
                if df is None:
                    raise ValueError("No DataFrame available.")
                csv_path = self._controller.resolve_export_target(
                    "csv", csv_dir, csv_name,
                )
                out = Path(csv_path)
                out.parent.mkdir(parents=True, exist_ok=True)
                df.to_csv(out, index=False)
                results.append(f"CSV: {out}")

            if pdf_wanted:
                from reports.pdf_renderer import render_figures_to_pdf
                pdf_path = self._controller.resolve_export_target(
                    "pdf", pdf_dir, pdf_name,
                )
                Path(pdf_path).parent.mkdir(parents=True, exist_ok=True)
                figures = self._controller.get_report_figures()
                render_figures_to_pdf(figures, pdf_path)
                self._controller.set_last_exported_pdf(pdf_path)
                results.append(f"PDF: {pdf_path}")

            self.after(0, self._on_export_success, "\n".join(results))
        except Exception:
            self.after(0, self._on_export_error, traceback.format_exc())

    def _on_export_success(self, msg: str):
        self._set_busy(False)
        self._status_var.set(f"Export complete:\n{msg}")
        self._status_label.configure(text_color=SUCCESS_COLOR)

        # Persist the FOLDER only, never the file name: the name is a per-export
        # choice, and remembering it would bring a stale filename back next run
        # (and a typed name is not uniquified, so it would overwrite).
        # The folder actually used is stored, so leaving the box empty and
        # ticking "save as default" pins whatever folder the export landed in.
        to_save = {}
        if self._save_csv_default.get():
            folder = self._csv_dir.get().strip() or self._controller.default_export_folder("csv")
            if folder:
                to_save[KEY_EXPORT_CSV] = folder
        if self._save_pdf_default.get():
            folder = self._pdf_dir.get().strip() or self._controller.default_export_folder("pdf")
            if folder:
                to_save[KEY_EXPORT_PDF] = folder
        if to_save:
            save_defaults(**to_save)

    def _on_export_error(self, msg: str):
        self._set_busy(False)
        self._status_var.set(f"Export failed:\n{msg}")
        self._status_label.configure(text_color=ERROR_COLOR)

    def _set_busy(self, busy: bool):
        self._exporting = busy
        if busy:
            self._progress.grid()
            self._progress.start()
            self._export_btn.configure(state="disabled")
            self._back_btn.configure(state="disabled")
        else:
            self._progress.stop()
            self._progress.grid_remove()
            self._export_btn.configure(state="normal")
            self._back_btn.configure(state="normal")
