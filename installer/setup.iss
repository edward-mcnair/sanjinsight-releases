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

; ── Basler USB3 Vision camera driver MSIs (extracted from pylon Runtime) ──
; These three MSIs were extracted from the Basler pylon 26.03 Runtime
; Redistributable.  Together they provide the Windows kernel-level USB3
; Vision camera driver that makes Basler cameras visible to the OS.
; Total: ~4 MB (vs 1.3 GB for the full Runtime installer).
;
; pypylon (bundled in the PyInstaller package) already includes the pylon
; C++ runtime.  These MSIs add only the missing kernel driver layer.
;
; Basler's EULA explicitly permits royalty-free redistribution of pylon
; Runtime components.
;
; Silent install: msiexec /i <file>.msi /quiet /norestart
#define PylonUSBDriverMsi  "redist\pylon_USB_Camera_Driver.msi"
#define PylonUSBTransport  "redist\USB_Transport_Layer_x64.msi"
#define PylonUSBGenTL      "redist\GenTL_Producer_USB_x64.msi"

; ── NI R Series Multifunction RIO driver (NI 9637 FPGA via PCIe) ──────────
; Online installer (~9 MB) for the NI R Series Multifunction RIO driver.
; Requires internet during installation — the online installer downloads
; ~200 MB of driver components from NI's servers.
;
; NI classifies the R Series driver as "Driver Interface Software" which
; permits royalty-free redistribution under NI's standard EULA.
; The nifpga Python package is a thin ctypes wrapper around NiFpga.dll
; and only needs the driver runtime (not the full NI-RIO SDK).
;
; Download from:
;   https://www.ni.com/en/support/downloads/drivers/download.ni-r-series-multifunction-rio.html
; Save as: installer\redist\ni-rio-online-installer.exe
;
; Silent install: ni-rio-online-installer.exe /q /AcceptLicenses yes
#define NIRIOSetupSrc "redist\ni-rio-online-installer.exe"

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

; ── Basler USB3 Vision camera driver MSIs ─────────────────────────────────
; Basler permits royalty-free redistribution of pylon Runtime components.
; Three MSIs provide the complete USB3 Vision camera driver stack.
; Always bundled — installed unconditionally.
Source: "{#PylonUSBDriverMsi}"; DestDir: "{tmp}"; \
  Flags: deleteafterinstall skipifsourcedoesntexist
Source: "{#PylonUSBTransport}"; DestDir: "{tmp}"; \
  Flags: deleteafterinstall skipifsourcedoesntexist
Source: "{#PylonUSBGenTL}"; DestDir: "{tmp}"; \
  Flags: deleteafterinstall skipifsourcedoesntexist

; ── NI R Series RIO driver (online installer) ─────────────────────────────
; Optional — only bundled if the file exists in installer\redist\.
; Requires internet during installation (downloads ~200 MB from NI).
; NI permits redistribution of driver installers.
Source: "{#NIRIOSetupSrc}"; DestDir: "{tmp}"; \
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
; Driver installation — controlled by the "Driver Selection" wizard page.
; All drivers are checked (selected) by default.  The user can uncheck any
; driver to skip it.  Each driver installer is idempotent: re-running it
; when already installed is a harmless no-op.
;
; Check: functions read the checkbox state from the custom wizard page.
; ══════════════════════════════════════════════════════════════════════════════

; ── Visual C++ Runtime (silent) ──────────────────────────────────────────────
Filename: "{tmp}\vc_redist.x64.exe"; \
  Parameters: "/quiet /norestart"; \
  StatusMsg: "Installing Visual C++ 2022 Runtime…"; \
  Check: ShouldInstallVCRedist; \
  Flags: waituntilterminated runhidden skipifdoesntexist

; ── FTDI VCP driver (silent) ─────────────────────────────────────────────────
Filename: "{tmp}\CDM_Setup.exe"; \
  Parameters: "/S"; \
  StatusMsg: "Installing FTDI USB-serial driver…"; \
  Check: ShouldInstallFTDI; \
  Flags: waituntilterminated runhidden skipifdoesntexist

; ── CH340 USB-serial driver (silent) ─────────────────────────────────────────
Filename: "{tmp}\CH341SER.EXE"; \
  Parameters: "/S"; \
  StatusMsg: "Installing CH340 USB-serial driver…"; \
  Check: ShouldInstallCH340; \
  Flags: waituntilterminated runhidden skipifdoesntexist

