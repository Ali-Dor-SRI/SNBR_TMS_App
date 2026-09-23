"""Every app module must import.

Cheap insurance with a specific target: the last refactor pass moved shared code
into new modules (parser/_common.py, gui/widgets.py, gui/page_shell.py) and
deleted 24 imports. A move that leaves one module importing a name that no
longer exists is invisible until something reaches that module -- and the suite
does not reach all of them. main.py and emailing/pdf_letterhead.py are imported
by no other test at all.

This also pins the optional-dependency policy. pdfplumber, python-docx and
keyring are imported inside the functions that need them, not at module scope,
so parser/cmap_parser.py and emailing/credentials.py import fine on a machine
that has none of them. Moving one of those to the top of its file would break a
clean install and nothing else here would notice.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

# Not application code: the virtualenv, build output, the vendored copy of
# customtkinter inside the macOS bundle, caches, and the tests themselves.
SKIP_DIRS = {
    ".venv", ".venv312", "venv", "env", "build", "dist", "dist_macos",
    "__pycache__", ".git", ".pytest_cache", "tests", "icons",
}


def _module_names() -> list[str]:
    names = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        rel = path.relative_to(APP_ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        parts = list(rel.parts)
        if parts[-1] == "__init__.py":
            parts = parts[:-1]
            if not parts:
                continue
        else:
            parts[-1] = parts[-1][: -len(".py")]
        names.append(".".join(parts))
    return names


APP_MODULES = _module_names()


def test_the_module_list_is_not_empty_or_truncated():
    """A discovery bug would make every import test below vacuously pass."""
    assert len(APP_MODULES) >= 45, (
        f"only found {len(APP_MODULES)} modules -- discovery is probably broken"
    )
    for expected in (
        "main", "gui.app", "gui.controller", "parser.mem_parser",
        "parser._common", "processing.df_builder", "reports.report_builder",
        "emailing.pdf_letterhead", "core.user_settings", "back_up_sync.file_sync",
        "dispatch_main", "dispatch.ledger", "dispatch_gui.app",
    ):
        assert expected in APP_MODULES, f"{expected} missing from the module list"

    # The vendored customtkinter inside the macOS bundle is not app code.
    assert not any("dist_macos" in name for name in APP_MODULES)


@pytest.mark.parametrize("module_name", APP_MODULES)
def test_module_imports(module_name):
    """Named one at a time so a failure says which module broke."""
    importlib.import_module(module_name)


def test_importing_main_does_not_launch_the_app():
    """main.py holds the mainloop; importing it must not start one."""
    module = importlib.import_module("main")
    assert hasattr(module, "main"), "main.py must keep its main() entry point"
    dispatch = importlib.import_module("dispatch_main")
    assert hasattr(dispatch, "main"), "dispatch_main.py must keep its main() entry point"


@pytest.mark.parametrize("module_name,attribute", [
    ("parser.cmap_parser", "pdfplumber"),
    ("emailing.credentials", "keyring"),
    ("dispatch.stamp", "pypdf"),
    ("dispatch.roster", "openpyxl"),
])
def test_optional_dependencies_are_not_imported_at_module_scope(module_name, attribute):
    """Importing these at the top would break a machine without the package.

    The app must run offline and install without the optional extras; both
    modules import theirs inside the function that needs it.
    """
    module = importlib.import_module(module_name)
    assert not hasattr(module, attribute), (
        f"{module_name} imported {attribute} at module scope -- that makes it a "
        f"hard dependency of the whole app"
    )


BACKEND_PACKAGES = (
    "parser", "processing", "reports", "emailing", "back_up_sync", "core",
    "dispatch",
)


def test_the_backend_never_imports_the_gui():
    """Architecture rule: the backend must run headless from the command line.

    Checked by importing every backend module in a fresh interpreter and asking
    whether ``gui`` ended up in sys.modules. That catches a transitive import --
    a backend module pulling in another that reaches gui/ -- which grepping the
    import lines would miss.
    """
    import json
    import subprocess

    # By top-level package, not string prefix: "dispatch_gui" starts with
    # "dispatch" but is a GUI package.
    backend = [n for n in APP_MODULES if n.split(".")[0] in BACKEND_PACKAGES]
    assert backend, "no backend modules found -- discovery is broken"

    program = (
        "import importlib, json, sys\n"
        f"sys.path.insert(0, {str(APP_ROOT)!r})\n"
        f"for name in {backend!r}:\n"
        "    importlib.import_module(name)\n"
        "leaked = sorted(m for m in sys.modules if m == 'gui' or m.startswith('gui.'))\n"
        "print(json.dumps(leaked))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True, text=True, cwd=str(APP_ROOT),
    )
    assert result.returncode == 0, (
        f"importing the backend failed:\n{result.stderr}"
    )

    leaked = json.loads(result.stdout.strip().splitlines()[-1])
    assert leaked == [], (
        f"importing only backend modules pulled in gui/: {leaked}. The backend "
        f"must run headless from the command line."
    )
