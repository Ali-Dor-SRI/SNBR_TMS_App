"""Page 6 — Backup & Sync: one-way file copy from source to destination."""

from __future__ import annotations

import threading
from tkinter import filedialog

import customtkinter as ctk

from back_up_sync.file_sync import SyncPair, sync_pairs
from gui.theme import (
    FONT_TITLE, FONT_HEADING, FONT_BODY, FONT_SMALL, FONT_SUBTITLE, FONT_BUTTON,
    ACCENT_COLOR, ACCENT_HOVER, ERROR_COLOR, SUCCESS_COLOR, DISABLED_FG, SUBTITLE_COLOR,
    PAD_X, PAD_Y, SECTION_PAD_Y, ENTRY_HEIGHT, BUTTON_HEIGHT, CORNER_RADIUS,
)


class SyncPanel(ctk.CTkFrame):
    """Backup & Sync page — copy files from source(s) to destination(s)."""

    def __init__(self, parent, controller, on_next, on_back, footer=None):
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

        self._save_default_var = ctk.BooleanVar(value=False)
        self._status_var = ctk.StringVar()
        self._current_file_var = ctk.StringVar()
        self._progress_var = ctk.DoubleVar(value=0.0)
        self._syncing = False
        self._cancel_event = threading.Event()

        # Each pair row is stored as a dict with widget references
        self._pair_rows: list[dict] = []

        self._build_ui()

    # ── UI ─────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)

        # Title
        ctk.CTkLabel(
            self, text="Back up & Sync", font=FONT_TITLE, anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=PAD_X, pady=(SECTION_PAD_Y, 4))

        ctk.CTkLabel(
            self,
            text="Copy files from source to destination folders. Only new or updated files are copied.",
            font=FONT_SUBTITLE,
            text_color=SUBTITLE_COLOR,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=PAD_X, pady=(0, SECTION_PAD_Y))

        # ── Scrollable pair list ───────────────────────────
        self._pairs_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent", height=260,
        )
        self._pairs_frame.grid(row=2, column=0, sticky="nsew", padx=PAD_X)
        self._pairs_frame.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # ── Add pair + save default ────────────────────────
        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.grid(row=3, column=0, sticky="ew", padx=PAD_X, pady=(PAD_Y, 0))
        controls.grid_columnconfigure(1, weight=1)

        self._add_btn = ctk.CTkButton(
            controls, text="+ Add Pair", width=120, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BODY,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._add_pair_row,
        )
        self._add_btn.grid(row=0, column=0, sticky="w")

        ctk.CTkCheckBox(
            controls, text="Save pairs as default",
            variable=self._save_default_var, font=FONT_SMALL,
            command=self._on_save_default_toggled,
        ).grid(row=0, column=2, sticky="e")

        # ── Progress bar (hidden) ──────────────────────────
        self._progress = ctk.CTkProgressBar(
            self._footer, mode="determinate", width=400,
            variable=self._progress_var,
        )
        self._progress.grid(row=0, column=0, padx=PAD_X, pady=(PAD_Y, 0))
        self._progress.grid_remove()

        # ── Current file label ─────────────────────────────
        # Shares the status row with the summary line below it: the file being
        # copied is only shown while a sync runs, and the summary only after.
        self._file_label = ctk.CTkLabel(
            self._footer, textvariable=self._current_file_var,
            font=FONT_SMALL, text_color=DISABLED_FG, anchor="w",
            wraplength=700,
        )
        self._file_label.grid(row=1, column=0, sticky="w", padx=PAD_X, pady=(2, 0))

        # ── Status label ───────────────────────────────────
        self._status_label = ctk.CTkLabel(
            self._footer, textvariable=self._status_var,
            font=FONT_SMALL, text_color=DISABLED_FG, anchor="w",
            wraplength=700,
        )
        self._status_label.grid(row=2, column=0, sticky="w", padx=PAD_X, pady=(2, 0))

        # ── Navigation (pinned; see gui.page_shell) ────────
        nav = ctk.CTkFrame(self._footer, fg_color="transparent")
        nav.grid(row=3, column=0, sticky="ew", padx=PAD_X, pady=(PAD_Y, PAD_Y))
        nav.grid_columnconfigure(1, weight=1)

        self._back_btn = ctk.CTkButton(
            nav, text="Back", width=100, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._on_back,
        )
        self._back_btn.grid(row=0, column=0, sticky="w")

        self._sync_btn = ctk.CTkButton(
            nav, text="Start Sync", width=130, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._handle_sync,
        )
        self._sync_btn.grid(row=0, column=1)

        self._cancel_btn = ctk.CTkButton(
            nav, text="Cancel", width=100, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ERROR_COLOR, hover_color="#C0392B",
            command=self._handle_cancel,
        )
        self._cancel_btn.grid(row=0, column=2)
        self._cancel_btn.grid_remove()

        self._next_btn = ctk.CTkButton(
            nav, text="Next", width=100, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._on_next,
        )
        self._next_btn.grid(row=0, column=3, sticky="e")

    # ── Pair rows ──────────────────────────────────────────

    def _add_pair_row(self, source: str = "", destination: str = ""):
        """Add a new source-destination pair row to the scrollable frame."""
        row_idx = len(self._pair_rows)

        frame = ctk.CTkFrame(self._pairs_frame, fg_color="transparent")
        frame.grid(row=row_idx, column=0, sticky="ew", pady=(0, PAD_Y))
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_columnconfigure(4, weight=1)

        # Row label
        ctk.CTkLabel(
            frame, text=f"Pair {row_idx + 1}", font=FONT_HEADING, anchor="w",
        ).grid(row=0, column=0, columnspan=7, sticky="w", pady=(0, 4))

        # Source
        ctk.CTkLabel(frame, text="Source:", font=FONT_BODY, anchor="w").grid(
            row=1, column=0, sticky="w", padx=(0, 8),
        )
        src_var = ctk.StringVar(value=source)
        src_entry = ctk.CTkEntry(
            frame, textvariable=src_var,
            height=ENTRY_HEIGHT, corner_radius=CORNER_RADIUS, font=FONT_BODY,
        )
        src_entry.grid(row=1, column=1, sticky="ew", padx=(0, 4))

        src_browse = ctk.CTkButton(
            frame, text="Browse", width=80, height=ENTRY_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_SMALL,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=lambda sv=src_var: self._browse_dir(sv, "Select Source Folder"),
        )
        src_browse.grid(row=1, column=2, padx=(0, 16))

        # Destination
        ctk.CTkLabel(frame, text="Dest:", font=FONT_BODY, anchor="w").grid(
            row=1, column=3, sticky="w", padx=(0, 8),
        )
        dst_var = ctk.StringVar(value=destination)
        dst_entry = ctk.CTkEntry(
            frame, textvariable=dst_var,
            height=ENTRY_HEIGHT, corner_radius=CORNER_RADIUS, font=FONT_BODY,
        )
        dst_entry.grid(row=1, column=4, sticky="ew", padx=(0, 4))

        dst_browse = ctk.CTkButton(
            frame, text="Browse", width=80, height=ENTRY_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_SMALL,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=lambda dv=dst_var: self._browse_dir(dv, "Select Destination Folder"),
        )
        dst_browse.grid(row=1, column=5, padx=(0, 4))

        # Remove button
        remove_btn = ctk.CTkButton(
            frame, text="X", width=36, height=ENTRY_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ERROR_COLOR, hover_color="#C0392B",
            command=lambda: self._remove_pair_row(row_info),
        )
        remove_btn.grid(row=1, column=6, padx=(4, 0))

        row_info = {
            "frame": frame,
            "src_var": src_var,
            "dst_var": dst_var,
        }
        self._pair_rows.append(row_info)

    def _remove_pair_row(self, row_info: dict):
        """Remove a pair row from the list and re-layout."""
        if row_info in self._pair_rows:
            row_info["frame"].destroy()
            self._pair_rows.remove(row_info)
            self._relayout_pairs()

    def _relayout_pairs(self):
        """Re-number and re-grid all pair rows after a removal."""
        for idx, row in enumerate(self._pair_rows):
            row["frame"].grid(row=idx, column=0, sticky="ew", pady=(0, PAD_Y))
            # Update the label text
            for child in row["frame"].winfo_children():
                if isinstance(child, ctk.CTkLabel) and hasattr(child, "cget"):
                    try:
                        text = child.cget("text")
                        if text.startswith("Pair "):
                            child.configure(text=f"Pair {idx + 1}")
                    except Exception:
                        pass

    def _browse_dir(self, var: ctk.StringVar, title: str):
        """Open a directory chooser and set the variable."""
        path = filedialog.askdirectory(title=title)
        if path:
            var.set(path)

    # ── Save defaults ──────────────────────────────────────

    def _save_all_pairs(self):
        """Persist all current pair rows to user settings."""
        pairs_data = []
        for row in self._pair_rows:
            src = row["src_var"].get().strip()
            dst = row["dst_var"].get().strip()
            if src and dst:
                pairs_data.append({"source": src, "destination": dst})
        self._controller.save_sync_defaults(pairs_data)

    def _on_save_default_toggled(self):
        """Save all pairs immediately when the checkbox is checked."""
        if self._save_default_var.get():
            self._save_all_pairs()

    # ── Refresh ────────────────────────────────────────────

    def refresh(self):
        """Load saved pairs from user settings and populate the UI."""
        # Clear existing rows
        for row in self._pair_rows:
            row["frame"].destroy()
        self._pair_rows.clear()

        # Load saved defaults
        saved_pairs = self._controller.get_sync_defaults()
        if saved_pairs:
            for pair in saved_pairs:
                src = pair.get("source", "")
                dst = pair.get("destination", "")
                self._add_pair_row(source=src, destination=dst)
        else:
            # Start with one empty pair
            self._add_pair_row()

        self._save_default_var.set(False)
        self._status_var.set("")
        self._current_file_var.set("")
        self._progress_var.set(0.0)
        self._status_label.configure(text_color=DISABLED_FG)

        msg = self._controller.consume_quick_start_message()
        if msg:
            self._status_var.set(msg)
            self._status_label.configure(text_color="#F39C12")

    # ── Sync logic ─────────────────────────────────────────

    def _collect_pairs(self) -> list[SyncPair]:
        """Read current pair rows and return a list of SyncPair objects."""
        pairs = []
        for row in self._pair_rows:
            src = row["src_var"].get().strip()
            dst = row["dst_var"].get().strip()
            if src and dst:
                pairs.append(SyncPair(source=src, destination=dst))
        return pairs

    def _handle_sync(self):
        if self._syncing:
            return

        pairs = self._collect_pairs()
        if not pairs:
            self._status_var.set("No valid pairs configured. Add at least one source and destination.")
            self._status_label.configure(text_color=ERROR_COLOR)
            return

        # Validate paths
        errors = []
        from pathlib import Path
        for i, p in enumerate(pairs, 1):
            if not Path(p.source).is_dir():
                errors.append(f"Pair {i}: source does not exist: {p.source}")
            if p.source == p.destination:
                errors.append(f"Pair {i}: source and destination are the same.")
        if errors:
            self._status_var.set("\n".join(errors))
            self._status_label.configure(text_color=ERROR_COLOR)
            return

        self._cancel_event.clear()
        self._set_busy(True)
        self._status_var.set("Syncing...")
        self._status_label.configure(text_color=DISABLED_FG)
        self._current_file_var.set("")
        self._progress_var.set(0.0)

        log_path = self._controller.get_sync_log_path()

        thread = threading.Thread(
            target=self._sync_worker,
            args=(pairs, log_path),
            daemon=True,
        )
        thread.start()

    def _sync_worker(self, pairs: list[SyncPair], log_path: str):
        try:
            def on_progress(current_file, done, total):
                if total > 0:
                    pct = done / total
                else:
                    pct = 0.0
                self.after(0, self._update_progress, current_file, pct)

            result = sync_pairs(
                pairs,
                retries=3,
                wait=5,
                progress_callback=on_progress,
                log_path=log_path,
                cancel_event=self._cancel_event,
            )

            summary = (
                f"Sync complete: {result.files_copied} copied, "
                f"{result.files_skipped} skipped, "
                f"{result.files_failed} failed, "
                f"{result.bytes_copied:,} bytes in {result.duration_seconds:.1f}s"
            )
            if result.errors:
                summary += f"\nErrors:\n" + "\n".join(result.errors[:10])

            if result.files_failed > 0:
                self.after(0, self._on_sync_done, summary, ERROR_COLOR)
            else:
                self.after(0, self._on_sync_done, summary, SUCCESS_COLOR)

        except Exception as exc:
            self.after(0, self._on_sync_done, f"Sync failed: {exc}", ERROR_COLOR)

    def _update_progress(self, current_file: str, pct: float):
        self._progress_var.set(pct)
        self._current_file_var.set(current_file)

    def _on_sync_done(self, message: str, color: str):
        self._set_busy(False)
        self._status_var.set(message)
        self._status_label.configure(text_color=color)
        self._current_file_var.set("")
        self._progress_var.set(1.0 if color == SUCCESS_COLOR else 0.0)

        # Save pairs as default if checked
        if self._save_default_var.get():
            self._save_all_pairs()

    def _handle_cancel(self):
        self._cancel_event.set()
        self._status_var.set("Cancelling...")
        self._status_label.configure(text_color=DISABLED_FG)

    def _set_busy(self, busy: bool):
        self._syncing = busy
        if busy:
            self._progress.grid()
            self._sync_btn.configure(state="disabled")
            self._back_btn.configure(state="disabled")
            self._next_btn.configure(state="disabled")
            self._add_btn.configure(state="disabled")
            self._cancel_btn.grid()
        else:
            self._progress.grid_remove()
            self._sync_btn.configure(state="normal")
            self._back_btn.configure(state="normal")
            self._next_btn.configure(state="normal")
            self._add_btn.configure(state="normal")
            self._cancel_btn.grid_remove()
