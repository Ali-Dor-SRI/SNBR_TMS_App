"""GUI-backend bridge. All GUI frames communicate with the backend through this module."""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")  # noqa: E402 — must precede any pyplot import

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from core.config import MEM_DIR, CSP_DIR
from core.user_settings import (
    load_defaults,
    save_defaults,
    KEY_MEM_DIR, KEY_CSP_DIR, KEY_CMAP_DIR, KEY_CSV_FILE,
    KEY_MEM_RECURSIVE, KEY_CSP_RECURSIVE, KEY_CMAP_RECURSIVE,
    KEY_EXPORT_CSV, KEY_EXPORT_PDF, KEY_SYNC_PAIRS,
    KEY_EXCLUDED_MEASUREMENTS, KEY_EXCLUDED_PARTICIPANTS,
    KEY_OUTLIER_BOUNDS,
    KEY_SKIPPED_PAGES,
    KEY_REDCAP_DATA_DIR, KEY_REDCAP_DICT_DIR,
    KEY_REDCAP_TEMPLATE_DIR, KEY_REDCAP_EXPORT_DIR,
    KEY_REDCAP_XLSX_DIR,
    KEY_SMTP_HOST, KEY_SMTP_PORT,
    KEY_EMAIL_USERNAME, KEY_EMAIL_FROM,
    KEY_EMAIL_DEFAULT_TO, KEY_EMAIL_DEFAULT_CC, KEY_EMAIL_DEFAULT_BCC,
    KEY_EMAIL_SUBJECT, KEY_EMAIL_BODY, KEY_EMAIL_REMEMBER_PASSWORD,
)
from parser.recording_target import MUSCLE_COLUMN, SIDE_COLUMN, target_key, target_label
from reports.export_naming import (
    default_dataframe_stem,
    default_graph_stem,
    default_report_stem,
    unique_path,
)
from processing.cohort_filters import (
    analysis_cortex_for,
    cohort_label_bases,
    cohort_scope_label,
    participant_study,
    restrict_cohort_to_analysis_cortex,
    restrict_cohort_to_study,
)
from processing.df_builder import (
    _apply_cmap_merge,
    archive_predates_recording_targets,
    build_combined_dataframe_incremental,
    csv_schema_is_current,
    detect_participant_id_mismatches,
    load_existing_csv,
    restrict_participant_to_muscle,
    restrict_participant_to_target,
    target_labels_in,
)
from processing.visualizer import (
    CSP_MEASURE_KEY,
    CSP_MEASURE_LABEL,
    CSP_PROFILE_COLUMNS,
    RMT_COLUMNS,
    WAVEFORM_MEASURE_CONFIGS,
    format_participant_label,
    normalize_mem_date,
    waveform_measure_config,
    plot_mem_graph,
)
from processing.figure_style import enlarge_result_figures
from reports.csv_exporter import find_latest_csv
from reports.report_builder import build_header_only_figure
from parser.sr_parser import SR_CURVE_COLUMN, SR_MAX_COLUMN
from parser.strength_duration_parser import (
    SD_POINTS_COLUMN,
    SD_RHEOBASE_COLUMN,
    SD_TAU_COLUMN,
)


