"""First page of the TMS App — lets the user set import paths."""

import customtkinter as ctk
from tkinter import filedialog
from pathlib import Path

from core.user_settings import (
    save_defaults, KEY_MEM_DIR, KEY_CSP_DIR, KEY_CMAP_DIR, KEY_CSV_FILE,
    KEY_MEM_RECURSIVE, KEY_CSP_RECURSIVE, KEY_CMAP_RECURSIVE,
)
from gui.theme import (
    FONT_TITLE, FONT_HEADING, FONT_BODY, FONT_SMALL, FONT_SUBTITLE, FONT_BUTTON,
    ACCENT_COLOR, ACCENT_HOVER, ERROR_COLOR, DISABLED_FG, SUBTITLE_COLOR,
    PAD_X, PAD_Y, SECTION_PAD_Y, ENTRY_HEIGHT, BUTTON_HEIGHT, CORNER_RADIUS,
)


class FilePanel(ctk.CTkFrame):
    """Path selection panel — page 1 of the workflow."""

    def __init__(self, parent, controller, on_next, on_back=None):
        super().__init__(parent, fg_color="transparent")
        self._controller = controller
        self._on_next = on_next
        self._on_back = on_back

        self._csv_var = ctk.StringVar()
        self._error_var = ctk.StringVar()

        self._save_mem = ctk.BooleanVar(value=False)
        self._save_csp = ctk.BooleanVar(value=False)
        self._save_cmap = ctk.BooleanVar(value=False)
        self._save_csv = ctk.BooleanVar(value=False)

        # Each multi-folder field keeps its own list of {frame, var} rows
        # and the container frame those rows are gridded into.
        self._dir_rows: dict[str, list[dict]] = {
            "mem": [], "csp": [], "cmap": [],
        }
        self._dir_lists: dict[str, ctk.CTkFrame] = {}
        # Per-field "scan subfolders" toggle vars + warning labels.
        self._recursive_vars: dict[str, ctk.BooleanVar] = {
            "mem": ctk.BooleanVar(value=False),
            "csp": ctk.BooleanVar(value=False),
            "cmap": ctk.BooleanVar(value=False),
        }
        self._recursive_helpers: dict[str, ctk.CTkLabel] = {}

        self._build_ui()
        self._load_defaults()

    def _load_defaults(self):
        """Pre-fill entries from controller defaults."""
        paths = self._controller.get_paths()
        self._set_dir_paths("mem", paths["mem_path"])
        self._set_dir_paths("csp", paths["csp_path"])
        self._set_dir_paths("cmap", paths.get("cmap_path", []))
        self._csv_var.set(paths["csv_path"])
        for name in ("mem", "csp", "cmap"):
            self._recursive_vars[name].set(
                bool(paths.get(f"{name}_recursive", False))
            )
            self._update_recursive_helper(name)

    def _set_dir_paths(self, name: str, value):
        """Populate a field's folder rows from a list (or legacy single string)."""
        if isinstance(value, str):
            paths = [value] if value.strip() else []
        else:
            paths = [str(v) for v in (value or []) if str(v).strip()]
        for row in self._dir_rows[name]:
            row["frame"].destroy()
        self._dir_rows[name].clear()
        if paths:
            for p in paths:
                self._add_dir_row(name, p)
        else:
            self._add_dir_row(name)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)

        # ── Title ──────────────────────────────────────────────
        title = ctk.CTkLabel(
            self, text="Import Settings", font=FONT_TITLE, anchor="w",
        )
        title.grid(row=0, column=0, sticky="w", padx=PAD_X, pady=(SECTION_PAD_Y, 4))

        subtitle = ctk.CTkLabel(
            self,
            text="Set the directories where your data files are located.",
            font=FONT_SUBTITLE,
            text_color=SUBTITLE_COLOR,
            anchor="w",
        )
        subtitle.grid(row=1, column=0, sticky="w", padx=PAD_X, pady=(0, SECTION_PAD_Y))

        # ── Fields container ───────────────────────────────────
        fields = ctk.CTkFrame(self, fg_color="transparent")
        fields.grid(row=2, column=0, sticky="nsew", padx=PAD_X)
        fields.grid_columnconfigure(0, weight=1)

        self._build_dir_section(
            fields, row=0, name="mem",
            title="MEM Files Directories *",
            helper=(
                "Folders containing .MEM files from Qtrack sessions. Add as "
                "many as you need — files may be stored in different "
                "locations. (At least one required)"
            ),
            save_var=self._save_mem,
        )
        self._build_dir_section(
            fields, row=1, name="csp",
            title="CSP MEM Files Directories",
            helper=(
                "Folders containing CSP-specific .MEM files. Add as many as "
                "you need. (Optional)"
            ),
            save_var=self._save_csp,
        )
        self._build_dir_section(
            fields, row=2, name="cmap",
            title="CMAP Files Directories",
            helper=(
                "Folders containing motor nerve-conduction study .pdf or "
                ".docx files. Add as many as you need. (Optional)"
            ),
            save_var=self._save_cmap,
        )
        self._add_path_row(
            fields, row=3,
            label="Archive CSV File",
            helper="Select a .csv archive file to build on. (Optional)",
            var=self._csv_var,
            browse_file=True,
            save_var=self._save_csv,
        )

        # ── Error label ───────────────────────────────────────
        self._error_label = ctk.CTkLabel(
            self,
            textvariable=self._error_var,
            font=FONT_SMALL,
            text_color=ERROR_COLOR,
            anchor="w",
            wraplength=500,
        )
        self._error_label.grid(
            row=3, column=0, sticky="w", padx=PAD_X, pady=(PAD_Y, 0),
        )

        # ── Navigation bar ────────────────────────────────────
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.grid(row=4, column=0, sticky="ew", padx=PAD_X, pady=(PAD_Y, SECTION_PAD_Y))
        nav.grid_columnconfigure(0, weight=1)

        if self._on_back:
            self._back_btn = ctk.CTkButton(
                nav,
                text="Back",
                width=100,
                height=BUTTON_HEIGHT,
                corner_radius=CORNER_RADIUS,
                font=FONT_BUTTON,
                fg_color=ACCENT_COLOR,
                hover_color=ACCENT_HOVER,
                command=self._on_back,
            )
        else:
            self._back_btn = ctk.CTkButton(
                nav,
                text="Back",
                width=100,
                height=BUTTON_HEIGHT,
                corner_radius=CORNER_RADIUS,
                font=FONT_BUTTON,
                state="disabled",
                fg_color=DISABLED_FG,
                hover=False,
            )
        self._back_btn.grid(row=0, column=0, sticky="w")

        self._next_btn = ctk.CTkButton(
            nav,
            text="Next",
            width=100,
            height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS,
            font=FONT_BUTTON,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER,
            command=self._handle_next,
        )
        self._next_btn.grid(row=0, column=1, sticky="e")

    # ── Reusable multi-folder section ──────────────────────

    def _build_dir_section(
        self, parent, row: int, *, name: str, title: str, helper: str,
        save_var: ctk.BooleanVar,
    ):
        """Build a directory field that accepts multiple folders.

        *name* keys the field's row list / container so MEM, CSP and CMAP
        can each reuse this same widget without code duplication.
        """
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", pady=(0, SECTION_PAD_Y))
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            frame, text=title, font=FONT_HEADING, anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 2))

        ctk.CTkLabel(
            frame, text=helper,
            font=FONT_SUBTITLE, text_color=SUBTITLE_COLOR, anchor="w",
            wraplength=560, justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 4))

        # Plain frame (not scrollable): the whole page already sits in an
        # outer scroll container, so this just needs to hug its rows — a
        # fixed-height scrollable frame would leave dead space below them.
        list_frame = ctk.CTkFrame(frame, fg_color="transparent")
        list_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        list_frame.grid_columnconfigure(0, weight=1)
        self._dir_lists[name] = list_frame

        controls = ctk.CTkFrame(frame, fg_color="transparent")
        controls.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        controls.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            controls, text="+ Add Folder", width=120, height=ENTRY_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_SMALL,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=lambda n=name: self._add_dir_row(n),
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkCheckBox(
            controls, text="Save as default", variable=save_var,
            font=FONT_SMALL,
        ).grid(row=0, column=2, sticky="e")

        # "Include subfolders" toggle + inline warning helper. The helper is
        # only shown while the toggle is on, so users see the cost note exactly
        # when it applies.
        ctk.CTkCheckBox(
            frame, text="Include subfolders",
            variable=self._recursive_vars[name],
            font=FONT_SMALL,
            command=lambda n=name: self._update_recursive_helper(n),
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        helper_label = ctk.CTkLabel(
            frame,
            text=(
                "Scanning subfolders may take longer on large folder trees."
            ),
            font=FONT_SMALL, text_color="#F39C12", anchor="w",
            wraplength=560, justify="left",
        )
        helper_label.grid(row=5, column=0, columnspan=2, sticky="w", pady=(2, 0))
        helper_label.grid_remove()
        self._recursive_helpers[name] = helper_label

    def _update_recursive_helper(self, name: str):
        """Show or hide the 'may take longer' warning for field *name*."""
        helper = self._recursive_helpers.get(name)
        if helper is None:
            return
        if self._recursive_vars[name].get():
            helper.grid()
        else:
            helper.grid_remove()

    def _add_dir_row(self, name: str, path: str = ""):
        """Append one folder row (entry + Browse + Remove) to field *name*."""
        rows = self._dir_rows[name]
        list_frame = self._dir_lists[name]
        row_frame = ctk.CTkFrame(list_frame, fg_color="transparent")
        row_frame.grid(row=len(rows), column=0, sticky="ew", pady=(0, 4))
        row_frame.grid_columnconfigure(0, weight=1)

        var = ctk.StringVar(value=path)
        ctk.CTkEntry(
            row_frame, textvariable=var, height=ENTRY_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BODY,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))

        ctk.CTkButton(
            row_frame, text="Browse", width=90, height=ENTRY_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BODY,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=lambda v=var: self._browse_dir(v),
        ).grid(row=0, column=1, padx=(0, 4))

        row_info = {"frame": row_frame, "var": var}
        ctk.CTkButton(
            row_frame, text="X", width=36, height=ENTRY_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ERROR_COLOR, hover_color="#C0392B",
            command=lambda ri=row_info: self._remove_dir_row(name, ri),
        ).grid(row=0, column=2)

        rows.append(row_info)

    def _remove_dir_row(self, name: str, row_info: dict):
        """Remove a folder row from field *name*; always keep at least one."""
        rows = self._dir_rows[name]
        if row_info not in rows:
            return
        if len(rows) == 1:
            row_info["var"].set("")  # keep one empty row rather than none
            return
        row_info["frame"].destroy()
        rows.remove(row_info)
        for i, ri in enumerate(rows):
            ri["frame"].grid(row=i, column=0, sticky="ew", pady=(0, 4))

    def _collect_dir_paths(self, name: str) -> list[str]:
        """Return the de-duplicated, non-empty folder paths for field *name*."""
        seen: set[str] = set()
        result: list[str] = []
        for ri in self._dir_rows[name]:
            p = ri["var"].get().strip()
            if p and p not in seen:
                seen.add(p)
                result.append(p)
        return result

    def _add_path_row(
        self, parent, row: int, label: str, helper: str,
        var: ctk.StringVar, browse_file: bool = False,
        save_var: ctk.BooleanVar | None = None,
    ):
        """Create a labeled path entry with a Browse button and optional save-default checkbox."""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", pady=(0, SECTION_PAD_Y))
        frame.grid_columnconfigure(0, weight=1)

        lbl = ctk.CTkLabel(frame, text=label, font=FONT_HEADING, anchor="w")
        lbl.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 2))

        entry = ctk.CTkEntry(
            frame,
            textvariable=var,
            height=ENTRY_HEIGHT,
            corner_radius=CORNER_RADIUS,
            font=FONT_BODY,
        )
        entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))

        if browse_file:
            cmd = lambda v=var: self._browse_file(v)
        else:
            cmd = lambda v=var: self._browse_dir(v)

        browse_btn = ctk.CTkButton(
            frame,
            text="Browse",
            width=90,
            height=ENTRY_HEIGHT,
            corner_radius=CORNER_RADIUS,
            font=FONT_BODY,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER,
            command=cmd,
        )
        browse_btn.grid(row=1, column=1, sticky="e")

        hlp = ctk.CTkLabel(
            frame, text=helper, font=FONT_SUBTITLE, text_color=SUBTITLE_COLOR, anchor="w",
        )
        hlp.grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 0))

        if save_var is not None:
            ctk.CTkCheckBox(
                frame,
                text="Save as default",
                variable=save_var,
                font=FONT_SMALL,
            ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))

    def _browse_dir(self, var: ctk.StringVar):
        """Open a folder-selection dialog and write the result into var."""
        initial = var.get() if var.get() and Path(var.get()).is_dir() else None
        path = filedialog.askdirectory(
            title="Select Directory",
            initialdir=initial,
        )
        if path:
            var.set(path)

    def _browse_file(self, var: ctk.StringVar):
        """Open a file-selection dialog filtered to .csv files."""
        current = var.get()
        initial_dir = None
        if current:
            p = Path(current)
            if p.is_file():
                initial_dir = str(p.parent)
            elif p.is_dir():
                initial_dir = current

        path = filedialog.askopenfilename(
            title="Select CSV File",
            initialdir=initial_dir,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            var.set(path)

    def refresh(self):
        """Re-load defaults and show any Quick Start redirect message."""
        self._load_defaults()
        msg = self._controller.consume_quick_start_message()
        if msg:
            self._error_var.set(msg)
            self._error_label.configure(text_color="#F39C12")
        else:
            self._error_var.set("")
            self._error_label.configure(text_color=ERROR_COLOR)

    def _handle_next(self):
        """Validate inputs, save to controller, persist defaults, and advance."""
        self._error_var.set("")

        mem_paths = self._collect_dir_paths("mem")
        csp_paths = self._collect_dir_paths("csp")
        cmap_paths = self._collect_dir_paths("cmap")
        mem_rec = self._recursive_vars["mem"].get()
        csp_rec = self._recursive_vars["csp"].get()
        cmap_rec = self._recursive_vars["cmap"].get()
        self._controller.set_paths(
            mem_path=mem_paths,
            csp_path=csp_paths,
            cmap_path=cmap_paths,
            csv_path=self._csv_var.get().strip(),
            mem_recursive=mem_rec,
            csp_recursive=csp_rec,
            cmap_recursive=cmap_rec,
        )

        errors = self._controller.validate_paths()
        if errors:
            self._error_var.set("\n".join(errors))
            return

        # Persist checked paths (and their recursion flags) as defaults for
        # next session. save_defaults pops keys when the value is falsy, so
        # a False toggle simply clears any previously-saved override.
        to_save = {}
        if self._save_mem.get():
            to_save[KEY_MEM_DIR] = mem_paths
            to_save[KEY_MEM_RECURSIVE] = mem_rec
        if self._save_csp.get():
            to_save[KEY_CSP_DIR] = csp_paths
            to_save[KEY_CSP_RECURSIVE] = csp_rec
        if self._save_cmap.get():
            to_save[KEY_CMAP_DIR] = cmap_paths
            to_save[KEY_CMAP_RECURSIVE] = cmap_rec
        if self._save_csv.get():
            to_save[KEY_CSV_FILE] = self._csv_var.get().strip()
        if to_save:
            save_defaults(**to_save)

        self._on_next()
