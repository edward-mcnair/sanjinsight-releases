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
  Flags: deleteafterinstall; Check: NeedsVCRedist

; ── FTDI CDM driver (USB-to-serial for Meerstetter TEC / LDD) ───────────────
; FTDI permits redistribution of the CDM (Combined Driver Model) package.
; build_installer.bat downloads CDM_Setup.exe to installer\redist\ automatically.
Source: "{#FTDISetupSrc}"; DestDir: "{tmp}"; \
  Flags: deleteafterinstall skipifsourcedoesntexist; Check: NeedsFTDIDriver

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
; ── Step 1: Visual C++ Runtime (silent, runs before app launches) ─────────────
; /quiet         — no UI
; /norestart     — suppress any reboot prompt (installer handles this if needed)
Filename: "{tmp}\vc_redist.x64.exe"; \
  Parameters: "/quiet /norestart"; \
  StatusMsg: "Installing Visual C++ 2022 Runtime (required by Qt5)…"; \
  Flags: waitprogress runhidden; \
  Check: NeedsVCRedist

; ── Step 2: FTDI VCP driver (silent, runs before app launches) ──────────────
; /S              — NSIS silent mode (no UI)
; FTDI CDM setup is an NSIS-based installer that supports /S for silent install.
Filename: "{tmp}\CDM_Setup.exe"; \
  Parameters: "/S"; \
  StatusMsg: "Installing FTDI USB-serial driver (required by Meerstetter TEC/LDD)…"; \
  Flags: waituntilterminated runhidden skipifdoesntexist; \
  Check: NeedsFTDIDriver

; ── Step 3: Launch SanjINSIGHT (optional checkbox on Finish page) ────────────
Filename: "{app}\{#AppExeName}"; \
  Description: "{cm:LaunchProgram,{#AppName}}"; \
  Flags: nowait postinstall skipifsilent

[Code]
{ ── VC++ Redistributable detection ──────────────────────────────────────────
  The VC++ 2015-2022 x64 runtime registers Installed=1 under:
    HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64
  Returns True when the runtime needs to be installed (key absent or Installed≠1).
}
function NeedsVCRedist(): Boolean;
var
  dwInstalled: Cardinal;
begin
  if RegQueryDWordValue(HKLM,
      'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64',
      'Installed', dwInstalled) then
    Result := (dwInstalled <> 1)
  else
    Result := True;  { Registry key absent → runtime not installed }
end;

{ ── FTDI VCP driver detection ──────────────────────────────────────────────
  The FTDI VCP (Virtual COM Port) driver registers a kernel service named
  FTSER2K.  If the service exists, the driver is already installed.
  Returns True when the FTDI driver needs to be installed.
}
function NeedsFTDIDriver(): Boolean;
begin
  Result := not RegKeyExists(HKLM,
    'SYSTEM\CurrentControlSet\Services\FTSER2K');
end;

{ ── Hardware SDK prerequisite guidance ───────────────────────────────────────
  Called after installation completes.  Checks for optional hardware SDKs that
  SanjINSIGHT can use but that cannot be bundled (vendor licensing terms).
  Shows a single informational dialog listing any that are missing.
  The user can dismiss it and install them later — everything inside the app
  still works in simulated mode until the SDKs are present.
}
procedure CheckHardwareSDKs();
var
  missing: String;
  pylonKey, niVisaKey, niRioKey: String;
  dummy: String;
begin
  missing := '';

  { Basler pylon SDK — key written by the pylon installer }
  pylonKey := 'SOFTWARE\Basler\pylon';
  if not RegKeyExists(HKLM, pylonKey) then
    missing := missing +
      '• Basler pylon 8 SDK (USB3 Vision camera driver)' + #13#10 +
      '  https://www.baslerweb.com/en-us/downloads/software-downloads/' + #13#10#13#10;

  { NI-VISA — key written by the NI-VISA installer }
  niVisaKey := 'SOFTWARE\National Instruments\NI-VISA\CurrentVersion';
  if not RegKeyExists(HKLM, niVisaKey) and
     not RegKeyExists(HKLM64, niVisaKey) then
    missing := missing +
      '• NI-VISA (Keithley/GPIB/USB instrument communication)' + #13#10 +
      '  https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html' + #13#10#13#10;

  { NI-RIO — key written by the NI-RIO / NI-DAQmx installer }
  niRioKey := 'SOFTWARE\National Instruments\RIO';
  if not RegKeyExists(HKLM, niRioKey) and
     not RegKeyExists(HKLM64, niRioKey) then
    missing := missing +
      '• NI-RIO drivers (NI 9637 FPGA module)' + #13#10 +
      '  https://www.ni.com/en/support/downloads/drivers/download.ni-rio.html' + #13#10#13#10;

  if missing <> '' then
    MsgBox(
      'SanjINSIGHT is installed and ready to run.' + #13#10#13#10 +
      'The following optional hardware SDKs were not detected on this machine. ' +
      'SanjINSIGHT will work in simulated mode without them. ' +
      'Install only the SDKs for hardware you own:' + #13#10#13#10 +
      missing +
      'You can also run  Settings → Hardware Setup  inside the app at any time ' +
      'for step-by-step setup guidance.',
      mbInformation, MB_OK);
end;

{ Called by Inno Setup after the main installation step completes. }
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    CheckHardwareSDKs();
end;
