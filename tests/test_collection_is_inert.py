"""Importing a test module must not do the app's work.

``tests/test_df.py`` and ``tests/test_report.py`` are developer scripts that read
the real lab share. They match pytest's ``test_*.py`` discovery pattern, so
pytest imports them on every run -- and an import runs whatever sits at module
level.

They used to sit at module level. The cost was invisible because both are silent
on success and their output directory is gitignored: every ``pytest`` run parsed
the share, built a full participant report and wrote a fresh CSV and a ~7MB PDF
into ``tests/output/``, contributing not one test item. Collection alone took
52s of a 64s run and the directory had grown to 939MB.

It also quietly inflated the suite's apparent reach: because those scripts
exercised the report pipeline as a side effect, ``reports/pdf_renderer.py``
measured 88.6% covered when the tests themselves reach 51.9%.

These tests load each script with its heavy entry points replaced by a function
that raises. A guarded script imports without calling them and passes; an
unguarded one calls one on import and fails.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TESTS_DIR = Path(__file__).resolve().parent


class ImportTimeSideEffect(RuntimeError):
    """Raised by a stand-in for work that must not happen at import time."""


def _load_isolated(path: Path):
    """Import *path* under a throwaway module name.

    A fresh name keeps this independent of whether pytest has already imported
    the real module during collection.
    """
    spec = importlib.util.spec_from_file_location(f"_inert_probe_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


# Each script, and the functions it must not call while being imported. These
# are patched on the *defining* module, so the script's ``from x import y`` picks
# up the stand-in.
SCRIPT_ENTRY_POINTS = {
    "test_df.py": [
        ("processing.df_builder", "build_combined_dataframe"),
        ("reports.csv_exporter", "export_dataframe"),
    ],
    "test_report.py": [
        ("processing.df_builder", "load_participant_dataframe"),
        ("reports.csv_exporter", "find_latest_csv"),
        ("reports.pdf_renderer", "generate_participant_report"),
    ],
}


@pytest.mark.parametrize("script", sorted(SCRIPT_ENTRY_POINTS))
def test_developer_script_does_no_work_when_imported(script, monkeypatch):
    """pytest imports these on every run; the import must be inert."""
    import importlib

    def boom(*args, **kwargs):
        raise ImportTimeSideEffect(
            f"{script} did real work while being imported -- put it behind "
            f"`if __name__ == \"__main__\":`"
        )

    for module_name, attribute in SCRIPT_ENTRY_POINTS[script]:
        monkeypatch.setattr(importlib.import_module(module_name), attribute, boom)

    _load_isolated(TESTS_DIR / script)


@pytest.mark.parametrize("script", sorted(SCRIPT_ENTRY_POINTS))
def test_developer_script_still_runs_when_executed(script, monkeypatch):
    """The guard must not cost the script its point: main() still does the work."""
    import importlib

    calls = []

    for module_name, attribute in SCRIPT_ENTRY_POINTS[script]:
        monkeypatch.setattr(
            importlib.import_module(module_name),
            attribute,
            lambda *a, _name=attribute, **k: calls.append(_name) or _Stub(),
        )

    module = _load_isolated(TESTS_DIR / script)
    assert hasattr(module, "main"), f"{script} must expose a main() to run"
    module.main()

    # Which ones, not in which order -- the call order is the script's business.
    expected = {attribute for _, attribute in SCRIPT_ENTRY_POINTS[script]}
    assert set(calls) == expected, (
        f"{script}: main() called {sorted(set(calls))}, expected {sorted(expected)}"
    )


class _Stub:
    """Stands in for a DataFrame or a path -- prints and indexes without work."""

    shape = (0, 0)

    def __repr__(self):
        return "<stub>"
