"""GUI-backend bridge. All GUI frames communicate with the backend through this module."""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")  # noqa: E402 — must precede any pyplot import

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
    KEY_REDCAP_DATA_DIR, KEY_REDCAP_DICT_DIR,
    KEY_REDCAP_TEMPLATE_DIR, KEY_REDCAP_EXPORT_DIR,
    KEY_REDCAP_XLSX_DIR,
    KEY_SMTP_HOST, KEY_SMTP_PORT,
    KEY_EMAIL_USERNAME, KEY_EMAIL_FROM,
    KEY_EMAIL_DEFAULT_TO, KEY_EMAIL_DEFAULT_CC, KEY_EMAIL_DEFAULT_BCC,
    KEY_EMAIL_SUBJECT, KEY_EMAIL_BODY, KEY_EMAIL_REMEMBER_PASSWORD,
)
from parser.mem_parser import iter_mem_files
from processing.df_builder import (
    _apply_cmap_merge,
    build_combined_dataframe_incremental,
    load_existing_csv,
)
from processing.visualizer import (
    CSP_MEASURE_LABEL,
    CSP_PROFILE_COLUMNS,
    RMT_COLUMNS,
    WAVEFORM_MEASURE_CONFIGS,
    format_participant_label,
    normalize_mem_date,
    waveform_measure_config,
    plot_mem_graph,
)
from reports.csv_exporter import find_latest_csv
from reports.report_builder import build_header_only_figure


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

    def __init__(self):
        self._mem_paths: list[str] = []
        self._csp_paths: list[str] = []
        self._cmap_paths: list[str] = []
        # Per-field "scan subfolders" toggle. Default OFF — recursion is opt-in.
        self._mem_recursive: bool = False
        self._csp_recursive: bool = False
        self._cmap_recursive: bool = False
        self._csv_path: str = ""  # a *file* path, not a directory
        self._dataframe: pd.DataFrame | None = None
        self._quick_start_message: str = ""
        self._last_exported_pdf: str = ""
        # Per-participant tests excluded from cohort averages and CSV export:
        # {participant_id: {test_key, ...}}. Loaded from saved defaults at
        # startup; mutated in-session by the exclusion panel and only
        # re-persisted when the user saves.
        self._excluded_tests: dict[int, set[str]] = {}

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
        self._dataframe = df
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
        self._dataframe = df
        return df

    def count_new_mem_files(self, df: pd.DataFrame) -> int:
        """Count .MEM files across the MEM directories not present in the DataFrame."""
        if not any(Path(p).is_dir() for p in self._mem_paths):
            return 0
        all_files = {
            p.name
            for p in iter_mem_files(
                self._mem_paths,
                exclude_dirs=[self._csp_paths or None, self._cmap_paths or None],
                recursive=self._mem_recursive,
            )
        }
        if "source_file" not in df.columns:
            return len(all_files)
        known = set(df["source_file"].dropna().unique())
        return len(all_files - known)

    def set_dataframe(self, df: pd.DataFrame):
        self._dataframe = df

    def get_dataframe(self) -> pd.DataFrame | None:
        return self._dataframe

    # ── Participant / date queries ─────────────────────────

    _DATE_FMT = "%d/%m/%Y"

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

        # Look up study from the dataframe
        study = ""
        df = self._dataframe
        if df is not None and "Study" in df.columns:
            rows = df[pd.to_numeric(df["ID"], errors="coerce") == pid]
            if not rows.empty:
                study = str(rows["Study"].iloc[0]).strip()

        if study:
            return f"_{study}_ID{pid}_{date_str}"
        return f"_ID{pid}_{date_str}"

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

    # ── Applying exclusions ───────────────────────────────

    def _measure_excluded_df(
        self, df: pd.DataFrame | None, *, exempt_id=None,
    ) -> pd.DataFrame | None:
        """Return a copy of *df* with excluded test columns blanked (NaN).

        For each (participant, test) exclusion, the test's value columns are
        set to NaN in that participant's rows. This removes the participant
        from that one measure's cohort average (the plotting layer drops rows
        whose measure value is NaN) and blanks the measure in the exported CSV
        — while leaving their other tests intact.

        *exempt_id* skips one participant entirely — used when plotting so the
        selected participant's own traces still render (they are already
        dropped from cohort means by the plotting layer).
        """
        if df is None or not self._excluded_tests or "ID" not in df.columns:
            return df
        exempt = None
        if exempt_id is not None:
            try:
                exempt = int(exempt_id)
            except (ValueError, TypeError):
                exempt = None

        work = None
        ids = None
        for pid, tests in self._excluded_tests.items():
            if pid == exempt or not tests:
                continue
            cols = []
            for test_key in tests:
                cols.extend(self._test_columns(test_key))
            cols = [c for c in dict.fromkeys(cols) if c in df.columns]
            if not cols:
                continue
            if work is None:
                work = df.copy()
                ids = pd.to_numeric(work["ID"], errors="coerce")
            mask = ids == pid
            if mask.any():
                work.loc[mask, cols] = np.nan
        return work if work is not None else df

    def get_export_dataframe(self) -> pd.DataFrame | None:
        """Return the working DataFrame with excluded tests blanked.

        Used for CSV/dataframe export so excluded measurements are blank in the
        exported file. The in-memory DataFrame is left untouched.
        """
        if self._dataframe is None:
            return None
        return self._measure_excluded_df(self._dataframe)

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

        df = self._dataframe
        if df is None:
            raise ValueError("No DataFrame available.")

        date_str = date.strftime(self._DATE_FMT)
        p_rows = df[pd.to_numeric(df["ID"], errors="coerce") == pid]
        cmap_rows = _extract_cmap_rows_for_visit(p_rows, date_str)
        if not cmap_rows:
            raise ValueError("No CMAP data for this visit.")

        plabel = format_participant_label(pid)
        fig = _build_cmap_table_figure(plabel, cmap_rows, date_str)
        return fig, None, {"cmap_row_count": len(cmap_rows)}

    def _build_munix_figure_for_selected(self, pid: int, date) -> tuple:
        """Build a MUNIX table figure for the selected participant/visit."""
        from reports.report_builder import (
            _build_munix_table_figure,
            _extract_munix_rows_for_visit,
        )
        from processing.visualizer import format_participant_label

        df = self._dataframe
        if df is None:
            raise ValueError("No DataFrame available.")

        date_str = date.strftime(self._DATE_FMT)
        p_rows = df[pd.to_numeric(df["ID"], errors="coerce") == pid]
        munix_rows = _extract_munix_rows_for_visit(p_rows, date_str)
        if not munix_rows:
            raise ValueError("No MUNIX data for this visit.")

        plabel = format_participant_label(pid)
        fig = _build_munix_table_figure(plabel, munix_rows, date_str)
        return fig, None, {"munix_row_count": len(munix_rows)}

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

    def _rows_for_selected_visit(self) -> pd.DataFrame | None:
        """Return the DataFrame rows for the currently selected (pid, date, cortex).

        Does the filter **once** so callers that need to check many
        graph-availability conditions don't re-scan the DataFrame per query.
        Returns ``None`` when no participant/date is selected.
        """
        pid, date = self.get_selected_participant()
        df = self._dataframe
        if df is None or pid is None or date is None:
            return None

        cortex = self.get_selected_cortex()
        if isinstance(cortex, str):
            df = self._get_cortex_filtered_df(cortex)

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

    def has_data_for_graph(self, graph_type: str, measure: str | None) -> bool:
        """Fast check whether the selected participant has data for a graph type."""
        rows = self._rows_for_selected_visit()
        if rows is None:
            return False
        return self._rows_have_graph_data(rows, graph_type, measure)

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
        """
        rows = self._rows_for_selected_visit()
        if rows is None:
            return {e.key: False for e in entries}
        return {
            e.key: self._rows_have_graph_data(rows, e.graph_type, e.measure)
            for e in entries
        }

    # ── Title builder ────────────────────────────────────

    _GRAPH_TYPE_NEEDS_CORTEX_OVERLAY = {
        "profile", "measure_profile",
        "over_time", "participant_over_time", "timeline", "longitudinal",
        "visit_profiles", "participant_visit_profiles", "visit_profile_grid",
        "rmt_over_time", "participant_rmt_over_time",
    }

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

        return " | ".join(parts)

    # ── Figure generation ─────────────────────────────────

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

        # CMAP / MUNIX tables are simple participant-visit tables rendered
        # directly from the DataFrame — no cortex handling, no plot_mem_graph.
        norm_type = str(graph_type).strip().lower()
        if norm_type == "cmap_table":
            return self._build_cmap_figure_for_selected(pid, date)
        if norm_type == "munix_table":
            return self._build_munix_figure_for_selected(pid, date)

        cortex = self.get_selected_cortex()
        norm_type = str(graph_type).strip().lower().replace("-", "_").replace(" ", "_")
        title = self._build_graph_title(graph_type, measure)

        # Blank excluded tests in the cohort data before plotting so those
        # measurements don't contribute to group averages. The selected
        # participant is exempted so their own traces still render even if some
        # of their tests are excluded (the plotting layer already removes the
        # highlight from the group means).
        base_df = self._measure_excluded_df(self._dataframe, exempt_id=pid)

        kwargs: dict = dict(
            participant_id=pid,
            mem_date=date.strftime(self._DATE_FMT),
            show=False,
            title=title,
        )

        if match_by is not None:
            kwargs["match_by"] = match_by

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

        if measure is not None:
            return plot_mem_graph(graph_type=graph_type, measure=measure, **kwargs)
        return plot_mem_graph(graph_type=graph_type, **kwargs)

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
            export_paths = self.get_default_export_paths()
            csv_path = self.stamp_export_path(export_paths.get("csv", ""))
            pdf_path = self.stamp_export_path(export_paths.get("pdf", ""))

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
