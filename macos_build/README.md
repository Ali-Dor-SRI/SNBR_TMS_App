# macOS Packaging

This folder contains everything needed to build the SNBR TMS App into a
deliverable **`.app`** bundle for macOS. The project's primary target is
Windows 10+ (see root `CLAUDE.md`); this build is an additional, unofficial
target for lab machines that run macOS.

The macOS build writes into `SNBR_TMS_App/dist_macos/` (and uses
`build_macos/` for intermediates), leaving the Windows build's default
`dist/` and `build/` directories untouched — so both platform builds can
coexist on the same checkout without overwriting each other.

## Contents

| File | Purpose |
|---|---|
| `SNBR_TMS_App_macos.spec` | PyInstaller spec — produces `dist_macos/SNBR_TMS_App.app`. |
| `build.sh` | One-shot build script. Run it on a Mac. |
| `README.md` | This file. |

---

## Prerequisites (one-time setup on the Mac)

1. **Python 3.14** that includes Tk.
   - Easiest path: the [python.org installer](https://www.python.org/downloads/macos/) — its Python ships with a working Tk.
   - Homebrew works too, but you must also install the Tk package that matches your Python version:
     ```bash
     brew install python@3.14 python-tk@3.14
     ```
   - Verify Tk:
     ```bash
     python3 -c "import tkinter; tkinter.Tcl()"
     ```
     Silent exit = OK. Any error = fix Tk before continuing.

2. **A virtual environment** inside the project (recommended, keeps deps isolated).
   ```bash
   cd /path/to/SNBR_TMS_App
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Dependencies.** `build.sh` installs these automatically, but if you want to do it by hand:
   ```bash
   pip install -r requirements.txt
   pip install pyinstaller
   ```

---

## Building

From the project root:

```bash
cd SNBR_TMS_App
./macos_build/build.sh
```

The script:
1. Confirms you're on macOS and that Tk is importable.
2. Installs `requirements.txt` + PyInstaller.
3. Cleans any previous `build_macos/` and `dist_macos/` (Windows outputs at
   `build/` and `dist/` are never touched).
4. Runs PyInstaller with `--distpath dist_macos --workpath build_macos`
   against `macos_build/SNBR_TMS_App_macos.spec`.
5. Reports the resulting bundle path.

On first success you get `dist_macos/SNBR_TMS_App.app` (expect 400–800 MB —
matplotlib, numpy, and pandas are all bundled).

Quick sanity check:

```bash
open dist_macos/SNBR_TMS_App.app
```

The welcome window should appear within a couple of seconds. If it doesn't,
see **Troubleshooting** below.

---

## Architecture (arm64 / x86_64 / universal2)

The spec builds for whatever architecture the running Python is. To check:

```bash
python3 -c "import platform; print(platform.machine())"
```

- Apple Silicon + arm64 Python → arm64 bundle (runs natively on M1/M2/M3/M4 only).
- Intel Mac → x86_64 bundle (runs on Intel, and on Apple Silicon under Rosetta).
- To build a **universal2** binary that runs natively on both architectures,
  install a universal2 Python (the python.org installer labels it
  "universal2 installer") and edit the spec:

  ```python
  exe = EXE(
      ...
      target_arch='universal2',
      ...
  )
  ```

  Every third-party wheel must also be universal2 or the build fails with
  "missing arm64 slice" or similar. For a lab-internal deliverable, just
  build on (and for) the Mac generation you actually use.

---

## Creating a deliverable package

You have two practical options. Pick based on how you're shipping the app.

### Option A — Zip (simplest, recommended for lab distribution)

```bash
cd SNBR_TMS_App/dist_macos
ditto -c -k --sequesterRsrc --keepParent SNBR_TMS_App.app SNBR_TMS_App-macOS.zip
```

Use `ditto` rather than `zip` — it preserves macOS metadata (the Info.plist
is already inside the bundle, but extended attributes survive too). Result:
`SNBR_TMS_App-macOS.zip`, typically 150–300 MB.

Send that file over a shared drive or USB stick. On the target Mac:

```bash
unzip SNBR_TMS_App-macOS.zip -d /Applications/
xattr -dr com.apple.quarantine /Applications/SNBR_TMS_App.app
open /Applications/SNBR_TMS_App.app
```

The `xattr` step is important — macOS flags anything downloaded or copied
from another machine as quarantined, and Gatekeeper will refuse to run an
unsigned bundle ("SNBR TMS App is damaged and can't be opened."). Stripping
the quarantine attribute clears the block. This is fine for a lab-internal
research tool; it is **not** a substitute for signing if you ever
distribute externally.

Alternative on the target Mac (no Terminal required):

> Right-click the `.app` → **Open** → **Open** in the confirmation dialog.
> macOS remembers this exception for the bundle.

### Option B — DMG installer (prettier, slightly more work)

```bash
brew install create-dmg
cd SNBR_TMS_App
create-dmg \
    --volname "SNBR TMS App" \
    --window-size 540 340 \
    --icon-size 96 \
    --icon "SNBR_TMS_App.app" 130 160 \
    --app-drop-link 410 160 \
    --hide-extension "SNBR_TMS_App.app" \
    dist_macos/SNBR_TMS_App-macOS.dmg \
    dist_macos/SNBR_TMS_App.app
```

The user mounts the DMG and drags the app icon onto the **Applications**
shortcut. They still have to clear the quarantine bit on first launch —
DMG doesn't sidestep Gatekeeper.

### Option C — Signed + notarized (only if you ship broadly)

If this tool ever leaves the lab network, you'll want a real signed and
notarized build so users don't see scary dialogs.

1. Enrol in the Apple Developer Program (~$99/year) and create a
   **Developer ID Application** certificate in Keychain.
2. Build with the cert identity baked into the spec:
   ```python
   exe = EXE(
       ...
       codesign_identity='Developer ID Application: Your Name (TEAMID)',
       entitlements_file='macos_build/entitlements.plist',
       ...
   )
   ```
   An entitlements file is only strictly required for hardened runtime; a
   minimal one:
   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0">
   <dict>
       <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
       <true/>
   </dict>
   </plist>
   ```
3. After building, notarize:
   ```bash
   ditto -c -k --keepParent dist_macos/SNBR_TMS_App.app dist_macos/SNBR_TMS_App.zip
   xcrun notarytool submit dist_macos/SNBR_TMS_App.zip \
       --apple-id you@example.com \
       --team-id TEAMID \
       --password "app-specific-password" \
       --wait
   xcrun stapler staple dist_macos/SNBR_TMS_App.app
   ```
4. Verify:
   ```bash
   spctl --assess --type execute -vv dist_macos/SNBR_TMS_App.app
   ```

For lab-internal use this is overkill — stick with Option A.

---

## Troubleshooting

**"App is damaged and can't be opened."**
Quarantine attribute on an unsigned bundle. `xattr -dr com.apple.quarantine /path/to/SNBR_TMS_App.app`.

**Double-click does nothing, no error.**
Run from Terminal to surface the crash: `/Applications/SNBR_TMS_App.app/Contents/MacOS/SNBR_TMS_App`. Missing dylibs, Tk errors, and hiddenimport gaps all print here.

**`ImportError: No module named tkinter`** at runtime.
Tk wasn't available in the Python you built with. Reinstall Python with Tk (see Prerequisites), rebuild.

**Matplotlib figures look blurry on Retina.**
The spec sets `NSHighResolutionCapable: True`. If you custom-edit the spec, keep that key.

**`saved_defaults.json` doesn't persist across app launches.**
This is handled. `core/user_settings.py` detects a frozen build and writes
settings to a per-user, writable location instead of inside the bundle —
on macOS that is `~/Library/Application Support/SNBR_TMS_App/saved_defaults.json`
(Windows uses `%APPDATA%\SNBR_TMS_App\`). The personal `saved_defaults.json`
is no longer bundled into the app, so each user starts with empty defaults and
their saved paths/exclusions persist across launches.

**Bundle is huge (600 MB+).**
Expected. matplotlib alone pulls in ~200 MB of fonts and backends. If you need to trim, the biggest wins come from stripping unused matplotlib backends (already excluded in the spec) and removing `pytest`/`IPython`/`notebook` (already excluded).

**Rebuild from scratch.**
```bash
rm -rf build_macos dist_macos
./macos_build/build.sh
```
(The script itself does this, so usually just re-running it is enough.)

**Switching between Windows and macOS builds.**
Each platform has its own spec. Don't ever run the Windows spec on Mac or vice versa — they bundle platform-specific runtime libraries that won't exist on the other OS.