; ── Basler USB3 Vision camera driver (three MSIs, silent) ────────────────────
Filename: "msiexec.exe"; \
  Parameters: "/i ""{tmp}\pylon_USB_Camera_Driver.msi"" /quiet /norestart"; \
  StatusMsg: "Installing Basler USB3 Vision camera driver (1/3)…"; \
  Check: ShouldInstallBasler; \
  Flags: waituntilterminated runhidden skipifdoesntexist

Filename: "msiexec.exe"; \
  Parameters: "/i ""{tmp}\USB_Transport_Layer_x64.msi"" /quiet /norestart"; \
  StatusMsg: "Installing Basler USB3 Vision transport layer (2/3)…"; \
  Check: ShouldInstallBasler; \
  Flags: waituntilterminated runhidden skipifdoesntexist

Filename: "msiexec.exe"; \
  Parameters: "/i ""{tmp}\GenTL_Producer_USB_x64.msi"" /quiet /norestart"; \
  StatusMsg: "Installing Basler USB3 Vision GenTL producer (3/3)…"; \
  Check: ShouldInstallBasler; \
  Flags: waituntilterminated runhidden skipifdoesntexist

; ── NI R Series RIO driver (online installer, silent) ────────────────────────
Filename: "{tmp}\ni-rio-online-installer.exe"; \
  Parameters: "/q /AcceptLicenses yes"; \
  StatusMsg: "Installing NI R Series RIO driver (downloading from NI…)"; \
  Check: ShouldInstallNIRIO; \
  Flags: waituntilterminated runhidden skipifdoesntexist

; ── Launch SanjINSIGHT (optional checkbox on Finish page) ────────────────────
Filename: "{app}\{#AppExeName}"; \
  Description: "{cm:LaunchProgram,{#AppName}}"; \
  Flags: nowait postinstall skipifsilent

[Code]
{ ══════════════════════════════════════════════════════════════════════════════
  Custom "Driver Selection" wizard page
  ──────────────────────────────────────
  Displayed after the Tasks page.  Lists every driver the installer can
  install, grouped into "Bundled (offline)" and "Internet required".
  All checkboxes are checked by default — the user can uncheck any driver
  to skip it.
  ══════════════════════════════════════════════════════════════════════════════ }

var
  DriverPage: TWizardPage;
  chkVCRedist: TNewCheckBox;
  chkFTDI:     TNewCheckBox;
  chkCH340:    TNewCheckBox;
  chkBasler:   TNewCheckBox;
  chkNIRIO:    TNewCheckBox;

{ ── Wizard page creation ─────────────────────────────────────────────────── }
procedure CreateDriverPage();
var
  lbl: TNewStaticText;
  yPos: Integer;
