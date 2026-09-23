"""Build-time preparation and verification of the application marks.

Not imported by either application at runtime. The PyInstaller specs import
it while PyInstaller executes them, ``build_dispatch.bat`` calls its CLI, and
``tests/test_build_assets.py`` imports it to check the invariants without
running a build.

Why it exists
-------------
The marks in ``icons/`` are **generated** files (``scripts/generate_logo.py``,
``scripts/generate_dispatch_logo.py``), so a checkout or a geometry edit can
leave a spec pointing at an ``.ico`` that is not there. That failure is worse
than it looks:

* PyInstaller raises ``FileNotFoundError: Icon input file ... not found`` --
  but only from ``EXE.assemble``, **after** the executable has been written.
  ``dist/`` is left holding an un-iconned binary and the process exits 1.
* ``build_dispatch.bat`` used to judge success with ``if exist dist\\...exe``,
  which that leftover satisfies -- as does a stale executable from an earlier
  successful build, since ``--clean`` clears the cache and ``build/`` but not
  ``dist/``. So a failed build reported "Build complete!" and the operator
  shipped an executable wearing the wrong icon or none.

So the mark is prepared *before* ``EXE()`` is constructed (:func:`ensure_icon`,
called from the spec), and confirmed to be inside the finished executable
*after* the build (:func:`exe_embeds_icon`, called from the build script).

A third step exists because embedding the icon is not enough to make Explorer
*show* it: the shell caches icons per path and does not reliably notice an
executable being replaced in place. See :func:`refresh_shell_icon`.

CLI
---
``python -m scripts.build_assets --ensure dispatch``
``python -m scripts.build_assets --verify-exe dist/SNBR_Report_Dispatch.exe --mark dispatch``
``python -m scripts.build_assets --refresh-shell dist/SNBR_Report_Dispatch.exe``
"""

from __future__ import annotations

import argparse
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Mark:
    """One application mark: where its icon lives and what regenerates it."""

    name: str
    ico: Path
    generator: str          # module under scripts/ exposing main()
    app: str                # human name, for error messages


MARKS: dict[str, Mark] = {
    "analysis": Mark(
        name="analysis",
        ico=PROJECT_ROOT / "icons" / "logo" / "logo.ico",
        generator="generate_logo",
        app="SNBR TMS App",
    ),
    "dispatch": Mark(
        name="dispatch",
        ico=PROJECT_ROOT / "icons" / "logo_dispatch" / "dispatch.ico",
        generator="generate_dispatch_logo",
        app="SNBR Report Dispatch",
    ),
}


class BuildAssetError(RuntimeError):
    """A mark could not be produced or verified. Always fails the build."""


def ensure_icon(mark_name: str, regenerate: bool = False) -> Path:
    """Return the mark's ``.ico``, generating it first if it is absent.

    *regenerate* forces a rebuild even when the file is present, which is what
    a release build wants: it guarantees the shipped icon matches the geometry
    currently in the generator rather than whatever happens to be on disk.

    Raises :class:`BuildAssetError` -- never returns a path that is not there.
    """
    mark = MARKS[mark_name]
    if regenerate or not mark.ico.is_file():
        _run_generator(mark)
    if not mark.ico.is_file():
        raise BuildAssetError(
            f"{mark.app}: {mark.ico} is still missing after running "
            f"scripts/{mark.generator}.py. The build cannot embed a mark that "
            f"does not exist."
        )
    return mark.ico


def _run_generator(mark: Mark) -> None:
    import importlib

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    try:
        module = importlib.import_module(f"scripts.{mark.generator}")
        module.main()
    except BuildAssetError:
        raise
    except Exception as exc:
        raise BuildAssetError(
            f"{mark.app}: scripts/{mark.generator}.py failed ({type(exc).__name__}: {exc}). "
            f"matplotlib and Pillow are needed to render the mark."
        ) from exc


# -- verification ------------------------------------------------------------

def ico_frames(ico_path: str | Path) -> list[bytes]:
    """The raw image payload of every frame in an ``.ico``, largest first.

    Parsed from the ICONDIR/ICONDIRENTRY headers rather than with Pillow,
    because what matters is the bytes PyInstaller copies into the executable's
    ``RT_ICON`` resources -- Pillow would hand back decoded pixels instead.
    """
    data = Path(ico_path).read_bytes()
    if len(data) < 6:
        raise BuildAssetError(f"{ico_path} is too short to be an .ico")
    reserved, image_type, count = struct.unpack("<HHH", data[:6])
    if reserved != 0 or image_type != 1 or count == 0:
        raise BuildAssetError(f"{ico_path} is not a valid .ico (type={image_type}, n={count})")

    frames = []
    for index in range(count):
        offset = 6 + index * 16
        entry = data[offset:offset + 16]
        if len(entry) < 16:
            raise BuildAssetError(f"{ico_path} has a truncated directory entry")
        size, start = struct.unpack("<II", entry[8:16])
        payload = data[start:start + size]
        if len(payload) != size:
            raise BuildAssetError(f"{ico_path} frame {index} is truncated")
        frames.append(payload)
    return sorted(frames, key=len, reverse=True)