def _as_path_list(value) -> list[str]:
    """Normalise a stored directory setting (legacy str or list) to list[str]."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(v).strip() for v in value if str(v).strip()]


class AppController:
    """Stores user selections and orchestrates backend calls for the GUI."""

    # Default directory to look for archive CSVs (sibling of MEM_DIR).
    _CSV_ARCHIVE_DIR = MEM_DIR.parent / "SNBR_CSV_Archive"

    # Optional workflow pages that may be hidden from the linear Next/Back flow
    # via "Skip this page in future runs". Required pages (paths, data, the
    # participant/visualization/export core) are deliberately excluded so a
    # skip can never strand the user. Skipped pages stay reachable from the
    # toolbar page-jump dropdown.
    SKIPPABLE_PAGES = frozenset({"exclusion", "email", "redcap", "sync"})

    def __init__(self):
        self._mem_paths: list[str] = []
        self._csp_paths: list[str] = []
        self._cmap_paths: list[str] = []
        # Per-field "scan subfolders" toggle. Default OFF — recursion is opt-in.
        self._mem_recursive: bool = False
        self._csp_recursive: bool = False
        self._cmap_recursive: bool = False
        # Memoized {filename: Path} index over the MEM folder(s), rebuilt only
        # when the paths/recursion change. Avoids re-scanning the whole MEM
        # directory on every peripheral (SR/SD) plot that falls back to reading
        # its source file.
        self._mem_file_index: dict | None = None
        self._mem_index_key: tuple | None = None
        # True when the working DataFrame was loaded from a schema-stale archive
        # WITHOUT re-parsing (the fast "archive as-is" path), so its newer parser
        # columns (e.g. SR/SD) are present-but-empty. Used to avoid exporting a
        # CSV that looks schema-current but has no SR/SD data. The companion
        # snapshot records that archive's raw columns AT LOAD TIME so the export
        # decision can't drift if the CSV path changes or the file is replaced.
        self._schema_stale: bool = False
        self._stale_raw_cols: set | None = None
        self._csv_path: str = ""  # a *file* path, not a directory
        self._dataframe: pd.DataFrame | None = None
        self._quick_start_message: str = ""
        self._last_exported_pdf: str = ""
        # Per-participant tests excluded from cohort averages and CSV export:
        # {participant_id: {test_key, ...}}. Loaded from saved defaults at
        # startup; mutated in-session by the exclusion panel and only
        # re-persisted when the user saves.
        self._excluded_tests: dict[int, set[str]] = {}

        # Cohort-wide outlier cutoffs per measure: {measure_key: {"lower":
        # float|None, "upper": float|None}}. Any participant-visit whose average
        # for a measure falls outside its range is blanked for that measure
        # (dropped from cohort averages, blanked in the CSV), applied on top of
        # the per-participant exclusions above.
        self._outlier_bounds: dict[str, dict[str, float | None]] = {}

        self._apply_defaults()

    def _apply_defaults(self):
        """Pre-populate paths from saved user defaults, then fall back to config.py."""
        saved = load_defaults()

        # Import paths — saved defaults take priority over hardcoded config.
        self._mem_paths = _as_path_list(saved.get(KEY_MEM_DIR, ""))
        if not self._mem_paths and MEM_DIR.is_dir():
            self._mem_paths = [str(MEM_DIR)]

        self._csp_paths = _as_path_list(saved.get(KEY_CSP_DIR, ""))
        if not self._csp_paths and CSP_DIR.is_dir():
            self._csp_paths = [str(CSP_DIR)]

        self._cmap_paths = _as_path_list(saved.get(KEY_CMAP_DIR, ""))

        self._mem_recursive = bool(saved.get(KEY_MEM_RECURSIVE, False))
        self._csp_recursive = bool(saved.get(KEY_CSP_RECURSIVE, False))
        self._cmap_recursive = bool(saved.get(KEY_CMAP_RECURSIVE, False))

        self._csv_path = saved.get(KEY_CSV_FILE, "")
        if not self._csv_path:
            latest = find_latest_csv(self._CSV_ARCHIVE_DIR)
            if latest is not None:
                self._csv_path = str(latest)

        # Export paths
        self._default_export_csv = saved.get(KEY_EXPORT_CSV, "")
        self._default_export_pdf = saved.get(KEY_EXPORT_PDF, "")

        # Pages the user has chosen to skip in the linear workflow flow.
        self._skipped_pages: set[str] = {
            str(p) for p in saved.get(KEY_SKIPPED_PAGES, [])
            if str(p) in self.SKIPPABLE_PAGES
        }

        # Excluded tests — apply saved defaults to the active session.
        self._excluded_tests = self._coerce_excluded_map(
            saved.get(KEY_EXCLUDED_MEASUREMENTS, {})
        )
        # One-way migration: a legacy whole-participant exclusion list means
        # "exclude every test" for each of those participants.
        if not self._excluded_tests:
            legacy_ids = self._coerce_id_list(
                saved.get(KEY_EXCLUDED_PARTICIPANTS, [])
            )
            if legacy_ids:
                all_tests = set(self.EXCLUDABLE_TEST_KEYS)
                self._excluded_tests = {pid: set(all_tests) for pid in legacy_ids}

        # Cohort-wide outlier bounds — apply saved defaults to the session.
        self._outlier_bounds = self._coerce_outlier_bounds(
            saved.get(KEY_OUTLIER_BOUNDS, {})
        )

    def get_default_export_paths(self) -> dict[str, str]:
        return {
            "csv": getattr(self, "_default_export_csv", ""),
            "pdf": getattr(self, "_default_export_pdf", ""),
        }

    def get_saved_defaults(self) -> dict:
        """Return all saved user defaults (for display in settings)."""
        return load_defaults()

    def clear_all_defaults(self) -> None:
        """Erase every saved default and reset in-memory paths."""
        from core.user_settings import clear_all_defaults
        clear_all_defaults()
        self._mem_paths = []
        self._csp_paths = []
        self._cmap_paths = []
        self._mem_recursive = False
        self._csp_recursive = False
        self._cmap_recursive = False
        self._csv_path = ""
        self._default_export_csv = ""
        self._default_export_pdf = ""
        self._excluded_tests = {}
        self._outlier_bounds = {}
        self._skipped_pages = set()

    def set_paths(
        self, mem_path, csp_path="", csv_path: str = "",
        cmap_path="",
        *,
        mem_recursive: bool | None = None,
        csp_recursive: bool | None = None,
        cmap_recursive: bool | None = None,
    ):
        """Save the user-selected import paths.

        *mem_path*, *csp_path* and *cmap_path* may each be a single directory
        string or a list of directories (the user can pick files from several
        locations).  *csv_path* is always a single archive file.  The
        ``*_recursive`` flags toggle whether subfolders are scanned for each
        field; ``None`` means leave the existing value unchanged.
        """
        self._mem_paths = _as_path_list(mem_path)
        self._csp_paths = _as_path_list(csp_path)
        self._cmap_paths = _as_path_list(cmap_path)
        self._csv_path = csv_path
        if mem_recursive is not None:
            self._mem_recursive = bool(mem_recursive)
        if csp_recursive is not None:
            self._csp_recursive = bool(csp_recursive)
        if cmap_recursive is not None:
            self._cmap_recursive = bool(cmap_recursive)

    def get_paths(self) -> dict:
        """Return the current import paths and per-field recursion flags."""
        return {
            "mem_path": list(self._mem_paths),
            "csp_path": list(self._csp_paths),
            "cmap_path": list(self._cmap_paths),
            "csv_path": self._csv_path,
            "mem_recursive": self._mem_recursive,
            "csp_recursive": self._csp_recursive,
            "cmap_recursive": self._cmap_recursive,
        }

    def validate_paths(self) -> list[str]:
        """Validate paths and return a list of error messages (empty = valid)."""
        errors = []

        if not self._mem_paths:
            errors.append("At least one MEM files directory is required.")
        else:
            for p in self._mem_paths:
                if not Path(p).is_dir():
                    errors.append(f"MEM files directory does not exist:\n{p}")

        for p in self._csp_paths:
            if not Path(p).is_dir():
                errors.append(f"CSP MEM directory does not exist:\n{p}")

        for p in self._cmap_paths:
            if not Path(p).is_dir():
                errors.append(f"CMAP files directory does not exist:\n{p}")

        if self._csv_path and not Path(self._csv_path).is_file():
            errors.append(f"Archive CSV file does not exist:\n{self._csv_path}")

        return errors

    # ── DataFrame operations ───────────────────────────────

    def load_csv_dataframe(self, *, merge_cmap: bool = True) -> pd.DataFrame:
        """Load the user-selected CSV into a DataFrame.

        When *merge_cmap* is True (the default) and a CMAP folder is
        configured, the CMAP merge is re-applied so users who load a CSV
        exported before CMAP/MUNIX support existed still pick up those fields
        without re-parsing the MEM folder. Pass ``merge_cmap=False`` for the
        fast "use the archive as-is" path, which touches no folders at all.
        """
        df = load_existing_csv(self._csv_path)
        if merge_cmap and self._cmap_paths:
            df = _apply_cmap_merge(
                df, self._cmap_paths, recursive=self._cmap_recursive,
            )
        # Flag when the archive predates newer parser columns (e.g. SR/SD): this
        # "as-is" load does no folder scan, so those columns stay empty and their
        # graphs will be unavailable until a re-parse. The UI surfaces this, and
        # the export path avoids writing a misleadingly schema-current CSV.
        stale = not csv_schema_is_current(self._csv_path)
        df.attrs["schema_stale"] = stale
        self._schema_stale = stale
        # Reported separately from generic staleness: an archive without the
        # muscle/side columns still has multi-muscle visits merged onto a single
        # row, which no amount of column backfilling can undo.
        try:
            df.attrs["targets_stale"] = archive_predates_recording_targets(
                set(pd.read_csv(self._csv_path, nrows=0).columns)
            )
        except Exception:
            df.attrs["targets_stale"] = False
        # Snapshot the archive's raw columns now (the file was just read
        # successfully by load_existing_csv), so the export-time drop compares
        # against the header this frame was actually loaded from — not a later
        # value of self._csv_path or a file replaced on disk.
        if stale:
            try:
                self._stale_raw_cols = set(pd.read_csv(self._csv_path, nrows=0).columns)
            except Exception:
                self._stale_raw_cols = set()  # unreadable → drop empty new cols
        else:
            self._stale_raw_cols = None
        self._dataframe = df
        self._flag_id_mismatches(df)
        return df

    def parse_and_build(self) -> pd.DataFrame:
        """Parse MEM files incrementally and return the combined DataFrame."""
        df = build_combined_dataframe_incremental(
            mem_dir=self._mem_paths,
            csp_dir=self._csp_paths or None,
            existing_csv=self._csv_path or None,
            cmap_dir=self._cmap_paths or None,
            mem_recursive=self._mem_recursive,
            csp_recursive=self._csp_recursive,
            cmap_recursive=self._cmap_recursive,
        )
        # A re-parse populates the current schema (SR/SD backfilled), so the
        # working frame is no longer schema-stale.
        self._schema_stale = False
        self._stale_raw_cols = None
        self._dataframe = df
        return df

    def set_dataframe(self, df: pd.DataFrame):
        self._dataframe = df
        self._flag_id_mismatches(df)

    def _flag_id_mismatches(self, df: pd.DataFrame | None) -> None:
        """Record files whose parsed participant contradicts their filename.

        Stored on the frame so whichever import page finished the load can
        surface it. A mislabelled file is otherwise invisible: it files itself
        under the participant its ``Name:`` header claims and simply goes
        missing from the intended one's report.
        """
        if df is None:
            return
        try:
            df.attrs["id_mismatches"] = detect_participant_id_mismatches(df)
        except Exception:
            # Never let a QC check block a load that otherwise succeeded.
            df.attrs["id_mismatches"] = []

    def get_id_mismatches(self) -> list:
        """Files whose parsed participant ID contradicts their filename."""
        df = self._dataframe
        if df is None:
            return []
        return list(getattr(df, "attrs", {}).get("id_mismatches") or [])

    def get_dataframe(self) -> pd.DataFrame | None:
        return self._dataframe

    # ── Participant / date queries ─────────────────────────

    _DATE_FMT = "%d/%m/%Y"

    # Graph types whose data is peripheral / visit-level, not cortex-specific.
    # Their availability must be judged against ALL of a visit's rows, not the
    # cortex-filtered subset: the peripheral .MEM rows (SR/SD/CMAP/MUNIX) carry
    # no Stimulated_cortex, so a single-cortex selection would otherwise grey
    # them out even though they exist and the render path (which ignores cortex)
    # can draw them.
    _CORTEX_INDEPENDENT_GRAPH_TYPES = frozenset({
        "visit_timeline", "visit_table", "cmap_table", "munix_table",
        "stimulus_response", "strength_duration_curve", "charge_duration_weiss",
    })

    # Graph types that describe the whole visit rather than one recording:
    # the visit's date list and the nerve-conduction tables read the same no
    # matter which muscle the user is looking at, so they are rendered once
    # instead of once per selected target. SR/SD are deliberately absent —
    # peripheral recordings ARE per-muscle (an APB stimulus-response curve is
    # not a TA one), and since parsing "S/R sites:" gives those rows a target
    # they now sit on the matching muscle's row.
    _TARGET_INDEPENDENT_GRAPH_TYPES = frozenset({
        "visit_timeline", "visit_table", "cmap_table", "munix_table",
    })

    # Graph types that stay one figure per recorded *side* instead of being
    # grouped per muscle. The cortical protocols run on both hemispheres are
    # the same test on two sides, so they overlay; a peripheral recruitment or
    # strength-duration curve from the left APB is a separate recording from
    # the right APB's, with no hemisphere to label the traces by.
    _PER_SIDE_GRAPH_TYPES = frozenset({
        "stimulus_response", "strength_duration_curve", "charge_duration_weiss",
    })

    def _filter_by_study(self, df: pd.DataFrame, study_filter: str | None) -> pd.DataFrame:
        """Apply a study filter to the DataFrame if provided."""
        if study_filter and "Study" in df.columns:
            df = df[df["Study"].str.upper() == study_filter.upper()]
        return df

    def get_unique_studies(self) -> list[str]:
        """Return sorted unique study names from the DataFrame."""
        df = self._dataframe
        if df is None or "Study" not in df.columns:
            return []
        studies = df["Study"].dropna().unique()
        return sorted(str(s) for s in studies)

    def get_unique_ids(
        self,
        date_filter: datetime | None = None,
        study_filter: str | None = None,
    ) -> list[int]:
        """Return sorted unique participant IDs, optionally filtered by date and/or study."""
        df = self._dataframe
        if df is None or "ID" not in df.columns:
            return []
        df = self._filter_by_study(df, study_filter)
        if date_filter is not None:
            date_str = date_filter.strftime(self._DATE_FMT)
            df = df[df["Date"] == date_str]
        ids = pd.to_numeric(df["ID"], errors="coerce").dropna().unique()
        return sorted(int(i) for i in ids)

    def get_visit_dates(
        self,
        id_filter: int | None = None,
        study_filter: str | None = None,
    ) -> list[datetime]:
        """Return sorted unique visit dates, optionally filtered by ID and/or study."""
        df = self._dataframe
        if df is None or "Date" not in df.columns:
            return []
        df = self._filter_by_study(df, study_filter)
        if id_filter is not None:
            df = df[pd.to_numeric(df["ID"], errors="coerce") == id_filter]
        raw = df["Date"].dropna().unique()
        dates = []
        for d in raw:
            try:
                dates.append(datetime.strptime(str(d), self._DATE_FMT))
            except ValueError:
                continue
        return sorted(dates)

    def get_most_recent_visit(
        self, study_filter: str | None = None,
    ) -> tuple[int | None, datetime | None]:
        """Return the (ID, date) pair for the most recent visit in the DataFrame."""
        dates = self.get_visit_dates(study_filter=study_filter)
        if not dates:
            return None, None
        latest = max(dates)
        ids = self.get_unique_ids(date_filter=latest, study_filter=study_filter)
        return (ids[0] if ids else None, latest)

    def set_selected_participant(self, participant_id: int, visit_date: datetime):
        """Store the user's participant/date selection for downstream use."""
        self._selected_id = participant_id
        self._selected_date = visit_date

    def get_selected_participant(self) -> tuple[int | None, datetime | None]:
        return getattr(self, "_selected_id", None), getattr(self, "_selected_date", None)

    def get_export_suffix(self) -> str:
        """Return '_{Study}_ID{pid}_{YYYYMMDD}' suffix for the selected participant."""
        pid, date = self.get_selected_participant()
        if pid is None or date is None:
            return ""
        date_str = date.strftime("%Y%m%d")

        # Look up study from the dataframe. Keyed on the visit date as well
        # as the number: participant numbers repeat across studies.
        study = participant_study(
            self._dataframe, pid, visit_date=date.strftime(self._DATE_FMT),
        ) or ""

        if study:
            return f"_{study}_ID{pid}_{date_str}"
        return f"_ID{pid}_{date_str}"

    # -- Naming an export the user did not name --------------------------

    def _selected_study(self) -> str | None:
        """The selected participant's study, disambiguated by their visit date.

        Participant numbers repeat across studies, so the date is what tells
        SNBR-003 from NIALS-003 (see processing.cohort_filters).
        """
        pid, date = self.get_selected_participant()
        if pid is None:
            return None
        return participant_study(
            self._dataframe, pid,
            visit_date=date.strftime(self._DATE_FMT) if date is not None else None,
        )

    def default_export_filename(self, kind: str) -> str:
        """The filename to use when the user left the name box empty.

        ``"csv"`` names the dataframe by export date; ``"pdf"`` names the report
        after the participant. See :mod:`reports.export_naming`.
        """
        if kind == "csv":
            return f"{default_dataframe_stem()}.csv"
        pid, _date = self.get_selected_participant()
        return f"{default_report_stem(self._selected_study(), pid)}.pdf"

    def default_graph_filename(self, graph_label: str) -> str:
        """The filename to offer when saving one figure as a PNG."""
        pid, date = self.get_selected_participant()
        stem = default_graph_stem(
            self._selected_study(), pid, graph_label,
            date.strftime(self._DATE_FMT) if date is not None else None,
        )
        return f"{stem}.png"

    def default_export_folder(self, kind: str) -> str:
        """Where an unnamed export goes.

        The folder of that export type's saved default, since it is where the
        user's exports already live. Falling back to the archive CSV's folder
        keeps the outputs beside the data they came from; Documents is the last
        resort, never the install directory, which may not be writable.
        """
        saved = self.get_default_export_paths().get(kind, "")
        if saved:
            candidate = Path(saved)
            return str(candidate if candidate.is_dir() else candidate.parent)
        if self._csv_path:
            return str(Path(self._csv_path).parent)
        documents = Path.home() / "Documents"
        return str(documents if documents.is_dir() else Path.home())

    def resolve_export_path(self, kind: str, typed_path: str = "") -> str:
        """Return the file to write for one export.

        A name the user typed keeps today's behaviour exactly — including the
        ``_<Study>_ID<n>_<date>`` stamp. An empty box, or a box holding only a
        folder, is filled in from :mod:`reports.export_naming` and made unique,
        so re-exporting never overwrites an earlier auto-named file.
        """
        typed = (typed_path or "").strip()
        if typed:
            candidate = Path(typed)
            if candidate.is_dir() or typed.endswith(("/", "\\")):
                return str(unique_path(candidate / self.default_export_filename(kind)))
            return self.stamp_export_path(typed)
        folder = Path(self.default_export_folder(kind))
        return str(unique_path(folder / self.default_export_filename(kind)))

    def stamp_export_path(self, path: str) -> str:
        """Insert study, participant ID and date before the file extension.

        Example: 'report.pdf' → 'report_SNBR_ID42_20260315.pdf'
        If the suffix is already present, the path is returned unchanged.
        """
        suffix = self.get_export_suffix()
        if not suffix or not path:
            return path
        p = Path(path)
        if p.stem.endswith(suffix):
            return path
        return str(p.with_stem(p.stem + suffix))

    # ── Excluded tests (from averages & export) ───────────

    # Tests that can be excluded per participant. Waveform measures come from
    # the visualization config; CSP and RMT are appended explicitly.
    EXCLUDABLE_TEST_KEYS: list[str] = list(WAVEFORM_MEASURE_CONFIGS.keys()) + ["csp", "rmt"]

    @staticmethod
    def _coerce_id_list(value) -> set[int]:
        """Coerce a stored/loose list of IDs into a set of ints."""
        out: set[int] = set()
        if isinstance(value, (list, tuple, set)):
            for v in value:
                try:
                    out.add(int(v))
                except (ValueError, TypeError):
                    continue
        return out

    @classmethod
    def _coerce_excluded_map(cls, value) -> dict[int, set[str]]:
        """Coerce a stored {id: [test_key, ...]} mapping into {int: {str}}."""
        out: dict[int, set[str]] = {}
        if isinstance(value, dict):
            valid = set(cls.EXCLUDABLE_TEST_KEYS)
            for k, v in value.items():
                try:
                    pid = int(k)
                except (ValueError, TypeError):
                    continue
                if isinstance(v, (list, tuple, set)):
                    tests = {str(t) for t in v if str(t) in valid}
                    if tests:
                        out[pid] = tests
        return out

    @classmethod
    def _coerce_outlier_bounds(cls, value) -> dict[str, dict[str, float | None]]:
        """Coerce a stored {measure: {"lower":.., "upper":..}} mapping.

        Drops unknown measures and unparseable numbers; omits a measure entirely
        if neither bound is a finite number. A stored lower > upper is kept as
        given (the panel/consumer treats it as "no value passes", which is the
        honest reading of a contradictory range).
        """
        out: dict[str, dict[str, float | None]] = {}
        if not isinstance(value, dict):
            return out
        valid = set(cls.EXCLUDABLE_TEST_KEYS)
        for measure, bounds in value.items():
            key = str(measure)
            if key not in valid or not isinstance(bounds, dict):
                continue
            lower = cls._coerce_bound(bounds.get("lower"))
            upper = cls._coerce_bound(bounds.get("upper"))
            if lower is None and upper is None:
                continue
            out[key] = {"lower": lower, "upper": upper}
        return out

    @staticmethod
    def _coerce_bound(value) -> float | None:
        """Coerce a single bound to a finite float, or None if unset/invalid."""
        if value is None or value == "":
            return None
        try:
            num = float(value)
        except (ValueError, TypeError):
            return None
        return num if np.isfinite(num) else None

    @classmethod
    def _test_label(cls, test_key: str) -> str:
        """Human-readable label for a test key (e.g. 't_sicf' -> 'T-SICF')."""
        if test_key in WAVEFORM_MEASURE_CONFIGS:
            return WAVEFORM_MEASURE_CONFIGS[test_key].get("label", test_key.upper())
        if test_key == "csp":
            return CSP_MEASURE_LABEL
        if test_key == "rmt":
            return "RMT"
        return str(test_key).upper()

    @staticmethod
    def _test_columns(test_key: str) -> list[str]:
        """DataFrame columns that hold the values for a given test."""
        if test_key in WAVEFORM_MEASURE_CONFIGS:
            cfg = WAVEFORM_MEASURE_CONFIGS[test_key]
            cols = [f"{cfg['prefix']}_{isi}" for isi in cfg.get("isis", [])]
            avg = cfg.get("avg_column")
            if avg:
                cols.append(avg)
            return cols
        if test_key == "csp":
            return list(CSP_PROFILE_COLUMNS)
        if test_key == "rmt":
            return list(RMT_COLUMNS)
        return []

    @staticmethod
    def _measure_value_columns(test_key: str) -> list[str]:
        """Sub-value columns whose mean is the measure's per-visit average.

        Unlike :meth:`_test_columns` this excludes the stored ``*_avg`` column
        (that column *is* the mean of these), so the outlier check aggregates
        the raw sub-values: each ISI for SICI/SICF, each %RMT level for CSP, and
        each RMT column.
        """
        if test_key in WAVEFORM_MEASURE_CONFIGS:
            cfg = WAVEFORM_MEASURE_CONFIGS[test_key]
            return [f"{cfg['prefix']}_{isi}" for isi in cfg.get("isis", [])]
        if test_key == "csp":
            return list(CSP_PROFILE_COLUMNS)
        if test_key == "rmt":
            return list(RMT_COLUMNS)
        return []

    @classmethod
    def _measure_aggregate_series(cls, df: pd.DataFrame, test_key: str) -> pd.Series:
        """Per-row average value for *test_key* — the number outlier bounds test.

        For SICI/SICF the parser already stores the across-ISI mean in the
        ``*_avg`` column, so that is used directly; CSP and RMT are averaged
        across their sub-columns on the fly. Missing sub-values are skipped (the
        parser computes the same skip-NaN mean); a row with no data is NaN and so
        never flagged as an outlier.
        """
        nan_series = pd.Series(np.nan, index=df.index, dtype="float64")
        if test_key in WAVEFORM_MEASURE_CONFIGS:
            avg_col = WAVEFORM_MEASURE_CONFIGS[test_key].get("avg_column")
            if avg_col and avg_col in df.columns:
                return pd.to_numeric(df[avg_col], errors="coerce")
        cols = [c for c in cls._measure_value_columns(test_key) if c in df.columns]
        if not cols:
            return nan_series
        numeric = df[cols].apply(pd.to_numeric, errors="coerce")
        return numeric.mean(axis=1, skipna=True)

    @classmethod
    def _test_keys_present(cls, rows: pd.DataFrame) -> list[str]:
        """Return the excludable test keys that have any data in *rows*."""
        present: list[str] = []
        for key in cls.EXCLUDABLE_TEST_KEYS:
            cols = cls._test_columns(key)
            if any(c in rows.columns and rows[c].notna().any() for c in cols):
                present.append(key)
        return present

    # ── Exclusion state (in-session) ──────────────────────

    def is_test_excluded(self, pid, test_key: str) -> bool:
        """True if *test_key* is excluded for participant *pid*."""
        try:
            pid_int = int(pid)
        except (ValueError, TypeError):
            return False
        return test_key in self._excluded_tests.get(pid_int, set())

    def set_test_excluded(self, pid, test_key: str, excluded: bool) -> None:
        """Add or remove one (participant, test) exclusion for this session."""
        try:
            pid_int = int(pid)
        except (ValueError, TypeError):
            return
        if test_key not in self.EXCLUDABLE_TEST_KEYS:
            return
        if excluded:
            self._excluded_tests.setdefault(pid_int, set()).add(test_key)
        elif pid_int in self._excluded_tests:
            self._excluded_tests[pid_int].discard(test_key)
            if not self._excluded_tests[pid_int]:
                del self._excluded_tests[pid_int]

    def is_participant_excluded(self, pid) -> bool:
        """True if the participant has *any* excluded test (for warnings)."""
        try:
            pid_int = int(pid)
        except (ValueError, TypeError):
            return False
        return bool(self._excluded_tests.get(pid_int))

    def get_excluded_test_count(self, pid) -> int:
        """Number of excluded tests for one participant."""
        try:
            pid_int = int(pid)
        except (ValueError, TypeError):
            return 0
        return len(self._excluded_tests.get(pid_int, set()))

    def get_excluded_test_labels(self, pid) -> list[str]:
        """Ordered labels of the excluded tests for one participant."""
        try:
            pid_int = int(pid)
        except (ValueError, TypeError):
            return []
        tests = self._excluded_tests.get(pid_int, set())
        return [self._test_label(k) for k in self.EXCLUDABLE_TEST_KEYS if k in tests]

    def get_excluded_entries(self) -> list[dict]:
        """Flat, ordered list of every exclusion for the bottom-of-page list.

        Each dict has: ``id``, ``test_key``, ``test_label``.
        """
        entries: list[dict] = []
        for pid in sorted(self._excluded_tests):
            for key in self.EXCLUDABLE_TEST_KEYS:
                if key in self._excluded_tests[pid]:
                    entries.append({
                        "id": pid,
                        "test_key": key,
                        "test_label": self._test_label(key),
                    })
        return entries

    def clear_excluded_tests(self) -> None:
        """Drop every exclusion from the in-session map (does not persist)."""
        self._excluded_tests.clear()

    def save_excluded_tests(self) -> None:
        """Persist the current exclusion map to saved defaults."""
        payload = {
            str(pid): sorted(tests)
            for pid, tests in self._excluded_tests.items() if tests
        }
        save_defaults(**{KEY_EXCLUDED_MEASUREMENTS: payload})

    def get_saved_excluded_map(self) -> dict[int, list[str]]:
        """Return the exclusion map currently persisted on disk."""
        saved = load_defaults()
        coerced = self._coerce_excluded_map(saved.get(KEY_EXCLUDED_MEASUREMENTS, {}))
        return {
            pid: sorted(tests) for pid, tests in sorted(coerced.items())
        }

    # ── Cohort-wide outlier bounds ────────────────────────

    def has_outlier_bounds(self) -> bool:
        """True if any measure has a lower or upper cutoff set this session."""
        return bool(self._outlier_bounds)

    def get_outlier_bound(self, measure: str) -> tuple[float | None, float | None]:
        """Return ``(lower, upper)`` for *measure* (``None`` where unset)."""
        bounds = self._outlier_bounds.get(measure) or {}
        return bounds.get("lower"), bounds.get("upper")

    def set_outlier_bound(self, measure: str, lower, upper) -> None:
        """Set (or clear) the cohort-wide cutoffs for one measure this session.

        *lower*/*upper* may be numbers, numeric strings, or ``None``/""; each is
        coerced independently. When both clear, the measure is dropped entirely.
        Unknown measure keys are ignored.
        """
        if measure not in self.EXCLUDABLE_TEST_KEYS:
            return
        low = self._coerce_bound(lower)
        up = self._coerce_bound(upper)
        if low is None and up is None:
            self._outlier_bounds.pop(measure, None)
        else:
            self._outlier_bounds[measure] = {"lower": low, "upper": up}

    def clear_outlier_bounds(self) -> None:
        """Drop every outlier bound from the in-session map (does not persist)."""
        self._outlier_bounds.clear()

    def save_outlier_bounds(self) -> None:
        """Persist the current outlier-bounds map to saved defaults."""
        payload = {
            measure: {"lower": b.get("lower"), "upper": b.get("upper")}
            for measure, b in self._outlier_bounds.items()
            if b.get("lower") is not None or b.get("upper") is not None
        }
        save_defaults(**{KEY_OUTLIER_BOUNDS: payload})

    def get_saved_outlier_bounds(self) -> dict[str, dict[str, float | None]]:
        """Return the outlier-bounds map currently persisted on disk."""
        saved = load_defaults()
        return self._coerce_outlier_bounds(saved.get(KEY_OUTLIER_BOUNDS, {}))

    def suggest_outlier_bounds(
        self, measure: str,
    ) -> tuple[float | None, float | None]:
        """Suggest ``(lower, upper)`` = mean ∓ 2·SD of *measure*'s per-visit
        averages across all loaded participants.

        Returns ``(None, None)`` when there is no data or fewer than two values
        (standard deviation is undefined). The sample standard deviation
        (``ddof=1``) is used, matching numpy/pandas defaults.
        """
        df = self._dataframe
        if df is None or measure not in self.EXCLUDABLE_TEST_KEYS:
            return None, None
        agg = self._measure_aggregate_series(df, measure).dropna()
        if len(agg) < 2:
            return None, None
        mean = float(agg.mean())
        std = float(agg.std(ddof=1))
        if not np.isfinite(mean) or not np.isfinite(std):
            return None, None
        return mean - 2.0 * std, mean + 2.0 * std

    def get_outlier_excluded_count(self, measure: str) -> int:
        """How many participant-visit rows *measure*'s bounds currently exclude.

        Counted over the whole loaded frame (no participant is exempted), for
        display next to the bounds fields.
        """
        df = self._dataframe
        if df is None or "ID" not in df.columns:
            return 0
        return int(self._outlier_row_mask(df, measure).sum())

    def get_outlier_bound_rows(self) -> list[dict]:
        """One row per excludable measure for the bounds table on the panel.

        Each dict has ``key``, ``label``, ``lower``, ``upper``, ``present``
        (the loaded data has any value for this measure) and ``excluded_count``.
        """
        df = self._dataframe
        present_keys = (
            set(self._test_keys_present(df))
            if df is not None and "ID" in df.columns else set()
        )
        rows: list[dict] = []
        for key in self.EXCLUDABLE_TEST_KEYS:
            lower, upper = self.get_outlier_bound(key)
            rows.append({
                "key": key,
                "label": self._test_label(key),
                "lower": lower,
                "upper": upper,
                "present": key in present_keys,
                "excluded_count": self.get_outlier_excluded_count(key),
            })
        return rows

    # ── Skipped workflow pages ────────────────────────────

    def get_skipped_pages(self) -> set[str]:
        """Return the set of page names hidden from the linear workflow flow."""
        return set(self._skipped_pages)

    def is_page_skipped(self, page_name: str) -> bool:
        """True if *page_name* is currently skipped in the Next/Back flow."""
        return page_name in self._skipped_pages

    def set_page_skipped(self, page_name: str, skipped: bool) -> None:
        """Skip or restore *page_name* and persist the choice for future runs.

        No-op for pages that are not in :attr:`SKIPPABLE_PAGES` so a required
        page can never be hidden from the flow.
        """
        if page_name not in self.SKIPPABLE_PAGES:
            return
        if skipped:
            self._skipped_pages.add(page_name)
        else:
            self._skipped_pages.discard(page_name)
        # A falsy (empty) list clears the key entirely; a populated list is
        # stored. Sorted for a stable, diff-friendly settings file.
        save_defaults(**{KEY_SKIPPED_PAGES: sorted(self._skipped_pages)})

    # ── Applying exclusions ───────────────────────────────

    def _measure_excluded_df(
        self, df: pd.DataFrame | None, *, exempt_id=None,
    ) -> pd.DataFrame | None:
        """Return a copy of *df* with excluded test columns blanked (NaN).

        Two exclusion mechanisms are applied together, per measure:

        * **Per-participant** — every (participant, test) the user ticked has
          that test's columns blanked in *all* of that participant's rows.
        * **Cohort-wide outlier bounds** — any participant-visit whose average
          for a measure falls outside that measure's [lower, upper] range has
          that measure's columns blanked in just that row.

        Blanking removes the row from the measure's cohort average (the plotting
        layer drops NaN rows) and blanks it in the exported CSV, while leaving
        other tests intact.

        *exempt_id* skips one participant entirely (for both mechanisms) — used
        when plotting so the selected participant's own traces still render
        (they are already dropped from cohort means by the plotting layer).
        """
        if df is None or "ID" not in df.columns:
            return df
        if not self._excluded_tests and not self._outlier_bounds:
            return df

        exempt = None
        if exempt_id is not None:
            try:
                exempt = int(exempt_id)
            except (ValueError, TypeError):
                exempt = None

        ids = pd.to_numeric(df["ID"], errors="coerce")
        # Participants who excluded a given measure by hand (built once).
        manual_by_measure: dict[str, set[int]] = {}
        for pid, tests in self._excluded_tests.items():
            for test_key in tests:
                manual_by_measure.setdefault(test_key, set()).add(pid)

        work = None
        for measure in self.EXCLUDABLE_TEST_KEYS:
            cols = [c for c in self._test_columns(measure) if c in df.columns]
            if not cols:
                continue

            manual_pids = manual_by_measure.get(measure)
            row_mask = (
                ids.isin(manual_pids) if manual_pids
                else pd.Series(False, index=df.index)
            )
            row_mask = row_mask | self._outlier_row_mask(df, measure)
            if exempt is not None:
                row_mask = row_mask & (ids != exempt)
            if not row_mask.any():
                continue

            if work is None:
                work = df.copy()
            work.loc[row_mask, cols] = np.nan
        return work if work is not None else df

    def _outlier_row_mask(self, df: pd.DataFrame, measure: str) -> pd.Series:
        """Boolean mask of rows whose *measure* average is out of bounds."""
        bounds = self._outlier_bounds.get(measure)
        if not bounds:
            return pd.Series(False, index=df.index)
        lower, upper = bounds.get("lower"), bounds.get("upper")
        if lower is None and upper is None:
            return pd.Series(False, index=df.index)
        agg = self._measure_aggregate_series(df, measure)
        mask = pd.Series(False, index=df.index)
        if lower is not None:
            mask = mask | (agg < lower)
        if upper is not None:
            mask = mask | (agg > upper)
        return mask & agg.notna()

    # -- Reference-cohort restriction (one study, one hemisphere) --------

    # Grouped plotting functions name the cohort legend bases
    # "patient_label_base"/"control_label_base"; the RMT comparison trio uses
    # the shorter "patient_label"/"control_label". Both need the study-aware
    # labels, so the two spellings are kept apart here.
    _GRAPH_TYPES_TAKE_COHORT_LABEL_BASE = frozenset({
        "grouped", "grouped_graph", "cohort", "group_comparison", "comparison",
        "rmt_grouped", "rmt_grouped_graph", "rmt_matched",
    })
    _GRAPH_TYPES_TAKE_COHORT_LABEL = frozenset({
        "rmt_comparison", "rmt_group_comparison", "rmt_overall",
    })
    # Profile graph types. Only the CSP profile draws cohort means; the
    # waveform profiles are participant-only and take no cohort label.
    _PROFILE_GRAPH_TYPES = frozenset({"profile", "measure_profile"})

    def _cohort_value_columns(self, norm_type: str, measure: str | None) -> list | None:
        """Return the DataFrame columns a graph actually plots, or ``None``.

        Handed to ``restrict_cohort_to_study`` so the study restriction is
        judged per measure: a study whose controls exist but recorded nothing
        for *this* measure must fall back, exactly like one with no controls at
        all. ``None`` leaves the check on row presence alone.
        """
        if norm_type.startswith("rmt"):
            return list(RMT_COLUMNS)
        if measure is None:
            return None
        key = str(measure).strip().lower().replace("-", "_")
        if key == "csp":
            return list(CSP_PROFILE_COLUMNS)
        config = WAVEFORM_MEASURE_CONFIGS.get(key)
        if config is None:
            return None
        return (
            [f"{config['prefix']}_{isi}" for isi in config["isis"]]
            + [config["avg_column"]]
        )

    def _cohort_restricted_df(
        self, df: pd.DataFrame | None, pid, *, visit_date=None, value_columns=None,
    ) -> tuple:
        """Narrow the reference cohort to one study and one hemisphere.

        Returns ``(dataframe, patient_label_base, control_label_base,
        scope_label)``. The selected participant is exempt from both
        restrictions, so their own traces still render in full — including both
        hemispheres overlaid when the visit was tested on each — while every
        cohort member contributes a single hemisphere and (where the archive
        allows it) only their own study.

        The hemisphere pass runs first so the study pass judges whether a cohort
        is usable on the rows that will really be plotted.
        """
        if df is None or df.empty:
            return df, None, None, None
        study = participant_study(df, pid, visit_date=visit_date)
        restricted = restrict_cohort_to_analysis_cortex(
            df, exempt_id=pid, exempt_study=study,
        )
        restricted, study_applied = restrict_cohort_to_study(
            restricted, study, exempt_id=pid, value_columns=value_columns,
        )
        patient_label, control_label = cohort_label_bases(study, study_applied)
        return (
            restricted,
            patient_label,
            control_label,
            cohort_scope_label(study, study_applied),
        )

    def get_analysis_cortex(self, participant_id=None) -> str | None:
        """Return the hemisphere a participant contributes to cohort averages.

        Read-only helper for panels and captions that want to state which side
        the averages came from. ``None`` when the participant has no hemisphere
        recorded at all.
        """
        df = self._dataframe
        if df is None:
            return None
        pid, date = self.get_selected_participant()
        if participant_id is not None:
            pid, date = participant_id, None
        if pid is None:
            return None
        return analysis_cortex_for(
            df, int(pid),
            visit_date=date.strftime(self._DATE_FMT) if date is not None else None,
        )

    def get_export_dataframe(self) -> pd.DataFrame | None:
        """Return the working DataFrame with excluded tests blanked.

        Used for CSV/dataframe export so excluded measurements are blank in the
        exported file. The in-memory DataFrame is left untouched.
        """
        if self._dataframe is None:
            return None
        df = self._measure_excluded_df(self._dataframe)
        # When the data came from a schema-stale archive that was NOT re-parsed
        # (the fast "archive as-is" path), the newer parser columns (e.g. SR/SD)
        # are present-but-empty. Exporting them would yield a CSV whose header
        # looks schema-current, so the staleness check would never fire again and
        # SR/SD would stay silently unavailable forever. Drop those empty,
        # newly-synthesised columns so the exported archive re-parses next load.
        if self._schema_stale and self._stale_raw_cols is not None:
            df = self._drop_synthesised_empty_columns(df)
        return df

    def _drop_synthesised_empty_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Drop columns that are entirely empty AND absent from the loaded
        archive's raw header — i.e. columns normalisation synthesised for a
        stale archive that carry no data.

        Uses the load-time snapshot ``self._stale_raw_cols`` (not a fresh read of
        ``self._csv_path``) so the decision reflects the header this frame was
        actually loaded from, even if the path changed or the file was replaced.
        """
        raw_cols = self._stale_raw_cols or set()
        to_drop = [
            c for c in df.columns
            if c not in raw_cols and df[c].isna().all()
        ]
        return df.drop(columns=to_drop) if to_drop else df

    # ── Participant / test queries (for the exclusion page) ──

    def get_participant_overviews(self) -> list[dict]:
        """Return one summary row per participant for the exclusion page.

        Each dict has: ``id``, ``study``, ``subject_type``, ``visit_count``,
        ``excluded_count`` (number of excluded tests).
        """
        df = self._dataframe
        if df is None or "ID" not in df.columns:
            return []
        ids = pd.to_numeric(df["ID"], errors="coerce")
        overviews: list[dict] = []
        for pid in sorted(int(i) for i in ids.dropna().unique()):
            rows = df[ids == pid]
            overviews.append({
                "id": pid,
                "study": self._first_str(rows, "Study"),
                "subject_type": self._first_str(rows, "Subject_type"),
                "visit_count": (
                    int(rows["Date"].dropna().nunique())
                    if "Date" in rows.columns else 0
                ),
                "excluded_count": self.get_excluded_test_count(pid),
            })
        return overviews

    def get_participant_tests(self, pid) -> list[dict]:
        """Return the excludable tests a participant has data for.

        Each dict has: ``key``, ``label``, ``excluded``.
        """
        df = self._dataframe
        if df is None or "ID" not in df.columns:
            return []
        try:
            pid_int = int(pid)
        except (ValueError, TypeError):
            return []
        ids = pd.to_numeric(df["ID"], errors="coerce")
        rows = df[ids == pid_int]
        if rows.empty:
            return []
        excluded = self._excluded_tests.get(pid_int, set())
        return [
            {"key": k, "label": self._test_label(k), "excluded": k in excluded}
            for k in self._test_keys_present(rows)
        ]

    def get_participant_measurements(self, pid) -> list[dict]:
        """Return read-only per-visit reference rows for one participant.

        Each dict has: ``date``, ``cortex``, ``subject_type``, ``tests`` (a
        list of measure labels that have data). Used to show the user what
        data a participant contributes.
        """
        df = self._dataframe
        if df is None or "ID" not in df.columns:
            return []
        try:
            pid_int = int(pid)
        except (ValueError, TypeError):
            return []
        ids = pd.to_numeric(df["ID"], errors="coerce")
        rows = df[ids == pid_int]
        if rows.empty:
            return []

        measurements: list[dict] = []
        group_cols = [
            c for c in ("Date", "Stimulated_cortex") if c in rows.columns
        ]
        if group_cols:
            for key, group in rows.groupby(group_cols, dropna=False):
                key_vals = key if isinstance(key, tuple) else (key,)
                info = dict(zip(group_cols, key_vals))
                measurements.append({
                    "date": str(info.get("Date", "") or "").strip(),
                    "cortex": str(info.get("Stimulated_cortex", "") or "").strip(),
                    "subject_type": self._first_str(group, "Subject_type"),
                    "tests": [self._test_label(k) for k in self._test_keys_present(group)],
                })
        else:
            measurements.append({
                "date": "", "cortex": "",
                "subject_type": self._first_str(rows, "Subject_type"),
                "tests": [self._test_label(k) for k in self._test_keys_present(rows)],
            })
        measurements.sort(key=lambda m: self._sort_key_date(m["date"]))
        return measurements

    @staticmethod
    def _first_str(rows: pd.DataFrame, column: str) -> str:
        """First non-null value of *column* as a stripped string ('' if none)."""
        if column not in rows.columns:
            return ""
        non_null = rows[column].dropna()
        if non_null.empty:
            return ""
        return str(non_null.iloc[0]).strip()

    def _sort_key_date(self, raw: str):
        """Sort key that orders parseable dates chronologically, blanks last."""
        try:
            return (0, datetime.strptime(raw, self._DATE_FMT))
        except (ValueError, TypeError):
            return (1, raw)

    # ── Cortex selection ──────────────────────────────────

    def get_cortex_options(
        self,
        pid: int,
        date: datetime,
        study_filter: str | None = None,
    ) -> list[str]:
        """Return unique Stimulated_cortex values for a (pid, date) pair."""
        df = self._dataframe
        if df is None or "Stimulated_cortex" not in df.columns:
            return []
        df = self._filter_by_study(df, study_filter)
        date_str = date.strftime(self._DATE_FMT)
        rows = df[
            (pd.to_numeric(df["ID"], errors="coerce") == pid)
            & (df["Date"] == date_str)
        ]
        vals = (
            rows["Stimulated_cortex"].astype("string").fillna("").str.strip()
            .replace("", pd.NA).dropna().unique()
        )
        return sorted(str(v) for v in vals)

    def set_selected_cortex(self, cortex: str | list[str] | None):
        """Store the user's cortex selection.

        A single string means one cortex; a list means 'Both'.
        None means no filtering (single cortex detected automatically).
        """
        self._selected_cortex = cortex

    def get_selected_cortex(self) -> str | list[str] | None:
        return getattr(self, "_selected_cortex", None)

    def _get_cortex_filtered_df(
        self, cortex_value: str | None = None, df: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Return *df* (or the main DataFrame) filtered to a cortex value.

        If *cortex_value* is None, returns the frame unfiltered.
        """
        if df is None:
            df = self._dataframe
        if df is None:
            raise ValueError("No DataFrame available.")
        if cortex_value is None or "Stimulated_cortex" not in df.columns:
            return df
        return df[
            df["Stimulated_cortex"].astype("string").fillna("").str.strip() == cortex_value
        ]

    # ── Recording-target selection ────────────────────────

    def get_target_options(
        self,
        pid: int,
        date: datetime,
        study_filter: str | None = None,
    ) -> list[str]:
        """Return the recording-target labels for one participant-visit.

        e.g. ``["Right FDI", "Right TA"]`` for a visit that recorded the same
        measures from a hand and a leg muscle.  Returns ``[]`` when the frame
        carries no muscle data at all — an archive that predates recording
        targets — so callers can fall back to the cortex selector.
        """
        df = self._dataframe
        if df is None or MUSCLE_COLUMN not in df.columns:
            return []
        df = self._filter_by_study(df, study_filter)
        date_str = date.strftime(self._DATE_FMT)
        rows = df[
            (pd.to_numeric(df["ID"], errors="coerce") == pid)
            & (df["Date"] == date_str)
        ]
        if rows.empty:
            return []
        # Rows with no muscle (a visit-level recording that could not be
        # attributed) are not selectable targets — they stay visible under
        # every target instead, see restrict_participant_to_target.
        return target_labels_in(rows)

    def set_selected_targets(self, targets: list[str] | None):
        """Store the user's recording-target selection (a list of labels)."""
        self._selected_targets = [str(t) for t in targets] if targets else []

    def get_selected_targets(self) -> list[str]:
        return list(getattr(self, "_selected_targets", []))

    def _get_target_filtered_df(
        self, target: str | None = None, df: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Return *df* with the selected participant restricted to one target.

        Only the **selected participant's** rows are filtered.  Cohort
        reference groups stay pooled across muscles by design, so every other
        participant's rows pass through untouched — a right-TA trace is still
        drawn against the whole reference cohort, not a TA-only subset.

        The participant's own rows that carry no target at all are kept too:
        they hold visit-level data (CMAP/MUNIX tables) that belongs to the
        visit rather than to one muscle.
        """
        if df is None:
            df = self._dataframe
        if df is None:
            raise ValueError("No DataFrame available.")
        pid, _date = self.get_selected_participant()
        return restrict_participant_to_target(df, pid, target)

    def _get_muscle_filtered_df(
        self, muscle: str | None = None, df: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Return *df* with the selected participant restricted to one muscle.

        Both recorded sides are kept, so a visit tested on each hemisphere
        overlays its two traces on one figure instead of splitting into two.
        """
        if df is None:
            df = self._dataframe
        if df is None:
            raise ValueError("No DataFrame available.")
        pid, _date = self.get_selected_participant()
        return restrict_participant_to_muscle(df, pid, muscle)

    def _participant_cortices(
        self, pid: int, date, df: pd.DataFrame | None = None,
    ) -> list[str]:
        """Return the hemispheres one participant-visit was stimulated on.

        Sorted and de-duplicated, so ``["L", "R"]`` means there are two traces
        to overlay and a single-element list means there is nothing to split.
        """
        if df is None:
            df = self._dataframe
        if df is None or "Stimulated_cortex" not in df.columns or date is None:
            return []
        rows = df[
            (pd.to_numeric(df["ID"], errors="coerce") == pid)
            & (df["Date"] == date.strftime(self._DATE_FMT))
        ]
        values = (
            rows["Stimulated_cortex"].astype("string")
            .fillna("").str.strip().replace("", pd.NA).dropna().unique()
        )
        return sorted(str(v) for v in values)

    def _target_muscles(self, pid: int, date) -> dict:
        """Map each of a visit's target labels to the muscle it recorded.

        Built from the rows rather than by parsing the labels back apart: the
        muscle is free text in the .MEM header, so an unrecognised value is
        kept verbatim and could not be split off a label reliably.
        """
        df = self._dataframe
        if df is None or MUSCLE_COLUMN not in df.columns or date is None:
            return {}
        rows = df[
            (pd.to_numeric(df["ID"], errors="coerce") == pid)
            & (df["Date"] == date.strftime(self._DATE_FMT))
        ]
        mapping: dict = {}
        for _, row in rows.iterrows():
            muscle, side = target_key(row[MUSCLE_COLUMN], row.get(SIDE_COLUMN))
            if not muscle:
                continue
            mapping[target_label(muscle, side)] = muscle
        return mapping

    def _group_targets_by_muscle(self, targets: list[str]) -> list:
        """Group selected target labels by muscle, keeping selection order.

        Returns ``[(group_label, [target_label, ...]), ...]``. A muscle recorded
        from both sides yields one group of two targets — the pair that gets
        overlaid — and its group label drops the side (``"FDI"``) because the
        figure shows both. Labels whose muscle cannot be resolved fall back to
        a group of their own, which reproduces the per-target behaviour.
        """
        pid, date = self.get_selected_participant()
        muscles = self._target_muscles(pid, date) if pid is not None else {}
        grouped: dict = {}
        order: list = []
        for label in targets:
            key = muscles.get(label, label)
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append(label)
        return [
            (key if len(grouped[key]) > 1 else grouped[key][0], grouped[key])
            for key in order
        ]

    def _target_scoped_dataframe(self) -> pd.DataFrame:
        """The working DataFrame, narrowed to the single selected target.

        The specially-built figures (SR/SD curves, CMAP/MUNIX tables) read
        their rows straight from the frame instead of going through
        ``plot_mem_graph``, so the target filter has to be applied for them
        here rather than via a ``data_df`` keyword.
        """
        df = self._dataframe
        if df is None:
            raise ValueError("No DataFrame available.")
        targets = self.get_selected_targets()
        if len(targets) == 1:
            return self._get_target_filtered_df(targets[0], df=df)
        return df

    def _target_suffix(self) -> str:
        """The ``" — Right FDI"`` suffix for figure titles, or ``""``.

        Empty whenever the visit has only one recording target: with nothing to
        disambiguate, the muscle belongs on the report's title page, not on
        every plot.  When both sides of one muscle are overlaid on the figure
        the suffix names the muscle alone (``"FDI"``), since the sides are
        already told apart by the plot's stimulated-cortex legend.
        """
        targets = self.get_selected_targets()
        pid, date = self.get_selected_participant()
        if not targets or pid is None or date is None:
            return ""
        if len(self.get_target_options(pid, date)) < 2:
            return ""
        if len(targets) == 1:
            return targets[0]
        groups = self._group_targets_by_muscle(targets)
        return groups[0][0] if len(groups) == 1 else ""

    # ── CMAP figure ───────────────────────────────────────

    def _build_cmap_figure_for_selected(self, pid: int, date) -> tuple:
        """Build a CMAP table figure for the selected participant/visit.

        Returns a ``(Figure, None, dict)`` tuple so it slots into the same
        plumbing as ``plot_mem_graph`` results.
        """
        from reports.report_builder import (
            _build_cmap_table_figure,
            _extract_cmap_rows_for_visit,
        )
        from processing.visualizer import format_participant_label

        df = self._target_scoped_dataframe()

        date_str = date.strftime(self._DATE_FMT)
        p_rows = df[pd.to_numeric(df["ID"], errors="coerce") == pid]
        cmap_rows = _extract_cmap_rows_for_visit(p_rows, date_str)
        if not cmap_rows:
            raise ValueError("No CMAP data for this visit.")

        plabel = format_participant_label(pid)
        fig = _build_cmap_table_figure(
            plabel, cmap_rows, date_str, self._target_suffix() or None,
        )
        return fig, None, {"cmap_row_count": len(cmap_rows)}

    def _build_munix_figure_for_selected(self, pid: int, date) -> tuple:
        """Build a MUNIX table figure for the selected participant/visit."""
        from reports.report_builder import (
            _build_munix_table_figure,
            _extract_munix_rows_for_visit,
        )
        from processing.visualizer import format_participant_label

        df = self._target_scoped_dataframe()

        date_str = date.strftime(self._DATE_FMT)
        p_rows = df[pd.to_numeric(df["ID"], errors="coerce") == pid]
        munix_rows = _extract_munix_rows_for_visit(p_rows, date_str)
        if not munix_rows:
            raise ValueError("No MUNIX data for this visit.")

        plabel = format_participant_label(pid)
        fig = _build_munix_table_figure(
            plabel, munix_rows, date_str, self._target_suffix() or None,
        )
        return fig, None, {"munix_row_count": len(munix_rows)}

    # ── Peripheral (SR/SD) plot-data loading ──────────────

    def _get_mem_file_index(self) -> dict:
        """Return a memoized ``{filename: Path}`` index over the MEM folder(s).

        Rebuilt only when the configured paths / recursion change, so a
        peripheral (SR/SD) plot that falls back to reading its source file does
        not trigger a full directory re-scan on every click.
        """
        from parser.mem_parser import iter_mem_files

        key = (tuple(self._mem_paths), bool(self._mem_recursive))
        if self._mem_file_index is None or self._mem_index_key != key:
            self._mem_file_index = {
                p.name: p
                for p in iter_mem_files(self._mem_paths, recursive=self._mem_recursive)
            }
            self._mem_index_key = key
        return self._mem_file_index

    @staticmethod
    def _first_json_list(rows: pd.DataFrame, column: str) -> list[dict]:
        """Return the first non-empty JSON list stored in *column*, or ``[]``.

        Lets SR/SD plot data be rebuilt straight from the DataFrame/CSV — fast,
        and works from an archived CSV without the source .MEM present.
        """
        if column not in rows.columns:
            return []
        for raw in rows[column].tolist():
            if raw is None or (isinstance(raw, float) and pd.isna(raw)):
                continue
            text = str(raw).strip()
            if not text or text.lower() == "nan" or text == "[]":
                continue
            try:
                parsed = json.loads(text)
            except (ValueError, TypeError):
                continue
            if isinstance(parsed, list) and parsed:
                return [p for p in parsed if isinstance(p, dict)]
        return []

    def _source_file_names(self, rows: pd.DataFrame) -> list[str]:
        """Flatten a visit's (possibly coalesced) ``source_file`` cells to names."""
        names: list[str] = []
        for value in rows["source_file"].tolist():
            if value is None or (isinstance(value, float) and pd.isna(value)):
                continue
            names.extend(n.strip() for n in str(value).split(";") if n.strip())
        return names

    # ── Stimulus-Response figure ──────────────────────────

    def _load_sr_curve_for_rows(self, rows: pd.DataFrame) -> tuple[list[dict], float | None]:
        """Load the stimulus-response curve for a visit.

        Prefers the curve persisted in the DataFrame/CSV (``SR_curve``) so the
        plot renders quickly and works from an archived CSV alone. Falls back to
        re-parsing the source .MEM (older archives that predate the stored
        column). Returns ``([], max_cmap)`` when no curve is found.
        """
        max_cmap: float | None = None
        if SR_MAX_COLUMN in rows.columns:
            stored = pd.to_numeric(rows[SR_MAX_COLUMN], errors="coerce").dropna()
            if not stored.empty:
                max_cmap = float(stored.iloc[0])

        # 1) Stored curve column — no file access needed.
        curve = self._first_json_list(rows, SR_CURVE_COLUMN)
        if curve:
            return curve, max_cmap

        # 2) Fall back to re-reading the source .MEM (cached file index).
        from parser.sr_parser import parse_sr_file

        names = self._source_file_names(rows)
        if not names:
            return [], max_cmap
        file_index = self._get_mem_file_index()
        for name in names:
            path = file_index.get(name)
            if path is None:
                continue
            try:
                block = parse_sr_file(path)
            except OSError:
                continue
            if block.get("curve"):
                return block["curve"], (
                    max_cmap if max_cmap is not None else block.get("max_cmap_1ms")
                )
        return [], max_cmap

    def _build_sr_figure_for_selected(self, pid: int, date) -> tuple:
        """Build a stimulus-response scatter for the selected participant/visit.

        Returns a ``(Figure, None, dict)`` tuple so it slots into the same
        plumbing as ``plot_mem_graph`` results. The plot covers this
        participant only; the reference Max CMAP at 1 ms is annotated on top.
        """
        from reports.report_builder import _build_sr_figure
        from processing.visualizer import format_participant_label

        df = self._target_scoped_dataframe()

        date_str = date.strftime(self._DATE_FMT)
        rows = df[
            (pd.to_numeric(df["ID"], errors="coerce") == pid)
            & (df["Date"] == date_str)
        ]
        if rows.empty:
            raise ValueError("No stimulus-response data for this visit.")

        curve, max_cmap = self._load_sr_curve_for_rows(rows)
        if not curve:
            raise ValueError("No stimulus-response data for this visit.")

        # Prefer the DataFrame's stored reference amplitude; it is the value
        # persisted to CSV and matches what other views report.
        if SR_MAX_COLUMN in rows.columns:
            stored = pd.to_numeric(rows[SR_MAX_COLUMN], errors="coerce").dropna()
            if not stored.empty:
                max_cmap = float(stored.iloc[0])

        plabel = format_participant_label(pid)
        fig = _build_sr_figure(
            plabel, curve, max_cmap, date_str, self._target_suffix() or None,
        )
        return fig, None, {"sr_max_cmap_1ms": max_cmap, "sr_point_count": len(curve)}

    # ── Strength-duration figures ─────────────────────────

    def _load_sd_points_for_rows(
        self, rows: pd.DataFrame,
    ) -> tuple[list[dict], float | None, float | None]:
        """Load the charge-duration points for a visit.

        Prefers the points persisted in the DataFrame/CSV (``SD_points``) so the
        plots render quickly and work from an archived CSV alone. Falls back to
        re-parsing the source .MEM (older archives that predate the stored
        column). Returns ``([], None, None)`` when no points are found. The
        derived scalars are best-effort here; callers prefer the stored
        ``Rheobase_mA`` / ``Tau_SD_ms`` columns.
        """
        # 1) Stored points column — no file access needed.
        points = self._first_json_list(rows, SD_POINTS_COLUMN)
        if points:
            return points, None, None

        # 2) Fall back to re-reading the source .MEM (cached file index).
        from parser.strength_duration_parser import parse_strength_duration_file

        names = self._source_file_names(rows)
        if not names:
            return [], None, None
        file_index = self._get_mem_file_index()
        for name in names:
            path = file_index.get(name)
            if path is None:
                continue
            try:
                block = parse_strength_duration_file(path)
            except OSError:
                continue
            if block.get("points"):
                return (
                    block["points"],
                    block.get("rheobase_mA"),
                    block.get("tau_sd_ms"),
                )
        return [], None, None

    def _sd_context_for_selected(self, pid: int, date):
        """Shared setup for the two strength-duration figures.

        Returns ``(participant_label, date_str, points, rheobase, tau)`` and
        raises ``ValueError`` when the visit has no charge-duration data. The
        derived scalars prefer the DataFrame's stored values (what CSV holds),
        falling back to the values re-parsed from the source file.
        """
        from processing.visualizer import format_participant_label

        df = self._target_scoped_dataframe()

        date_str = date.strftime(self._DATE_FMT)
        rows = df[
            (pd.to_numeric(df["ID"], errors="coerce") == pid)
            & (df["Date"] == date_str)
        ]
        if rows.empty:
            raise ValueError("No strength-duration data for this visit.")

        points, rheobase, tau = self._load_sd_points_for_rows(rows)
        if not points:
            raise ValueError("No strength-duration data for this visit.")

        # Prefer the DataFrame's stored scalars; they are the values persisted
        # to CSV and match what other views report.
        if SD_RHEOBASE_COLUMN in rows.columns:
            stored = pd.to_numeric(rows[SD_RHEOBASE_COLUMN], errors="coerce").dropna()
            if not stored.empty:
                rheobase = float(stored.iloc[0])
        if SD_TAU_COLUMN in rows.columns:
            stored = pd.to_numeric(rows[SD_TAU_COLUMN], errors="coerce").dropna()
            if not stored.empty:
                tau = float(stored.iloc[0])

        return format_participant_label(pid), date_str, points, rheobase, tau

    def _build_strength_duration_curve_for_selected(self, pid: int, date) -> tuple:
        """Build the strength-duration curve for the selected participant/visit.

        Returns a ``(Figure, None, dict)`` tuple so it slots into the same
        plumbing as ``plot_mem_graph`` results. Participant-only; the fitted
        hyperbola uses the QtracP-derived rheobase and tau.
        """
        from reports.report_builder import _build_strength_duration_curve_figure

        plabel, date_str, points, rheobase, tau = self._sd_context_for_selected(pid, date)
        fig = _build_strength_duration_curve_figure(
            plabel, points, rheobase, tau, date_str, self._target_suffix() or None,
        )
        return fig, None, {
            "rheobase_mA": rheobase,
            "tau_sd_ms": tau,
            "sd_point_count": len(points),
        }

    def _build_charge_duration_weiss_for_selected(self, pid: int, date) -> tuple:
        """Build the charge-duration (Weiss) plot for the selected participant/visit.

        Returns a ``(Figure, None, dict)`` tuple. The straight line uses the
        derived rheobase (slope) and tau (x-intercept = -tau); the fit R^2 is of
        the measured charge points about that line.
        """
        from reports.report_builder import _build_charge_duration_figure
        from parser.strength_duration_parser import charge_duration_r_squared

        plabel, date_str, points, rheobase, tau = self._sd_context_for_selected(pid, date)
        r2 = charge_duration_r_squared(points, rheobase, tau)
        fig = _build_charge_duration_figure(
            plabel, points, rheobase, tau, r2, date_str, self._target_suffix() or None,
        )
        return fig, None, {
            "rheobase_mA": rheobase,
            "tau_sd_ms": tau,
            "r_squared": r2,
            "sd_point_count": len(points),
        }

    # ── Header figure ─────────────────────────────────────

    def build_header_figure(self):
        """Build a standalone header page figure for the selected participant."""
        pid, date = self.get_selected_participant()
        if pid is None or date is None:
            raise ValueError("No participant/date selected.")
        df = self._dataframe
        if df is None:
            raise ValueError("No DataFrame available.")

        date_str = date.strftime(self._DATE_FMT)
        rows = df[
            (pd.to_numeric(df["ID"], errors="coerce") == pid)
            & (df["Date"] == date_str)
        ]
        if rows.empty:
            rows = df[pd.to_numeric(df["ID"], errors="coerce") == pid]

        cortex = self.get_selected_cortex()
        if isinstance(cortex, str) and "Stimulated_cortex" in rows.columns:
            rows = rows[
                rows["Stimulated_cortex"].astype("string").fillna("").str.strip() == cortex
            ]

        return build_header_only_figure(rows)

    # ── Visualization ─────────────────────────────────────

    def _rows_for_selected_visit(
        self, apply_cortex: bool = True, target: str | None = None,
    ) -> pd.DataFrame | None:
        """Return the DataFrame rows for the currently selected (pid, date).

        Does the filter **once** so callers that need to check many
        graph-availability conditions don't re-scan the DataFrame per query.
        Returns ``None`` when no participant/date is selected. When
        *apply_cortex* is ``False`` the single-cortex filter is skipped — used
        for peripheral / visit-level graphs whose data carries no cortex.

        *target* restricts the rows to one recording target; pass ``None`` to
        keep every target of the visit.
        """
        pid, date = self.get_selected_participant()
        df = self._dataframe
        if df is None or pid is None or date is None:
            return None

        if target:
            df = self._get_target_filtered_df(target, df=df)

        cortex = self.get_selected_cortex()
        if apply_cortex and isinstance(cortex, str):
            df = self._get_cortex_filtered_df(cortex, df=df)

        date_str = date.strftime(self._DATE_FMT)
        return df[
            (pd.to_numeric(df["ID"], errors="coerce") == pid)
            & (df["Date"] == date_str)
        ]

    @staticmethod
    def _rows_have_graph_data(
        rows: pd.DataFrame, graph_type: str, measure: str | None,
    ) -> bool:
        """Given the already-filtered visit rows, decide if *graph_type* has data.

        Pure function; no DataFrame filtering.
        """
        if rows is None or rows.empty:
            return False

        if graph_type in ("visit_timeline", "visit_table"):
            return True

        if graph_type in ("cmap_table", "munix_table"):
            col = "CMAP_table" if graph_type == "cmap_table" else "MUNIX_table"
            if col not in rows.columns:
                return False
            vals = rows[col].dropna().astype(str).str.strip()
            return any(v and v.lower() != "nan" and v != "[]" for v in vals)

        if graph_type == "stimulus_response":
            return SR_MAX_COLUMN in rows.columns and rows[SR_MAX_COLUMN].notna().any()

        if graph_type in ("strength_duration_curve", "charge_duration_weiss"):
            # Both derived scalars are needed to draw the fitted line/curve.
            return (
                SD_RHEOBASE_COLUMN in rows.columns
                and rows[SD_RHEOBASE_COLUMN].notna().any()
                and SD_TAU_COLUMN in rows.columns
                and rows[SD_TAU_COLUMN].notna().any()
            )

        if graph_type in ("rmt_over_time", "rmt_comparison", "rmt_grouped"):
            for col in RMT_COLUMNS:
                if col in rows.columns and rows[col].notna().any():
                    return True
            return False

        if measure == "csp":
            for col in CSP_PROFILE_COLUMNS:
                if col in rows.columns and rows[col].notna().any():
                    return True
            return False

        if measure and measure in WAVEFORM_MEASURE_CONFIGS:
            avg_col = WAVEFORM_MEASURE_CONFIGS[measure]["avg_column"]
            if avg_col in rows.columns and rows[avg_col].notna().any():
                return True
            return False

        return True

    def _participant_has_repeat_trajectory(self, measure: str | None) -> bool:
        """Whether the selected participant has >= 2 visits with a *measure* value.

        Used to gate the cohort-trajectory graphs, which are only meaningful for
        participants with repeated visits. Respects the current single-cortex
        selection (like the other cortex-specific waveform graphs) but scans the
        participant's whole visit history, not just the selected visit.
        """
        if measure is None or measure not in WAVEFORM_MEASURE_CONFIGS:
            return False
        pid, _date = self.get_selected_participant()
        df = self._dataframe
        if df is None or pid is None:
            return False
        cortex = self.get_selected_cortex()
        if isinstance(cortex, str):
            df = self._get_cortex_filtered_df(cortex)
        avg_col = WAVEFORM_MEASURE_CONFIGS[measure]["avg_column"]
        if avg_col not in df.columns:
            return False
        rows = df[pd.to_numeric(df["ID"], errors="coerce") == pid]
        rows = rows[rows[avg_col].notna()]
        if rows.empty:
            return False
        dates = rows["Date"].astype("string").fillna("").str.strip()
        return int(dates[dates != ""].nunique()) >= 2

    def has_data_for_graph(self, graph_type: str, measure: str | None) -> bool:
        """Fast check whether the selected participant has data for a graph type."""
        norm_type = str(graph_type).strip().lower().replace("-", "_").replace(" ", "_")
        if norm_type in self._TRAJECTORY_GRAPH_TYPES:
            return self._participant_has_repeat_trajectory(measure)
        apply_cortex = graph_type not in self._CORTEX_INDEPENDENT_GRAPH_TYPES
        if graph_type in self._CORTEX_INDEPENDENT_GRAPH_TYPES:
            targets: list[str | None] = [None]
        else:
            targets = list(self.get_selected_targets()) or [None]
        for target in targets:
            rows = self._rows_for_selected_visit(
                apply_cortex=apply_cortex, target=target,
            )
            if rows is not None and self._rows_have_graph_data(
                rows, graph_type, measure,
            ):
                return True
        return False

    def graph_availability_map(
        self, entries: list,
    ) -> dict[str, bool]:
        """Bulk availability check — one DataFrame filter, N pure-Python lookups.

        *entries* is an iterable of objects with ``.key``, ``.graph_type`` and
        ``.measure`` attributes (e.g. ``GraphEntry`` from the visualization
        panel). Returns a ``{key: bool}`` dict.

        Use this instead of calling ``has_data_for_graph`` in a loop — it
        eliminates the O(N × df_filter) cost when the visualization panel
        refreshes its ~90 checkboxes.

        Cortex-independent (peripheral / visit-level) graphs are checked
        against the unfiltered visit rows so a single-cortex selection never
        hides SR/SD/CMAP/MUNIX data, which lives on cortex-less rows.

        With several recording targets selected, a graph counts as available
        when **any** selected target can draw it: ticking both hands and a leg
        must not grey out a measure that only the hand recording carries.
        """
        targets = self.get_selected_targets()
        rows_all = self._rows_for_selected_visit(apply_cortex=False)
        if rows_all is None:
            return {e.key: False for e in entries}

        # One filtered view per selected target, computed once and reused
        # across every entry (the panel refreshes ~90 checkboxes at a time).
        per_target = [
            self._rows_for_selected_visit(target=t) for t in targets
        ] or [self._rows_for_selected_visit()]

        result: dict[str, bool] = {}
        for e in entries:
            norm_type = str(e.graph_type).strip().lower().replace("-", "_").replace(" ", "_")
            if norm_type in self._TRAJECTORY_GRAPH_TYPES:
                result[e.key] = self._participant_has_repeat_trajectory(e.measure)
            elif e.graph_type in self._CORTEX_INDEPENDENT_GRAPH_TYPES:
                result[e.key] = self._rows_have_graph_data(
                    rows_all, e.graph_type, e.measure,
                )
            else:
                result[e.key] = any(
                    self._rows_have_graph_data(rows, e.graph_type, e.measure)
                    for rows in per_target
                )
        return result

    # ── Title builder ────────────────────────────────────

    # Graph types whose builder takes an explicit ``group_by_cortex`` flag to
    # split one participant's trace per stimulated hemisphere.
    _GRAPH_TYPE_NEEDS_CORTEX_OVERLAY = {
        "over_time", "participant_over_time", "timeline", "longitudinal",
        "trajectory", "measure_trajectory", "cohort_trajectory",
        "visit_profiles", "participant_visit_profiles", "visit_profile_grid",
        "rmt_over_time", "participant_rmt_over_time",
    }

    # Cohort-trajectory graph types are only meaningful when the selected
    # participant has repeated visits, so their availability is judged
    # participant-wide (>= 2 visits with a value), not on the selected visit's
    # rows like the other waveform graphs.
    _TRAJECTORY_GRAPH_TYPES = frozenset({
        "trajectory", "measure_trajectory", "cohort_trajectory",
    })

    # The profile builders overlay one trace per hemisphere on their own, by
    # detecting several cortex values among the participant's rows. Passing
    # them a group_by_cortex flag raises TypeError, so they are kept out of
    # the set above and simply handed unfiltered rows.
    _CORTEX_OVERLAY_AUTODETECT_TYPES = frozenset({"profile", "measure_profile"})

    _GRAPH_TYPE_IS_GROUPED = {
        "grouped", "grouped_graph", "cohort", "group_comparison", "comparison",
        "rmt_grouped", "rmt_grouped_graph", "rmt_matched",
        "rmt_comparison", "rmt_group_comparison", "rmt_overall",
    }

    def _cortex_values_with_data(
        self, pid: int, date_str: str, measure: str | None, cortex_list: list[str],
    ) -> list[str]:
        """Return only the cortex values from *cortex_list* that have data."""
        df = self._dataframe
        if df is None or "Stimulated_cortex" not in df.columns:
            return cortex_list

        rows = df[
            (pd.to_numeric(df["ID"], errors="coerce") == pid)
            & (df["Date"] == date_str)
        ]
        if rows.empty:
            return cortex_list

        present = []
        for cv in cortex_list:
            cv_rows = rows[
                rows["Stimulated_cortex"].astype("string").fillna("").str.strip() == cv
            ]
            if cv_rows.empty:
                continue
            # For measure-specific graphs, check the measure column has data
            if measure and measure != "csp" and measure in WAVEFORM_MEASURE_CONFIGS:
                avg_col = WAVEFORM_MEASURE_CONFIGS[measure]["avg_column"]
                if avg_col in cv_rows.columns and cv_rows[avg_col].notna().any():
                    present.append(cv)
            elif measure == "csp":
                if any(c in cv_rows.columns and cv_rows[c].notna().any() for c in CSP_PROFILE_COLUMNS):
                    present.append(cv)
            else:
                # No specific measure (e.g., RMT) — check RMT columns
                has_any = False
                for col in RMT_COLUMNS:
                    if col in cv_rows.columns and cv_rows[col].notna().any():
                        has_any = True
                        break
                if has_any or not RMT_COLUMNS:
                    present.append(cv)
        return present if present else cortex_list

    def _build_graph_title(self, graph_type: str, measure: str | None) -> str | None:
        """Build a title that includes date and cortex info."""
        pid, date = self.get_selected_participant()
        if pid is None or date is None:
            return None

        plabel = format_participant_label(pid)
        date_str = date.strftime(self._DATE_FMT)
        cortex = self.get_selected_cortex()
        cortex_text = ""
        if isinstance(cortex, str):
            cortex_text = cortex
        elif isinstance(cortex, list):
            # Only include cortex values that actually have data for this test
            actual = self._cortex_values_with_data(pid, date_str, measure, cortex)
            cortex_text = " & ".join(actual) if len(actual) > 1 else (actual[0] if actual else "")

        norm_type = str(graph_type).strip().lower().replace("-", "_").replace(" ", "_")

        # Measure label
        mlabel = ""
        if measure and measure != "csp":
            try:
                mlabel = waveform_measure_config(measure)["label"]
            except (KeyError, ValueError):
                mlabel = str(measure).upper()
        elif measure == "csp":
            mlabel = CSP_MEASURE_LABEL

        # Build title based on graph type
        parts = [plabel]

        if norm_type in {"profile", "measure_profile"}:
            parts.append(date_str)
            if cortex_text:
                parts.append(cortex_text)
            if mlabel:
                parts.append(mlabel)
        elif norm_type in {"over_time", "participant_over_time", "timeline", "longitudinal"}:
            if mlabel:
                parts.append(f"Averaged {mlabel} over time")
            if cortex_text:
                parts.append(cortex_text)
        elif norm_type in {"trajectory", "measure_trajectory", "cohort_trajectory"}:
            if mlabel:
                parts.append(f"{mlabel} trajectory vs cohort")
            if cortex_text:
                parts.append(cortex_text)
        elif norm_type in {"visit_profiles", "participant_visit_profiles", "visit_profile_grid"}:
            if mlabel:
                parts.append(f"{mlabel} profile by visit")
            if cortex_text:
                parts.append(cortex_text)
        elif norm_type in {"rmt_over_time", "participant_rmt_over_time"}:
            parts.append("RMT thresholds over time")
            if cortex_text:
                parts.append(cortex_text)
        elif norm_type in {"visit_timeline", "participant_visit_timeline", "visit_dates"}:
            parts.append("Visit timeline")
        elif norm_type in {"visit_table", "visit_tests", "visit_summary", "visit_test_table"}:
            parts.append("Visit summary and tests present")
        else:
            # Grouped/comparison — include date but cortex is N/A (both sides used)
            parts.append(date_str)
            if mlabel:
                parts.append(mlabel)

        # Name the recording only when the visit has more than one: with a
        # single target the muscle is stated once on the report's title page
        # instead of being repeated on every plot.
        suffix = self._target_suffix()
        if suffix:
            parts.append(suffix)

        return " | ".join(parts)

    # ── Figure generation ─────────────────────────────────

    def _generate_figure_per_group(
        self, graph_type: str, measure: str | None, groups: list, *, match_by=None,
    ) -> tuple:
        """Render *graph_type* once per recording-target group.

        A group is normally one muscle, holding every side it was recorded
        from, so a visit tested on both hemispheres produces **one** figure per
        protocol per muscle with the two sides overlaid — not one figure per
        side. The peripheral graphs group per side instead (see
        ``_PER_SIDE_GRAPH_TYPES``), because a left-APB recruitment curve is a
        different recording from a right-APB one rather than the same protocol
        run on the other hemisphere.

        Implemented by re-entering :meth:`generate_figure` with one group
        selected, so every graph type is multiplied the same way without each
        individual figure builder having to know about targets. The recursion
        terminates because a single group never splits again.

        Groups with no data for this graph are skipped rather than raising —
        a visit that recorded T-SICI from the hand and only a stimulus-response
        curve from the leg should still show the hand's T-SICI.

        Returns ``(figures, axes, data)`` where *data* carries three parallel
        lists: ``figure_keys`` (the builder's own sub-key, e.g. ``"RMT50"``, so
        captions keep working), ``figure_targets`` (the group label), and
        ``figure_data`` (that figure's own plot data, so a caption quotes the
        values of the figure it sits under).
        """
        saved = self.get_selected_targets()
        figures: list = []
        axes: list = []
        keys: list = []
        target_labels: list = []
        per_figure: list = []
        try:
            for label, group_targets in groups:
                self.set_selected_targets(list(group_targets))
                try:
                    figs, axs, data = self.generate_figure(
                        graph_type, measure, match_by=match_by,
                    )
                except (ValueError, KeyError):
                    continue  # no data for this group — skip it
                if isinstance(figs, list):
                    sub_keys = (data or {}).get("figure_keys") or [None] * len(figs)
                    for i, fig in enumerate(figs):
                        figures.append(fig)
                        axes.append(axs[i] if isinstance(axs, list) and i < len(axs) else None)
                        keys.append(sub_keys[i] if i < len(sub_keys) else None)
                        target_labels.append(label)
                        per_figure.append(data)
                else:
                    figures.append(figs)
                    axes.append(axs)
                    keys.append(None)
                    target_labels.append(label)
                    per_figure.append(data)
        finally:
            self.set_selected_targets(saved)

        if not figures:
            raise ValueError("No data for the selected recording targets.")

        combined = {
            "figure_keys": keys,
            "figure_targets": target_labels,
            "figure_data": per_figure,
        }
        return figures, axes, combined

    def generate_figure(
        self, graph_type: str, measure: str | None, *, match_by=None,
    ) -> tuple:
        """Call plot_mem_graph and return the raw result tuple.

        Returns (Figure, Axes, dict) or (list[Figure], list[Axes], dict)
        depending on whether the graph type produces multiple figures.

        Handles cortex overlay (both sides overlaid with legend) and
        cortex highlight splitting for grouped graphs automatically.
        """
        pid, date = self.get_selected_participant()
        if pid is None or date is None:
            raise ValueError("No participant/date selected.")

        # Several recording targets selected — render the graph once per group.
        # Cortical graphs group by muscle, so a protocol run on both
        # hemispheres overlays its two sides on one figure; the peripheral
        # graphs stay one figure per side. Done before the dispatch below so
        # every graph type is multiplied the same way, including the
        # specially-built SR/SD and table figures.
        norm_type = str(graph_type).strip().lower()
        targets = self.get_selected_targets()
        group_muscle = None
        if len(targets) > 1 and norm_type not in self._TARGET_INDEPENDENT_GRAPH_TYPES:
            if norm_type in self._PER_SIDE_GRAPH_TYPES:
                groups = [(label, [label]) for label in targets]
            else:
                groups = self._group_targets_by_muscle(targets)
            if len(groups) > 1:
                return self._generate_figure_per_group(
                    graph_type, measure, groups, match_by=match_by,
                )
            # One group holding several sides of one muscle: keep them all and
            # let the plot overlay them, labelled by stimulated cortex.
            group_muscle, targets = groups[0][0], list(groups[0][1])

        # CMAP / MUNIX tables are simple participant-visit tables rendered
        # directly from the DataFrame — no cortex handling, no plot_mem_graph.
        if norm_type == "cmap_table":
            return self._build_cmap_figure_for_selected(pid, date)
        if norm_type == "munix_table":
            return self._build_munix_figure_for_selected(pid, date)
        if norm_type == "stimulus_response":
            return enlarge_result_figures(self._build_sr_figure_for_selected(pid, date))
        if norm_type == "strength_duration_curve":
            return enlarge_result_figures(
                self._build_strength_duration_curve_for_selected(pid, date)
            )
        if norm_type == "charge_duration_weiss":
            return enlarge_result_figures(
                self._build_charge_duration_weiss_for_selected(pid, date)
            )

        cortex = self.get_selected_cortex()
        norm_type = str(graph_type).strip().lower().replace("-", "_").replace(" ", "_")
        title = self._build_graph_title(graph_type, measure)

        # Blank excluded tests in the cohort data before plotting so those
        # measurements don't contribute to group averages. The selected
        # participant is exempted so their own traces still render even if some
        # of their tests are excluded (the plotting layer already removes the
        # highlight from the group means).
        base_df = self._measure_excluded_df(self._dataframe, exempt_id=pid)

        # Narrow the reference cohort to the participant's own study and to one
        # hemisphere per cohort member. The participant's own rows are exempt,
        # so a both-cortex visit still overlays both traces here.
        (
            base_df, patient_label_base, control_label_base, cohort_scope,
        ) = self._cohort_restricted_df(
            base_df, pid,
            visit_date=date.strftime(self._DATE_FMT),
            value_columns=self._cohort_value_columns(norm_type, measure),
        )

        kwargs: dict = dict(
            participant_id=pid,
            mem_date=date.strftime(self._DATE_FMT),
            show=False,
            title=title,
        )

        if match_by is not None:
            kwargs["match_by"] = match_by

        # Name the cohort the plot actually drew, which is not always the
        # requested study (see cohort_filters.restrict_cohort_to_study).
        if patient_label_base and control_label_base:
            if norm_type in self._GRAPH_TYPES_TAKE_COHORT_LABEL_BASE:
                kwargs["patient_label_base"] = patient_label_base
                kwargs["control_label_base"] = control_label_base
            elif norm_type in self._GRAPH_TYPES_TAKE_COHORT_LABEL:
                kwargs["patient_label"] = patient_label_base
                kwargs["control_label"] = control_label_base
            elif (
                norm_type in self._PROFILE_GRAPH_TYPES
                and str(measure).strip().lower() == CSP_MEASURE_KEY
            ):
                kwargs["patient_label_base"] = patient_label_base
                kwargs["control_label_base"] = control_label_base
            elif norm_type in self._TRAJECTORY_GRAPH_TYPES:
                # One cohort band (same subject type), so it is named by
                # scope rather than split into patient/control.
                kwargs["cohort_label_base"] = cohort_scope

        if isinstance(cortex, list) and len(cortex) > 1:
            # "Both" mode
            if norm_type in self._GRAPH_TYPE_NEEDS_CORTEX_OVERLAY:
                # Pass unfiltered data + group_by_cortex flag
                kwargs["data_df"] = base_df
                kwargs["group_by_cortex"] = True
            elif norm_type in self._GRAPH_TYPE_IS_GROUPED:
                # Pass unfiltered data + highlight_cortex_values
                kwargs["data_df"] = base_df
                kwargs["highlight_cortex_values"] = cortex
            else:
                # visit_timeline, visit_table, rmt_over_time — no cortex-specific handling
                kwargs["data_df"] = base_df
        elif isinstance(cortex, str):
            # Single cortex — filter data
            kwargs["data_df"] = self._get_cortex_filtered_df(cortex, df=base_df)
        else:
            kwargs["data_df"] = base_df

        # A single selected target narrows the participant's own rows to that
        # muscle/side. Applied after the cortex branches so it composes with
        # them; the reference cohort is left pooled either way.
        if len(targets) == 1:
            kwargs["data_df"] = self._get_target_filtered_df(
                targets[0], df=kwargs["data_df"],
            )
        elif len(targets) > 1 and group_muscle:
            # Both sides of one muscle: narrow to the muscle and let the two
            # hemispheres overlay on the same axes.
            kwargs["data_df"] = self._get_muscle_filtered_df(
                group_muscle, df=kwargs["data_df"],
            )
            overlay_cortices = self._participant_cortices(
                pid, date, df=kwargs["data_df"],
            )
            if len(overlay_cortices) > 1:
                if norm_type in self._GRAPH_TYPE_NEEDS_CORTEX_OVERLAY:
                    kwargs["group_by_cortex"] = True
                elif norm_type in self._GRAPH_TYPE_IS_GROUPED:
                    kwargs["highlight_cortex_values"] = overlay_cortices
                # The profile builders detect the split themselves; see
                # _CORTEX_OVERLAY_AUTODETECT_TYPES.

        result = (
            plot_mem_graph(graph_type=graph_type, measure=measure, **kwargs)
            if measure is not None
            else plot_mem_graph(graph_type=graph_type, **kwargs)
        )
        # Enlarge the axis text on real plots. The "visit_table" graph is a
        # matplotlib table (no axes), so it keeps its hand-tuned layout.
        if norm_type != "visit_table":
            enlarge_result_figures(result)
        return result

    def set_selected_graphs(self, keys: list[str]):
        """Store the graph keys the user checked for report generation."""
        self._selected_graph_keys = keys

    def get_selected_graphs(self) -> list[str]:
        return getattr(self, "_selected_graph_keys", [])

    def set_report_figures(self, figures: list):
        """Store matplotlib Figure objects for PDF export."""
        self._report_figures = figures

    def get_report_figures(self) -> list:
        return getattr(self, "_report_figures", [])

    # ── Quick Start ─────────────────────────────────────────

    def set_quick_start_message(self, msg: str) -> None:
        self._quick_start_message = msg

    def consume_quick_start_message(self) -> str:
        """Return the redirect message and clear it."""
        msg = self._quick_start_message
        self._quick_start_message = ""
        return msg

    def check_quick_start_readiness(self) -> str | None:
        """Check saved defaults for Quick Start.

        Returns the page name to redirect to if a required default is
        missing, or ``None`` if everything is ready.  Sets the redirect
        message before returning.
        """
        saved = load_defaults()

        if not saved.get(KEY_MEM_DIR, ""):
            self._quick_start_message = (
                "No default MEM directory saved. "
                "Please set your paths and save them as default."
            )
            return "file_panel"

        csv_file = saved.get(KEY_CSV_FILE, "")
        if not csv_file:
            self._quick_start_message = (
                "No default CSV file saved. "
                "Quick Start requires a saved CSV path."
            )
            return "file_panel"

        if not Path(csv_file).is_file():
            self._quick_start_message = (
                f"Saved CSV file not found:\n{csv_file}"
            )
            return "file_panel"

        export_csv = saved.get(KEY_EXPORT_CSV, "")
        export_pdf = saved.get(KEY_EXPORT_PDF, "")
        if not export_csv and not export_pdf:
            self._quick_start_message = (
                "No default export paths saved. "
                "Please set export paths and save them as default."
            )
            return "export"

        rc_data = saved.get(KEY_REDCAP_DATA_DIR, "")
        rc_dict = saved.get(KEY_REDCAP_DICT_DIR, "")
        rc_tpl = saved.get(KEY_REDCAP_TEMPLATE_DIR, "")
        rc_out = saved.get(KEY_REDCAP_EXPORT_DIR, "")
        if not (rc_data and rc_dict and rc_tpl and rc_out):
            self._quick_start_message = (
                "No default REDCap directories saved. "
                "Please set REDCap paths and save them as default."
            )
            return "redcap"

        return None

    # ── Backup & Sync ─────────────────────────────────────

    def get_sync_defaults(self) -> list[dict]:
        """Return saved sync pairs (list of {source, destination} dicts)."""
        saved = load_defaults()
        pairs = saved.get(KEY_SYNC_PAIRS, [])
        if not isinstance(pairs, list):
            return []
        return pairs

    def save_sync_defaults(self, pairs: list[dict]) -> None:
        """Persist sync pairs to user settings."""
        save_defaults(**{KEY_SYNC_PAIRS: pairs})

    def get_sync_log_path(self) -> str:
        """Return the default log file path inside back_up_sync/."""
        from pathlib import Path
        return str(
            Path(__file__).resolve().parent.parent / "back_up_sync" / "sync_log.txt"
        )

    # ── REDCap Export ─────────────────────────────────────

    def get_redcap_defaults(self) -> dict[str, str]:
        """Return saved REDCap directory paths."""
        saved = load_defaults()
        return {
            "data_dir": saved.get(KEY_REDCAP_DATA_DIR, ""),
            "dict_dir": saved.get(KEY_REDCAP_DICT_DIR, ""),
            "template_dir": saved.get(KEY_REDCAP_TEMPLATE_DIR, ""),
            "export_dir": saved.get(KEY_REDCAP_EXPORT_DIR, ""),
            "xlsx_dir": saved.get(KEY_REDCAP_XLSX_DIR, ""),
        }

    def save_redcap_defaults(self, **kwargs: str) -> None:
        """Persist REDCap directory paths to user settings."""
        key_map = {
            "data_dir": KEY_REDCAP_DATA_DIR,
            "dict_dir": KEY_REDCAP_DICT_DIR,
            "template_dir": KEY_REDCAP_TEMPLATE_DIR,
            "export_dir": KEY_REDCAP_EXPORT_DIR,
            "xlsx_dir": KEY_REDCAP_XLSX_DIR,
        }
        to_save = {
            key_map[k]: v for k, v in kwargs.items() if k in key_map
        }
        if to_save:
            save_defaults(**to_save)

    def run_redcap_export(
        self,
        data_dir: str,
        dict_dir: str,
        template_dir: str,
        export_dir: str,
        *,
        include_new_ids: bool = False,
        xlsx_report_dir: str | None = None,
    ) -> dict:
        """Generate a REDCap import CSV from the current DataFrame.

        Finds the latest date-stamped file in each directory, runs the
        comparison, and writes the import CSV.

        Returns a summary dict with keys: matched, rows_changed,
        cells_changed, cells_filled, per_column, per_participant,
        quality_checks, output_path.
        """
        from reports.redcap_exporter import (
            find_latest_dated_file,
            generate_redcap_import,
        )

        df = self.get_dataframe()
        if df is None or df.empty:
            raise ValueError("No DataFrame loaded. Parse or load data first.")

        redcap_data = find_latest_dated_file(data_dir, "SNBR_DATA_")
        redcap_dict = find_latest_dated_file(dict_dir, "SNBR_DataDictionary_")
        redcap_template = find_latest_dated_file(
            template_dir, "SNBR_ImportTemplate_"
        )

        import_df, output_path, summary = generate_redcap_import(
            py_dataframe=df,
            redcap_data_csv=redcap_data,
            redcap_dict_csv=redcap_dict,
            redcap_template_csv=redcap_template,
            output_dir=export_dir,
            include_new_ids=include_new_ids,
            xlsx_report_dir=xlsx_report_dir or None,
        )

        summary["output_path"] = str(output_path)
        summary["redcap_data_file"] = redcap_data.name
        summary["redcap_dict_file"] = redcap_dict.name
        summary["redcap_template_file"] = redcap_template.name
        return summary

    # ── Email Report ──────────────────────────────────────

    def set_last_exported_pdf(self, path: str) -> None:
        """Record the path of the most recently written PDF report.

        The Email Report panel reads this to pre-fill the attachment field.
        """
        self._last_exported_pdf = path or ""

    def get_last_exported_pdf(self) -> str:
        return self._last_exported_pdf

    def get_email_defaults(self) -> dict[str, str]:
        """Return all saved email defaults plus the password (from keyring).

        Password is resolved from Windows Credential Manager keyed by the
        saved username; absent or unreadable returns "".
        """
        from emailing.credentials import load_password
        saved = load_defaults()
        username = saved.get(KEY_EMAIL_USERNAME, "")
        remember = saved.get(KEY_EMAIL_REMEMBER_PASSWORD, "") == "1"
        password = ""
        if remember and username:
            password = load_password(username) or ""
        return {
            "smtp_host": saved.get(KEY_SMTP_HOST, ""),
            "smtp_port": saved.get(KEY_SMTP_PORT, ""),
            "username": username,
            "password": password,
            "from_addr": saved.get(KEY_EMAIL_FROM, ""),
            "to": saved.get(KEY_EMAIL_DEFAULT_TO, ""),
            "cc": saved.get(KEY_EMAIL_DEFAULT_CC, ""),
            "bcc": saved.get(KEY_EMAIL_DEFAULT_BCC, ""),
            "subject": saved.get(KEY_EMAIL_SUBJECT, ""),
            "body": saved.get(KEY_EMAIL_BODY, ""),
            "remember_password": remember,
        }

    def save_email_defaults(
        self,
        *,
        smtp_host: str,
        smtp_port: str,
        username: str,
        from_addr: str,
        to: str,
        cc: str,
        bcc: str,
        subject: str,
        body: str,
        remember_password: bool,
        password: str | None,
    ) -> None:
        """Persist email defaults to JSON; password to Windows Credential Manager."""
        from emailing.credentials import save_password, delete_password
        save_defaults(**{
            KEY_SMTP_HOST: smtp_host,
            KEY_SMTP_PORT: smtp_port,
            KEY_EMAIL_USERNAME: username,
            KEY_EMAIL_FROM: from_addr,
            KEY_EMAIL_DEFAULT_TO: to,
            KEY_EMAIL_DEFAULT_CC: cc,
            KEY_EMAIL_DEFAULT_BCC: bcc,
            KEY_EMAIL_SUBJECT: subject,
            KEY_EMAIL_BODY: body,
            KEY_EMAIL_REMEMBER_PASSWORD: "1" if remember_password else "",
        })
        if remember_password and username and password:
            save_password(username, password)
        elif username:
            # User unchecked the box (or cleared the password) — purge any
            # previously-stored credential so we don't leave a stale entry.
            delete_password(username)

    def prepare_report_pdf_for_email(self) -> str:
        """Return a path to a PDF suitable for emailing.

        Uses the file written by the Export page if one exists; otherwise
        renders the in-memory report figures to a temp file so the user can
        email without an explicit export. Raises ValueError if no figures
        are available either.
        """
        existing = self.get_last_exported_pdf()
        if existing and Path(existing).is_file():
            return existing

        figures = self.get_report_figures()
        if not figures:
            raise ValueError(
                "No report figures are available — please open the "
                "Visualization page first.",
            )

        import tempfile
        from datetime import datetime
        from reports.pdf_renderer import render_figures_to_pdf

        suffix = self.get_export_suffix() or ""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        tmp_dir = Path(tempfile.gettempdir()) / "snbr_email_outgoing"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / f"SNBR_TMS_Report{suffix}_{stamp}.pdf"
        render_figures_to_pdf(figures, str(tmp_path))
        return str(tmp_path)

    def send_report_email(
        self,
        *,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        from_addr: str,
        to_addrs: list[str],
        cc_addrs: list[str],
        bcc_addrs: list[str],
        subject: str,
        body: str,
        attachment_path: str,
    ) -> None:
        """Send the email synchronously. GUI callers must run on a worker thread."""
        from emailing.smtp_sender import send_email_with_attachment
        send_email_with_attachment(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            username=username,
            password=password,
            from_addr=from_addr,
            to_addrs=to_addrs,
            cc_addrs=cc_addrs,
            bcc_addrs=bcc_addrs,
            subject=subject,
            body=body,
            attachment_path=Path(attachment_path),
        )

    # ── Default Phase Execution ───────────────────────────

    # Page-index mapping (must match _page_order in app.py)
    PAGE_NAMES = [
        "welcome", "file_panel", "data_mode", "exclusion", "participant",
        "visualization", "export", "email", "redcap", "sync", "finish",
    ]

    def check_defaults_for_range(
        self, from_index: int, to_index: int,
    ) -> list[str]:
        """Return a list of missing-default messages for phases in [from, to).

        Returns an empty list if all required defaults are present.
        """
        missing: list[str] = []
        saved = load_defaults()

        for idx in range(from_index, to_index):
            if idx <= 0:
                continue  # welcome — no defaults needed
            elif idx == 1:  # file_panel
                if not saved.get(KEY_MEM_DIR, ""):
                    missing.append("Import Settings: No default MEM directory.")
                csv_file = saved.get(KEY_CSV_FILE, "")
                if not csv_file:
                    missing.append("Import Settings: No default CSV file.")
                elif not Path(csv_file).is_file():
                    missing.append(
                        f"Import Settings: CSV file not found: {csv_file}"
                    )
            elif idx == 2:  # data_mode — needs CSV from phase 1
                pass  # covered by file_panel check
            elif idx == 3:  # exclusion — optional, no defaults required
                pass  # saved exclusions auto-apply at startup
            elif idx == 4:  # participant — auto-selects most recent
                pass  # no user default needed
            elif idx == 5:  # visualization — auto-generates all
                pass  # no user default needed
            elif idx == 6:  # export
                csv_out = saved.get(KEY_EXPORT_CSV, "")
                pdf_out = saved.get(KEY_EXPORT_PDF, "")
                if not csv_out and not pdf_out:
                    missing.append(
                        "Export: No default CSV or PDF export path."
                    )
            elif idx == 7:  # email — opt-in, never required
                pass
            elif idx == 8:  # redcap
                for key, label in [
                    (KEY_REDCAP_DATA_DIR, "REDCap Data Directory"),
                    (KEY_REDCAP_DICT_DIR, "REDCap Dictionary Directory"),
                    (KEY_REDCAP_TEMPLATE_DIR, "REDCap Template Directory"),
                    (KEY_REDCAP_EXPORT_DIR, "REDCap Export Directory"),
                ]:
                    if not saved.get(key, ""):
                        missing.append(f"REDCap Export: No default {label}.")
                        break  # one message is enough
            elif idx == 9:  # sync — best-effort, no hard requirement
                pass

        return missing

    def run_default_phases(
        self,
        from_index: int,
        to_index: int,
        status_callback=None,
    ) -> dict:
        """Execute workflow phases [from_index, to_index) using saved defaults.

        Parameters
        ----------
        from_index, to_index : int
            Phase range (inclusive start, exclusive end).
        status_callback : callable, optional
            ``status_callback(msg)`` is called with progress strings.

        Returns
        -------
        dict
            Summary with keys matching the Quick Start summary format.
        """
        saved = load_defaults()

        def _status(msg: str):
            if status_callback:
                status_callback(msg)

        summary: dict = {
            "study": "",
            "pid": None,
            "date": "",
            "cortex": [],
            "mem_dir": "",
            "csp_dir": "",
            "cmap_dir": "",
            "csv_file": "",
            "csv_export": "",
            "pdf_export": "",
            "graphs": [],
            "figure_count": 0,
            "sync_pairs": [],
            "sync_result": None,
            "redcap_summary": None,
            "email_sent": False,
            "email_to": [],
            "email_error": "",
        }

        # Phase 1 — file_panel: set paths
        if from_index <= 1 < to_index:
            _status("Loading data...")
            self.set_paths(
                mem_path=saved.get(KEY_MEM_DIR, ""),
                csp_path=saved.get(KEY_CSP_DIR, ""),
                cmap_path=saved.get(KEY_CMAP_DIR, ""),
                csv_path=saved.get(KEY_CSV_FILE, ""),
                mem_recursive=bool(saved.get(KEY_MEM_RECURSIVE, False)),
                csp_recursive=bool(saved.get(KEY_CSP_RECURSIVE, False)),
                cmap_recursive=bool(saved.get(KEY_CMAP_RECURSIVE, False)),
            )
            errors = self.validate_paths()
            if errors:
                raise ValueError(
                    "Import Settings: " + "; ".join(errors)
                )
            summary["mem_dir"] = "; ".join(
                _as_path_list(saved.get(KEY_MEM_DIR, ""))
            )
            summary["csp_dir"] = "; ".join(
                _as_path_list(saved.get(KEY_CSP_DIR, ""))
            )
            summary["cmap_dir"] = "; ".join(
                _as_path_list(saved.get(KEY_CMAP_DIR, ""))
            )
            summary["csv_file"] = saved.get(KEY_CSV_FILE, "")

        # Phase 2 — data_mode: load CSV
        if from_index <= 2 < to_index:
            # If the saved archive predates newer parser columns (e.g. SR/SD)
            # and a MEM folder is available, do an incremental build so those
            # columns get backfilled — otherwise this automated report would
            # silently omit the SR/SD figures.
            if self._mem_paths and not csv_schema_is_current(self._csv_path):
                _status("Archive out of date — re-parsing MEM files to add SR/SD...")
                self.parse_and_build()
                summary["schema_rebuilt"] = True
            else:
                _status("Loading CSV data...")
                self.load_csv_dataframe()
            df = self.get_dataframe()
            if df is None or df.empty:
                raise ValueError("Loaded CSV contains no data.")

        # Phase 3 — exclusion: saved exclusions are applied at controller
        # startup, so an automated run has nothing to do here. The active set
        # is already reflected in the report figures and the export DataFrame.
        if from_index <= 3 < to_index:
            pass

        # Phase 4 — participant: auto-select most recent
        if from_index <= 4 < to_index:
            _status("Selecting most recent participant...")
            pid, date = self.get_most_recent_visit()
            if pid is None or date is None:
                raise ValueError("No participant visits found in data.")
            self.set_selected_participant(pid, date)
            cortex_options = self.get_cortex_options(pid, date)
            if len(cortex_options) > 1:
                self.set_selected_cortex(cortex_options)
            elif len(cortex_options) == 1:
                self.set_selected_cortex(cortex_options[0])
            else:
                self.set_selected_cortex(None)

            summary["pid"] = pid
            date_str = date.strftime("%d/%m/%Y")
            summary["date"] = date_str
            summary["cortex"] = cortex_options

            # Look up study
            df = self.get_dataframe()
            if df is not None and "Study" in df.columns:
                rows = df[
                    (pd.to_numeric(df["ID"], errors="coerce") == pid)
                    & (df["Date"] == date_str)
                ]
                if not rows.empty:
                    summary["study"] = str(rows["Study"].iloc[0])

        # Phase 5 — visualization: generate all figures
        if from_index <= 5 < to_index:
            from gui.visualization_panel import GRAPH_REGISTRY
            from matplotlib.figure import Figure
            from reports.captions import caption_for
            from reports.pdf_layout import ReportItem

            available_keys: list[str] = []
            for entry in GRAPH_REGISTRY:
                if self.has_data_for_graph(entry.graph_type, entry.measure):
                    available_keys.append(entry.key)

            all_items: list = []
            _status("Generating header figure...")
            try:
                header_fig = self.build_header_figure()
                all_items.append(ReportItem(
                    figure=header_fig, caption=None, section_key="summary",
                ))
            except Exception:
                pass

            total = len(available_keys)
            for idx, key in enumerate(available_keys, 1):
                _status(f"Generating figures {idx}/{total}...")
                entry = next(e for e in GRAPH_REGISTRY if e.key == key)
                try:
                    result = self.generate_figure(
                        entry.graph_type, entry.measure,
                        match_by=entry.match_by,
                    )
                    figs, _axes, plot_data = result[0], result[1], result[2]
                    figure_keys = (
                        plot_data.get("figure_keys")
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
                            all_items.append(ReportItem(
                                figure=f,
                                caption=caption_for(
                                    entry.graph_type, entry.measure,
                                    plot_data, sub_key,
                                ),
                                section_key=entry.key,
                            ))
                    elif isinstance(figs, Figure):
                        all_items.append(ReportItem(
                            figure=figs,
                            caption=caption_for(
                                entry.graph_type, entry.measure,
                                plot_data, None,
                            ),
                            section_key=entry.key,
                        ))
                except Exception:
                    pass

            if not all_items:
                raise ValueError("Could not generate any figures.")

            self.set_selected_graphs(available_keys)
            self.set_report_figures(all_items)

            summary["graphs"] = [
                next(e for e in GRAPH_REGISTRY if e.key == k).label
                for k in available_keys
            ]
            summary["figure_count"] = len(all_items)

        # Phase 6 — export: CSV + PDF
        if from_index <= 6 < to_index:
            # resolve_export_path falls back to an auto-generated name, so
            # Quick Start still produces both files for a user who has never
            # saved an export default.
            export_paths = self.get_default_export_paths()
            csv_path = self.resolve_export_path("csv", export_paths.get("csv", ""))
            pdf_path = self.resolve_export_path("pdf", export_paths.get("pdf", ""))

            if csv_path:
                _status("Exporting CSV...")
                out = Path(csv_path)
                out.parent.mkdir(parents=True, exist_ok=True)
                self.get_export_dataframe().to_csv(out, index=False)

            if pdf_path:
                _status("Exporting PDF...")
                from reports.pdf_renderer import render_figures_to_pdf
                figs = self.get_report_figures()
                render_figures_to_pdf(figs, pdf_path)
                self.set_last_exported_pdf(pdf_path)

            summary["csv_export"] = csv_path
            summary["pdf_export"] = pdf_path

        # Phase 7 — email (opt-in, auto-send only with full saved defaults)
        if from_index <= 7 < to_index:
            email_defaults = self.get_email_defaults()
            to_list = [a.strip() for a in email_defaults["to"].split(",") if a.strip()]
            cc_list = [a.strip() for a in email_defaults["cc"].split(",") if a.strip()]
            bcc_list = [a.strip() for a in email_defaults["bcc"].split(",") if a.strip()]
            ready = (
                email_defaults["remember_password"]
                and email_defaults["password"]
                and email_defaults["smtp_host"]
                and email_defaults["smtp_port"].isdigit()
                and email_defaults["from_addr"]
                and to_list
            )
            if ready:
                _status("Sending email...")
                try:
                    attach = self.prepare_report_pdf_for_email()
                    self.send_report_email(
                        smtp_host=email_defaults["smtp_host"],
                        smtp_port=int(email_defaults["smtp_port"]),
                        username=email_defaults["username"],
                        password=email_defaults["password"],
                        from_addr=email_defaults["from_addr"],
                        to_addrs=to_list,
                        cc_addrs=cc_list,
                        bcc_addrs=bcc_list,
                        subject=email_defaults["subject"],
                        body=email_defaults["body"],
                        attachment_path=attach,
                    )
                    summary["email_sent"] = True
                    summary["email_to"] = to_list
                except Exception as exc:
                    summary["email_sent"] = False
                    summary["email_error"] = f"{type(exc).__name__}: {exc}"
            else:
                summary["email_sent"] = False
                summary["email_error"] = "Skipped (no saved email defaults)."

        # Phase 8 — redcap
        if from_index <= 8 < to_index:
            rc_data = saved.get(KEY_REDCAP_DATA_DIR, "")
            rc_dict = saved.get(KEY_REDCAP_DICT_DIR, "")
            rc_tpl = saved.get(KEY_REDCAP_TEMPLATE_DIR, "")
            rc_out = saved.get(KEY_REDCAP_EXPORT_DIR, "")
            if rc_data and rc_dict and rc_tpl and rc_out:
                _status("Generating REDCap import...")
                try:
                    summary["redcap_summary"] = self.run_redcap_export(
                        data_dir=rc_data,
                        dict_dir=rc_dict,
                        template_dir=rc_tpl,
                        export_dir=rc_out,
                    )
                except Exception:
                    pass  # best-effort

        # Phase 9 — sync
        if from_index <= 9 < to_index:
            sync_pairs_data = self.get_sync_defaults()
            if sync_pairs_data:
                _status("Syncing files...")
                try:
                    from back_up_sync.file_sync import SyncPair, sync_pairs
                    pair_list = [
                        SyncPair(
                            source=p["source"],
                            destination=p["destination"],
                        )
                        for p in sync_pairs_data
                        if p.get("source") and p.get("destination")
                    ]
                    if pair_list:
                        result = sync_pairs(
                            pair_list,
                            retries=3,
                            wait=5,
                            log_path=self.get_sync_log_path(),
                        )
                        summary["sync_pairs"] = pair_list
                        summary["sync_result"] = result
                except Exception:
                    pass  # best-effort

        return summary