begin
  DriverPage := CreateCustomPage(
    wpSelectTasks,
    'Driver Installation',
    'Select which hardware drivers to install.  All drivers are recommended ' +
    'for full hardware support.  Uncheck any you do not need.');

  yPos := 0;

  { ── Section: Bundled drivers (offline) ─────────────────────────────── }
  lbl := TNewStaticText.Create(WizardForm);
  lbl.Parent   := DriverPage.Surface;
  lbl.Caption  := 'Bundled drivers (no internet required):';
  lbl.Font.Style := [fsBold];
  lbl.Left     := 0;
  lbl.Top      := yPos;
  lbl.AutoSize := True;
  yPos := yPos + 22;

  chkVCRedist := TNewCheckBox.Create(WizardForm);
  chkVCRedist.Parent  := DriverPage.Surface;
  chkVCRedist.Caption := 'Visual C++ 2022 Runtime (x64) — required by Qt5 and numpy';
  chkVCRedist.Checked := True;
  chkVCRedist.Left    := 16;
  chkVCRedist.Top     := yPos;
  chkVCRedist.Width   := DriverPage.SurfaceWidth - 16;
  yPos := yPos + 22;

  chkFTDI := TNewCheckBox.Create(WizardForm);
  chkFTDI.Parent  := DriverPage.Surface;
  chkFTDI.Caption := 'FTDI USB-serial driver — Meerstetter TEC-1089 / LDD-1121';
  chkFTDI.Checked := True;
  chkFTDI.Left    := 16;
  chkFTDI.Top     := yPos;
  chkFTDI.Width   := DriverPage.SurfaceWidth - 16;
  yPos := yPos + 22;

  chkCH340 := TNewCheckBox.Create(WizardForm);
  chkCH340.Parent  := DriverPage.Surface;
  chkCH340.Caption := 'CH340 USB-serial driver — Arduino Nano, serial adapters';
  chkCH340.Checked := True;
  chkCH340.Left    := 16;
  chkCH340.Top     := yPos;
  chkCH340.Width   := DriverPage.SurfaceWidth - 16;
  yPos := yPos + 22;

  chkBasler := TNewCheckBox.Create(WizardForm);
  chkBasler.Parent  := DriverPage.Surface;
  chkBasler.Caption := 'Basler USB3 Vision camera driver — Basler area-scan cameras';
  chkBasler.Checked := True;
  chkBasler.Left    := 16;
  chkBasler.Top     := yPos;
  chkBasler.Width   := DriverPage.SurfaceWidth - 16;
  yPos := yPos + 38;

  { ── Section: Internet-required drivers ─────────────────────────────── }
  lbl := TNewStaticText.Create(WizardForm);
  lbl.Parent   := DriverPage.Surface;
  lbl.Caption  := 'Internet-required drivers (downloaded during install):';
  lbl.Font.Style := [fsBold];
  lbl.Left     := 0;
  lbl.Top      := yPos;
  lbl.AutoSize := True;
  yPos := yPos + 22;

  chkNIRIO := TNewCheckBox.Create(WizardForm);
  chkNIRIO.Parent  := DriverPage.Surface;
  chkNIRIO.Caption := 'NI R Series RIO driver — NI 9637 FPGA (~200 MB download)';
  chkNIRIO.Checked := True;
  chkNIRIO.Left    := 16;
  chkNIRIO.Top     := yPos;
  chkNIRIO.Width   := DriverPage.SurfaceWidth - 16;
  yPos := yPos + 32;

  { ── Footer note ────────────────────────────────────────────────────── }
  lbl := TNewStaticText.Create(WizardForm);
  lbl.Parent   := DriverPage.Surface;
  lbl.Caption  :=
    'All drivers are installed silently.  Each is idempotent — re-running ' +
    'the installer with a driver already present is a harmless no-op.' + #13#10 + #13#10 +
    'Skipped drivers can be installed later by re-running this installer ' +
    'or downloading them individually:' + #13#10 +
    '  • FTDI:   ftdichip.com/drivers/vcp-drivers' + #13#10 +
    '  • CH340:  wch-ic.com/downloads/CH341SER_EXE.html' + #13#10 +
    '  • Basler: baslerweb.com/downloads (pylon Runtime)' + #13#10 +
    '  • NI-RIO: ni.com/en/support/downloads/drivers/download.ni-r-series-multifunction-rio.html';
  lbl.Left     := 0;
  lbl.Top      := yPos;
  lbl.AutoSize := False;
  lbl.Width    := DriverPage.SurfaceWidth;
  lbl.Height   := 130;
  lbl.Font.Color := clGray;
end;

{ ── Check functions for [Run] entries ────────────────────────────────────── }
{ These return True when the user has checked the corresponding checkbox on
  the Driver Selection page.  Used by [Run] Check: clauses. }

function ShouldInstallVCRedist(): Boolean;
begin
  Result := chkVCRedist.Checked;
end;

function ShouldInstallFTDI(): Boolean;
begin
  Result := chkFTDI.Checked;
end;

function ShouldInstallCH340(): Boolean;
begin
  Result := chkCH340.Checked;
end;

function ShouldInstallBasler(): Boolean;
begin
  Result := chkBasler.Checked;
end;

function ShouldInstallNIRIO(): Boolean;
begin
  Result := chkNIRIO.Checked;
end;

