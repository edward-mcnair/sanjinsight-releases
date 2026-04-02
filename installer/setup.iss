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

; ── CH340/CH341 driver (Arduino Nano, USB-serial adapters) ──────────────
; WCH permits free redistribution of their VCP driver.
; build_installer.bat downloads CH341SER.EXE to installer\redist\ automatically.
Source: "{#CH340SetupSrc}"; DestDir: "{tmp}"; \
  Flags: deleteafterinstall skipifsourcedoesntexist; Check: NeedsCH340Driver

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
  Flags: waituntilterminated runhidden; \
  Check: NeedsVCRedist

; ── Step 2: FTDI VCP driver (silent, runs before app launches) ──────────────
; /S              — NSIS silent mode (no UI)
; FTDI CDM setup is an NSIS-based installer that supports /S for silent install.
Filename: "{tmp}\CDM_Setup.exe"; \
  Parameters: "/S"; \
  StatusMsg: "Installing FTDI USB-serial driver (required by Meerstetter TEC/LDD)…"; \
  Flags: waituntilterminated runhidden; \
  Check: NeedsFTDIDriver

; ── Step 3: CH340 USB-serial driver (silent, runs before app launches) ──────
; /S              — NSIS silent mode (no UI)
; CH341SER.EXE from WCH supports /S for silent install.
Filename: "{tmp}\CH341SER.EXE"; \
  Parameters: "/S"; \
  StatusMsg: "Installing CH340 USB-serial driver (required by Arduino Nano)…"; \
  Flags: waituntilterminated runhidden skipifdoesntexist; \
  Check: NeedsCH340Driver

; ── Step 4: Launch SanjINSIGHT (optional checkbox on Finish page) ────────────
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
  { Skip if FTDI driver is already installed }
  if RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\FTSER2K') then
  begin
    Result := False;
    Exit;
  end;
  { Skip if CDM_Setup.exe was not bundled (skipifsourcedoesntexist in [Files]) }
  Result := FileExists(ExpandConstant('{tmp}\CDM_Setup.exe'));
end;

{ ── CH340/CH341 VCP driver detection ─────────────────────────────────────────
  The WCH CH340/CH341 USB-serial chip registers a kernel service named
  CH341SER_A64 (64-bit) or a device class under USB\VID_1A86.
  Returns True when the CH340 driver needs to be installed.
}
function NeedsCH340Driver(): Boolean;
begin
  { Skip if CH341 driver is already installed (64-bit service) }
  if RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\CH341SER_A64') then
  begin
    Result := False;
    Exit;
  end;
  { Also check the older 32-bit service name }
  if RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\CH341SER') then
  begin
    Result := False;
    Exit;
  end;
  { Skip if CH341SER.EXE was not bundled }
  Result := FileExists(ExpandConstant('{tmp}\CH341SER.EXE'));
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
  niVisaKey, niRioKey: String;
  dummy: String;
begin
  missing := '';

  { NI-VISA — needed only for Keithley SMU and GPIB instruments.
    Not required for cameras, TECs, stages, or Arduino. }
  niVisaKey := 'SOFTWARE\National Instruments\NI-VISA\CurrentVersion';
  if not RegKeyExists(HKLM, niVisaKey) and
     not RegKeyExists(HKLM64, niVisaKey) then
    missing := missing +
      '• NI-VISA (only needed for Keithley SMU / GPIB instruments)' + #13#10 +
      '  https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html' + #13#10#13#10;

  { NI-RIO — needed only for NI 9637 FPGA via PCIe.
    Not required for BNC 745 or USB DAQ. }
  niRioKey := 'SOFTWARE\National Instruments\RIO';
  if not RegKeyExists(HKLM, niRioKey) and
     not RegKeyExists(HKLM64, niRioKey) then
    missing := missing +
      '• NI-RIO drivers (only needed for NI 9637 FPGA via PCIe)' + #13#10 +
      '  https://www.ni.com/en/support/downloads/drivers/download.ni-rio.html' + #13#10#13#10;

  if missing <> '' then
    MsgBox(
      'SanjINSIGHT is installed and ready to run.' + #13#10#13#10 +
      'All essential drivers (USB-serial, camera) have been installed.' + #13#10#13#10 +
      'The following optional SDKs were not detected. ' +
      'Install only if you have the matching hardware:' + #13#10#13#10 +
      missing +
      'You can also run  Settings → Hardware Setup  inside the app at any time ' +
      'for step-by-step setup guidance.',
      mbInformation, MB_OK)
  else
    MsgBox(
      'SanjINSIGHT is installed and ready to run!' + #13#10#13#10 +
      'All drivers have been installed. Launch the application and open ' +
      'Device Manager to connect your hardware.',
      mbInformation, MB_OK);
end;

{ Called by Inno Setup after the main installation step completes. }
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    CheckHardwareSDKs();
end;
