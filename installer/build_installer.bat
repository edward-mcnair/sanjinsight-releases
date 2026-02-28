@echo off
REM ============================================================
REM  build_installer.bat
REM  Builds the SanjINSIGHT Windows installer in one step.
REM
REM  Run this from the project root:
REM      installer\build_installer.bat
REM
REM  Prerequisites (must be installed first):
REM      pip install pyinstaller
REM      Inno Setup 6  https://jrsoftware.org/isinfo.php
REM      UPX (optional, for smaller exe)  https://upx.github.io
REM ============================================================

setlocal enabledelayedexpansion

echo.
echo ============================================================
echo   SanjINSIGHT Installer Build
echo ============================================================
echo.

REM ── Check we are in the project root ─────────────────────────
if not exist "main_app.py" (
    echo ERROR: Run this script from the project root directory.
    echo        cd C:\path\to\sanjinsight
    echo        installer\build_installer.bat
    pause
    exit /b 1
)

REM ── Read version from version.py ─────────────────────────────
for /f "tokens=3 delims== " %%V in ('findstr /R "^__version__" version.py') do (
    set APP_VERSION=%%~V
)
echo Building version: %APP_VERSION%
echo.

REM ── Step 1: Clean previous build ─────────────────────────────
echo [1/4] Cleaning previous build...
if exist "dist\SanjINSIGHT"     rmdir /s /q "dist\SanjINSIGHT"
if exist "build\SanjINSIGHT"    rmdir /s /q "build\SanjINSIGHT"
if exist "installer_output"     rmdir /s /q "installer_output"
mkdir installer_output
echo       Done.
echo.

REM ── Step 2: PyInstaller ──────────────────────────────────────
echo [2/4] Running PyInstaller (this takes 2-5 minutes)...
pyinstaller installer\sanjinsight.spec --noconfirm --clean

if %ERRORLEVEL% neq 0 (
    echo.
    echo ERROR: PyInstaller failed. See output above for details.
    echo Common causes:
    echo   - Missing package: pip install -r requirements.txt
    echo   - Missing icon:    installer\assets\sanjinsight.ico
    pause
    exit /b 1
)
echo       Done.
echo.

REM ── Step 3: Verify PyInstaller output ────────────────────────
echo [3/4] Verifying bundle...
if not exist "dist\SanjINSIGHT\SanjINSIGHT.exe" (
    echo ERROR: SanjINSIGHT.exe not found in dist\SanjINSIGHT\
    pause
    exit /b 1
)
echo       SanjINSIGHT.exe found.

REM Count bundled files for a sanity check
set FILE_COUNT=0
for /r "dist\SanjINSIGHT" %%F in (*) do set /a FILE_COUNT+=1
echo       Bundle contains %FILE_COUNT% files.
echo.

REM ── Step 4: Inno Setup ───────────────────────────────────────
echo [4/4] Running Inno Setup...

REM Try both common install locations
set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"

if not exist %ISCC% (
    echo ERROR: Inno Setup 6 not found.
    echo Download from: https://jrsoftware.org/isinfo.php
    echo Then re-run this script.
    pause
    exit /b 1
)

%ISCC% "installer\sanjinsight.iss"

if %ERRORLEVEL% neq 0 (
    echo.
    echo ERROR: Inno Setup failed. See output above.
    pause
    exit /b 1
)

REM ── Summary ───────────────────────────────────────────────────
echo.
echo ============================================================
echo   BUILD SUCCESSFUL
echo ============================================================
echo.
echo   Installer: installer_output\SanjINSIGHT-Setup-%APP_VERSION%.exe
echo.
echo   Next steps:
echo     1. Test the installer on a clean Windows machine
echo     2. Upload to GitHub:
echo        Releases - Draft new release - attach the .exe
echo.

REM Open the output folder in Explorer
explorer installer_output

pause
