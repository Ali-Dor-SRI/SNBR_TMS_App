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


class ExportPanel(ctk.CTkFrame):
    """Export page — page 5 (final) of the workflow."""

    def __init__(self, parent, controller, on_next, on_back):
        super().__init__(parent, fg_color="transparent")
        self._controller = controller
        self._on_next = on_next
        self._on_back = on_back

        # Checkbox + path state
        self._csv_check = ctk.BooleanVar(value=False)
        self._csv_path = ctk.StringVar()
        self._pdf_check = ctk.BooleanVar(value=False)
        self._pdf_path = ctk.StringVar()

        self._save_csv_default = ctk.BooleanVar(value=False)
        self._save_pdf_default = ctk.BooleanVar(value=False)

        self._status_var = ctk.StringVar()
        self._exporting = False

        self._build_ui()

        # Auto-check when a path is entered
        self._csv_path.trace_add("write", self._auto_check_csv)
        self._pdf_path.trace_add("write", self._auto_check_pdf)

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

        self._build_export_row(
            rows_frame, row=0,
            label="Export DataFrame to CSV",
            helper="Saves the working data frame as a .csv file for future use.",
            check_var=self._csv_check,
            path_var=self._csv_path,
            browse_cmd=self._browse_csv,
            save_var=self._save_csv_default,
        )

        self._build_export_row(
            rows_frame, row=1,
            label="Export Report to PDF",
            helper="Appends the selected graphs into a single PDF report.",
            check_var=self._pdf_check,
            path_var=self._pdf_path,
            browse_cmd=self._browse_pdf,
            save_var=self._save_pdf_default,
        )

        # ── Progress bar (hidden) ──────────────────────────
        self._progress = ctk.CTkProgressBar(self, mode="indeterminate", width=400)
        self._progress.grid(row=3, column=0, padx=PAD_X, pady=(PAD_Y, 0))
        self._progress.grid_remove()

        # ── Status label ───────────────────────────────────
        self._status_label = ctk.CTkLabel(
            self,
            textvariable=self._status_var,
            font=FONT_SMALL,
            text_color=DISABLED_FG,
            anchor="w",
            wraplength=700,
        )
        self._status_label.grid(row=4, column=0, sticky="w", padx=PAD_X, pady=(PAD_Y, 0))

        # ── Navigation ─────────────────────────────────────
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.grid(row=5, column=0, sticky="ew", padx=PAD_X, pady=(PAD_Y, SECTION_PAD_Y))
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
        check_var: ctk.BooleanVar, path_var: ctk.StringVar, browse_cmd,
        save_var: ctk.BooleanVar | None = None,
    ):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", pady=(0, SECTION_PAD_Y))
        frame.grid_columnconfigure(1, weight=1)

        cb = ctk.CTkCheckBox(
            frame, text=label, variable=check_var, font=FONT_HEADING,
        )
        cb.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))

        entry = ctk.CTkEntry(
            frame, textvariable=path_var,
            height=ENTRY_HEIGHT, corner_radius=CORNER_RADIUS, font=FONT_BODY,
        )
        entry.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(26, 8))

        browse_btn = ctk.CTkButton(
            frame, text="Browse", width=90, height=ENTRY_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BODY,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=browse_cmd,
        )
        browse_btn.grid(row=1, column=2, sticky="e")

        ctk.CTkLabel(
            frame, text=helper, font=FONT_SUBTITLE, text_color=SUBTITLE_COLOR, anchor="w",
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=(26, 0), pady=(2, 0))

        if save_var is not None:
            ctk.CTkCheckBox(
                frame, text="Save as default", variable=save_var, font=FONT_SMALL,
            ).grid(row=3, column=0, columnspan=3, sticky="w", padx=(26, 0), pady=(4, 0))

    # ── Browse dialogs ─────────────────────────────────────

    def _browse_csv(self):
        path = filedialog.asksaveasfilename(
            title="Save CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self._csv_path.set(path)

    def _browse_pdf(self):
        path = filedialog.asksaveasfilename(
            title="Save PDF",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self._pdf_path.set(path)

    # ── Auto-check ─────────────────────────────────────────

    def _auto_check_csv(self, *_args):
        self._csv_check.set(bool(self._csv_path.get().strip()))

    def _auto_check_pdf(self, *_args):
        self._pdf_check.set(bool(self._pdf_path.get().strip()))

    # ── Refresh ────────────────────────────────────────────

    def refresh(self):
        # Pre-populate from saved defaults (auto-check triggers via trace).
        defaults = self._controller.get_default_export_paths()
        self._csv_path.set(defaults.get("csv", ""))
        self._pdf_path.set(defaults.get("pdf", ""))
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
        csv_path = self._csv_path.get().strip() if csv_checked else ""
        pdf_path = self._pdf_path.get().strip() if pdf_checked else ""

        if csv_checked and not csv_path:
            errors.append("CSV export is checked but no path is set.")
        if pdf_checked and not pdf_path:
            errors.append("PDF export is checked but no path is set.")
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
            args=(csv_path, pdf_path),
            daemon=True,
        )
        thread.start()

    def _export_worker(self, csv_path: str, pdf_path: str):
        results: list[str] = []
        try:
            if csv_path:
                df = self._controller.get_export_dataframe()
                if df is None:
                    raise ValueError("No DataFrame available.")
                csv_path = self._controller.stamp_export_path(csv_path)
                out = Path(csv_path)
                out.parent.mkdir(parents=True, exist_ok=True)
                df.to_csv(out, index=False)
                results.append(f"CSV: {out}")

            if pdf_path:
                from reports.pdf_renderer import render_figures_to_pdf
                pdf_path = self._controller.stamp_export_path(pdf_path)
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

        # Persist checked export paths as defaults for next session.
        to_save = {}
        if self._save_csv_default.get() and self._csv_path.get().strip():
            to_save[KEY_EXPORT_CSV] = self._csv_path.get().strip()
        if self._save_pdf_default.get() and self._pdf_path.get().strip():
            to_save[KEY_EXPORT_PDF] = self._pdf_path.get().strip()
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