{ ══════════════════════════════════════════════════════════════════════════════
  Driver detection — used only by PostInstallSummary to verify results.
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

function HasNIRIO(): Boolean;
begin
  Result := RegKeyExists(HKLM, 'SOFTWARE\National Instruments\RIO')
         or RegKeyExists(HKLM64, 'SOFTWARE\National Instruments\RIO');
end;

{ ── Post-install verification ────────────────────────────────────────────────
  Called after installation completes.  Reports which selected drivers
  installed successfully, which failed, and which were skipped by the user.
  Also checks for optional SDKs (NI-VISA) not bundled in the installer.
}
procedure PostInstallSummary();
var
  summary: String;
  issues: String;
  skipped: String;
  optional: String;
  msg: String;
  niVisaKey: String;
begin
  summary  := '';
  issues   := '';
  skipped  := '';
  optional := '';

  { ── VC++ Runtime ───────────────────────────────────────────────────── }
  if not chkVCRedist.Checked then
    skipped := skipped + '  -  Visual C++ 2022 Runtime (skipped by user)' + #13#10
  else if HasVCRedist() then
    summary := summary + '  ✓  Visual C++ 2022 Runtime' + #13#10
  else
    issues := issues + '  ✗  Visual C++ Runtime — may not have installed correctly' + #13#10;

  { ── FTDI ───────────────────────────────────────────────────────────── }
  if not chkFTDI.Checked then
    skipped := skipped + '  -  FTDI USB-serial driver (skipped by user)' + #13#10
  else if HasFTDIDriver() then
    summary := summary + '  ✓  FTDI USB-serial driver (Meerstetter TEC/LDD)' + #13#10
  else
    issues := issues + '  ✗  FTDI driver — re-run installer or install from ftdichip.com' + #13#10;

  { ── CH340 ──────────────────────────────────────────────────────────── }
  if not chkCH340.Checked then
    skipped := skipped + '  -  CH340 USB-serial driver (skipped by user)' + #13#10
  else if HasCH340Driver() then
    summary := summary + '  ✓  CH340 USB-serial driver (Arduino Nano)' + #13#10
  else
    issues := issues + '  ✗  CH340 driver — re-run installer or install from wch-ic.com' + #13#10;

  { ── Basler ─────────────────────────────────────────────────────────── }
  if not chkBasler.Checked then
    skipped := skipped + '  -  Basler USB3 Vision camera driver (skipped by user)' + #13#10
  else if HasBaslerDriver() then
    summary := summary + '  ✓  Basler USB3 Vision camera driver' + #13#10
  else
    issues := issues + '  ✗  Basler camera driver — re-run installer or install pylon Runtime' + #13#10;

  { ── NI-RIO ─────────────────────────────────────────────────────────── }
  if not chkNIRIO.Checked then
    skipped := skipped + '  -  NI R Series RIO driver (skipped by user)' + #13#10
  else if HasNIRIO() then
    summary := summary + '  ✓  NI R Series RIO driver (NI 9637 FPGA)' + #13#10
  else
    issues := issues +
      '  ✗  NI-RIO driver — installation may have failed (requires internet)' + #13#10 +
      '     Download manually:' + #13#10 +
      '     ni.com/en/support/downloads/drivers/download.ni-r-series-multifunction-rio.html' + #13#10;

  { ── Optional SDKs (not bundled) ────────────────────────────────────── }
  niVisaKey := 'SOFTWARE\National Instruments\NI-VISA\CurrentVersion';
  if not RegKeyExists(HKLM, niVisaKey) and
     not RegKeyExists(HKLM64, niVisaKey) then
    optional := optional +
      '  •  NI-VISA (only needed for Keithley SMU / GPIB instruments)' + #13#10 +
      '     ni.com/en/support/downloads/drivers/download.ni-visa.html' + #13#10;

  { ── Build the final message ─────────────────────────────────────────── }
  if (issues = '') and (skipped = '') then
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
  else if issues = '' then
  begin
    MsgBox(
      'SanjINSIGHT is installed and ready!' + #13#10#13#10 +
      'Drivers installed:' + #13#10 +
      summary + #13#10 +
      'Skipped by user:' + #13#10 +
      skipped + #13#10 +
      'You can install skipped drivers later by re-running this installer.',
      mbInformation, MB_OK);
  end
  else
  begin
    { Build message with only non-empty sections }
    msg := 'SanjINSIGHT is installed.' + #13#10#13#10 +
      'Drivers installed:' + #13#10 + summary;
    if issues <> '' then
      msg := msg + #13#10 + 'Issues detected:' + #13#10 + issues;
    if skipped <> '' then
      msg := msg + #13#10 + 'Skipped by user:' + #13#10 + skipped;
    msg := msg + #13#10 +
      'The application will still launch, but affected hardware ' +
      'may not connect until the missing drivers are installed.';
    MsgBox(msg, mbWarning, MB_OK);
  end;
end;

{ ── Wizard initialization ────────────────────────────────────────────────── }
procedure InitializeWizard();
begin
  CreateDriverPage();
end;

{ Called by Inno Setup after the main installation step completes. }
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    PostInstallSummary();
end;
