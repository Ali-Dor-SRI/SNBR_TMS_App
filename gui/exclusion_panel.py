"""Page 3 — exclude individual tests from the report averages.

The user picks a participant, then ticks which of that participant's tests
(T-SICI, T-SICF, A-SICI, A-SICF, CSP, RMT) should be left out of the cohort
averages (the Control / ALS benchmark means) and blanked in the exported CSV.
A participant can have some tests excluded and others kept.

Exclusions take effect immediately for the session; "Save for future" persists
them so they are re-applied automatically on the next launch.
"""

from __future__ import annotations

import customtkinter as ctk

from gui.theme import (
    FONT_TITLE, FONT_HEADING, FONT_BODY, FONT_SMALL, FONT_SUBTITLE, FONT_BUTTON,
    ACCENT_COLOR, ACCENT_HOVER, ERROR_COLOR, SUCCESS_COLOR, DISABLED_FG, SUBTITLE_COLOR,
    PAD_X, PAD_Y, SECTION_PAD_Y, ENTRY_HEIGHT, BUTTON_HEIGHT, CORNER_RADIUS,
)

_NORMAL_TEXT = ("gray10", "gray90")


class ExclusionPanel(ctk.CTkFrame):
    """Per-test exclusion picker — sits between Data Mode and Participant."""

    def __init__(self, parent, controller, on_next, on_back):
        super().__init__(parent, fg_color="transparent")
        self._controller = controller
        self._on_next = on_next
        self._on_back = on_back

        self._search_var = ctk.StringVar()
        self._status_var = ctk.StringVar()

        # Rebuilt on every refresh().
        self._overviews: list[dict] = []
        self._overview_by_id: dict[int, dict] = {}
        self._participant_buttons: dict[int, ctk.CTkButton] = {}
        self._selected_pid: int | None = None

        # Test checkboxes for the currently selected participant.
        self._test_vars: dict[str, ctk.BooleanVar] = {}
        self._select_all_var = ctk.BooleanVar(value=False)

        self._build_ui()

        self._search_var.trace_add("write", self._on_search_changed)

    # ── UI construction ────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Title + prompt
        ctk.CTkLabel(
            self, text="Exclude Tests", font=FONT_TITLE, anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=PAD_X, pady=(SECTION_PAD_Y, 4))

        ctk.CTkLabel(
            self,
            text=(
                "Choose a participant, then select which of their tests to exclude "
                "from the averages in the created report. You can exclude some tests "
                "for a participant while keeping the rest. Excluded tests are also "
                "blanked in the exported CSV."
            ),
            font=FONT_SUBTITLE,
            text_color=SUBTITLE_COLOR,
            anchor="w",
            justify="left",
            wraplength=900,
        ).grid(row=1, column=0, sticky="w", padx=PAD_X, pady=(0, SECTION_PAD_Y))

        # ── Content (participants left, tests right) ───────
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=2, column=0, sticky="nsew", padx=PAD_X)
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=1)
        content.grid_rowconfigure(0, weight=1)

        # Left column — search + participant list
        left = ctk.CTkFrame(content, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            left, text="Participants", font=FONT_HEADING, anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))

        self._search_entry = ctk.CTkEntry(
            left,
            textvariable=self._search_var,
            placeholder_text="Search by ID, study, or group...",
            height=ENTRY_HEIGHT,
            corner_radius=CORNER_RADIUS,
            font=FONT_BODY,
        )
        self._search_entry.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        self._list_frame = ctk.CTkScrollableFrame(
            left, height=300, corner_radius=CORNER_RADIUS,
        )
        self._list_frame.grid(row=2, column=0, sticky="nsew")
        self._list_frame.grid_columnconfigure(0, weight=1)

        # Right column — per-test checkboxes for the selected participant
        right = ctk.CTkFrame(content, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        self._tests_header = ctk.CTkLabel(
            right, text="Tests", font=FONT_HEADING, anchor="w",
        )
        self._tests_header.grid(row=0, column=0, sticky="w", pady=(0, 4))

        self._tests_frame = ctk.CTkScrollableFrame(
            right, height=300, corner_radius=CORNER_RADIUS,
        )
        self._tests_frame.grid(row=1, column=0, sticky="nsew")
        self._tests_frame.grid_columnconfigure(0, weight=1)

        # ── Excluded list ─────────────────────────────────
        excluded_section = ctk.CTkFrame(self, fg_color="transparent")
        excluded_section.grid(row=3, column=0, sticky="ew", padx=PAD_X, pady=(SECTION_PAD_Y, 0))
        excluded_section.grid_columnconfigure(0, weight=1)

        header_row = ctk.CTkFrame(excluded_section, fg_color="transparent")
        header_row.grid(row=0, column=0, sticky="ew")
        header_row.grid_columnconfigure(0, weight=1)

        self._excluded_header = ctk.CTkLabel(
            header_row, text="Excluded tests (0)", font=FONT_HEADING, anchor="w",
        )
        self._excluded_header.grid(row=0, column=0, sticky="w")

        self._clear_all_btn = ctk.CTkButton(
            header_row, text="Clear All", width=90, height=28,
            corner_radius=CORNER_RADIUS, font=FONT_SMALL,
            fg_color="transparent", hover_color=ACCENT_COLOR,
            border_width=1, border_color=ACCENT_COLOR, text_color=ACCENT_COLOR,
            command=self._clear_all,
        )
        self._clear_all_btn.grid(row=0, column=1, sticky="e")

        self._excluded_frame = ctk.CTkScrollableFrame(
            excluded_section, height=90, corner_radius=CORNER_RADIUS,
        )
        self._excluded_frame.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self._excluded_frame.grid_columnconfigure(0, weight=1)

        # ── Save + status row ─────────────────────────────
        save_row = ctk.CTkFrame(self, fg_color="transparent")
        save_row.grid(row=4, column=0, sticky="ew", padx=PAD_X, pady=(PAD_Y, 0))
        save_row.grid_columnconfigure(1, weight=1)

        self._save_btn = ctk.CTkButton(
            save_row, text="Save for future", width=140, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._save_for_future,
        )
        self._save_btn.grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            save_row, textvariable=self._status_var, font=FONT_SMALL,
            text_color=SUCCESS_COLOR, anchor="w", wraplength=700,
        ).grid(row=0, column=1, sticky="w", padx=(12, 0))

        # ── Navigation ────────────────────────────────────
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.grid(row=5, column=0, sticky="ew", padx=PAD_X, pady=(PAD_Y, SECTION_PAD_Y))
        nav.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(
            nav, text="Back", width=100, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._handle_back,
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            nav, text="Next", width=100, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._handle_next,
        ).grid(row=0, column=1, sticky="e")

    # ── Refresh (called each time page is shown) ──────────

    def refresh(self):
        """Reload participants from the current DataFrame and rebuild the UI."""
        self._status_var.set("")
        self._suppress_search = True
        self._search_var.set("")
        self._suppress_search = False
        self._selected_pid = None

        self._overviews = self._controller.get_participant_overviews()
        self._overview_by_id = {o["id"]: o for o in self._overviews}
        self._rebuild_participant_list(self._overviews)
        self._show_tests_placeholder(
            "Select a participant on the left to choose which tests to exclude.",
        )
        self._rebuild_excluded_list()

    # ── Participant list ───────────────────────────────────

    def _on_search_changed(self, *_args):
        if getattr(self, "_suppress_search", False):
            return
        query = self._search_var.get().strip().lower()
        if not query:
            filtered = self._overviews
        else:
            filtered = [o for o in self._overviews if self._matches(o, query)]
        self._rebuild_participant_list(filtered)

    @staticmethod
    def _matches(overview: dict, query: str) -> bool:
        return (
            query in str(overview["id"])
            or query in overview.get("study", "").lower()
            or query in overview.get("subject_type", "").lower()
        )

    def _rebuild_participant_list(self, overviews: list[dict]):
        for widget in self._list_frame.winfo_children():
            widget.destroy()
        self._participant_buttons = {}

        if not self._overviews:
            ctk.CTkLabel(
                self._list_frame,
                text="No participant data is loaded.\nLoad data on the Data Mode page first.",
                font=FONT_SMALL, text_color=SUBTITLE_COLOR, justify="left",
            ).grid(row=0, column=0, sticky="w", padx=6, pady=8)
            return

        if not overviews:
            ctk.CTkLabel(
                self._list_frame, text="No participants match your search.",
                font=FONT_SMALL, text_color=SUBTITLE_COLOR,
            ).grid(row=0, column=0, sticky="w", padx=6, pady=8)
            return

        for row, overview in enumerate(overviews):
            pid = overview["id"]
            btn = ctk.CTkButton(
                self._list_frame,
                text=self._button_text(pid),
                font=FONT_BODY, height=30, corner_radius=4,
                fg_color="transparent", anchor="w",
                hover_color=(ACCENT_COLOR, ACCENT_COLOR),
                command=lambda p=pid: self._select_participant(p),
            )
            btn.grid(row=row, column=0, sticky="ew", pady=1)
            self._participant_buttons[pid] = btn
            self._style_button(pid)

    def _button_text(self, pid: int) -> str:
        overview = self._overview_by_id.get(pid, {"id": pid})
        parts = [f"ID {pid}"]
        if overview.get("study"):
            parts.append(overview["study"])
        if overview.get("subject_type"):
            parts.append(overview["subject_type"])
        text = "  •  ".join(parts)
        count = self._controller.get_excluded_test_count(pid)
        if count:
            text += f"   ({count} excluded)"
        return text

    def _style_button(self, pid: int):
        """Apply selection / exclusion styling to one participant button."""
        btn = self._participant_buttons.get(pid)
        if btn is None:
            return
        if pid == self._selected_pid:
            btn.configure(fg_color=ACCENT_COLOR, text_color="white")
        elif self._controller.is_participant_excluded(pid):
            btn.configure(fg_color="transparent", text_color=ERROR_COLOR)
        else:
            btn.configure(fg_color="transparent", text_color=_NORMAL_TEXT)

    def _refresh_participant_button(self, pid: int):
        btn = self._participant_buttons.get(pid)
        if btn is not None:
            btn.configure(text=self._button_text(pid))
            self._style_button(pid)

    def _select_participant(self, pid: int):
        previous = self._selected_pid
        self._selected_pid = pid
        if previous is not None and previous != pid:
            self._style_button(previous)
        self._style_button(pid)
        self._populate_tests(pid)

    # ── Test checkboxes ────────────────────────────────────

    def _show_tests_placeholder(self, message: str):
        for widget in self._tests_frame.winfo_children():
            widget.destroy()
        self._test_vars = {}
        self._tests_header.configure(text="Tests")
        ctk.CTkLabel(
            self._tests_frame, text=message,
            font=FONT_SMALL, text_color=SUBTITLE_COLOR, justify="left", wraplength=380,
        ).grid(row=0, column=0, sticky="w", padx=6, pady=8)

    def _populate_tests(self, pid: int):
        for widget in self._tests_frame.winfo_children():
            widget.destroy()
        self._test_vars = {}

        overview = self._overview_by_id.get(pid, {"id": pid})
        self._tests_header.configure(text=f"Tests for {self._button_label_plain(overview)}")

        tests = self._controller.get_participant_tests(pid)
        if not tests:
            ctk.CTkLabel(
                self._tests_frame, text="This participant has no test data to exclude.",
                font=FONT_SMALL, text_color=SUBTITLE_COLOR,
            ).grid(row=0, column=0, sticky="w", padx=6, pady=8)
            return

        ctk.CTkLabel(
            self._tests_frame,
            text="Tick a test to exclude it from the averages for this participant.",
            font=FONT_SMALL, text_color=SUBTITLE_COLOR, anchor="w",
            justify="left", wraplength=380,
        ).grid(row=0, column=0, sticky="w", padx=6, pady=(4, 6))

        # "Exclude all tests" convenience toggle.
        all_excluded = all(t["excluded"] for t in tests)
        self._select_all_var = ctk.BooleanVar(value=all_excluded)
        ctk.CTkCheckBox(
            self._tests_frame, text="Exclude all tests", variable=self._select_all_var,
            font=FONT_BUTTON, command=lambda p=pid: self._on_select_all_tests(p),
        ).grid(row=1, column=0, sticky="w", padx=6, pady=(0, 4))

        for idx, test in enumerate(tests, start=2):
            key = test["key"]
            var = ctk.BooleanVar(value=test["excluded"])
            ctk.CTkCheckBox(
                self._tests_frame, text=test["label"], variable=var, font=FONT_BODY,
                command=lambda p=pid, k=key: self._on_test_toggled(p, k),
            ).grid(row=idx, column=0, sticky="w", padx=6, pady=1)
            self._test_vars[key] = var

        # Visit reference, for context.
        measurements = self._controller.get_participant_measurements(pid)
        if measurements:
            ctk.CTkFrame(
                self._tests_frame, height=1, fg_color=DISABLED_FG,
            ).grid(row=len(tests) + 2, column=0, sticky="ew", padx=6, pady=(8, 6))
            ctk.CTkLabel(
                self._tests_frame, text="Visits on record:", font=FONT_SMALL,
                text_color=SUBTITLE_COLOR, anchor="w",
            ).grid(row=len(tests) + 3, column=0, sticky="w", padx=6)
            for j, m in enumerate(measurements, start=len(tests) + 4):
                bits = [b for b in (m.get("date"), m.get("cortex")) if b]
                tests_str = ", ".join(m.get("tests", [])) or "no test data"
                line = "  —  ".join(bits) if bits else "Visit"
                ctk.CTkLabel(
                    self._tests_frame, text=f"• {line}  ({tests_str})",
                    font=FONT_SMALL, text_color=SUBTITLE_COLOR, anchor="w",
                    justify="left", wraplength=380,
                ).grid(row=j, column=0, sticky="w", padx=6, pady=(0, 1))

    @staticmethod
    def _button_label_plain(overview: dict) -> str:
        parts = [f"ID {overview['id']}"]
        if overview.get("study"):
            parts.append(overview["study"])
        if overview.get("subject_type"):
            parts.append(overview["subject_type"])
        return "  •  ".join(parts)

    def _on_test_toggled(self, pid: int, key: str):
        excluded = self._test_vars[key].get()
        self._controller.set_test_excluded(pid, key, excluded)
        self._sync_select_all()
        self._refresh_participant_button(pid)
        self._rebuild_excluded_list()
        self._status_var.set("")

    def _on_select_all_tests(self, pid: int):
        state = self._select_all_var.get()
        for key, var in self._test_vars.items():
            var.set(state)
            self._controller.set_test_excluded(pid, key, state)
        self._refresh_participant_button(pid)
        self._rebuild_excluded_list()
        self._status_var.set("")

    def _sync_select_all(self):
        if self._test_vars:
            self._select_all_var.set(all(v.get() for v in self._test_vars.values()))

    # ── Excluded list ──────────────────────────────────────

    def _rebuild_excluded_list(self):
        for widget in self._excluded_frame.winfo_children():
            widget.destroy()

        entries = self._controller.get_excluded_entries()
        self._excluded_header.configure(text=f"Excluded tests ({len(entries)})")
        self._clear_all_btn.configure(state="normal" if entries else "disabled")

        if not entries:
            ctk.CTkLabel(
                self._excluded_frame, text="No tests are excluded.",
                font=FONT_SMALL, text_color=SUBTITLE_COLOR,
            ).grid(row=0, column=0, sticky="w", padx=6, pady=6)
            return

        for row, entry in enumerate(entries):
            pid = entry["id"]
            chip = ctk.CTkFrame(self._excluded_frame, fg_color="transparent")
            chip.grid(row=row, column=0, sticky="ew", pady=1)
            chip.grid_columnconfigure(0, weight=1)

            overview = self._overview_by_id.get(pid)
            who = self._button_label_plain(overview) if overview else f"ID {pid}"
            ctk.CTkLabel(
                chip, text=f"{who}  —  {entry['test_label']}", font=FONT_BODY, anchor="w",
            ).grid(row=0, column=0, sticky="w", padx=(6, 0))

            ctk.CTkButton(
                chip, text="Remove", width=80, height=26,
                corner_radius=CORNER_RADIUS, font=FONT_SMALL,
                fg_color="transparent", hover_color=ERROR_COLOR,
                border_width=1, border_color=ERROR_COLOR, text_color=ERROR_COLOR,
                command=lambda p=pid, k=entry["test_key"]: self._remove_entry(p, k),
            ).grid(row=0, column=1, sticky="e", padx=(8, 6))

    def _remove_entry(self, pid: int, key: str):
        self._controller.set_test_excluded(pid, key, False)
        # Reflect in the right-hand checkboxes if this participant is showing.
        if pid == self._selected_pid and key in self._test_vars:
            self._test_vars[key].set(False)
            self._sync_select_all()
        self._refresh_participant_button(pid)
        self._rebuild_excluded_list()
        self._status_var.set("")

    def _clear_all(self):
        self._controller.clear_excluded_tests()
        if self._selected_pid is not None and self._test_vars:
            for var in self._test_vars.values():
                var.set(False)
            self._sync_select_all()
        # Restyle / relabel every visible participant button.
        for pid in list(self._participant_buttons):
            self._refresh_participant_button(pid)
        self._rebuild_excluded_list()
        self._status_var.set("")

    # ── Save ───────────────────────────────────────────────

    def _save_for_future(self):
        self._controller.save_excluded_tests()
        count = len(self._controller.get_excluded_entries())
        if count:
            self._status_var.set(
                f"Saved {count} excluded test(s) as the default for future sessions."
            )
        else:
            self._status_var.set("Cleared the saved exclusion default.")

    # ── Navigation ─────────────────────────────────────────

    def _handle_back(self):
        self._on_back()

    def _handle_next(self):
        self._on_next()
