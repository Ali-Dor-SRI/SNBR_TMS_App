"""Page 4 — graph selection and preview for the report."""

from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass

import customtkinter as ctk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from tkinter import filedialog

from gui.theme import (
    FONT_TITLE, FONT_HEADING, FONT_BODY, FONT_SMALL, FONT_SUBTITLE, FONT_BUTTON,
    ACCENT_COLOR, ACCENT_HOVER, ERROR_COLOR, SUCCESS_COLOR, DISABLED_FG, SUBTITLE_COLOR,
    PAD_X, PAD_Y, SECTION_PAD_Y, BUTTON_HEIGHT, CORNER_RADIUS,
)

# ── Graph registry ─────────────────────────────────────


@dataclass(frozen=True)
class GraphEntry:
    key: str
    label: str
    group: str
    graph_type: str
    measure: str | None
    multi_figure: bool = False
    match_by: str | None = None


GRAPH_REGISTRY: list[GraphEntry] = [
    # Visit Summary
    GraphEntry("visit_timeline", "Visit Timeline", "Visit Summary", "visit_timeline", None),
    GraphEntry("visit_table", "Visit Test Table", "Visit Summary", "visit_table", None),
    GraphEntry("cmap_table", "CMAP Table", "Visit Summary", "cmap_table", None),
    GraphEntry("munix_table", "MUNIX Table", "Visit Summary", "munix_table", None),
    GraphEntry("stimulus_response", "Stimulus-Response", "Visit Summary", "stimulus_response", None),
    GraphEntry("strength_duration_curve", "Strength-Duration Curve", "Visit Summary", "strength_duration_curve", None),
    GraphEntry("charge_duration_weiss", "Charge-Duration (Weiss)", "Visit Summary", "charge_duration_weiss", None),
    # T-SICI cluster (everything about t-SICI together, in the report's section order)
    GraphEntry("profile__t_sici", "T-SICI Profile", "Waveform Profiles", "profile", "t_sici"),
    GraphEntry("grouped__t_sici", "T-SICI Grouped", "Cohort Comparisons", "grouped", "t_sici"),
    GraphEntry("grouped_age__t_sici", "T-SICI Age-Matched", "Age-Matched Comparisons", "grouped", "t_sici", match_by="age"),
    GraphEntry("grouped_sex__t_sici", "T-SICI Sex-Matched", "Sex-Matched Comparisons", "grouped", "t_sici", match_by="sex"),
    GraphEntry("grouped_sex_age__t_sici", "T-SICI Sex & Age", "Sex & Age Matched", "grouped", "t_sici", match_by="sex,age"),
    GraphEntry("over_time__t_sici", "T-SICI Over Time", "Over Time", "over_time", "t_sici"),
    GraphEntry("trajectory__t_sici", "T-SICI Trajectory", "Over Time", "trajectory", "t_sici"),
    GraphEntry("visit_profiles__t_sici", "T-SICI Visit Profiles", "Visit Profiles", "visit_profiles", "t_sici"),
    # RMT cluster
    GraphEntry("rmt_over_time", "RMT Over Time", "RMT", "rmt_over_time", None, multi_figure=True),
    GraphEntry("rmt_comparison", "RMT Comparison", "RMT", "rmt_comparison", None, multi_figure=True),
    GraphEntry("rmt_grouped", "RMT Grouped", "RMT", "rmt_grouped", None, multi_figure=True),
    GraphEntry("rmt_age", "RMT Age-Matched", "RMT", "rmt_grouped", None, multi_figure=True, match_by="age"),
    GraphEntry("rmt_sex", "RMT Sex-Matched", "RMT", "rmt_grouped", None, multi_figure=True, match_by="sex"),
    GraphEntry("rmt_sex_age", "RMT Sex & Age", "RMT", "rmt_grouped", None, multi_figure=True, match_by="sex,age"),
    # A-SICI cluster
    GraphEntry("profile__a_sici", "A-SICI Profile", "Waveform Profiles", "profile", "a_sici"),
    GraphEntry("grouped__a_sici", "A-SICI Grouped", "Cohort Comparisons", "grouped", "a_sici"),
    GraphEntry("grouped_age__a_sici", "A-SICI Age-Matched", "Age-Matched Comparisons", "grouped", "a_sici", match_by="age"),
    GraphEntry("grouped_sex__a_sici", "A-SICI Sex-Matched", "Sex-Matched Comparisons", "grouped", "a_sici", match_by="sex"),
    GraphEntry("grouped_sex_age__a_sici", "A-SICI Sex & Age", "Sex & Age Matched", "grouped", "a_sici", match_by="sex,age"),
    GraphEntry("over_time__a_sici", "A-SICI Over Time", "Over Time", "over_time", "a_sici"),
    GraphEntry("visit_profiles__a_sici", "A-SICI Visit Profiles", "Visit Profiles", "visit_profiles", "a_sici"),
    # A-SICF cluster
    GraphEntry("profile__a_sicf", "A-SICF Profile", "Waveform Profiles", "profile", "a_sicf"),
    GraphEntry("grouped__a_sicf", "A-SICF Grouped", "Cohort Comparisons", "grouped", "a_sicf"),
    GraphEntry("grouped_age__a_sicf", "A-SICF Age-Matched", "Age-Matched Comparisons", "grouped", "a_sicf", match_by="age"),
    GraphEntry("grouped_sex__a_sicf", "A-SICF Sex-Matched", "Sex-Matched Comparisons", "grouped", "a_sicf", match_by="sex"),
    GraphEntry("grouped_sex_age__a_sicf", "A-SICF Sex & Age", "Sex & Age Matched", "grouped", "a_sicf", match_by="sex,age"),
    GraphEntry("over_time__a_sicf", "A-SICF Over Time", "Over Time", "over_time", "a_sicf"),
    GraphEntry("visit_profiles__a_sicf", "A-SICF Visit Profiles", "Visit Profiles", "visit_profiles", "a_sicf"),
    # T-SICF cluster
    GraphEntry("profile__t_sicf", "T-SICF Profile", "Waveform Profiles", "profile", "t_sicf"),
    GraphEntry("grouped__t_sicf", "T-SICF Grouped", "Cohort Comparisons", "grouped", "t_sicf"),
    GraphEntry("grouped_age__t_sicf", "T-SICF Age-Matched", "Age-Matched Comparisons", "grouped", "t_sicf", match_by="age"),
    GraphEntry("grouped_sex__t_sicf", "T-SICF Sex-Matched", "Sex-Matched Comparisons", "grouped", "t_sicf", match_by="sex"),
    GraphEntry("grouped_sex_age__t_sicf", "T-SICF Sex & Age", "Sex & Age Matched", "grouped", "t_sicf", match_by="sex,age"),
    GraphEntry("over_time__t_sicf", "T-SICF Over Time", "Over Time", "over_time", "t_sicf"),
    GraphEntry("visit_profiles__t_sicf", "T-SICF Visit Profiles", "Visit Profiles", "visit_profiles", "t_sicf"),
    # CSP cluster
    GraphEntry("profile__csp", "CSP Profile", "Waveform Profiles", "profile", "csp"),
    GraphEntry("grouped__csp", "CSP Grouped", "Cohort Comparisons", "grouped", "csp", multi_figure=True),
    GraphEntry("grouped_age__csp", "CSP Age-Matched", "Age-Matched Comparisons", "grouped", "csp", multi_figure=True, match_by="age"),
    GraphEntry("grouped_sex__csp", "CSP Sex-Matched", "Sex-Matched Comparisons", "grouped", "csp", multi_figure=True, match_by="sex"),
    GraphEntry("grouped_sex_age__csp", "CSP Sex & Age", "Sex & Age Matched", "grouped", "csp", multi_figure=True, match_by="sex,age"),
    GraphEntry("over_time__csp", "CSP Over Time", "Over Time", "over_time", "csp", multi_figure=True),
    GraphEntry("visit_profiles__csp", "CSP Visit Profiles", "Visit Profiles", "visit_profiles", "csp", multi_figure=True),
]

