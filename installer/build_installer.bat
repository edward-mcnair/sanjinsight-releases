@echo off
:: installer/build_installer.bat
:: One-command build for the SanjINSIGHT Windows installer.
::
:: Usage:
::   cd installer
::   build_installer.bat 1.1.2
::
:: What this script does:
::   1. Downloads vc_redist.x64.exe into installer\redist\ (skipped if already there)
::   2. Runs PyInstaller to build the one-folder application bundle
::   3. Runs Inno Setup to produce SanjINSIGHT-Setup-{version}.exe
::
:: Requirements (must be on PATH or at default install locations):
::   - Python with all deps installed:  pip install -r ..\requirements.txt
::   - PyInstaller:                     pip install pyinstaller
::   - Inno Setup 6:                    https://jrsoftware.org/isinfo.php
::   - UPX (optional, for compression): https://upx.github.io/

setlocal EnableDelayedExpansion

:: ── Version argument ──────────────────────────────────────────────────────────
set VERSION=%~1
if "%VERSION%"=="" (
    echo Usage: build_installer.bat ^<version^>
    echo Example: build_installer.bat 1.1.2
    exit /b 1
)

:: ── Locate project root (one level above this script) ────────────────────────
set SCRIPT_DIR=%~dp0
set PROJECT_DIR=%SCRIPT_DIR%..
pushd "%PROJECT_DIR%"

echo.
echo ============================================================
echo  SanjINSIGHT Installer Build  v%VERSION%
echo ============================================================
echo.

:: ── Step 1: Ensure pip dependencies are current ───────────────────────────────
echo [1/4] Installing / updating Python dependencies...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: pip install failed. Check requirements.txt and your Python environment.
    popd & exit /b 1
)
echo       Done.
echo.

:: ── Step 2: Download VC++ Redistributable if not present ─────────────────────
set REDIST_DIR=%SCRIPT_DIR%redist
set REDIST_EXE=%REDIST_DIR%\vc_redist.x64.exe

if not exist "%REDIST_EXE%" (
    echo [2/4] Downloading Visual C++ 2022 Redistributable...
    if not exist "%REDIST_DIR%" mkdir "%REDIST_DIR%"
    powershell -NoProfile -Command ^
      "Invoke-WebRequest -Uri 'https://aka.ms/vs/17/release/vc_redist.x64.exe' -OutFile '%REDIST_EXE%'"
    if errorlevel 1 (
        echo ERROR: Failed to download vc_redist.x64.exe.
        echo        Download it manually from https://aka.ms/vs/17/release/vc_redist.x64.exe
        echo        and place it at:  installer\redist\vc_redist.x64.exe
        popd & exit /b 1
    )
    echo       Downloaded to %REDIST_EXE%
) else (
    echo [2/4] vc_redist.x64.exe already present — skipping download.
)
echo.

:: ── Step 3: Build the PyInstaller bundle ─────────────────────────────────────
echo [3/4] Building application bundle with PyInstaller...
pyinstaller installer\sanjinsight.spec --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    popd & exit /b 1
)
echo       Bundle written to dist\SanjINSIGHT\
echo.

:: ── Step 4: Build the Inno Setup installer ───────────────────────────────────
echo [4/4] Building installer with Inno Setup...

:: Try common Inno Setup install locations
set ISCC=""
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
    set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
)
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" (
    set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
)
:: Also try PATH
where iscc >nul 2>&1 && set ISCC=iscc

if %ISCC%=="" (
    echo ERROR: Inno Setup 6 not found.
    echo        Download from https://jrsoftware.org/isinfo.php and install.
    popd & exit /b 1
)

%ISCC% /DAppVersion=%VERSION% installer\setup.iss
if errorlevel 1 (
    echo ERROR: Inno Setup build failed.
    popd & exit /b 1
)

echo.
echo ============================================================
echo  Build complete!
echo  Output: installer_output\SanjINSIGHT-Setup-%VERSION%.exe
echo ============================================================
echo.

popd
endlocal
