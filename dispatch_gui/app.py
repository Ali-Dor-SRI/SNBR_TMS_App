"""The dispatch window: a Worklist tab and a Settings tab.

Worklist: load, tick the reports for this week's batch, Prepare, then for each
part -- Copy subject / Copy body / Open folder / Open mail / Mark as sent. The
send itself happens in Outlook on the web by hand; "Mark as sent" is the
operator's declaration and is what the ledger records.

All backend work goes through :class:`dispatch_gui.controller.DispatchController`
on a background thread; results come back via ``after(0, ...)``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from dispatch_gui.controller import DispatchController
from gui.theme import (
    ACCENT_COLOR, ACCENT_HOVER, BUTTON_HEIGHT, CORNER_RADIUS, DISABLED_FG, ENTRY_HEIGHT,
    ERROR_COLOR, FONT_BODY, FONT_BUTTON, FONT_HEADING, FONT_SMALL, FONT_SUBTITLE,
    FONT_TITLE, PAD_X, PAD_Y, SECTION_PAD_Y, SUBTITLE_COLOR, SUCCESS_COLOR,
)

# Settings keys are addressed by name so this module needs no dispatch import.
_S = {
    "roster_path": ("Enrolment workbook (.xlsx)", "file"),
    "roster_sheet": ("Worksheet name", "text"),
    "col_patient_id": ("Patient ID column header", "text"),
    "col_patient_name": ("Patient Name column header", "text"),
    "col_mrn": ("MRN column header", "text"),
    "reports_dir": ("Exported reports folder", "dir"),
    "identified_dir": ("Identified reports folder (batches)", "dir"),
    "ledger_path": ("Ledger file (.jsonl, on the shared drive)", "savefile"),
    "recipients": ("Recipients (comma-separated)", "text"),
    "allowed_domain": ("Allowed recipient domain", "text"),
    "size_cap_mb": ("Attachment cap per email (MB)", "int"),
    "subject_template": ("Subject template  ({week_start}, {part}, {count})", "text"),
}

_STATUS_COLOR = {
    "unsent": ACCENT_COLOR,
    "revision": "#B7791F",
    "sent": SUCCESS_COLOR,
    "closed": DISABLED_FG,
}
_STATUS_ORDER = {"unsent": 0, "revision": 0, "sent": 1, "closed": 2}
_WARN_COLOR = "#B7791F"


def _resolve_logo_dir() -> Path:
    """The dispatch app's own mark, not the analysis app's.

    ``icons/logo_dispatch/`` (the envelope) rather than ``icons/logo/`` (the
    coil), so the two executables are told apart in the taskbar. In a bundle
    ``sys._MEIPASS`` is the extracted data root, where the spec's
    ``('icons', 'icons')`` entry lands -- the whole tree, both marks.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "icons" / "logo_dispatch"
    return Path(__file__).resolve().parent.parent / "icons" / "logo_dispatch"


