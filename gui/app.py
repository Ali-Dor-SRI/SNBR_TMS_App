"""Main application window for the SNBR TMS App."""

import threading

import customtkinter as ctk

from gui.controller import AppController
from gui.nav import next_visible_page, prev_visible_page
from gui.data_mode_panel import DataModePanel
from gui.exclusion_panel import ExclusionPanel
from gui.email_panel import EmailPanel
from gui.export_panel import ExportPanel
from gui.file_panel import FilePanel
from gui.finish_panel import FinishPanel
from gui.sync_panel import SyncPanel
from gui.participant_panel import ParticipantPanel
from gui.visualization_panel import VisualizationPanel
from gui.welcome_panel import WelcomePanel
from gui.redcap_panel import RedcapPanel
from gui.settings_panel import SettingsPanel
from gui.page_shell import PageShell
from gui.theme import (
    FONT_SMALL, FONT_BUTTON, FONT_BODY, FONT_HEADING, FONT_TITLE,
    ACCENT_COLOR, ACCENT_HOVER, ERROR_COLOR, SUCCESS_COLOR, DISABLED_FG,
    PAD_X, PAD_Y, BUTTON_HEIGHT, CORNER_RADIUS, SECTION_PAD_Y,
)

# Friendly labels for the page-jump dropdown.
PAGE_LABELS = [
    ("welcome",       "Welcome"),
    ("file_panel",    "Import Settings"),
    ("data_mode",     "Data Mode"),
    ("exclusion",     "Exclude Participants"),
    ("participant",   "Participant"),
    ("visualization", "Visualization"),
    ("export",        "Export"),
    ("email",         "Email Report"),
    ("redcap",        "REDCap Export"),
    ("sync",          "Backup & Sync"),
    ("finish",        "Finish"),
]
_LABEL_TO_NAME = {label: name for name, label in PAGE_LABELS}
_NAME_TO_LABEL = {name: label for name, label in PAGE_LABELS}


