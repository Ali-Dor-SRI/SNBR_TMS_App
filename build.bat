@echo off
REM ============================================================
REM  Build SNBR TMS App as a single Windows .exe (--onefile).
REM  Run this from the SNBR_TMS_App directory on Windows.
REM  Output: dist\SNBR_TMS_App.exe
REM ============================================================
setlocal

echo ============================================
echo  Building SNBR TMS App (Windows, single-file)
echo ============================================
echo.

echo Installing requirements...
python -m pip install -r requirements.txt
python -m pip install pyinstaller
echo.

echo Running PyInstaller...
python -m PyInstaller --clean --noconfirm SNBR_TMS_App.spec
echo.

if exist "dist\SNBR_TMS_App.exe" (
    echo ============================================
    echo  Build complete!
    echo  Output: dist\SNBR_TMS_App.exe
    echo  Hand out that single .exe file.
    echo ============================================
) else (
    echo ERROR: dist\SNBR_TMS_App.exe was not produced. Check the log above.
    exit /b 1
)

pause