def _open_path(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # noqa: S606 - opening a folder the app wrote
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class DispatchApp(ctk.CTk):
    WIDTH = 1180
    HEIGHT = 780

    def __init__(self, controller: DispatchController | None = None):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("SNBR Report Dispatch")
        self.geometry(f"{self.WIDTH}x{self.HEIGHT}")
        self.minsize(900, 600)
        self._apply_window_icon()

        self._controller = controller or DispatchController()
        self._busy = False
        self._row_vars: list[tuple[ctk.BooleanVar, object]] = []   # (var, WorklistItem)
        self._part_widgets: list[dict] = []
        self._setting_vars: dict[str, ctk.StringVar] = {}

        self._build()
        if self._controller.missing_configuration():
            self._tabs.set("Settings")
            self._set_status(
                "Fill in the settings first: "
                + ", ".join(self._controller.missing_configuration()), warn=True,
            )

    def _apply_window_icon(self) -> None:
        """Put the dispatch mark on the window and the taskbar button.

        Windows only, and purely cosmetic -- a missing or unreadable file must
        not stop the app opening. Calling ``iconbitmap`` at all also stops
        CustomTkinter installing its own icon on a timer.
        """
        if not sys.platform.startswith("win"):
            return
        try:
            self.iconbitmap(str(_resolve_logo_dir() / "dispatch.ico"))
        except Exception:
            pass

    # -- layout ------------------------------------------------------------------

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=PAD_X, pady=(SECTION_PAD_Y, 0))
        ctk.CTkLabel(header, text="SNBR Report Dispatch", font=FONT_TITLE, anchor="w").pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Bind patient identity to exported reports, pack this week's batch, "
                 "and record what was sent. The email itself is sent from Outlook on the web.",
            font=FONT_SUBTITLE, text_color=SUBTITLE_COLOR, anchor="w", wraplength=1000, justify="left",
        ).pack(anchor="w")

        self._tabs = ctk.CTkTabview(self, corner_radius=CORNER_RADIUS)
        self._tabs.grid(row=1, column=0, sticky="nsew", padx=PAD_X, pady=(PAD_Y, 0))
        self._build_worklist_tab(self._tabs.add("Worklist"))
        self._build_settings_tab(self._tabs.add("Settings"))

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=PAD_X, pady=(4, PAD_Y))
        self._status_var = ctk.StringVar(value="")
        self._status_label = ctk.CTkLabel(
            footer, textvariable=self._status_var, font=FONT_SMALL, anchor="w",
            wraplength=1100, justify="left",
        )
        self._status_label.pack(anchor="w", fill="x")
        # configure(text_color=None) is rejected by CTk; keep the default to restore.
        self._status_default_color = self._status_label.cget("text_color")

    # -- worklist tab ------------------------------------------------------------

    def _build_worklist_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=3)
        tab.grid_rowconfigure(2, weight=1)

        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(0, PAD_Y))
        self._load_btn = ctk.CTkButton(
            bar, text="Load / Refresh", width=140, height=BUTTON_HEIGHT, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER, command=self._on_load,
        )
        self._load_btn.pack(side="left")
        self._select_all_btn = ctk.CTkButton(
            bar, text="Tick all proposed", width=140, height=BUTTON_HEIGHT, font=FONT_SMALL,
            fg_color="transparent", border_width=1, command=lambda: self._tick_all(True),
        )
        self._select_all_btn.pack(side="left", padx=(PAD_Y, 0))
        self._clear_btn = ctk.CTkButton(
            bar, text="Untick all", width=100, height=BUTTON_HEIGHT, font=FONT_SMALL,
            fg_color="transparent", border_width=1, command=lambda: self._tick_all(False),
        )
        self._clear_btn.pack(side="left", padx=(6, 0))
        self._counts_var = ctk.StringVar(value="Nothing loaded yet.")
        ctk.CTkLabel(bar, textvariable=self._counts_var, font=FONT_SMALL, anchor="w").pack(
            side="left", padx=(PAD_X, 0),
        )
        self._prepare_btn = ctk.CTkButton(
            bar, text="Prepare batch", width=150, height=BUTTON_HEIGHT, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER, command=self._on_prepare,
            state="disabled",
        )
        self._prepare_btn.pack(side="right")

        self._table = ctk.CTkScrollableFrame(tab, corner_radius=CORNER_RADIUS)
        self._table.grid(row=1, column=0, sticky="nsew")
        for col, weight in ((2, 3), (3, 2), (6, 4)):
            self._table.grid_columnconfigure(col, weight=weight)
        self._render_table_header()

        lower = ctk.CTkFrame(tab, fg_color="transparent")
        lower.grid(row=2, column=0, sticky="nsew", pady=(PAD_Y, 0))
        lower.grid_columnconfigure(0, weight=3)
        lower.grid_columnconfigure(1, weight=2)
        lower.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(lower, text="This batch", font=FONT_HEADING, anchor="w").grid(
            row=0, column=0, sticky="w",
        )
        self._parts_frame = ctk.CTkScrollableFrame(lower, corner_radius=CORNER_RADIUS)
        self._parts_frame.grid(row=1, column=0, sticky="nsew", padx=(0, PAD_Y))
        self._parts_frame.grid_columnconfigure(0, weight=1)
        self._parts_placeholder = ctk.CTkLabel(
            self._parts_frame, text="Tick the reports to send, then Prepare batch.",
            font=FONT_SMALL, text_color=DISABLED_FG, anchor="w",
        )
        self._parts_placeholder.grid(row=0, column=0, sticky="w", padx=8, pady=8)

        ctk.CTkLabel(lower, text="Issues", font=FONT_HEADING, anchor="w").grid(
            row=0, column=1, sticky="w",
        )
        self._issues = ctk.CTkTextbox(lower, corner_radius=CORNER_RADIUS, font=FONT_SMALL, wrap="word")
        self._issues.grid(row=1, column=1, sticky="nsew")
        self._issues.configure(state="disabled")

    def _render_table_header(self):
        headers = ("", "Study ID", "Patient name", "MRN", "Visit", "Status", "Note")
        for col, text in enumerate(headers):
            ctk.CTkLabel(self._table, text=text, font=FONT_HEADING, anchor="w").grid(
                row=0, column=col, sticky="w", padx=6, pady=(0, 4),
            )

    def _clear_table(self):
        for widget in self._table.winfo_children():
            widget.destroy()
        self._row_vars = []
        self._render_table_header()

    def _apply_worklist(self, worklist):
        """Render *worklist* (called on the Tk thread)."""
        self._clear_table()
        items = sorted(
            worklist.items,
            key=lambda i: (_STATUS_ORDER.get(i.status, 9), i.report.key, i.report.visit_token),
        )
        for row, item in enumerate(items, start=1):
            var = ctk.BooleanVar(value=item.proposed)
            box = ctk.CTkCheckBox(self._table, text="", variable=var, width=24)
            box.grid(row=row, column=0, sticky="w", padx=(6, 0))
            if not item.proposed:
                box.configure(state="disabled")
            self._row_vars.append((var, item))

            status_text = item.status.upper()
            if item.sent is not None:
                status_text += f" ({item.sent.at[:10]} by {item.sent.user})"
            note = item.unresolved_reason
            if item.is_revision:
                note = ("revised since a version was sent" + (f"; {note}" if note else ""))
            cells = (
                item.report.key.label(), item.display_name, item.display_mrn,
                item.report.visit_label, status_text, note or "",
            )
            for col, text in enumerate(cells, start=1):
                color = _STATUS_COLOR.get(item.status) if col == 5 else (
                    _WARN_COLOR if (col == 6 and note) else None
                )
                ctk.CTkLabel(
                    self._table, text=text, font=FONT_SMALL, anchor="w",
                    text_color=color, wraplength=360 if col == 6 else 0, justify="left",
                ).grid(row=row, column=col, sticky="w", padx=6, pady=1)

        counts = worklist.counts()
        self._counts_var.set(
            f"{counts['unsent']} unsent, {counts['revision']} revised, "
            f"{counts['sent']} sent, {counts['closed']} closed"
        )
        self._prepare_btn.configure(state="normal" if worklist.proposed() else "disabled")
        self._set_issues(self._controller.issues_lines())

    def _set_issues(self, lines: list[str]):
        self._issues.configure(state="normal")
        self._issues.delete("1.0", "end")
        self._issues.insert("1.0", "\n".join(lines) if lines else "None.")
        self._issues.configure(state="disabled")

    def _tick_all(self, value: bool):
        for var, item in self._row_vars:
            if item.proposed:
                var.set(value)

    def _selected_items(self):
        return [item for var, item in self._row_vars if item.proposed and var.get()]

    # -- batch panel -------------------------------------------------------------

    def _apply_batch(self, batch):
        """Render the parts of *batch* (called on the Tk thread)."""
        for widget in self._parts_frame.winfo_children():
            widget.destroy()
        self._part_widgets = []
        row = 0
        ctk.CTkLabel(
            self._parts_frame, text=f"Batch folder: {batch.folder}", font=FONT_SMALL,
            anchor="w", wraplength=620, justify="left",
        ).grid(row=row, column=0, sticky="w", padx=8, pady=(6, 2))
        row += 1
        for warning in batch.warnings:
            ctk.CTkLabel(
                self._parts_frame, text=warning, font=FONT_SMALL, text_color=_WARN_COLOR,
                anchor="w", wraplength=620, justify="left",
            ).grid(row=row, column=0, sticky="w", padx=8, pady=1)
            row += 1
        for part in batch.parts:
            card = ctk.CTkFrame(self._parts_frame, corner_radius=CORNER_RADIUS)
            card.grid(row=row, column=0, sticky="ew", padx=6, pady=6)
            card.grid_columnconfigure(0, weight=1)
            row += 1
            size_mb = part.total_bytes / (1024 * 1024)
            ctk.CTkLabel(
                card,
                text=f"Part {part.index} of {part.parts}  -  {len(part.entries)} attachment(s), "
                     f"{size_mb:.1f} MB\nSubject: {part.subject}",
                font=FONT_BODY, anchor="w", justify="left",
            ).grid(row=0, column=0, sticky="w", padx=8, pady=(6, 2))
            names = "\n".join(f"  {e.filename}" for e in part.entries)
            ctk.CTkLabel(card, text=names, font=FONT_SMALL, anchor="w", justify="left").grid(
                row=1, column=0, sticky="w", padx=8,
            )
            buttons = ctk.CTkFrame(card, fg_color="transparent")
            buttons.grid(row=2, column=0, sticky="w", padx=8, pady=(4, 8))
            widgets = {"part": part}
            for text, cmd in (
                ("Copy subject", lambda p=part: self._copy(p.subject)),
                ("Copy body", lambda p=part: self._copy(p.body)),
                ("Open folder", lambda p=part: _open_path(p.folder)),
                ("Open mail", lambda p=part: webbrowser.open(self._controller.mailto(p))),
            ):
                ctk.CTkButton(
                    buttons, text=text, width=110, height=30, font=FONT_SMALL,
                    fg_color="transparent", border_width=1, command=cmd,
                ).pack(side="left", padx=(0, 6))
            sent_btn = ctk.CTkButton(
                buttons, text="Mark as sent", width=130, height=30, font=FONT_BUTTON,
                fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
                command=lambda p=part: self._on_mark_sent(p),
            )
            sent_btn.pack(side="left", padx=(12, 0))
            widgets["sent_button"] = sent_btn
            self._part_widgets.append(widgets)

    def _copy(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)
        self._set_status("Copied to the clipboard.")

    # -- settings tab ------------------------------------------------------------

    def _build_settings_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(1, weight=1)

        settings = self._controller.settings
        for row, (key, (label, kind)) in enumerate(_S.items()):
            ctk.CTkLabel(scroll, text=label, font=FONT_BODY, anchor="w").grid(
                row=row, column=0, sticky="w", padx=(0, PAD_Y), pady=4,
            )
            value = settings.get(key, "")
            if isinstance(value, list):
                value = ", ".join(value)
            var = ctk.StringVar(value=str(value))
            self._setting_vars[key] = var
            entry = ctk.CTkEntry(
                scroll, textvariable=var, height=ENTRY_HEIGHT, corner_radius=CORNER_RADIUS,
                font=FONT_BODY,
            )
            entry.grid(row=row, column=1, sticky="ew", pady=4)
            if kind in ("file", "dir", "savefile"):
                ctk.CTkButton(
                    scroll, text="Browse", width=90, height=ENTRY_HEIGHT - 6, font=FONT_SMALL,
                    fg_color="transparent", border_width=1,
                    command=lambda k=key, kd=kind: self._browse(k, kd),
                ).grid(row=row, column=2, padx=(6, 0), pady=4)

        row = len(_S)
        ctk.CTkLabel(
            scroll,
            text="Recipients must all be at the allowed domain. The identified folder is refused "
                 "if it sits inside a backup/sync source of the analysis app. The ledger holds "
                 "study IDs, visit dates and file hashes only - never names or MRNs.",
            font=FONT_SMALL, text_color=SUBTITLE_COLOR, anchor="w", wraplength=900, justify="left",
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(PAD_Y, 4))
        row += 1
        self._save_btn = ctk.CTkButton(
            scroll, text="Save settings", width=150, height=BUTTON_HEIGHT, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER, command=self._on_save_settings,
        )
        self._save_btn.grid(row=row, column=0, sticky="w", pady=(PAD_Y, 0))
        self._settings_msg = ctk.CTkLabel(
            scroll, text="", font=FONT_SMALL, anchor="w", wraplength=900, justify="left",
        )
        self._settings_msg.grid(row=row, column=1, columnspan=2, sticky="w", pady=(PAD_Y, 0))

    def _browse(self, key: str, kind: str):
        var = self._setting_vars[key]
        current = var.get()
        if kind == "file":
            chosen = filedialog.askopenfilename(
                title="Enrolment workbook", filetypes=[("Excel workbook", "*.xlsx *.xlsm"), ("All files", "*.*")],
                initialdir=str(Path(current).parent) if current else None,
            )
        elif kind == "savefile":
            chosen = filedialog.asksaveasfilename(
                title="Ledger file", defaultextension=".jsonl",
                filetypes=[("JSON Lines", "*.jsonl"), ("All files", "*.*")],
                initialfile=Path(current).name if current else "dispatch_ledger.jsonl",
                initialdir=str(Path(current).parent) if current else None,
                confirmoverwrite=False,
            )
        else:
            chosen = filedialog.askdirectory(initialdir=current or None)
        if chosen:
            var.set(chosen)

    def _settings_values(self) -> dict:
        values = {}
        for key, var in self._setting_vars.items():
            text = var.get().strip()
            if key == "recipients":
                values[key] = [a.strip() for a in text.replace(";", ",").split(",") if a.strip()]
            elif key == "size_cap_mb":
                values[key] = text
            else:
                values[key] = text
        return values

    def _on_save_settings(self):
        values = self._settings_values()
        problems = self._controller.save_settings(values)
        if problems:
            self._settings_msg.configure(text="\n".join(problems), text_color=ERROR_COLOR)
            return
        self._settings_msg.configure(text="Saved.", text_color=SUCCESS_COLOR)
        self._set_status("Settings saved.")

    # -- actions -----------------------------------------------------------------

    def _set_busy(self, busy: bool):
        self._busy = busy
        state = "disabled" if busy else "normal"
        for btn in (self._load_btn, self._select_all_btn, self._clear_btn, self._save_btn):
            btn.configure(state=state)
        if busy:
            self._prepare_btn.configure(state="disabled")
        elif self._controller.worklist is not None and self._controller.worklist.proposed():
            self._prepare_btn.configure(state="normal")

    def _set_status(self, text: str, warn: bool = False, error: bool = False):
        self._status_var.set(text)
        color = ERROR_COLOR if error else (_WARN_COLOR if warn else self._status_default_color)
        self._status_label.configure(text_color=color)

    def _run_in_thread(self, work, on_done):
        def target():
            try:
                result = work()
            except Exception as exc:   # surfaced to the status line, never lost
                self.after(0, lambda: self._on_error(exc))
                return
            self.after(0, lambda: on_done(result))
        threading.Thread(target=target, daemon=True).start()

    def _on_error(self, exc: Exception):
        self._set_busy(False)
        self._set_status(f"{type(exc).__name__}: {exc}", error=True)

    def _on_load(self):
        if self._busy:
            return
        missing = self._controller.missing_configuration()
        if missing:
            self._tabs.set("Settings")
            self._set_status("Fill in the settings first: " + ", ".join(missing), warn=True)
            return
        self._set_busy(True)
        self._set_status("Reading the roster and indexing reports...")
        self._run_in_thread(self._controller.load, self._on_loaded)

    def _on_loaded(self, worklist):
        self._apply_worklist(worklist)
        self._set_busy(False)
        n = len(worklist.proposed())
        self._set_status(
            f"Loaded {len(worklist.items)} report(s); {n} proposed for the next batch."
            + (f" First run: {self._controller.seeded_on_first_run} older report(s) closed."
               if self._controller.seeded_on_first_run else "")
        )

    def _on_prepare(self):
        if self._busy:
            return
        items = self._selected_items()
        if not items:
            self._set_status("Nothing ticked.", warn=True)
            return
        # Counted apart: a partly identified report still carries a name or an
        # MRN, so calling it de-identified would overstate what is missing.
        partial = sum(1 for i in items if i.partially_identified)
        unidentified = sum(1 for i in items if i.unidentified)
        caveats = []
        if partial:
            caveats.append(f"{partial} with incomplete identification")
        if unidentified:
            caveats.append(f"{unidentified} de-identified")
        self._set_busy(True)
        self._set_status(
            f"Stamping {len(items)} report(s)"
            + (", " + ", ".join(caveats) if caveats else "") + "..."
        )
        self._run_in_thread(lambda: self._controller.prepare_batch(items), self._on_prepared)

    def _on_prepared(self, batch):
        self._apply_batch(batch)
        self._set_busy(False)
        self._set_status(
            f"Batch ready: {batch.count} report(s) in {len(batch.parts)} part(s). "
            f"Attach each part's files in Outlook on the web, send, then Mark as sent."
            + (" Warnings above." if batch.warnings else ""),
            warn=bool(batch.warnings),
        )

    def _on_mark_sent(self, part):
        results = self._controller.mark_part_sent(part)
        recorded = sum(1 for _, ok, _ in results if ok)
        refused = [(e.filename, msg) for e, ok, msg in results if not ok]
        for widgets in self._part_widgets:
            if widgets["part"] is part:
                widgets["sent_button"].configure(text="Sent", state="disabled")
        self._apply_worklist(self._controller.worklist)
        if refused:
            self._set_status(
                f"Part {part.index}: {recorded} recorded; {len(refused)} already marked by someone "
                f"else - {refused[0][0]}: {refused[0][1]}", warn=True,
            )
        else:
            self._set_status(f"Part {part.index} of {part.parts}: {recorded} report(s) recorded as sent.")
