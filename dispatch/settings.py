"""Persisted settings for the dispatch app.

Kept entirely separate from :mod:`core.user_settings`: the analysis app's
``KEY_*`` schema is frozen (see CLAUDE.md), and the dispatch app is installed
on a different machine — the one that has the enrolment workbook. Same
storage policy though: repo-local in development, per-user ``%APPDATA%`` when
frozen, and every write is atomic.

Every path the app touches is a setting. Nothing is hard-coded to a share.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_APP_NAME = "SNBR_Report_Dispatch"


def _resolve_settings_file() -> Path:
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent / "saved_settings.json"
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / _APP_NAME / "settings.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / _APP_NAME / "settings.json"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / _APP_NAME / "settings.json"


_SETTINGS_FILE = _resolve_settings_file()

# ── Keys ───────────────────────────────────────────────────────────────
KEY_ROSTER_PATH = "roster_path"            # the enrolment workbook (.xlsx)
KEY_ROSTER_SHEET = "roster_sheet"          # worksheet name inside it
KEY_COL_PATIENT_ID = "col_patient_id"      # header of the study-ID column
KEY_COL_PATIENT_NAME = "col_patient_name"  # header of the name column
KEY_COL_MRN = "col_mrn"                    # header of the MRN column
KEY_REPORTS_DIR = "reports_dir"            # where the analysis app exports PDFs
KEY_IDENTIFIED_DIR = "identified_dir"      # where stamped batches are written
KEY_LEDGER_PATH = "ledger_path"            # the append-only JSONL ledger
KEY_RECIPIENTS = "recipients"              # list[str], the fixed To list
KEY_SIZE_CAP_MB = "size_cap_mb"            # per-part cap on raw attachment bytes
KEY_ALLOWED_DOMAIN = "allowed_domain"      # recipients must be @this
KEY_SUBJECT_TEMPLATE = "subject_template"  # see batch.render_subject

DEFAULTS: dict = {
    KEY_ROSTER_PATH: "",
    KEY_ROSTER_SHEET: "SNBR enrolment log",
    KEY_COL_PATIENT_ID: "Patient ID",
    KEY_COL_PATIENT_NAME: "Patient Name",
    KEY_COL_MRN: "MRN",
    KEY_REPORTS_DIR: "",
    KEY_IDENTIFIED_DIR: "",
    KEY_LEDGER_PATH: "",
    KEY_RECIPIENTS: [],
    KEY_SIZE_CAP_MB: 20,
    KEY_ALLOWED_DOMAIN: "sunnybrook.ca",
    KEY_SUBJECT_TEMPLATE: "SNBR TMS reports - week of {week_start}{part}",
}

# Keys whose value is a filesystem path (validated as such by the GUI).
PATH_KEYS = (KEY_ROSTER_PATH, KEY_REPORTS_DIR, KEY_IDENTIFIED_DIR, KEY_LEDGER_PATH)


def _read() -> dict:
    if _SETTINGS_FILE.exists():
        try:
            data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _write(data: dict) -> None:
    _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(_SETTINGS_FILE.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, str(_SETTINGS_FILE))
    except BaseException:
        os.unlink(tmp)
        raise


def load_settings() -> dict:
    """Return every setting, defaults filled in for anything unset."""
    raw = _read()
    out = {}
    for key, default in DEFAULTS.items():
        value = raw.get(key, default)
        if isinstance(default, list) and not isinstance(value, list):
            value = default
        if isinstance(default, int) and not isinstance(default, bool):
            try:
                value = int(value)
            except (TypeError, ValueError):
                value = default
        out[key] = value
    return out


def save_settings(**kwargs) -> None:
    """Merge the given key=value pairs into the saved settings (atomic)."""
    data = _read()
    for key, value in kwargs.items():
        if key not in DEFAULTS:
            raise KeyError(f"unknown dispatch setting: {key}")
        data[key] = value
    _write(data)


# ── Validation ──────────────────────────────────────────────────────────

def parse_recipients(raw: str) -> list[str]:
    """Split a comma/semicolon/newline separated address list."""
    parts = []
    for chunk in raw.replace(";", ",").replace("\n", ",").split(","):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return parts


def validate_recipients(recipients: list[str], allowed_domain: str) -> list[str]:
    """Return one message per recipient that is not at *allowed_domain*.

    PHI leaves only for the hospital's own tenant; an address anywhere else is
    rejected at settings time so it cannot reach a batch.
    """
    problems = []
    domain = allowed_domain.strip().lower().lstrip("@")
    for addr in recipients:
        local, sep, host = addr.rpartition("@")
        if not sep or not local or host.lower() != domain:
            problems.append(f"{addr!r} is not an @{domain} address")
    return problems


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def sync_source_conflicts(folder: str | Path, sync_pairs: list) -> list[str]:
    """Return the sync sources that contain (or equal) *folder*.

    The analysis app's backup module copies every file under a ``SyncPair``
    source to its destination. A stamped, identified PDF written inside one
    would be copied there automatically, so the identified folder is refused
    whenever it sits under a source. *sync_pairs* is the list the analysis
    app persists under its ``sync_pairs`` key (dicts with ``source``).
    """
    if not str(folder).strip():
        return []
    target = Path(folder)
    hits = []
    for pair in sync_pairs or []:
        source = pair.get("source") if isinstance(pair, dict) else getattr(pair, "source", None)
        if source and _is_within(target, Path(source)):
            hits.append(str(source))
    return hits


def analysis_app_sync_pairs() -> list:
    """The analysis app's saved sync pairs on this machine, read-only.

    Returns ``[]`` when the analysis app has never saved any (or is not
    installed here); the dispatch app never writes that file.
    """
    try:
        from core.user_settings import KEY_SYNC_PAIRS, load_defaults
        pairs = load_defaults().get(KEY_SYNC_PAIRS, [])
        return list(pairs) if isinstance(pairs, list) else []
    except Exception:
        return []