class TMSApp(ctk.CTk):
    """Root window — manages page navigation and the theme toggle."""

    WIDTH = 1100
    HEIGHT = 700
    MIN_WIDTH = 1000
    MIN_HEIGHT = 650

    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("SNBR TMS App")
        self.geometry(f"{self.WIDTH}x{self.HEIGHT}")
        self.minsize(self.MIN_WIDTH, self.MIN_HEIGHT)

        self._controller = AppController()
        self._pages: dict[str, ctk.CTkFrame] = {}
        # One PageShell per page — the frame actually raised by _show_page.
        # self._pages holds the panels themselves, which sit inside them.
        self._shells: dict[str, PageShell] = {}
        self._current_page: str = ""
        self._previous_page: str = ""

        # Ordered page names for keyboard navigation.
        self._page_order = [
            "welcome", "file_panel", "data_mode", "exclusion", "participant",
            "visualization", "export", "email", "redcap", "sync", "finish",
        ]

        self._build_toolbar()
        self._build_container()
        self._bind_keyboard_shortcuts()
        self._show_page("welcome")

    # ── Toolbar ────────────────────────────────────────────
    def _build_toolbar(self):
        toolbar = ctk.CTkFrame(self, height=40, corner_radius=0)
        toolbar.pack(fill="x", side="top")
        toolbar.pack_propagate(False)

        app_label = ctk.CTkLabel(
            toolbar, text="SNBR TMS", font=("Segoe UI", 14, "bold"),
        )
        app_label.pack(side="left", padx=12)

        # Page-jump dropdown
        self._jump_var = ctk.StringVar(value="Welcome")
        self._jump_dropdown = ctk.CTkOptionMenu(
            toolbar,
            variable=self._jump_var,
            values=[label for _, label in PAGE_LABELS],
            width=160,
            height=28,
            corner_radius=6,
            font=FONT_SMALL,
            fg_color=ACCENT_COLOR,
            button_color=ACCENT_HOVER,
            dropdown_font=FONT_SMALL,
            command=self._on_page_jump,
        )
        self._jump_dropdown.pack(side="left", padx=(12, 6))

        # Complete All button
        self._complete_btn = ctk.CTkButton(
            toolbar,
            text="Complete All",
            width=110,
            height=28,
            corner_radius=6,
            font=FONT_SMALL,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER,
            command=self._on_complete_remaining,
        )
        self._complete_btn.pack(side="left", padx=(0, 6))

        settings_btn = ctk.CTkButton(
            toolbar,
            text="Settings",
            width=80,
            height=28,
            corner_radius=6,
            font=FONT_SMALL,
            fg_color="transparent",
            hover_color=ACCENT_COLOR,
            border_width=1,
            border_color=ACCENT_COLOR,
            text_color=ACCENT_COLOR,
            command=lambda: self._show_page("settings"),
        )
        settings_btn.pack(side="right", padx=(0, 8))

        self._dark_mode_var = ctk.BooleanVar(value=True)
        theme_switch = ctk.CTkSwitch(
            toolbar,
            text="Dark Mode",
            variable=self._dark_mode_var,
            onvalue=True,
            offvalue=False,
            command=self._toggle_theme,
            font=FONT_SMALL,
        )
        theme_switch.pack(side="right", padx=12)

    def _toggle_theme(self):
        mode = "dark" if self._dark_mode_var.get() else "light"
        ctk.set_appearance_mode(mode)

    # ── Page container ─────────────────────────────────────
    def _add_page(self, name: str, factory, scrolling: bool = True):
        """Build one page inside its own shell and register both.

        *factory* receives the content parent and the footer frame, and returns
        the panel. The panel grids its own controls into that footer.
        """
        shell = PageShell(self._container, scrolling=scrolling)
        shell.grid(row=0, column=0, sticky="nsew")
        page = factory(shell.content, shell.footer)
        page.grid(row=0, column=0, sticky="nsew")
        shell.finalize()
        self._pages[name] = page
        self._shells[name] = shell
        return page

    def _build_container(self):
        # Pages are no longer wrapped in one window-wide scroller. Each gets a
        # PageShell that scrolls its own content and pins its Back/Next bar to
        # the bottom of the window, so the controls never scroll out of reach.
        self._container = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self._container.pack(fill="both", expand=True)
        self._container.grid_rowconfigure(0, weight=1)
        self._container.grid_columnconfigure(0, weight=1)


        # Page 0 — welcome
        self._add_page(
            "welcome",
            lambda parent, footer: WelcomePanel(
                parent,
                footer=footer,
                controller=self._controller,
                on_done=lambda: self._show_page("finish"),
                on_custom=lambda: self._show_page("file_panel"),
                on_redirect=lambda name: self._show_page(name),
            ),
        )

        # Pages 1-9 use computed linear navigation: Next/Back move to the next
        # or previous page that the user has NOT chosen to skip (see
        # _next_page / _prev_page). With no skips this is the plain 1→2→3 flow.

        # Page 1 — path selection
        self._add_page(
            "file_panel",
            lambda parent, footer: FilePanel(
                parent,
                footer=footer,
                controller=self._controller,
                on_next=lambda: self._show_page(self._next_page("file_panel")),
                on_back=lambda: self._show_page(self._prev_page("file_panel")),
            ),
        )

        # Page 2 — data import mode
        self._add_page(
            "data_mode",
            lambda parent, footer: DataModePanel(
                parent,
                footer=footer,
                controller=self._controller,
                on_next=lambda: self._show_page(self._next_page("data_mode")),
                on_back=lambda: self._show_page(self._prev_page("data_mode")),
            ),
        )

        # Page 3 — exclude participants from averages (skippable)
        self._add_page(
            "exclusion",
            lambda parent, footer: ExclusionPanel(
                parent,
                footer=footer,
                controller=self._controller,
                on_next=lambda: self._show_page(self._next_page("exclusion")),
                on_back=lambda: self._show_page(self._prev_page("exclusion")),
            ),
        )

        # Page 4 — participant / visit date selection
        self._add_page(
            "participant",
            lambda parent, footer: ParticipantPanel(
                parent,
                footer=footer,
                controller=self._controller,
                on_next=lambda: self._show_page(self._next_page("participant")),
                on_back=lambda: self._show_page(self._prev_page("participant")),
            ),
        )

        # Page 5 — visualization selection & preview
        self._add_page(
            "visualization",
            lambda parent, footer: VisualizationPanel(
                parent,
                footer=footer,
                controller=self._controller,
                on_next=lambda: self._show_page(self._next_page("visualization")),
                on_back=lambda: self._show_page(self._prev_page("visualization")),
            ),
            scrolling=False,
        )

        # Page 6 — export
        self._add_page(
            "export",
            lambda parent, footer: ExportPanel(
                parent,
                footer=footer,
                controller=self._controller,
                on_next=lambda: self._show_page(self._next_page("export")),
                on_back=lambda: self._show_page(self._prev_page("export")),
            ),
        )

        # Page 7 — Email report (skippable)
        self._add_page(
            "email",
            lambda parent, footer: EmailPanel(
                parent,
                footer=footer,
                controller=self._controller,
                on_next=lambda: self._show_page(self._next_page("email")),
                on_back=lambda: self._show_page(self._prev_page("email")),
            ),
        )

        # Page 8 — REDCap export (skippable)
        self._add_page(
            "redcap",
            lambda parent, footer: RedcapPanel(
                parent,
                footer=footer,
                controller=self._controller,
                on_next=lambda: self._show_page(self._next_page("redcap")),
                on_back=lambda: self._show_page(self._prev_page("redcap")),
            ),
        )

        # Page 9 — backup & sync (skippable)
        self._add_page(
            "sync",
            lambda parent, footer: SyncPanel(
                parent,
                footer=footer,
                controller=self._controller,
                on_next=lambda: self._show_page(self._next_page("sync")),
                on_back=lambda: self._show_page(self._prev_page("sync")),
            ),
        )

        # Page 10 — finish (restart or close)
        self._add_page(
            "finish",
            lambda parent, footer: FinishPanel(
                parent,
                footer=footer,
                controller=self._controller,
                on_restart=lambda: self._show_page("participant"),
                on_back=lambda: self._show_page(self._prev_page("finish")),
            ),
        )

        # Settings (not in page order — accessed via toolbar)
        self._add_page(
            "settings",
            lambda parent, footer: SettingsPanel(
                parent,
                footer=footer,
                controller=self._controller,
                on_back=self._return_from_settings,
            ),
        )

    def _show_page(self, name: str):
        """Raise the requested page to the front."""
        if name == "settings" and self._current_page != "settings":
            self._previous_page = self._current_page
        self._current_page = name
        page = self._pages[name]
        if hasattr(page, "refresh"):
            page.refresh()
        # The shell carries the page's pinned footer, so raising the panel alone
        # would leave the previous page's Back/Next bar on top.
        self._shells[name].tkraise()
        # Sync the toolbar dropdown to the current page
        label = _NAME_TO_LABEL.get(name)
        if label and hasattr(self, "_jump_var"):
            self._jump_var.set(label)

    def _return_from_settings(self):
        """Navigate back to whichever page the user was on before Settings."""
        self._show_page(self._previous_page or "welcome")

    # ── Page jump & Complete All ──────────────────────────

    def _current_page_index(self) -> int:
        try:
            return self._page_order.index(self._current_page)
        except ValueError:
            return 0

    def _next_page(self, current: str) -> str:
        """Next page in the flow the user hasn't skipped (see next_visible_page)."""
        return next_visible_page(
            self._page_order, self._controller.get_skipped_pages(), current,
        )

    def _prev_page(self, current: str) -> str:
        """Previous page in the flow the user hasn't skipped."""
        return prev_visible_page(
            self._page_order, self._controller.get_skipped_pages(), current,
        )

    def _on_page_jump(self, selected_label: str):
        """Handle a selection from the page-jump dropdown."""
        target_name = _LABEL_TO_NAME.get(selected_label)
        if not target_name or target_name == self._current_page:
            return

        target_idx = self._page_order.index(target_name)
        current_idx = self._current_page_index()

        if target_idx <= current_idx:
            # Jumping backward — just navigate
            self._show_page(target_name)
        else:
            # Jumping forward — need to run default phases for skipped pages
            # Check defaults first (phases from current+1 to target)
            missing = self._controller.check_defaults_for_range(
                current_idx + 1, target_idx,
            )
            if missing:
                self._show_error_popup(
                    "Cannot jump forward",
                    "The following defaults are missing:\n\n"
                    + "\n".join(f"  - {m}" for m in missing),
                )
                # Reset dropdown to current page
                self._jump_var.set(
                    _NAME_TO_LABEL.get(self._current_page, "Welcome")
                )
                return

            self._set_toolbar_busy(True)
            thread = threading.Thread(
                target=self._run_phases_worker,
                args=(current_idx + 1, target_idx, target_name),
                daemon=True,
            )
            thread.start()

    def _on_complete_remaining(self):
        """Run all remaining phases with defaults and jump to Finish."""
        current_idx = self._current_page_index()
        finish_idx = len(self._page_order) - 1  # "finish"

        if current_idx >= finish_idx:
            return  # already at finish

        missing = self._controller.check_defaults_for_range(
            current_idx + 1, finish_idx,
        )
        if missing:
            self._show_error_popup(
                "Cannot complete remaining steps",
                "The following defaults are missing:\n\n"
                + "\n".join(f"  - {m}" for m in missing),
            )
            return

        self._set_toolbar_busy(True)
        thread = threading.Thread(
            target=self._run_phases_worker,
            args=(current_idx + 1, finish_idx, "finish"),
            daemon=True,
        )
        thread.start()

    def _run_phases_worker(self, from_idx, to_idx, target_page):
        """Background thread: execute phases and navigate on completion."""
        try:
            summary = self._controller.run_default_phases(
                from_idx, to_idx,
                status_callback=lambda msg: None,  # silent
            )
            if target_page == "finish":
                self.after(0, self._on_phases_complete, summary)
            else:
                self.after(0, self._on_jump_complete, target_page)
        except Exception as exc:
            self.after(0, self._on_phases_error, str(exc))

    def _on_jump_complete(self, target_page):
        self._set_toolbar_busy(False)
        self._show_page(target_page)

    def _on_phases_complete(self, summary):
        self._set_toolbar_busy(False)
        self._show_page("finish")
        # Show summary popup (reuse welcome panel's summary logic)
        welcome = self._pages.get("welcome")
        if welcome and hasattr(welcome, "_show_summary_popup"):
            welcome._show_summary_popup(summary)

    def _on_phases_error(self, msg):
        self._set_toolbar_busy(False)
        self._show_error_popup("Error running workflow", msg)

    def _set_toolbar_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        self._jump_dropdown.configure(state=state)
        self._complete_btn.configure(
            state=state,
            text="Running..." if busy else "Complete All",
        )

    def _show_error_popup(self, title: str, message: str):
        """Show a modal error dialog."""
        popup = ctk.CTkToplevel(self)
        popup.title(title)
        popup.geometry("480x280")
        popup.resizable(False, False)
        popup.grab_set()
        popup.after(100, popup.focus_force)

        popup.grid_columnconfigure(0, weight=1)
        popup.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            popup, text=title, font=FONT_HEADING,
            text_color=ERROR_COLOR, anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=PAD_X, pady=(PAD_Y, 4))

        msg_label = ctk.CTkLabel(
            popup, text=message, font=FONT_SMALL,
            anchor="nw", justify="left", wraplength=420,
        )
        msg_label.grid(
            row=1, column=0, sticky="nsew", padx=PAD_X, pady=(0, PAD_Y),
        )

        ctk.CTkButton(
            popup, text="OK", width=100, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=popup.destroy,
        ).grid(row=2, column=0, pady=(0, PAD_Y))

    # ── Keyboard shortcuts ─────────────────────────────────

    def _bind_keyboard_shortcuts(self):
        """Bind global keyboard shortcuts for navigation."""
        # Ctrl+B / Ctrl+N — fire regardless of focused widget; the modifier
        # makes the intent unambiguous and avoids collisions with typing.
        self.bind_all("<Control-b>", self._on_key_nav_back)
        self.bind_all("<Control-B>", self._on_key_nav_back)
        self.bind_all("<Control-n>", self._on_key_nav_next)
        self.bind_all("<Control-N>", self._on_key_nav_next)

    def _on_key_nav_back(self, event):
        """Trigger the current page's Back action — prefer ``_handle_back``
        (which may run backend work like saving defaults) and fall back to
        the plain navigation callback ``_on_back`` when no handler exists.
        Returns ``"break"`` so Entry widgets don't also consume the key.
        """
        page = self._pages.get(self._current_page)
        if page is not None:
            handler = getattr(page, "_handle_back", None) or getattr(
                page, "_on_back", None
            )
            if callable(handler):
                handler()
        return "break"

    def _on_key_nav_next(self, event):
        """Trigger the current page's Next action — prefer ``_handle_next``
        (which runs validation / parsing / CSV load before navigating) and
        fall back to ``_on_next`` when no handler exists.
        """
        page = self._pages.get(self._current_page)
        if page is not None:
            handler = getattr(page, "_handle_next", None) or getattr(
                page, "_on_next", None
            )
            if callable(handler):
                handler()
        return "break"