def exe_embeds_icon(exe_path: str | Path, ico_path: str | Path) -> bool:
    """Whether *exe_path* actually carries the images from *ico_path*.

    PyInstaller copies each frame's payload into an ``RT_ICON`` resource
    verbatim, so the frame bytes appear in the executable. Checking the
    **largest** frame is the meaningful test: it is far too big to collide by
    chance, and a build that embedded some other icon will not contain it.
    """
    exe_bytes = Path(exe_path).read_bytes()
    frames = ico_frames(ico_path)
    return any(frame in exe_bytes for frame in frames[:1])


def refresh_shell_icon(exe_path: str | Path, broad: bool = True) -> bool:
    """Tell the Windows shell that *exe_path* changed, so Explorer re-reads it.

    Embedding the right icon is not enough to make Explorer *show* it. The
    shell keeps an icon cache keyed on the file's path, both on disk
    (``%LocalAppData%\\Microsoft\\Windows\\Explorer\\iconcache_*.db``) and in the
    running ``explorer.exe``'s own image list, and replacing an executable in
    place does not reliably invalidate either. Every build writes to the same
    ``dist\\`` path, so the icon Explorer cached the *first* time that filename
    appeared is the one it keeps drawing -- which is why the dispatch app went
    on showing the analysis app's coil in Explorer long after the binary
    carried the envelope, while the taskbar (drawn from the running window's
    own ``iconbitmap``) was already correct.

    ``SHCNE_UPDATEITEM`` targets the one file; ``SHCNE_ASSOCCHANGED`` is the
    broader nudge installers use, and is what actually evicts a stale
    executable icon. Returns False on non-Windows and on any failure -- a
    cosmetic refresh must never fail a build.
    """
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes

        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        SHCNE_UPDATEITEM, SHCNE_ASSOCCHANGED = 0x00002000, 0x08000000
        SHCNF_PATHW, SHCNF_FLUSH = 0x0005, 0x1000
        flags = SHCNF_PATHW | SHCNF_FLUSH
        shell32.SHChangeNotify(
            SHCNE_UPDATEITEM, flags, ctypes.c_wchar_p(str(Path(exe_path).resolve())), None,
        )
        if broad:
            shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_FLUSH, None, None)
        return True
    except Exception:
        return False


def verify_exe(exe_path: str | Path, mark_name: str) -> Path:
    """Raise unless *exe_path* exists and carries the named mark."""
    mark = MARKS[mark_name]
    exe = Path(exe_path)
    if not exe.is_file():
        raise BuildAssetError(f"{mark.app}: {exe} was not produced.")
    if not mark.ico.is_file():
        raise BuildAssetError(f"{mark.app}: {mark.ico} is missing, so nothing can be verified.")
    if not exe_embeds_icon(exe, mark.ico):
        raise BuildAssetError(
            f"{mark.app}: {exe.name} does not carry {mark.ico.name}. The build wrote an "
            f"executable but the mark did not reach it -- do not ship this binary. "
            f"(A stale {exe.name} from an earlier build is the usual cause; delete dist/ "
            f"and rebuild.)"
        )
    return exe


# -- CLI ---------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ensure", choices=sorted(MARKS), help="generate the mark if absent")
    parser.add_argument("--regenerate", action="store_true", help="with --ensure, rebuild it anyway")
    parser.add_argument("--verify-exe", metavar="EXE", help="check a built executable carries the mark")
    parser.add_argument("--mark", choices=sorted(MARKS), help="which mark --verify-exe expects")
    parser.add_argument(
        "--refresh-shell", metavar="EXE",
        help="tell Explorer the executable changed, so it stops drawing a cached icon",
    )
    args = parser.parse_args(argv)

    try:
        if args.ensure:
            print(f"mark ready: {ensure_icon(args.ensure, regenerate=args.regenerate)}")
        if args.verify_exe:
            if not args.mark:
                parser.error("--verify-exe needs --mark")
            print(f"mark embedded: {verify_exe(args.verify_exe, args.mark)}")
        if args.refresh_shell:
            done = refresh_shell_icon(args.refresh_shell)
            print("shell notified" if done else "shell refresh skipped (not Windows, or it failed)")
        if not any((args.ensure, args.verify_exe, args.refresh_shell)):
            parser.error("nothing to do: pass --ensure, --verify-exe and/or --refresh-shell")
    except BuildAssetError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
