; installer/setup.iss
; Inno Setup 6 script — wraps the PyInstaller one-folder bundle into a
; single Windows installer .exe.
;
; ── Building ─────────────────────────────────────────────────────────────────
; Use build_installer.bat (downloads vc_redist automatically, then calls iscc):
;
;   cd installer
;   build_installer.bat 1.1.2
;
; Or manually:
;   1. Place vc_redist.x64.exe in installer\redist\
;      (download from https://aka.ms/vs/17/release/vc_redist.x64.exe)
;   2. Run PyInstaller:  pyinstaller installer\sanjinsight.spec
;   3. Build installer:  iscc /DAppVersion=1.1.2 installer\setup.iss
;
; Output: installer_output\SanjINSIGHT-Setup-{AppVersion}.exe
;
; ── CI ────────────────────────────────────────────────────────────────────────
; GitHub Actions (.github/workflows/build-installer.yml) generates a fresh copy
; of this script with the correct version injected and runs it automatically.
; The committed copy below is identical except for the AppVersion placeholder.

; ── Version (pass with /DAppVersion=x.y.z on the command line) ───────────────
#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif

#define AppName      "SanjINSIGHT"
#define AppPublisher "Microsanj, LLC"
#define AppURL       "https://microsanj.com"
#define AppExeName   "SanjINSIGHT.exe"

; ── VC++ Redistributable prerequisite ────────────────────────────────────────
; Place vc_redist.x64.exe in installer\redist\ before building.
; build_installer.bat downloads it automatically.
; The installer bundles it and runs it silently on the end-user machine if the
; VC++ 2015-2022 runtime is not already installed.
#define VCRedistSrc "redist\vc_redist.x64.exe"

; ── FTDI VCP driver (USB-to-serial for Meerstetter TEC-1089/LDD-1121) ──────
; Place CDM_Setup.exe in installer\redist\ before building.
; build_installer.bat downloads it automatically from FTDI's CDM page.
; The installer bundles it and runs it silently if FTDI VCP is not installed.
; FTDI explicitly permits redistribution of CDM drivers.
#define FTDISetupSrc "redist\CDM_Setup.exe"

; ── CH340 USB-serial driver (Arduino Nano, many serial adapters) ──────────
; Place CH341SER.EXE in installer\redist\ before building.
; build_installer.bat downloads it automatically from WCH's site.
; Many clone Arduino boards and USB-serial adapters use the CH340/CH341 chip.
; WCH permits free redistribution of their VCP driver.
#define CH340SetupSrc "redist\CH341SER.EXE"

; ── Basler pylon Runtime (USB3 Vision camera driver) ─────────────────────
; Place the Basler pylon Runtime Redistributable .exe in installer\redist\.
; build_installer.bat provides download instructions (manual download required
; due to Basler's download portal requiring acceptance of terms).
;
; We install ONLY the USB3 camera driver component — pypylon (bundled in the
; PyInstaller package) already includes the pylon C++ runtime and GenTL
; transport layer producers.  The missing piece is the Windows kernel-level
; USB camera driver that makes Basler cameras visible to the OS.
;
; Basler's EULA explicitly permits royalty-free redistribution of the pylon
; Runtime Redistributable.
;
; Silent install: pylon_Runtime_x.x.x.exe /install=USB_Camera_Driver /quiet
#define PylonRuntimeSrc "redist\Basler_pylon_Runtime.exe"

[Setup]
; {A1B2C3D4…} — unique GUID identifies this app for Windows Add/Remove Programs.
; Do NOT change this GUID — changing it breaks in-place upgrades.
AppId               ={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName             ={#AppName}
AppVersion          ={#AppVersion}
AppVerName          ={#AppName} {#AppVersion}
AppPublisher        ={#AppPublisher}
AppPublisherURL     ={#AppURL}
AppSupportURL       =https://microsanj.com/support
AppUpdatesURL       =https://github.com/edward-mcnair/sanjinsight/releases

; Installation paths
DefaultDirName      ={autopf}\Microsanj\{#AppName}
DefaultGroupName    =Microsanj\{#AppName}

; Branding — reference the project-level ICO directly so there is a single
; source of truth and no risk of installer/assets/sanjinsight.ico going stale.
SetupIconFile       =..\assets\app-icon.ico
LicenseFile         =..\LICENSE
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} {#AppVersion}

; Output
OutputDir           =..\installer_output
OutputBaseFilename  =SanjINSIGHT-Setup-{#AppVersion}

; Compression (lzma2/ultra64 gives the best ratio; ~10 min on first build, fast after cache)
Compression         =lzma2/ultra64
SolidCompression    =yes

; UI
WizardStyle         =modern
WizardSizePercent   =120

; Require admin rights (needed to write to Program Files, register in Add/Remove Programs,
; and run the VC++ redistributable which writes to protected registry paths)
PrivilegesRequired  =admin

; Windows 10 minimum (build 17763 = RS5, October 2018 Update)
MinVersion          =10.0.17763

; 64-bit only — matches our PyInstaller x64 build
ArchitecturesAllowed              =x64compatible
ArchitecturesInstallIn64BitMode   =x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
  GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; ── PyInstaller one-folder bundle ─────────────────────────────────────────────
; All files, preserving directory structure.
Source: "..\dist\SanjINSIGHT\*"; DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

; ── Microsoft Visual C++ 2015-2022 Redistributable (x64) ─────────────────────
; Bundled so end users never need to find and install it manually.
; Microsoft allows redistribution under the Visual Studio license terms.
; build_installer.bat downloads this automatically from:
;   https://aka.ms/vs/17/release/vc_redist.x64.exe
Source: "{#VCRedistSrc}"; DestDir: "{tmp}"; \
  Flags: deleteafterinstall

; ── FTDI CDM driver (USB-to-serial for Meerstetter TEC / LDD) ───────────────
; FTDI permits redistribution of the CDM (Combined Driver Model) package.
; build_installer.bat downloads CDM_Setup.exe to installer\redist\ automatically.
; Always bundled — installed unconditionally even if hardware is not present,
; so devices plugged in later work immediately without re-running the installer.
Source: "{#FTDISetupSrc}"; DestDir: "{tmp}"; \
  Flags: deleteafterinstall skipifsourcedoesntexist

; ── CH340/CH341 driver (Arduino Nano, USB-serial adapters) ──────────────
; WCH permits free redistribution of their VCP driver.
; build_installer.bat downloads CH341SER.EXE to installer\redist\ automatically.
; Always bundled — installed unconditionally.
Source: "{#CH340SetupSrc}"; DestDir: "{tmp}"; \
  Flags: deleteafterinstall skipifsourcedoesntexist

; ── Basler pylon Runtime (USB3 Vision camera driver) ──────────────────────
; Basler permits royalty-free redistribution of the pylon Runtime.
; Only the USB camera kernel driver component is installed — pypylon bundles
; the rest.  Always bundled — installed unconditionally.
Source: "{#PylonRuntimeSrc}"; DestDir: "{tmp}"; \
  Flags: deleteafterinstall skipifsourcedoesntexist

[Dirs]
; Ensure writable directories exist at install time so the app can write to them
; without requesting elevation at runtime.
Name: "{app}\logs"
Name: "{app}\profiles\user"

[Icons]
Name: "{group}\{#AppName}";           Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";     Filename: "{app}\{#AppExeName}"; \
  Tasks: desktopicon

[Registry]
; Store version so updater.py can read it without querying Add/Remove Programs
Root: HKCU; Subkey: "Software\Microsanj\SanjINSIGHT"; \
  ValueType: string; ValueName: "Version";     ValueData: "{#AppVersion}"; \
  Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Microsanj\SanjINSIGHT"; \
  ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"

[Run]
; ══════════════════════════════════════════════════════════════════════════════
; ALL drivers are installed UNCONDITIONALLY — even if the hardware is not
; currently connected.  This ensures devices plugged in later (or not powered
; during install) work immediately without re-running the installer.
;
; Each driver installer is idempotent: re-running it when the driver is
; already present is a harmless no-op (exits quickly with success).
; ══════════════════════════════════════════════════════════════════════════════

; ── Step 1: Visual C++ Runtime (silent) ──────────────────────────────────────
; /quiet         — no UI
; /norestart     — suppress any reboot prompt (installer handles this if needed)
; Always runs — the VC++ installer itself detects if already present and
; exits immediately with code 0 (no-op).
Filename: "{tmp}\vc_redist.x64.exe"; \
  Parameters: "/quiet /norestart"; \
  StatusMsg: "Installing Visual C++ 2022 Runtime…"; \
  Flags: waituntilterminated runhidden skipifdoesntexist

; ── Step 2: FTDI VCP driver (silent) ─────────────────────────────────────────
; /S              — NSIS silent mode (no UI)
; Always runs — CDM_Setup detects existing install and exits cleanly.
Filename: "{tmp}\CDM_Setup.exe"; \
  Parameters: "/S"; \
  StatusMsg: "Installing FTDI USB-serial driver…"; \
  Flags: waituntilterminated runhidden skipifdoesntexist

; ── Step 3: CH340 USB-serial driver (silent) ─────────────────────────────────
; /S              — NSIS silent mode (no UI)
; Always runs — CH341SER detects existing install and exits cleanly.
Filename: "{tmp}\CH341SER.EXE"; \
  Parameters: "/S"; \
  StatusMsg: "Installing CH340 USB-serial driver…"; \
  Flags: waituntilterminated runhidden skipifdoesntexist

; ── Step 4: Basler pylon USB3 Vision driver (silent, minimal) ────────────────
; /install=USB_Camera_Driver  — install ONLY the USB3 camera kernel driver
; /quiet                      — no UI at all
; Always runs — pylon Runtime detects existing components and skips them.
; pypylon (bundled) provides the C++ runtime and GenTL transport producers.
; This step installs only the Windows kernel driver that makes Basler
; cameras visible to the OS.  Without it, EnumerateDevices() returns empty.
Filename: "{tmp}\Basler_pylon_Runtime.exe"; \
  Parameters: "/install=USB_Camera_Driver /quiet"; \
  StatusMsg: "Installing Basler USB3 Vision camera driver…"; \
  Flags: waituntilterminated runhidden skipifdoesntexist

; ── Step 5: Launch SanjINSIGHT (optional checkbox on Finish page) ────────────
Filename: "{app}\{#AppExeName}"; \
  Description: "{cm:LaunchProgram,{#AppName}}"; \
  Flags: nowait postinstall skipifsilent

[Code]
{ ══════════════════════════════════════════════════════════════════════════════
  Driver detection functions are NO LONGER used as install gates.
  All drivers are installed unconditionally (each installer is idempotent).
  These functions are retained only for the post-install verification dialog.
  ══════════════════════════════════════════════════════════════════════════════ }

function HasVCRedist(): Boolean;
var
  dwInstalled: Cardinal;
begin
  Result := RegQueryDWordValue(HKLM,
      'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64',
      'Installed', dwInstalled) and (dwInstalled = 1);
end;

function HasFTDIDriver(): Boolean;
begin
  Result := RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\FTSER2K');
end;

function HasCH340Driver(): Boolean;
begin
  Result := RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\CH341SER_A64')
         or RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\CH341SER');
end;

function HasBaslerDriver(): Boolean;
begin
  Result := RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\BvcUsbU3v')
         or RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\pylonusb')
         or RegKeyExists(HKLM, 'SOFTWARE\Basler\pylon');
end;

{ ── Post-install verification and guidance ───────────────────────────────────
  Called after installation completes.  Verifies that all bundled drivers
  installed successfully and checks for optional SDKs (NI-VISA, NI-RIO)
  that cannot be bundled due to vendor licensing.
}
procedure PostInstallSummary();
var
  summary: String;
  issues: String;
  optional: String;
  niVisaKey, niRioKey: String;
begin
  summary := '';
  issues := '';
  optional := '';

  { ── Verify bundled driver installation ──────────────────────────────── }
  if HasVCRedist() then
    summary := summary + '  ✓  Visual C++ 2022 Runtime' + #13#10
  else
    issues := issues + '  ✗  Visual C++ Runtime — may not have installed correctly' + #13#10;

  if HasFTDIDriver() then
    summary := summary + '  ✓  FTDI USB-serial driver (Meerstetter TEC/LDD)' + #13#10
  else
    issues := issues + '  ✗  FTDI driver — re-run installer or install from ftdichip.com' + #13#10;

  if HasCH340Driver() then
    summary := summary + '  ✓  CH340 USB-serial driver (Arduino Nano)' + #13#10
  else
    issues := issues + '  ✗  CH340 driver — re-run installer or install from wch-ic.com' + #13#10;

  if HasBaslerDriver() then
    summary := summary + '  ✓  Basler USB3 Vision camera driver' + #13#10
  else
    issues := issues + '  ✗  Basler camera driver — re-run installer or install pylon Runtime' + #13#10;

  { ── Check optional SDKs (cannot be bundled) ─────────────────────────── }
  niVisaKey := 'SOFTWARE\National Instruments\NI-VISA\CurrentVersion';
  if not RegKeyExists(HKLM, niVisaKey) and
     not RegKeyExists(HKLM64, niVisaKey) then
    optional := optional +
      '  •  NI-VISA (only needed for Keithley SMU / GPIB instruments)' + #13#10 +
      '     https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html' + #13#10;

  niRioKey := 'SOFTWARE\National Instruments\RIO';
  if not RegKeyExists(HKLM, niRioKey) and
     not RegKeyExists(HKLM64, niRioKey) then
    optional := optional +
      '  •  NI-RIO (only needed for NI 9637 FPGA via PCIe)' + #13#10 +
      '     https://www.ni.com/en/support/downloads/drivers/download.ni-rio.html' + #13#10;

  { ── Build the final message ─────────────────────────────────────────── }
  if issues = '' then
  begin
    if optional <> '' then
      MsgBox(
        'SanjINSIGHT is installed and ready!' + #13#10#13#10 +
        'Drivers installed:' + #13#10 +
        summary + #13#10 +
        'Optional SDKs (install only if you have the hardware):' + #13#10 +
        optional,
        mbInformation, MB_OK)
    else
      MsgBox(
        'SanjINSIGHT is installed and ready!' + #13#10#13#10 +
        'All drivers installed:' + #13#10 +
        summary,
        mbInformation, MB_OK);
  end
  else
  begin
    MsgBox(
      'SanjINSIGHT is installed.' + #13#10#13#10 +
      'Drivers installed:' + #13#10 +
      summary + #13#10 +
      'Issues detected:' + #13#10 +
      issues + #13#10 +
      'The application will still launch, but affected hardware ' +
      'may not connect until the drivers are installed.',
      mbWarning, MB_OK);
  end;
end;

{ Called by Inno Setup after the main installation step completes. }
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    PostInstallSummary();
end;
