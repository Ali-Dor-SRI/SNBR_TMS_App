"""Page 0 — Welcome screen with Quick Start and Custom Workflow options."""

from __future__ import annotations

import threading
import traceback
from pathlib import Path

import customtkinter as ctk
from gui.theme import (
    FONT_TITLE, FONT_HEADING, FONT_BODY, FONT_SMALL, FONT_SUBTITLE, FONT_BUTTON,
    ACCENT_COLOR, ACCENT_HOVER, ERROR_COLOR, SUCCESS_COLOR, DISABLED_FG, SUBTITLE_COLOR,
    PAD_X, PAD_Y, SECTION_PAD_Y, BUTTON_HEIGHT, CORNER_RADIUS,
)


class WelcomePanel(ctk.CTkFrame):
    """Welcome page — choose Quick Start (fully automatic) or Custom Workflow."""

    def __init__(self, parent, controller, on_done, on_custom, on_redirect,
                 footer=None):
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
        self._on_done = on_done
        self._on_custom = on_custom
        self._on_redirect = on_redirect

        self._status_var = ctk.StringVar()
        self._running = False

        self._build_ui()

    # ── UI ─────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.grid(row=0, column=0)

        # Title
        ctk.CTkLabel(
            inner, text="Welcome to SNBR TMS Reports", font=FONT_TITLE,
        ).pack(pady=(0, 8))

        ctk.CTkLabel(
            inner,
            text="Generate TMS reports from your data files.",
            font=FONT_SUBTITLE,
            text_color=SUBTITLE_COLOR,
        ).pack(pady=(0, 40))

        # Quick Start button
        self._quick_btn = ctk.CTkButton(
            inner,
            text="Quick Start",
            width=420,
            height=BUTTON_HEIGHT + 8,
            corner_radius=CORNER_RADIUS,
            font=FONT_BUTTON,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER,
            command=self._handle_quick_start,
        )
        self._quick_btn.pack(pady=(0, 4))

        ctk.CTkLabel(
            inner,
            text=(
                "Use saved defaults to automatically generate and export\n"
                "all graphs for the most recent visit."
            ),
            font=FONT_SMALL,
            text_color=SUBTITLE_COLOR,
            justify="center",
        ).pack(pady=(0, 28))

        # Custom Workflow button
        self._custom_btn = ctk.CTkButton(
            inner,
            text="Custom Workflow",
            width=420,
            height=BUTTON_HEIGHT + 8,
            corner_radius=CORNER_RADIUS,
            font=FONT_BUTTON,
            fg_color="transparent",
            hover_color=ACCENT_HOVER,
            border_width=2,
            border_color=ACCENT_COLOR,
            text_color=ACCENT_COLOR,
            command=self._on_custom,
        )
        self._custom_btn.pack(pady=(0, 4))

        ctk.CTkLabel(
            inner,
            text="Choose files, participant, and graphs step by step.",
            font=FONT_SMALL,
            text_color=SUBTITLE_COLOR,
            justify="center",
        ).pack(pady=(0, 36))

        # Progress bar (hidden)
        self._progress = ctk.CTkProgressBar(
            inner, mode="indeterminate", width=380,
        )
        self._progress.pack(pady=(0, 4))
        self._progress.pack_forget()

        # Status label
        self._status_label = ctk.CTkLabel(
            inner,
            textvariable=self._status_var,
            font=FONT_SMALL,
            text_color=DISABLED_FG,
            wraplength=500,
        )
        self._status_label.pack()

    # ── Quick Start ────────────────────────────────────────

    def _handle_quick_start(self):
        if self._running:
            return

        # Pre-flight check: are all required defaults saved?
        redirect = self._controller.check_quick_start_readiness()
        if redirect is not None:
            self._on_redirect(redirect)
            return

        self._set_busy(True)
        self._status_var.set("Starting Quick Start...")
        self._status_label.configure(text_color=DISABLED_FG)

        thread = threading.Thread(
            target=self._quick_start_worker,
            daemon=True,
        )
        thread.start()

    def _quick_start_worker(self):
        try:
            self._run_quick_start()
        except Exception:
            tb = traceback.format_exc()
            self.after(0, self._on_error, f"Quick Start failed:\n{tb}")

    def _run_quick_start(self):
        ctrl = self._controller

        def _status(msg):
            self.after(0, self._update_status, msg)

        summary = ctrl.run_default_phases(
            from_index=0,
            to_index=len(ctrl.PAGE_NAMES) - 1,
            status_callback=_status,
        )

        self.after(0, self._on_quick_start_done, summary)

    # ── UI update callbacks (main thread) ──────────────────

    def _update_status(self, msg: str):
        self._status_var.set(msg)

    def _redirect(self, page_name: str):
        self._set_busy(False)
        self._on_redirect(page_name)

    def _on_quick_start_done(self, summary: dict):
        self._set_busy(False)
        self._status_var.set("Quick Start complete.")
        self._status_label.configure(text_color=SUCCESS_COLOR)
        self._show_summary_popup(summary)

    def _show_summary_popup(self, s: dict):
        """Show a summary pop-up with details of the Quick Start run."""
        popup = ctk.CTkToplevel(self)
        popup.title("Quick Start Summary")
        popup.geometry("560x520")
        popup.resizable(False, False)
        popup.grab_set()
        popup.after(100, popup.focus_force)

        popup.grid_columnconfigure(0, weight=1)
        popup.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            popup, text="Quick Start Summary", font=FONT_TITLE,
        ).grid(row=0, column=0, padx=PAD_X, pady=(PAD_Y, 4), sticky="w")

        # Scrollable content
        scroll = ctk.CTkScrollableFrame(popup, fg_color="transparent")
        scroll.grid(row=1, column=0, sticky="nsew", padx=PAD_X, pady=(0, PAD_Y))
        scroll.grid_columnconfigure(0, weight=1)

        row = 0

        # Participant info
        study_label = f"{s['study']} - " if s["study"] else ""
        pid_text = f"{study_label}ID {s['pid']}  |  {s['date']}"
        cortex_text = ", ".join(s["cortex"]) if s["cortex"] else "N/A"

        row = self._add_section(scroll, row, "Participant", [
            f"ID: {pid_text}",
            f"Cortex: {cortex_text}",
        ])

        # Paths
        path_lines = []
        if s["mem_dir"]:
            path_lines.append(f"MEM Dir: {s['mem_dir']}")
        if s["csp_dir"]:
            path_lines.append(f"CSP Dir: {s['csp_dir']}")
        if s["csv_file"]:
            path_lines.append(f"CSV Source: {s['csv_file']}")
        if s["csv_export"]:
            path_lines.append(f"CSV Export: {s['csv_export']}")
        if s["pdf_export"]:
            path_lines.append(f"PDF Export: {s['pdf_export']}")
        row = self._add_section(scroll, row, "Paths", path_lines)

        # Graphs
        graph_lines = [f"{i+1}. {g}" for i, g in enumerate(s["graphs"])]
        graph_lines.append(f"Total figures: {s['figure_count']}")
        row = self._add_section(scroll, row, "Graphs in Report", graph_lines)

        # REDCap Export
        rc = s.get("redcap_summary")
        redcap_lines = []
        if rc:
            rows = rc.get("rows_changed", 0)
            cells = rc.get("cells_changed", 0) + rc.get("cells_filled", 0)
            out = rc.get("output_path", "")
            if rows > 0:
                redcap_lines.append(f"Rows: {rows}, Cells updated: {cells}")
                if out:
                    redcap_lines.append(f"File: {Path(out).name}")
            else:
                redcap_lines.append("No differences found.")
            qc = rc.get("quality_checks", {})
            if qc.get("warnings"):
                for w in qc["warnings"][:3]:
                    redcap_lines.append(f"Warning: {w}")
        else:
            redcap_lines.append("Skipped (no defaults saved or export failed).")
        row = self._add_section(scroll, row, "REDCap Export", redcap_lines)

        # Sync
        sync_lines = []
        if s["sync_pairs"]:
            for i, pair in enumerate(s["sync_pairs"], 1):
                sync_lines.append(f"Pair {i}: {pair.source} -> {pair.destination}")
            sr = s["sync_result"]
            if sr:
                sync_lines.append(
                    f"Result: {sr.files_copied} copied, "
                    f"{sr.files_skipped} skipped, "
                    f"{sr.files_failed} failed, "
                    f"{sr.bytes_copied:,} bytes in {sr.duration_seconds:.1f}s"
                )
                if sr.errors:
                    for err in sr.errors[:5]:
                        sync_lines.append(f"Error: {err}")
        else:
            sync_lines.append("No sync pairs configured.")
        row = self._add_section(scroll, row, "Backup & Sync", sync_lines)

        # OK button
        ctk.CTkButton(
            popup,
            text="OK",
            width=120,
            height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS,
            font=FONT_BUTTON,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER,
            command=lambda: self._close_summary(popup),
        ).grid(row=2, column=0, pady=(0, PAD_Y))

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

    def _close_summary(self, popup):
        popup.destroy()
        self._on_done()

    def _on_error(self, msg: str):
        self._set_busy(False)
        self._status_var.set(msg)
        self._status_label.configure(text_color=ERROR_COLOR)

    def _set_busy(self, busy: bool):
        self._running = busy
        if busy:
            self._progress.pack(pady=(0, 4), before=self._status_label)
            self._progress.start()
            self._quick_btn.configure(state="disabled")
            self._custom_btn.configure(state="disabled")
        else:
            self._progress.stop()
            self._progress.pack_forget()
            self._quick_btn.configure(state="normal")
            self._custom_btn.configure(state="normal")

    # ── Refresh ────────────────────────────────────────────

    def refresh(self):
        self._status_var.set("")
        self._status_label.configure(text_color=DISABLED_FG)