_REGISTRY_BY_KEY: dict[str, GraphEntry] = {e.key: e for e in GRAPH_REGISTRY}


def _sub_labels(entry: GraphEntry, data, count: int) -> list[str]:
    """Navigation sub-labels for a multi-figure result.

    A result can be split two ways at once — a builder's own sub-figures
    (``RMT50``/``RMT200``/…) and one copy per selected recording target — so
    both are appended when present, giving ``"RMT Comparison — RMT50 — Right FDI"``.
    """
    keys = (data.get("figure_keys") if isinstance(data, dict) else None) or []
    targets = (data.get("figure_targets") if isinstance(data, dict) else None) or []
    labels: list[str] = []
    for i in range(count):
        parts = [entry.label]
        if i < len(keys) and keys[i]:
            parts.append(str(keys[i]))
        if i < len(targets) and targets[i]:
            parts.append(str(targets[i]))
        labels.append(" — ".join(parts) if len(parts) > 1 else f"{entry.label} — {i + 1}")
    return labels


# ── Nav item ───────────────────────────────────────────

@dataclass
class _NavItem:
    """One navigable figure in the flat list."""
    entry_key: str
    sub_index: int
    sub_label: str
    figure: Figure | None


# ── Panel ──────────────────────────────────────────────


class VisualizationPanel(ctk.CTkFrame):
    """Graph selection & preview — page 4 of the workflow."""

    def __init__(self, parent, controller, on_next, on_back):
        super().__init__(parent, fg_color="transparent")
        self._controller = controller
        self._on_next = on_next
        self._on_back = on_back

        # Checkbox state
        self._check_vars: dict[str, ctk.BooleanVar] = {}
        self._check_widgets: dict[str, ctk.CTkCheckBox] = {}
        self._select_all_var = ctk.BooleanVar(value=False)

        # Cortex checkbox state
        self._cortex_vars: dict[str, ctk.BooleanVar] = {}
        self._cortex_widgets: dict[str, ctk.CTkCheckBox] = {}
        self._cortex_options: list[str] = []
        # "target" when the visit's muscle/side data drives the checkboxes,
        # "cortex" for archives that predate recording targets, "" for neither.
        self._selection_mode: str = ""

        # Figure cache: key → raw result tuple from plot_mem_graph
        self._figure_cache: dict[str, tuple] = {}

        # Navigation
        self._nav_list: list[_NavItem] = []
        self._nav_index: int = 0

        # Generation lock
        self._generating = False

        # Canvas reference
        self._current_canvas: FigureCanvasTkAgg | None = None

        # Status
        self._status_var = ctk.StringVar()
        self._nav_label_var = ctk.StringVar(value="No graphs selected")

        # Arrow key bind IDs
        self._bind_ids: list[str] = []

        self._build_ui()

    # ── UI ─────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=0)   # sidebar
        self.grid_columnconfigure(1, weight=1)    # preview
        self.grid_rowconfigure(1, weight=1)

        # Title row (spans both columns)
        title_frame = ctk.CTkFrame(self, fg_color="transparent")
        title_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=PAD_X, pady=(SECTION_PAD_Y, 4))

        ctk.CTkLabel(title_frame, text="Visualization", font=FONT_TITLE, anchor="w").pack(
            side="top", anchor="w",
        )
        ctk.CTkLabel(
            title_frame,
            text="Select graphs to include in the report, then browse with the arrows.",
            font=FONT_SUBTITLE, text_color=SUBTITLE_COLOR, anchor="w",
        ).pack(side="top", anchor="w", pady=(0, 4))

        # ── Left sidebar ──────────────────────────────────
        sidebar = ctk.CTkScrollableFrame(self, width=240, corner_radius=CORNER_RADIUS)
        sidebar.grid(row=1, column=0, sticky="ns", padx=(PAD_X, 8), pady=(0, 0))
        sidebar.grid_columnconfigure(0, weight=1)
        self._sidebar = sidebar

        sidebar_row = 0

        # Cortex selection section (populated dynamically in refresh)
        self._cortex_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        self._cortex_frame.grid(row=sidebar_row, column=0, sticky="ew")
        self._cortex_frame.grid_columnconfigure(0, weight=1)
        self._cortex_frame.grid_remove()  # hidden until refresh populates it
        sidebar_row += 1

        # Select-all toggle
        sa_cb = ctk.CTkCheckBox(
            sidebar,
            text="Select All",
            variable=self._select_all_var,
            font=FONT_BUTTON,
            command=self._on_select_all,
        )
        sa_cb.grid(row=sidebar_row, column=0, sticky="w", pady=(0, SECTION_PAD_Y))
        sidebar_row += 1

        current_group = ""
        for entry in GRAPH_REGISTRY:
            if entry.group != current_group:
                current_group = entry.group
                ctk.CTkLabel(sidebar, text=current_group, font=FONT_HEADING, anchor="w").grid(
                    row=sidebar_row, column=0, sticky="w", pady=(8, 2),
                )
                sidebar_row += 1

            var = ctk.BooleanVar(value=False)
            cb = ctk.CTkCheckBox(
                sidebar,
                text=entry.label,
                variable=var,
                font=FONT_BODY,
                command=lambda k=entry.key: self._on_checkbox_toggled(k),
            )
            cb.grid(row=sidebar_row, column=0, sticky="w", pady=1)
            sidebar_row += 1
            self._check_vars[entry.key] = var
            self._check_widgets[entry.key] = cb

        # ── Right preview area ────────────────────────────
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=1, column=1, sticky="nsew", padx=(8, PAD_X))
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)

        # Canvas host
        self._canvas_frame = ctk.CTkFrame(right, corner_radius=CORNER_RADIUS)
        self._canvas_frame.grid(row=0, column=0, sticky="nsew")
        self._canvas_frame.grid_rowconfigure(0, weight=1)
        self._canvas_frame.grid_columnconfigure(0, weight=1)

        self._placeholder_label = ctk.CTkLabel(
            self._canvas_frame,
            text="Check graphs on the left,\nthen use the arrows to browse.",
            font=FONT_SUBTITLE,
            text_color=SUBTITLE_COLOR,
        )
        self._placeholder_label.grid(row=0, column=0)

        # Progress bar (hidden)
        self._progress = ctk.CTkProgressBar(self._canvas_frame, mode="indeterminate", width=300)

        # Nav arrows
        nav_row = ctk.CTkFrame(right, fg_color="transparent")
        nav_row.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        nav_row.grid_columnconfigure(1, weight=1)

        self._prev_btn = ctk.CTkButton(
            nav_row, text="\u25C0", width=40, height=32,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=lambda: self._navigate(-1),
        )
        self._prev_btn.grid(row=0, column=0)

        ctk.CTkLabel(nav_row, textvariable=self._nav_label_var, font=FONT_SMALL).grid(
            row=0, column=1, padx=8,
        )

        self._next_arrow_btn = ctk.CTkButton(
            nav_row, text="\u25B6", width=40, height=32,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=lambda: self._navigate(1),
        )
        self._next_arrow_btn.grid(row=0, column=2)

        # Save button
        self._save_btn = ctk.CTkButton(
            nav_row, text="Save", width=70, height=32,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._save_current_figure,
        )
        self._save_btn.grid(row=0, column=3, padx=(12, 0))

        # Status / error
        ctk.CTkLabel(
            self, textvariable=self._status_var, font=FONT_SMALL,
            text_color=ERROR_COLOR, anchor="w", wraplength=600,
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=PAD_X, pady=(4, 0))

        # ── Bottom navigation bar ─────────────────────────
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.grid(row=3, column=0, columnspan=2, sticky="ew", padx=PAD_X, pady=(PAD_Y, SECTION_PAD_Y))
        nav.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(
            nav, text="Back", width=100, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._handle_back,
        ).grid(row=0, column=0, sticky="w")

        self._next_page_btn = ctk.CTkButton(
            nav, text="Next", width=100, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._handle_next,
        )
        self._next_page_btn.grid(row=0, column=1, sticky="e")

    # ── Refresh (called when page is shown) ────────────────

    def refresh(self):
        self._status_var.set("")
        self._clear_cache()
        for var in self._check_vars.values():
            var.set(False)
        self._select_all_var.set(False)
        self._nav_list.clear()
        self._nav_index = 0
        self._display_placeholder()
        self._update_nav_buttons()
        self._reset_highlights()
        self._bind_arrow_keys()
        self._populate_cortex_checkboxes()
        self._update_checkbox_availability()

    # ── Recording-target selection ────────────────────────

    def _populate_cortex_checkboxes(self):
        """Build the recording-target checkboxes, or the cortex fallback.

        A visit that recorded the same measures from several muscles/sides
        (left FDI, right FDI, right TA) gets one checkbox per target, and every
        ticked graph is then rendered once per ticked target.  Archives written
        before recording targets existed carry no muscle data at all, so those
        fall back to the original Stimulated Cortex checkboxes and behave
        exactly as they did before.
        """
        # Clear old widgets
        for w in self._cortex_frame.winfo_children():
            w.destroy()
        self._cortex_vars.clear()
        self._cortex_widgets.clear()

        pid, date = self._controller.get_selected_participant()
        if pid is None or date is None:
            self._cortex_options = []
            self._selection_mode = ""
            self._controller.set_selected_targets([])
            self._cortex_frame.grid_remove()
            return

        targets = self._controller.get_target_options(pid, date)
        if targets:
            self._selection_mode = "target"
            self._cortex_options = targets
            heading = "Recording Target"
            # The target subsumes the stimulated cortex (the hemisphere and the
            # recorded side are contralateral), so only one of the two ever
            # filters the data.
            self._controller.set_selected_cortex(None)
        else:
            self._selection_mode = "cortex"
            self._cortex_options = self._controller.get_cortex_options(pid, date)
            heading = "Stimulated Cortex"
            self._controller.set_selected_targets([])

        if len(self._cortex_options) < 2:
            # Nothing to choose between — still push the single target through
            # so the render path filters to it.
            self._sync_cortex_to_controller()
            self._cortex_frame.grid_remove()
            return

        self._cortex_frame.grid()
        ctk.CTkLabel(
            self._cortex_frame, text=heading, font=FONT_HEADING, anchor="w",
        ).grid(sticky="w", pady=(0, 2))

        for cv in self._cortex_options:
            var = ctk.BooleanVar(value=True)  # all checked by default
            cb = ctk.CTkCheckBox(
                self._cortex_frame,
                text=cv,
                variable=var,
                font=FONT_BODY,
                command=self._on_cortex_changed,
            )
            cb.grid(sticky="w", pady=1)
            self._cortex_vars[cv] = var
            self._cortex_widgets[cv] = cb

        # Separator
        ctk.CTkFrame(
            self._cortex_frame, height=1, fg_color=DISABLED_FG,
        ).grid(sticky="ew", pady=(6, 6))

        # Sync controller with initial "all checked" state
        self._sync_cortex_to_controller()

    def _on_cortex_changed(self):
        """User toggled a target/cortex checkbox — update and regenerate."""
        checked = [cv for cv, var in self._cortex_vars.items() if var.get()]
        if not checked:
            # Don't allow unchecking all — re-check the one that was just unchecked
            for cv, var in self._cortex_vars.items():
                var.set(True)
            checked = list(self._cortex_vars.keys())

        self._sync_cortex_to_controller()
        self._clear_cache()
        self._update_checkbox_availability()

        # Regenerate the currently viewed graph if any
        self._rebuild_nav_list()
        if self._nav_list:
            self._nav_index = min(self._nav_index, len(self._nav_list) - 1)
            self._show_current()
        else:
            self._display_placeholder()
        self._update_nav_buttons()

    def _sync_cortex_to_controller(self):
        """Push the current checkbox state to the controller."""
        if self._cortex_vars:
            checked = [cv for cv, var in self._cortex_vars.items() if var.get()]
        else:
            # No checkboxes were built (a single option, or none at all).
            checked = list(self._cortex_options)

        if self._selection_mode == "target":
            self._controller.set_selected_targets(checked)
        elif self._selection_mode == "cortex":
            if len(checked) == 1:
                self._controller.set_selected_cortex(checked[0])
            elif len(checked) > 1:
                self._controller.set_selected_cortex(checked)
            else:
                self._controller.set_selected_cortex(None)

    # ── Select All ─────────────────────────────────────────

    def _on_select_all(self):
        state = self._select_all_var.get()
        available = getattr(self, "_available_keys", set(self._check_vars.keys()))
        for key, var in self._check_vars.items():
            if key in available:
                var.set(state)
        self._rebuild_nav_list()
        if self._nav_list:
            self._nav_index = 0
            self._show_current()
        else:
            self._display_placeholder()
        self._update_nav_buttons()

    # ── Data availability ───────────────────────────────────

    def _update_checkbox_availability(self):
        """Disable checkboxes for graphs that have no data for the selected participant."""
        # One DataFrame filter for the whole registry, not one per checkbox.
        availability = self._controller.graph_availability_map(GRAPH_REGISTRY)
        self._available_keys: set[str] = {
            key for key, has_data in availability.items() if has_data
        }
        for entry in GRAPH_REGISTRY:
            widget = self._check_widgets[entry.key]
            var = self._check_vars[entry.key]
            if availability.get(entry.key, False):
                widget.configure(state="normal")
            else:
                var.set(False)
                widget.configure(state="disabled", text_color=DISABLED_FG)

    # ── Checkbox toggle ────────────────────────────────────

    def _on_checkbox_toggled(self, key: str):
        just_checked = self._check_vars[key].get()
        self._rebuild_nav_list()

        if not self._nav_list:
            self._nav_index = 0
            self._display_placeholder()
            self._update_nav_buttons()
            self._reset_highlights()
            return

        if just_checked:
            # Jump to the graph that was just checked
            idx = self._find_nav_index(key)
            self._nav_index = idx if idx is not None else 0
            self._show_current()
        else:
            # Unchecked — keep showing whatever is current, just clamp index
            self._nav_index = min(self._nav_index, len(self._nav_list) - 1)
            self._update_highlight()
            self._update_nav_label()

        self._update_nav_buttons()

    # ── Navigation ─────────────────────────────────────────

    def _navigate(self, delta: int):
        if not self._nav_list or self._generating:
            return
        new = self._nav_index + delta
        if new < 0 or new >= len(self._nav_list):
            return
        self._nav_index = new
        self._show_current()
        self._update_nav_buttons()

    def _on_left_key(self, _event):
        if self.winfo_ismapped():
            self._navigate(-1)

    def _on_right_key(self, _event):
        if self.winfo_ismapped():
            self._navigate(1)

    def _bind_arrow_keys(self):
        self._unbind_arrow_keys()
        top = self.winfo_toplevel()
        self._bind_ids = [
            top.bind("<Left>", self._on_left_key, add="+"),
            top.bind("<Right>", self._on_right_key, add="+"),
        ]

    def _unbind_arrow_keys(self):
        if self._bind_ids:
            top = self.winfo_toplevel()
            for bid in self._bind_ids:
                try:
                    top.unbind("<Left>", bid)
                    top.unbind("<Right>", bid)
                except Exception:
                    pass
            self._bind_ids.clear()

    # ── Display logic ──────────────────────────────────────

    def _show_current(self):
        """Display the figure at the current nav index (lazy-generate if needed)."""
        if not self._nav_list:
            self._display_placeholder()
            return

        item = self._nav_list[self._nav_index]
        self._update_highlight()
        self._update_nav_label()

        if item.figure is not None:
            self._display_figure(item.figure)
            return

        # Need to generate
        entry = _REGISTRY_BY_KEY[item.entry_key]
        if entry.key in self._figure_cache:
            self._expand_cached(entry)
            item = self._nav_list[self._nav_index]
            if item.figure is not None:
                self._display_figure(item.figure)
                return

        self._generate_async(entry)

    def _display_figure(self, fig: Figure):
        """Embed a matplotlib Figure in the canvas frame."""
        self._clear_canvas()
        self._placeholder_label.grid_remove()
        self._progress.grid_remove()
        self._progress.stop()

        canvas = FigureCanvasTkAgg(fig, master=self._canvas_frame)
        canvas.draw()
        widget = canvas.get_tk_widget()
        widget.grid(row=0, column=0, sticky="nsew")
        self._current_canvas = canvas

    def _display_placeholder(self):
        self._clear_canvas()
        self._progress.grid_remove()
        self._progress.stop()
        self._placeholder_label.grid()
        self._nav_label_var.set("No graphs selected")

    def _clear_canvas(self):
        if self._current_canvas is not None:
            self._current_canvas.get_tk_widget().destroy()
            self._current_canvas = None

    # ── Async generation ───────────────────────────────────

    def _generate_async(self, entry: GraphEntry):
        if self._generating:
            return
        self._generating = True
        self._status_var.set("")
        self._clear_canvas()
        self._placeholder_label.grid_remove()
        self._progress.grid(row=0, column=0)
        self._progress.start()
        self._prev_btn.configure(state="disabled")
        self._next_arrow_btn.configure(state="disabled")

        thread = threading.Thread(
            target=self._generate_worker, args=(entry,), daemon=True,
        )
        thread.start()

    def _generate_worker(self, entry: GraphEntry):
        try:
            result = self._controller.generate_figure(
                entry.graph_type, entry.measure, match_by=entry.match_by,
            )
            self.after(0, self._on_gen_success, entry.key, result)
        except Exception:
            self.after(0, self._on_gen_error, entry.key, traceback.format_exc())

    def _on_gen_success(self, key: str, result: tuple):
        self._generating = False
        self._progress.stop()
        self._progress.grid_remove()
        self._figure_cache[key] = result
        self._expand_cached(_REGISTRY_BY_KEY[key])

        item = self._nav_list[self._nav_index]
        if item.figure is not None:
            self._display_figure(item.figure)
        self._update_nav_buttons()
        self._update_nav_label()

    def _on_gen_error(self, key: str, msg: str):
        self._generating = False
        self._progress.stop()
        self._progress.grid_remove()

        # Silently skip this graph — uncheck it and remove from nav
        if key in self._check_vars:
            self._check_vars[key].set(False)

        # Mark as a failed entry so it's excluded from export
        self._figure_cache[key] = None  # sentinel: no figure

        self._rebuild_nav_list()
        if self._nav_list:
            self._nav_index = min(self._nav_index, len(self._nav_list) - 1)
            self._show_current()
        else:
            self._display_placeholder()
        self._update_nav_buttons()
        self._update_nav_label()

    # ── Nav list management ────────────────────────────────

    def _rebuild_nav_list(self):
        """Rebuild the flat navigation list from checked entries."""
        self._nav_list.clear()
        for entry in GRAPH_REGISTRY:
            if not self._check_vars[entry.key].get():
                continue
            if entry.key in self._figure_cache:
                self._append_cached_items(entry)
            else:
                # Placeholder — will be expanded after generation
                self._nav_list.append(_NavItem(entry.key, 0, entry.label, None))

    def _append_cached_items(self, entry: GraphEntry):
        """Append nav items from a cached result."""
        result = self._figure_cache[entry.key]
        figs, _axes, data = result[0], result[1], result[2]

        if isinstance(figs, list):
            labels = _sub_labels(entry, data, len(figs))
            for i, (fig, label) in enumerate(zip(figs, labels)):
                self._nav_list.append(_NavItem(entry.key, i, label, fig))
        else:
            fig = figs if isinstance(figs, Figure) else (figs[0] if figs else None)
            self._nav_list.append(_NavItem(entry.key, 0, entry.label, fig))

    def _expand_cached(self, entry: GraphEntry):
        """Replace placeholder nav items for *entry* with real cached figures."""
        if entry.key not in self._figure_cache:
            return

        # Find the range of items for this key and which one we're viewing
        old_indices = [i for i, it in enumerate(self._nav_list) if it.entry_key == entry.key]
        if not old_indices:
            return

        # Build new items
        new_items: list[_NavItem] = []
        result = self._figure_cache[entry.key]
        figs, _axes, data = result[0], result[1], result[2]

        if isinstance(figs, list):
            labels = _sub_labels(entry, data, len(figs))
            for i, (fig, label) in enumerate(zip(figs, labels)):
                new_items.append(_NavItem(entry.key, i, label, fig))
        else:
            fig = figs if isinstance(figs, Figure) else (figs[0] if figs else None)
            new_items.append(_NavItem(entry.key, 0, entry.label, fig))

        # Replace in nav list
        first = old_indices[0]
        for idx in reversed(old_indices):
            self._nav_list.pop(idx)
        for i, item in enumerate(new_items):
            self._nav_list.insert(first + i, item)

        # Adjust nav_index
        if self._nav_index >= first and self._nav_index < first + len(old_indices):
            self._nav_index = first
        elif self._nav_index >= first + len(old_indices):
            self._nav_index += len(new_items) - len(old_indices)

    def _find_nav_index(self, key: str) -> int | None:
        for i, item in enumerate(self._nav_list):
            if item.entry_key == key:
                return i
        return None

    def _current_entry_key(self) -> str | None:
        if self._nav_list and 0 <= self._nav_index < len(self._nav_list):
            return self._nav_list[self._nav_index].entry_key
        return None

    # ── UI state updates ───────────────────────────────────

    def _update_nav_buttons(self):
        has_items = bool(self._nav_list)
        at_start = self._nav_index <= 0
        at_end = self._nav_index >= len(self._nav_list) - 1

        self._prev_btn.configure(
            state="normal" if (has_items and not at_start and not self._generating) else "disabled",
        )
        self._next_arrow_btn.configure(
            state="normal" if (has_items and not at_end and not self._generating) else "disabled",
        )

    def _update_nav_label(self):
        if not self._nav_list:
            self._nav_label_var.set("No graphs selected")
            return
        item = self._nav_list[self._nav_index]
        total = len(self._nav_list)
        self._nav_label_var.set(f"Figure {self._nav_index + 1} of {total} — {item.sub_label}")

    def _update_highlight(self):
        """Turn the active entry's checkbox green, reset all others."""
        active_key = self._current_entry_key()
        available = getattr(self, "_available_keys", set(self._check_vars.keys()))
        for key, widget in self._check_widgets.items():
            if key not in available:
                continue  # leave disabled styling as-is
            if key == active_key:
                widget.configure(text_color=SUCCESS_COLOR)
            else:
                widget.configure(text_color=("gray10", "gray90"))

    def _reset_highlights(self):
        available = getattr(self, "_available_keys", set(self._check_vars.keys()))
        for key, widget in self._check_widgets.items():
            if key in available:
                widget.configure(text_color=("gray10", "gray90"))

    # ── Cache ──────────────────────────────────────────────

    def _clear_cache(self):
        for result in self._figure_cache.values():
            if result is None:
                continue
            figs = result[0]
            if isinstance(figs, list):
                for f in figs:
                    plt.close(f)
            elif isinstance(figs, Figure):
                plt.close(figs)
        self._figure_cache.clear()

    # ── Save ───────────────────────────────────────────────

    def _save_current_figure(self):
        """Export the currently displayed figure as a 600 DPI PNG."""
        if not self._nav_list or self._nav_index >= len(self._nav_list):
            self._status_var.set("No figure to save.")
            return

        item = self._nav_list[self._nav_index]
        if item.figure is None:
            self._status_var.set("Figure has not been generated yet.")
            return

        # Build a default filename from the graph label
        safe_name = item.sub_label.replace(" ", "_").replace("—", "-")
        default_name = f"{safe_name}.png"

        path = filedialog.asksaveasfilename(
            title="Save Figure",
            defaultextension=".png",
            initialfile=default_name,
            filetypes=[("PNG Image", "*.png"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            item.figure.savefig(path, dpi=600, bbox_inches="tight")
            self._status_var.set(f"Saved: {path}")
        except Exception as e:
            self._status_var.set(f"Save failed: {e}")

    # ── Page navigation ────────────────────────────────────

    def _handle_back(self):
        self._unbind_arrow_keys()
        self._on_back()

    def _handle_next(self):
        checked = [k for k, v in self._check_vars.items() if v.get()]
        if not checked:
            self._status_var.set("Please select at least one graph.")
            return

        # Find checked graphs that haven't been generated yet.
        missing = [
            _REGISTRY_BY_KEY[k] for k in checked
            if k in _REGISTRY_BY_KEY and k not in self._figure_cache
        ]

        if missing:
            # Generate all missing figures in a background thread before advancing.
            self._status_var.set(f"Generating {len(missing)} remaining graph(s)...")
            self._set_busy_for_export(True)
            thread = threading.Thread(
                target=self._generate_missing_worker,
                args=(missing, checked),
                daemon=True,
            )
            thread.start()
        else:
            self._finish_next(checked)

    def _generate_missing_worker(self, missing: list, checked: list[str]):
        """Generate all uncached figures in the background."""
        errors: list[str] = []
        for entry in missing:
            try:
                result = self._controller.generate_figure(
                    entry.graph_type, entry.measure, match_by=entry.match_by,
                )
                self.after(0, self._cache_result, entry.key, result)
            except Exception as e:
                errors.append(f"{entry.label}: {e}")
        self.after(0, self._on_missing_done, checked, errors)

    def _cache_result(self, key: str, result: tuple):
        self._figure_cache[key] = result

    def _on_missing_done(self, checked: list[str], errors: list[str]):
        self._set_busy_for_export(False)
        if errors:
            self._status_var.set(
                f"Some graphs could not be generated:\n" + "\n".join(errors)
            )
        self._finish_next(checked)

    def _finish_next(self, checked: list[str]):
        """Collect all cached figures and advance to the next page.

        Each cached graph result is wrapped as a
        :class:`reports.pdf_layout.ReportItem` so that the raw-value caption
        line ends up beneath the visualization in the exported PDF.  The
        header figure is tagged with ``section_key="summary"`` so the PDF
        renderer places it on page 1 under the letterhead banner.
        """
        from reports.captions import caption_for
        from reports.pdf_layout import ReportItem

        self._status_var.set("")
        self._controller.set_selected_graphs(checked)

        items: list = []

        # Prepend header page with participant metadata (section_key="summary"
        # so the PDF renderer routes it to the letterhead page).
        try:
            header_fig = self._controller.build_header_figure()
            items.append(ReportItem(
                figure=header_fig, caption=None, section_key="summary",
            ))
        except Exception:
            pass  # Skip header if it can't be built

        for entry in GRAPH_REGISTRY:
            if entry.key not in checked or entry.key not in self._figure_cache:
                continue
            result = self._figure_cache[entry.key]
            if result is None:
                continue  # skip failed/no-data entries

            figs, _axes, plot_data = result[0], result[1], result[2]
            figure_keys = (
                plot_data.get("figure_keys")
                if isinstance(plot_data, dict) else None
            )
            # Per-target results carry one plot-data dict per figure, so each
            # caption quotes the values of the figure it sits under rather than
            # the first target's.
            figure_data = (
                plot_data.get("figure_data")
                if isinstance(plot_data, dict) else None
            )

            if isinstance(figs, list):
                for i, f in enumerate(figs):
                    if f is None:
                        continue
                    sub_key = (
                        figure_keys[i]
                        if figure_keys and i < len(figure_keys) else None
                    )
                    caption_data = (
                        figure_data[i]
                        if figure_data and i < len(figure_data) else plot_data
                    )
                    caption = caption_for(
                        entry.graph_type, entry.measure, caption_data, sub_key,
                    )
                    items.append(ReportItem(
                        figure=f, caption=caption, section_key=entry.key,
                    ))
            elif isinstance(figs, Figure):
                caption = caption_for(
                    entry.graph_type, entry.measure, plot_data, None,
                )
                items.append(ReportItem(
                    figure=figs, caption=caption, section_key=entry.key,
                ))

        self._controller.set_report_figures(items)

        self._unbind_arrow_keys()
        self._on_next()

    def _set_busy_for_export(self, busy: bool):
        if busy:
            self._progress.grid(row=0, column=0)
            self._progress.start()
            self._next_page_btn.configure(state="disabled")
            self._prev_btn.configure(state="disabled")
            self._next_arrow_btn.configure(state="disabled")
        else:
            self._progress.stop()
            self._progress.grid_remove()
            self._next_page_btn.configure(state="normal")
            self._update_nav_buttons()
