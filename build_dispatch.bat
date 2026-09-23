@echo off
REM ============================================================
REM  Build SNBR Report Dispatch as a single Windows .exe (--onefile).
REM  Run this from the SNBR_TMS_App directory on Windows.
REM  Output: dist\SNBR_Report_Dispatch.exe
REM
REM  The application mark is a generated file, so it is rendered before
REM  PyInstaller runs and confirmed to be inside the finished executable
REM  afterwards -- see scripts/build_assets.py for why both steps are needed.
REM ============================================================
setlocal

set EXE=dist\SNBR_Report_Dispatch.exe

echo ============================================
echo  Building SNBR Report Dispatch (Windows, single-file)
echo ============================================
echo.

echo Installing requirements...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: installing requirements failed.
    exit /b 1
)
python -m pip install pyinstaller
if errorlevel 1 (
    echo ERROR: installing PyInstaller failed.
    exit /b 1
)
echo.

REM Remove any earlier executable first. PyInstaller's --clean clears its cache
REM and build\ but not dist\, and it writes the executable *before* it embeds
REM the icon -- so a leftover binary can outlive a failed build and be mistaken
REM for a good one.
if exist "%EXE%" del /q "%EXE%"

echo Rendering the application mark...
python scripts\generate_dispatch_logo.py
if errorlevel 1 (
    echo ERROR: could not render the dispatch mark ^(icons\logo_dispatch\dispatch.ico^).
    exit /b 1
)
echo.

echo Running PyInstaller...
python -m PyInstaller --clean --noconfirm SNBR_Report_Dispatch.spec
if errorlevel 1 (
    echo ERROR: PyInstaller failed. Anything now in dist\ is incomplete -- do not ship it.
    exit /b 1
)
echo.

echo Verifying the mark reached the executable...
python -m scripts.build_assets --verify-exe "%EXE%" --mark dispatch
if errorlevel 1 (
    echo ERROR: the build produced an executable without its mark.
    exit /b 1
)
echo.

REM Explorer caches icons per file path and does not reliably notice an .exe
REM being replaced in place, so a correct binary can still be drawn with the
REM icon this filename had on its first build. Nudge the shell.
echo Refreshing the Explorer icon cache for the new executable...
python -m scripts.build_assets --refresh-shell "%EXE%"
echo.

echo ============================================
echo  Build complete!
echo  Output: %EXE%
echo  Install on the machine that has the enrolment workbook.
echo ============================================

pause
