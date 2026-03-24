@echo off
:: installer/build_installer.bat
:: One-command build for the SanjINSIGHT Windows installer.
::
:: Usage (from anywhere — script finds the project root automatically):
::   build_installer.bat 1.1.2
::
:: What this script does:
::   1. Resolves the active Python interpreter and prints it so you can verify it
::   2. pip install -r requirements.txt  (uses the SAME Python as step 3)
::   3. Downloads vc_redist.x64.exe      (skipped if already present)
::   4. python -m PyInstaller            (uses the SAME Python as step 2)
::   5. Inno Setup iscc                  (produces the .exe installer)
::
:: Key design choice: everything uses "python -m pip" and "python -m PyInstaller"
:: rather than bare "pip" / "pyinstaller" commands.  This guarantees that the
:: same Python interpreter is used for both installing packages and building
:: the bundle — mismatched interpreters are the #1 cause of a ~13 MB output.
::
:: Requirements:
::   - Python 3.10+ on PATH                 (check: python --version)
::   - Inno Setup 6 installed               https://jrsoftware.org/isinfo.php
::   - UPX on PATH (optional, compresses)   https://upx.github.io/

setlocal EnableDelayedExpansion

:: ── Version argument ──────────────────────────────────────────────────────────
set VERSION=%~1
if "%VERSION%"=="" (
    echo.
    echo Usage: build_installer.bat ^<version^>
    echo Example: build_installer.bat 1.1.2
    echo.
    exit /b 1
)

:: ── Locate project root (one level above installer\) ─────────────────────────
set SCRIPT_DIR=%~dp0
:: Remove trailing backslash from SCRIPT_DIR
if "%SCRIPT_DIR:~-1%"=="\" set SCRIPT_DIR=%SCRIPT_DIR:~0,-1%
set PROJECT_DIR=%SCRIPT_DIR%\..
pushd "%PROJECT_DIR%"

echo.
echo ============================================================
echo  SanjINSIGHT Installer Build  v%VERSION%
echo ============================================================

:: ── Resolve the active Python interpreter ────────────────────────────────────
:: We use "python" from PATH.  Print it so the user can verify it is correct.
for /f "delims=" %%i in ('python -c "import sys; print(sys.executable)"') do (
    set PYTHON_EXE=%%i
)
if "%PYTHON_EXE%"=="" (
    echo.
    echo ERROR: 'python' not found on PATH.
    echo        Install Python 3.10+ and add it to your PATH.
    popd & exit /b 1
)
echo.
echo Python interpreter: %PYTHON_EXE%
echo.

:: ── Step 1: Install / update Python dependencies ─────────────────────────────
echo [1/4] Installing Python dependencies with the above interpreter...
python -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo.
    echo ERROR: pip install failed.
    echo        Check requirements.txt and try running manually:
    echo          python -m pip install -r requirements.txt
    popd & exit /b 1
)
echo       Done.
echo.

:: ── Step 1b: Install optional GitHub-only drivers (not on PyPI) ──────────────
:: These are hardware protocol libraries that must be installed from GitHub.
:: Failures are non-fatal — the app falls back to simulated mode without them.
echo [1b/4] Installing optional hardware drivers from GitHub...
python -m pip install git+https://github.com/meerstetter/pyMeCom --quiet 2>nul && (
    echo       [OK] pyMeCom installed ^(Meerstetter TEC-1089 / LDD-1121^)
) || (
    echo       [SKIP] pyMeCom unavailable — TEC will use simulated mode
)
python -m pip install git+https://github.com/tspspi/pydp832 --quiet 2>nul && (
    echo       [OK] pydp832 installed ^(Rigol DP832 native LAN driver^)
) || (
    echo       [SKIP] pydp832 unavailable — Rigol DP832 will use VISA mode
)
echo.

:: ── Step 2: Download VC++ Redistributable if not present ─────────────────────
set REDIST_DIR=%SCRIPT_DIR%\redist
set REDIST_EXE=%REDIST_DIR%\vc_redist.x64.exe

