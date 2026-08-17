"""Page 3 — participant ID and visit date selection."""

from __future__ import annotations

from datetime import datetime

import customtkinter as ctk
from tkcalendar import Calendar

from gui.theme import (
    FONT_TITLE, FONT_HEADING, FONT_BODY, FONT_SMALL, FONT_SUBTITLE, FONT_BUTTON,
    ACCENT_COLOR, ACCENT_HOVER, ERROR_COLOR, DISABLED_FG, SUBTITLE_COLOR,
    PAD_X, PAD_Y, SECTION_PAD_Y, BUTTON_HEIGHT, CORNER_RADIUS,
)

# Tag used on the tkcalendar widget to mark visit dates.
_VISIT_TAG = "visit"


class ParticipantPanel(ctk.CTkFrame):
    """Participant / visit-date picker — page 3 of the workflow."""

    def __init__(self, parent, controller, on_next, on_back):
        super().__init__(parent, fg_color="transparent")
        self._controller = controller
        self._on_next = on_next
        self._on_back = on_back

        self._id_var = ctk.StringVar()
        self._error_var = ctk.StringVar()
        self._study_var = ctk.StringVar(value="All Studies")

        # Master (unfiltered) ID list — updated by _set_id_options.
        self._all_ids: list[int] = []

        # Guard against re-entrant updates during cross-filtering.
        self._updating = False
        # Guard against search trace firing while we set the var programmatically.
        self._suppress_search = False

        self._build_ui()

        # Wire up live search after UI is built.
        self._id_var.trace_add("write", self._on_search_changed)

    # ── UI construction ────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)

        # Title
        ctk.CTkLabel(
            self, text="Select Participant", font=FONT_TITLE, anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=PAD_X, pady=(SECTION_PAD_Y, 4))

        ctk.CTkLabel(
            self,
            text="Choose a participant ID and visit date for the report.",
            font=FONT_SUBTITLE,
            text_color=SUBTITLE_COLOR,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=PAD_X, pady=(0, SECTION_PAD_Y))

        # ── Content area (ID left, calendar right) ─────────
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=2, column=0, sticky="nsew", padx=PAD_X)
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Left column — Study filter + ID search + dropdown
        left = ctk.CTkFrame(content, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 20))
        left.grid_columnconfigure(0, weight=1)

        # ── Study filter dropdown ──
        ctk.CTkLabel(left, text="Study", font=FONT_HEADING, anchor="w").grid(
            row=0, column=0, sticky="w", pady=(0, 4),
        )

        self._study_menu = ctk.CTkOptionMenu(
            left,
            variable=self._study_var,
            values=["All Studies"],
            height=36,
            corner_radius=CORNER_RADIUS,
            font=FONT_BODY,
            fg_color=ACCENT_COLOR,
            button_color=ACCENT_HOVER,
            command=self._on_study_changed,
        )
        self._study_menu.grid(row=1, column=0, sticky="ew", pady=(0, 12))

        # ── Participant ID search ──
        ctk.CTkLabel(left, text="Participant ID", font=FONT_HEADING, anchor="w").grid(
            row=2, column=0, sticky="w", pady=(0, 4),
        )

        self._id_entry = ctk.CTkEntry(
            left,
            textvariable=self._id_var,
            placeholder_text="Type to search...",
            height=36,
            corner_radius=CORNER_RADIUS,
            font=FONT_BODY,
        )
        self._id_entry.grid(row=3, column=0, sticky="ew", pady=(0, 0))
        self._id_entry.bind("<FocusIn>", lambda e: self._show_dropdown())
        self._id_entry.bind("<Return>", self._on_entry_return)

        # Scrollable dropdown shown beneath the entry
        self._dropdown = ctk.CTkScrollableFrame(
            left, height=150, corner_radius=CORNER_RADIUS,
        )
        self._dropdown.grid(row=4, column=0, sticky="ew", pady=(2, 0))
        self._dropdown.grid_columnconfigure(0, weight=1)
        self._dropdown.grid_remove()  # hidden by default

        ctk.CTkLabel(
            left,
            text="Type an ID or select from the list.",
            font=FONT_SUBTITLE,
            text_color=SUBTITLE_COLOR,
            anchor="w",
        ).grid(row=5, column=0, sticky="w", pady=(4, 0))

        # Right column — calendar
        right = ctk.CTkFrame(content, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(20, 0))

        ctk.CTkLabel(right, text="Visit Date", font=FONT_HEADING, anchor="w").grid(
            row=0, column=0, sticky="w", pady=(0, 4),
        )

        self._calendar = Calendar(
            right,
            selectmode="day",
            date_pattern="dd/mm/yyyy",
            showweeknumbers=False,
            font=("Segoe UI", 11),
            borderwidth=0,
            background="#2B2B2B",
            foreground="white",
            headersbackground="#1F6AA5",
            headersforeground="white",
            selectbackground="#1F6AA5",
            selectforeground="white",
            normalbackground="#2B2B2B",
            normalforeground="white",
            weekendbackground="#333333",
            weekendforeground="white",
            othermonthbackground="#1E1E1E",
            othermonthforeground="#666666",
            othermonthwebackground="#1E1E1E",
            othermonthweforeground="#666666",
        )
        self._calendar.grid(row=1, column=0, sticky="w", pady=(0, 4))
        self._calendar.bind("<<CalendarSelected>>", self._on_date_changed)

        self._calendar.tag_config(_VISIT_TAG, background="#2ECC71", foreground="white")

        ctk.CTkLabel(
            right,
            text="Green dates have recorded visits.",
            font=FONT_SUBTITLE,
            text_color=SUBTITLE_COLOR,
            anchor="w",
        ).grid(row=2, column=0, sticky="w")

        # ── Error label ────────────────────────────────────
        self._error_label = ctk.CTkLabel(
            self,
            textvariable=self._error_var,
            font=FONT_SMALL,
            text_color=ERROR_COLOR,
            anchor="w",
            wraplength=600,
        )
        self._error_label.grid(row=3, column=0, sticky="w", padx=PAD_X, pady=(PAD_Y, 0))

        # ── Navigation ─────────────────────────────────────
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.grid(row=4, column=0, sticky="ew", padx=PAD_X, pady=(PAD_Y, SECTION_PAD_Y))
        nav.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(
            nav, text="Back", width=100, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._on_back,
        ).grid(row=0, column=0, sticky="w")

        self._next_btn = ctk.CTkButton(
            nav, text="Next", width=100, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._handle_next,
        )
        self._next_btn.grid(row=0, column=1, sticky="e")

    # ── Refresh (called each time page is shown) ──────────

    def _get_study_filter(self) -> str | None:
        """Return the current study filter, or None if 'All Studies'."""
        val = self._study_var.get()
        return None if val == "All Studies" else val

    def refresh(self):
        """Populate controls from the current DataFrame."""
        self._error_var.set("")

        # Populate study dropdown
        studies = self._controller.get_unique_studies()
        options = ["All Studies"] + studies
        self._study_menu.configure(values=options)
        if len(studies) == 1:
            self._study_var.set(studies[0])
        else:
            self._study_var.set("All Studies")

        study = self._get_study_filter()

        # Load all IDs (filtered by study if applicable)
        all_ids = self._controller.get_unique_ids(study_filter=study)
        self._set_id_options(all_ids)

        # Pre-select the most recent visit
        recent_id, recent_date = self._controller.get_most_recent_visit(study_filter=study)

        if recent_id is not None:
            self._suppress_search = True
            self._id_var.set(str(recent_id))
            self._suppress_search = False

        if recent_date is not None:
            self._calendar.selection_set(recent_date)

        # Mark visit dates for the pre-selected ID
        self._update_calendar_markers(id_filter=recent_id)

        # Show dropdown immediately so user can browse/select
        self._show_dropdown()

    # ── Cross-filtering callbacks ──────────────────────────

    def _on_study_changed(self, _value: str):
        """User changed the study dropdown — refresh IDs and calendar."""
        if self._updating:
            return
        self._updating = True
        self._error_var.set("")

        study = self._get_study_filter()
        all_ids = self._controller.get_unique_ids(study_filter=study)
        self._suppress_search = True
        self._set_id_options(all_ids)
        self._id_var.set("")
        self._suppress_search = False

        # Clear calendar markers and select most recent for this study
        recent_id, recent_date = self._controller.get_most_recent_visit(study_filter=study)
        if recent_id is not None:
            self._suppress_search = True
            self._id_var.set(str(recent_id))
            self._suppress_search = False
        if recent_date is not None:
            self._calendar.selection_set(recent_date)
        self._update_calendar_markers(id_filter=recent_id)

        self._updating = False

    def _on_id_changed(self, value: str):
        """User changed the ID dropdown — update calendar markers."""
        if self._updating:
            return
        self._updating = True
        self._error_var.set("")

        study = self._get_study_filter()
        pid = self._parse_id(value)
        if pid is not None:
            self._update_calendar_markers(id_filter=pid)
            # Auto-select the most recent date for this ID.
            dates = self._controller.get_visit_dates(id_filter=pid, study_filter=study)
            if dates:
                self._calendar.selection_set(max(dates))

        self._updating = False

    def _on_date_changed(self, _event):
        """User picked a date on the calendar — filter IDs to that date."""
        if self._updating:
            return
        self._updating = True
        self._error_var.set("")

        study = self._get_study_filter()
        selected = self._get_selected_date()
        if selected is None:
            self._updating = False
            return

        ids = self._controller.get_unique_ids(date_filter=selected, study_filter=study)
        self._suppress_search = True
        if not ids:
            self._error_var.set("No visits recorded on this date.")
            # Keep the full ID list so user can still navigate
            all_ids = self._controller.get_unique_ids(study_filter=study)
            self._set_id_options(all_ids)
            self._id_var.set("")
        else:
            self._set_id_options(ids)
            # Keep current ID if it's in the filtered list, else pick first
            current = self._parse_id(self._id_var.get())
            if current not in ids:
                self._id_var.set(str(ids[0]))
        self._suppress_search = False

        self._updating = False

    # ── Navigation ─────────────────────────────────────────

    def _handle_next(self):
        self._error_var.set("")

        pid = self._parse_id(self._id_var.get())
        selected_date = self._get_selected_date()

        if pid is None:
            self._error_var.set("Please select a participant ID.")
            return

        if selected_date is None:
            self._error_var.set("Please select a visit date.")
            return

        # Verify this (ID, date) pair actually exists
        study = self._get_study_filter()
        dates_for_id = self._controller.get_visit_dates(id_filter=pid, study_filter=study)
        if selected_date not in dates_for_id:
            self._error_var.set(
                f"No visit found for participant {pid} on "
                f"{selected_date.strftime('%d/%m/%Y')}."
            )
            return

        # Warn if this participant is on the exclusion list — their data is
        # held out of the cohort averages and the exported CSV.
        if self._controller.is_participant_excluded(pid):
            if not self._confirm_excluded(pid):
                return

        self._controller.set_selected_participant(pid, selected_date)

        # Seed the recording-target selection — the visualization panel owns the
        # selection UI. Visits whose files identify a muscle select every target;
        # archives that predate recording targets fall back to the cortex options.
        target_options = self._controller.get_target_options(pid, selected_date, study)
        if target_options:
            self._controller.set_selected_targets(target_options)
            self._controller.set_selected_cortex(None)
        else:
            self._controller.set_selected_targets([])
            cortex_options = self._controller.get_cortex_options(pid, selected_date, study)
            if len(cortex_options) > 1:
                self._controller.set_selected_cortex(cortex_options)
            else:
                self._controller.set_selected_cortex(
                    cortex_options[0] if cortex_options else None
                )
        self._on_next()

    def _confirm_excluded(self, pid: int) -> bool:
        """Warn that *pid* is excluded; return True if the user proceeds."""
        popup = ctk.CTkToplevel(self)
        popup.title("Participant excluded")
        popup.geometry("480x250")
        popup.resizable(False, False)
        popup.grab_set()
        popup.after(100, popup.focus_force)

        popup.grid_columnconfigure(0, weight=1)
        popup.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            popup, text="Participant has excluded tests", font=FONT_HEADING,
            text_color=ERROR_COLOR, anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=PAD_X, pady=(PAD_Y, 4))

        excluded_tests = self._controller.get_excluded_test_labels(pid)
        tests_str = ", ".join(excluded_tests) if excluded_tests else "some tests"
        ctk.CTkLabel(
            popup,
            text=(
                f"Participant {pid} has excluded test(s): {tests_str}. "
                "Those measurements are left out of the cohort averages and "
                "blanked in the exported CSV.\n\n"
                "You can still create this participant's report, but the cohort "
                "benchmark lines for those tests will not include their data. Continue?"
            ),
            font=FONT_SMALL, anchor="nw", justify="left", wraplength=430,
        ).grid(row=1, column=0, sticky="nsew", padx=PAD_X, pady=(0, PAD_Y))

        result = {"ok": False}

        btn_row = ctk.CTkFrame(popup, fg_color="transparent")
        btn_row.grid(row=2, column=0, sticky="ew", padx=PAD_X, pady=(0, PAD_Y))
        btn_row.grid_columnconfigure(0, weight=1)

        def _continue():
            result["ok"] = True
            popup.destroy()

        ctk.CTkButton(
            btn_row, text="Cancel", width=110, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color="transparent", hover_color=ACCENT_COLOR,
            border_width=1, border_color=ACCENT_COLOR, text_color=ACCENT_COLOR,
            command=popup.destroy,
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            btn_row, text="Continue anyway", width=150, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=_continue,
        ).grid(row=0, column=1, sticky="e")

        self.wait_window(popup)
        return result["ok"]

    # ── Search / dropdown helpers ─────────────────────────

    def _set_id_options(self, ids: list[int]):
        """Update the master ID list and rebuild the visible dropdown."""
        self._all_ids = ids
        self._rebuild_dropdown(ids)

    def _on_search_changed(self, *_args):
        """Called on every keystroke in the ID entry."""
        if self._suppress_search or self._updating:
            return
        query = self._id_var.get().strip()
        if query == "":
            filtered = self._all_ids
        else:
            filtered = [i for i in self._all_ids if query in str(i)]
        self._rebuild_dropdown(filtered)
        if filtered:
            self._show_dropdown()
        else:
            self._hide_dropdown()

    def _rebuild_dropdown(self, ids: list[int]):
        """Destroy existing buttons and create new ones for *ids*."""
        for widget in self._dropdown.winfo_children():
            widget.destroy()
        self._dropdown_buttons: dict[int, ctk.CTkButton] = {}
        for pid in ids:
            btn = ctk.CTkButton(
                self._dropdown,
                text=str(pid),
                font=FONT_BODY,
                height=30,
                corner_radius=4,
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=(ACCENT_COLOR, ACCENT_COLOR),
                anchor="w",
                command=lambda p=pid: self._select_id(p),
            )
            btn.grid(sticky="ew", pady=1)
            self._dropdown_buttons[pid] = btn
        # Highlight current selection if it's in the list
        current = self._parse_id(self._id_var.get())
        if current is not None:
            self._highlight_selected(current)

    def _select_id(self, pid: int):
        """User clicked an item in the dropdown."""
        self._suppress_search = True
        self._id_var.set(str(pid))
        self._suppress_search = False
        self._highlight_selected(pid)
        self._on_id_changed(str(pid))

    def _highlight_selected(self, pid: int):
        """Visually highlight the selected ID in the dropdown."""
        buttons = getattr(self, "_dropdown_buttons", {})
        for p, btn in buttons.items():
            if p == pid:
                btn.configure(fg_color=ACCENT_COLOR, text_color="white")
            else:
                btn.configure(fg_color="transparent", text_color=("gray10", "gray90"))

    def _on_entry_return(self, _event):
        """User pressed Enter in the search entry — select if exact match."""
        pid = self._parse_id(self._id_var.get())
        if pid is not None and pid in self._all_ids:
            self._select_id(pid)

    def _show_dropdown(self):
        self._dropdown.grid()

    def _hide_dropdown(self):
        self._dropdown.grid_remove()

    # ── Helpers ────────────────────────────────────────────

    def _parse_id(self, value: str) -> int | None:
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None

    def _get_selected_date(self) -> datetime | None:
        raw = self._calendar.get_date()
        if not raw:
            return None
        try:
            return datetime.strptime(raw, "%d/%m/%Y")
        except ValueError:
            return None

    def _update_calendar_markers(self, id_filter: int | None = None):
        """Clear existing markers and highlight every visit date in the
        current study — regardless of which participant is selected.

        *id_filter* is accepted for call-site compatibility but intentionally
        unused: the green markers reflect the full set of recorded visits so
        the researcher can see at a glance which days have data.
        """
        del id_filter  # retained for API compatibility; see docstring
        self._calendar.calevent_remove("all")
        study = self._get_study_filter()
        dates = self._controller.get_visit_dates(study_filter=study)
        for d in dates:
            self._calendar.calevent_create(d, "Visit", _VISIT_TAG)
