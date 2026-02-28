# Building the SanjINSIGHT Windows Installer

This guide walks through producing `SanjINSIGHT-Setup-1.0.0.exe` from source.
The build must be run on a **Windows 10 or 11** machine (64-bit).

---

## Overview

The build uses two tools in sequence:

```
Source code  →  [PyInstaller]  →  dist/SanjINSIGHT/  →  [Inno Setup]  →  SanjINSIGHT-Setup-1.0.0.exe
```

| Tool | What it does |
|---|---|
| **PyInstaller** | Bundles Python + all dependencies into a self-contained folder |
| **Inno Setup** | Wraps that folder into a single `.exe` installer with Start menu, shortcuts, and uninstaller |

---

## One-time setup (do this once on the build machine)

### 1. Install Python 3.10+ (64-bit)
Download from [python.org](https://python.org). Check **"Add Python to PATH"** during install.

### 2. Clone the repository
```
git clone https://github.com/edward-mcnair/sanjinsight.git
cd sanjinsight
```

Or download the ZIP from GitHub and extract it.

### 3. Install Python dependencies
```
pip install -r requirements.txt
pip install pyinstaller
```

### 4. Install Inno Setup 6
Download from [jrsoftware.org/isinfo.php](https://jrsoftware.org/isinfo.php) and install.
The default install location (`C:\Program Files (x86)\Inno Setup 6\`) is expected by the build script.

### 5. Install UPX (optional — makes the installer ~30% smaller)
Download from [upx.github.io](https://upx.github.io), extract, and add to your PATH.

### 6. Create the application icon
See `installer/assets/README.md` for instructions on creating `sanjinsight.ico`.
Place the finished `.ico` file at `installer/assets/sanjinsight.ico`.

---

## Building the installer

### Automated (recommended)
From the project root in Command Prompt (run as Administrator):
```
installer\build_installer.bat
```

The script will:
1. Clean the previous build
2. Run PyInstaller (2–5 minutes)
3. Run Inno Setup
4. Open `installer_output\` in Explorer when done

The finished installer will be at:
```
installer_output\SanjINSIGHT-Setup-1.0.0.exe
```

### Manual (step by step)
If you prefer to run the steps separately:

```
REM Step 1 — PyInstaller
pyinstaller installer\sanjinsight.spec --noconfirm --clean

REM Step 2 — Inno Setup
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\sanjinsight.iss
```

---

## Troubleshooting

### "Module not found" during PyInstaller
Add the missing module to `hiddenimports` in `installer/sanjinsight.spec`.

### App crashes on launch after install
Run from Command Prompt temporarily to see errors:
```
"C:\Program Files\Microsanj\SanjINSIGHT\SanjINSIGHT.exe"
```
Or set `console=True` in `sanjinsight.spec`, rebuild, and check the console output.

### Missing DLL errors on target PC
The target PC may need the **Microsoft Visual C++ Redistributable**:
[Download from Microsoft](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)

### Icon not showing in Explorer after install
Windows icon cache may need refreshing. The user can right-click Desktop → Refresh, or log out and back in.

### Antivirus flags the installer
This is common with PyInstaller-built executables. Options:
- Submit the installer to your antivirus vendor for whitelisting
- Sign the installer with a code signing certificate (see below)

---

## Code signing (recommended before wide release)

An unsigned installer will trigger a **"Windows protected your PC"** SmartScreen warning
on first run. A code signing certificate suppresses this.

**To get a certificate:**
1. Purchase from DigiCert, Sectigo, or GlobalSign (~$200–400/year)
2. Install the certificate on your build machine
3. Sign after building:
   ```
   signtool sign /a /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 ^
     "installer_output\SanjINSIGHT-Setup-1.0.0.exe"
   ```

For beta testing with a small known group, SmartScreen warnings are acceptable —
testers can click "More info → Run anyway".

---

## Releasing a new version

1. Update `version.py` — change `__version__` and `BUILD_DATE`
2. Update `installer/version_info.txt` — change both `filevers` and `prodvers` tuples
3. Update `installer/sanjinsight.iss` — change `#define AppVersion`
4. Update `CHANGELOG.md` — add the new release section
5. Run `installer\build_installer.bat`
6. Test the installer on a clean machine
7. Commit, tag, and push to GitHub:
   ```
   git add -A
   git commit -m "Release v1.0.1"
   git tag -a v1.0.1 -m "Release v1.0.1"
   git push origin main --tags
   ```
8. On GitHub: **Releases → Draft new release → attach the .exe**
9. The in-app update checker notifies users automatically

---

## What the installer does

When a user runs `SanjINSIGHT-Setup-1.0.0.exe`:

1. Shows the Inno Setup wizard (welcome, install location, shortcuts)
2. Installs to `C:\Program Files\Microsanj\SanjINSIGHT\`
3. Creates a Start menu entry under `Microsanj\SanjINSIGHT`
4. Optionally creates a desktop shortcut
5. Registers the uninstaller in Windows Settings → Apps
6. Preserves `config.yaml` if upgrading (keeps COM ports / driver settings)
7. Offers to launch the app immediately after install

When a user runs the **new version installer** to upgrade:
- Inno Setup detects the existing installation via the AppId
- Overwrites all application files
- Leaves `config.yaml` untouched (the user's hardware settings are preserved)
- The uninstaller updates to the new version