if not exist "%REDIST_EXE%" (
    echo [2/4] Downloading Visual C++ 2022 Redistributable...
    if not exist "%REDIST_DIR%" mkdir "%REDIST_DIR%"
    powershell -NoProfile -Command ^
      "Invoke-WebRequest -Uri 'https://aka.ms/vs/17/release/vc_redist.x64.exe' -OutFile '%REDIST_EXE%'" 2>&1
    if errorlevel 1 (
        echo.
        echo ERROR: Download failed.
        echo        Download manually from: https://aka.ms/vs/17/release/vc_redist.x64.exe
        echo        Save to: installer\redist\vc_redist.x64.exe
        popd & exit /b 1
    )
    echo       Saved to: %REDIST_EXE%
) else (
    echo [2/4] vc_redist.x64.exe already present — skipping download.
)
echo.

:: ── Step 2b: Download FTDI CDM driver if not present ───────────────────────
set FTDI_EXE=%REDIST_DIR%\CDM_Setup.exe

if not exist "%FTDI_EXE%" (
    echo [2b/4] Downloading FTDI CDM driver ^(USB-serial for Meerstetter TEC/LDD^)...
    if not exist "%REDIST_DIR%" mkdir "%REDIST_DIR%"
    :: FTDI CDM v2.12.36.4 WHQL Certified — unified VCP + D2XX driver.
    :: FTDI permits redistribution of CDM drivers without prior authorization.
    :: If this URL stops working, download manually from:
    ::   https://ftdichip.com/drivers/vcp-drivers/
    :: Save the setup .exe as: installer\redist\CDM_Setup.exe
    powershell -NoProfile -Command ^
      "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://ftdichip.com/wp-content/uploads/2024/11/CDM-v2.12.36.4-WHQL-Certified.exe' -OutFile '%FTDI_EXE%'" 2>&1
    if errorlevel 1 (
        echo.
        echo WARNING: FTDI CDM download failed.
        echo          The installer will still build, but without the FTDI driver.
        echo          To bundle it, download manually from:
        echo            https://ftdichip.com/drivers/vcp-drivers/
        echo          Save the CDM setup .exe as: installer\redist\CDM_Setup.exe
        echo.
    ) else (
        echo       Saved to: %FTDI_EXE%
    )
) else (
    echo [2b/4] CDM_Setup.exe already present — skipping download.
)
echo.

:: ── Step 3: Build the PyInstaller bundle ─────────────────────────────────────
echo [3/4] Building application bundle...
echo       (using: %PYTHON_EXE%)
echo.

:: Use "python -m PyInstaller" — CRITICAL: ensures the SAME Python that has
:: numpy/cv2/Qt5 installed is the one building the bundle.
python -m PyInstaller installer\sanjinsight.spec --noconfirm
if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller build failed.  Check the output above.
    echo.
    echo Common causes:
    echo   - The spec printed an ERROR about missing critical packages.
    echo     Fix: the Python shown above is not the right one, or you need
    echo          to run:  python -m pip install -r requirements.txt
    popd & exit /b 1
)

:: Sanity-check: warn if the output looks too small (indicates a broken build)
set DIST_DIR=dist\SanjINSIGHT
if exist "%DIST_DIR%\SanjINSIGHT.exe" (
    for %%F in ("%DIST_DIR%\SanjINSIGHT.exe") do set EXE_SIZE=%%~zF
    :: 5 MB threshold — a correct build launcher is typically 1-3 MB, but if
    :: the whole folder is missing the scientific stack the .exe is ~1 MB.
    :: We check the _dir_ size indirectly by counting files.
    for /f %%C in ('dir /s /b "%DIST_DIR%" 2^>nul ^| find /c /v ""') do set FILE_COUNT=%%C
    if !FILE_COUNT! LSS 100 (
        echo.
        echo WARNING: dist\SanjINSIGHT\ contains only !FILE_COUNT! files.
        echo          A full build typically has 300+ files.
        echo          The bundle may be incomplete — check PyInstaller output above.
        echo.
    ) else (
        echo       Bundle OK: !FILE_COUNT! files in dist\SanjINSIGHT\
    )
) else (
    echo WARNING: dist\SanjINSIGHT\SanjINSIGHT.exe not found after build.
)
echo.

:: ── Step 4: Build the Inno Setup installer ───────────────────────────────────
echo [4/4] Building installer with Inno Setup...

set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe"       set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
where iscc >nul 2>&1 && set ISCC=iscc

if "%ISCC%"=="" (
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
