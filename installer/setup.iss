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

; ── FTDI VCP driver (USB-to-serial for TEC, LDD, stage controllers) ─────────
; Covers: Meerstetter TEC-1089, Meerstetter LDD-1121, Newport NPC3SG piezo,
;         Thorlabs BSC203/MPC320 stage controllers (all use FTDI chips).
; Place CDM_Setup.exe in installer\redist\ before building.
; build_installer.bat downloads it automatically from FTDI's CDM page.
; FTDI explicitly permits redistribution of CDM drivers.
#define FTDISetupSrc "redist\CDM_Setup.exe"

; ── CH340 USB-serial driver (Arduino Nano, many serial adapters) ──────────
; Covers: Arduino Nano GPIO / LED wavelength selector.
; Place CH341SER.EXE in installer\redist\ before building.
; build_installer.bat downloads it automatically from WCH's site.
; WCH permits free redistribution of their VCP driver.
#define CH340SetupSrc "redist\CH341SER.EXE"

; ── Basler USB3 Vision camera driver MSIs (extracted from pylon Runtime) ──
; Covers: Basler acA1920-155um and all Basler USB3 area-scan cameras.
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

; ── NI R Series Multifunction RIO driver (sbRIO / NI 9637 FPGA) ─────────
; Covers: NI sbRIO (built-in EZ-500 FPGA), NI 9637 CompactRIO module.
; Online installer (~9 MB) — downloads ~200 MB of driver components from NI.
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

; ── NI-VISA Runtime (GPIB / USB TMC instrument communication) ────────────
; Covers: Keithley 2400/2450 SMU (GPIB), BNC 745 digital delay generator,
;         Rigol DP832 power supply (USB TMC fallback — pyvisa-py handles most
;         Rigol communication without NI-VISA).
; Optional — only needed for GPIB instruments or when pyvisa-py is
; insufficient (rare).  Most EZ-500 setups do not need this.
;
; NI permits royalty-free redistribution of the VISA runtime.
; Download from:
;   https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html
; Save as: installer\redist\ni-visa-runtime.exe
;
; Silent install: ni-visa-runtime.exe /q /AcceptLicenses yes
#define NIVISASrc "redist\ni-visa-runtime.exe"

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

; ── FTDI CDM driver (USB-to-serial: TEC, LDD, NPC3, Thorlabs) ──────────────
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

; ── NI-VISA Runtime (online installer) ────────────────────────────────────
; Optional — only bundled if the file exists in installer\redist\.
; Requires internet during installation (downloads ~400 MB from NI).
; NI permits redistribution of the VISA runtime.
Source: "{#NIVISASrc}"; DestDir: "{tmp}"; \
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
  StatusMsg: "Installing FTDI USB-serial driver (TEC, LDD, NPC3, Thorlabs)…"; \
  Check: ShouldInstallFTDI; \
  Flags: waituntilterminated runhidden skipifdoesntexist

; ── CH340 USB-serial driver (silent) ─────────────────────────────────────────
Filename: "{tmp}\CH341SER.EXE"; \
  Parameters: "/S"; \
  StatusMsg: "Installing CH340 USB-serial driver (Arduino Nano)…"; \
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
  StatusMsg: "Installing NI R Series RIO driver for sbRIO / NI 9637 (downloading…)"; \
  Check: ShouldInstallNIRIO; \
  Flags: waituntilterminated runhidden skipifdoesntexist

; ── NI-VISA Runtime (online installer, silent) ───────────────────────────────
Filename: "{tmp}\ni-visa-runtime.exe"; \
  Parameters: "/q /AcceptLicenses yes"; \
  StatusMsg: "Installing NI-VISA Runtime for GPIB/SMU instruments (downloading…)"; \
  Check: ShouldInstallNIVISA; \
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

  EZ-500 device → driver mapping:
    Basler acA1920-155um        → Basler USB3 Vision MSIs
    Meerstetter TEC-1089        → FTDI CDM driver
    Meerstetter LDD-1121        → FTDI CDM driver (same)
    Arduino Nano (CH340)        → CH340 driver
    Thorlabs BSC203 stage       → FTDI CDM driver (Thorlabs uses FTDI chips)
    Newport NPC3SG piezo        → FTDI CDM driver (same)
    NI sbRIO (built-in FPGA)    → NI R Series RIO driver
    Rigol DP832 (USB)           → Windows built-in USB TMC (no driver needed)
    Rigol DP832 (LAN)           → No driver needed (TCP/IP)
    Keithley SMU (GPIB)         → NI-VISA Runtime
  ══════════════════════════════════════════════════════════════════════════════ }

var
  DriverPage: TWizardPage;
  chkVCRedist: TNewCheckBox;
  chkFTDI:     TNewCheckBox;
  chkCH340:    TNewCheckBox;
  chkBasler:   TNewCheckBox;
  chkNIRIO:    TNewCheckBox;
  chkNIVISA:   TNewCheckBox;

{ ── Wizard page creation ─────────────────────────────────────────────────── }
procedure CreateDriverPage();
var
  lbl: TNewStaticText;
  sublbl: TNewStaticText;
  yPos: Integer;
begin
  DriverPage := CreateCustomPage(
    wpSelectTasks,
    'Driver Installation',
    'Select which hardware drivers to install.  All drivers are recommended ' +
    'for full EZ-500 hardware support.  Uncheck any you do not need.');

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
  chkFTDI.Caption := 'FTDI USB-serial driver — TEC-1089, LDD-1121, NPC3SG piezo, Thorlabs stage';
  chkFTDI.Checked := True;
  chkFTDI.Left    := 16;
  chkFTDI.Top     := yPos;
  chkFTDI.Width   := DriverPage.SurfaceWidth - 16;
  yPos := yPos + 22;

  chkCH340 := TNewCheckBox.Create(WizardForm);
  chkCH340.Parent  := DriverPage.Surface;
  chkCH340.Caption := 'CH340 USB-serial driver — Arduino Nano GPIO / LED wavelength selector';
  chkCH340.Checked := True;
  chkCH340.Left    := 16;
  chkCH340.Top     := yPos;
  chkCH340.Width   := DriverPage.SurfaceWidth - 16;
  yPos := yPos + 22;

  chkBasler := TNewCheckBox.Create(WizardForm);
  chkBasler.Parent  := DriverPage.Surface;
  chkBasler.Caption := 'Basler USB3 Vision camera driver — Basler acA1920-155um (TR camera)';
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
  chkNIRIO.Caption := 'NI R Series RIO driver — sbRIO / NI 9637 FPGA (~200 MB download)';
  chkNIRIO.Checked := True;
  chkNIRIO.Left    := 16;
  chkNIRIO.Top     := yPos;
  chkNIRIO.Width   := DriverPage.SurfaceWidth - 16;
  yPos := yPos + 22;

  chkNIVISA := TNewCheckBox.Create(WizardForm);
  chkNIVISA.Parent  := DriverPage.Surface;
  chkNIVISA.Caption := 'NI-VISA Runtime — Keithley SMU / GPIB instruments (~400 MB download)';
  chkNIVISA.Checked := False;
  chkNIVISA.Left    := 16;
  chkNIVISA.Top     := yPos;
  chkNIVISA.Width   := DriverPage.SurfaceWidth - 16;
  yPos := yPos + 16;

  { NI-VISA sub-label: explain when it is needed }
  sublbl := TNewStaticText.Create(WizardForm);
  sublbl.Parent   := DriverPage.Surface;
  sublbl.Caption  := '(Only needed for GPIB connections.  USB and LAN instruments work without it.)';
  sublbl.Font.Color := clGray;
  sublbl.Left     := 32;
  sublbl.Top      := yPos;
  sublbl.AutoSize := True;
  yPos := yPos + 32;

  { ── Footer note ────────────────────────────────────────────────────── }
  lbl := TNewStaticText.Create(WizardForm);
  lbl.Parent   := DriverPage.Surface;
  lbl.Caption  :=
    'All drivers are installed silently.  Each is idempotent — re-running ' +
    'the installer with a driver already present is a harmless no-op.' + #13#10 + #13#10 +
    'Note: The Rigol DP832 power supply uses Windows built-in USB TMC drivers ' +
    '(no separate install needed).  LAN connections work out of the box.' + #13#10 + #13#10 +
    'Skipped drivers can be installed later by re-running this installer ' +
    'or downloading them individually:' + #13#10 +
    '  FTDI:     ftdichip.com/drivers/vcp-drivers  (TEC, LDD, NPC3, Thorlabs)' + #13#10 +
    '  CH340:    wch-ic.com/downloads/CH341SER_EXE.html  (Arduino Nano)' + #13#10 +
    '  Basler:   baslerweb.com/downloads  (pylon Runtime — USB3 Vision cameras)' + #13#10 +
    '  NI-RIO:   ni.com > Drivers > NI R Series Multifunction RIO' + #13#10 +
    '  NI-VISA:  ni.com > Drivers > NI-VISA';
  lbl.Left     := 0;
  lbl.Top      := yPos;
  lbl.AutoSize := False;
  lbl.Width    := DriverPage.SurfaceWidth;
  lbl.Height   := 160;
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

function ShouldInstallNIVISA(): Boolean;
begin
  Result := chkNIVISA.Checked;
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

function HasNIVISA(): Boolean;
begin
  Result := RegKeyExists(HKLM, 'SOFTWARE\National Instruments\NI-VISA\CurrentVersion')
         or RegKeyExists(HKLM64, 'SOFTWARE\National Instruments\NI-VISA\CurrentVersion');
end;

{ ── Post-install verification ────────────────────────────────────────────────
  Called after installation completes.  Reports which selected drivers
  installed successfully, which failed, and which were skipped by the user.
}
procedure PostInstallSummary();
var
  summary: String;
  issues: String;
  skipped: String;
  builtin: String;
  msg: String;
begin
  summary  := '';
  issues   := '';
  skipped  := '';
  builtin  := '';

  { ── VC++ Runtime ───────────────────────────────────────────────────── }
  if not chkVCRedist.Checked then
    skipped := skipped + '  -  Visual C++ 2022 Runtime (skipped by user)' + #13#10
  else if HasVCRedist() then
    summary := summary + '  OK  Visual C++ 2022 Runtime' + #13#10
  else
    issues := issues + '  !!  Visual C++ Runtime — may not have installed correctly' + #13#10;

  { ── FTDI ───────────────────────────────────────────────────────────── }
  if not chkFTDI.Checked then
    skipped := skipped + '  -  FTDI USB-serial driver (skipped by user)' + #13#10
  else if HasFTDIDriver() then
    summary := summary + '  OK  FTDI USB-serial driver (TEC, LDD, NPC3, Thorlabs)' + #13#10
  else
    issues := issues + '  !!  FTDI driver — re-run installer or install from ftdichip.com' + #13#10;

  { ── CH340 ──────────────────────────────────────────────────────────── }
  if not chkCH340.Checked then
    skipped := skipped + '  -  CH340 USB-serial driver (skipped by user)' + #13#10
  else if HasCH340Driver() then
    summary := summary + '  OK  CH340 USB-serial driver (Arduino Nano)' + #13#10
  else
    issues := issues + '  !!  CH340 driver — re-run installer or install from wch-ic.com' + #13#10;

  { ── Basler ─────────────────────────────────────────────────────────── }
  if not chkBasler.Checked then
    skipped := skipped + '  -  Basler USB3 Vision camera driver (skipped by user)' + #13#10
  else if HasBaslerDriver() then
    summary := summary + '  OK  Basler USB3 Vision camera driver' + #13#10
  else
    issues := issues + '  !!  Basler camera driver — re-run installer or install pylon Runtime' + #13#10;

  { ── NI-RIO ─────────────────────────────────────────────────────────── }
  if not chkNIRIO.Checked then
    skipped := skipped + '  -  NI R Series RIO driver (skipped by user)' + #13#10
  else if HasNIRIO() then
    summary := summary + '  OK  NI R Series RIO driver (sbRIO / NI 9637 FPGA)' + #13#10
  else
    issues := issues +
      '  !!  NI-RIO driver — installation may have failed (requires internet)' + #13#10 +
      '     Download manually:' + #13#10 +
      '     ni.com > Drivers > NI R Series Multifunction RIO' + #13#10;

  { ── NI-VISA ────────────────────────────────────────────────────────── }
  if not chkNIVISA.Checked then
    skipped := skipped + '  -  NI-VISA Runtime (skipped — only needed for GPIB)' + #13#10
  else if HasNIVISA() then
    summary := summary + '  OK  NI-VISA Runtime (GPIB / SMU instruments)' + #13#10
  else
    issues := issues +
      '  !!  NI-VISA Runtime — installation may have failed (requires internet)' + #13#10 +
      '     Download manually: ni.com > Drivers > NI-VISA' + #13#10;

  { ── Built-in (no install needed) ───────────────────────────────────── }
  builtin :=
    'Devices that need no driver installation:' + #13#10 +
    '  OK  Rigol DP832 power supply (Windows built-in USB TMC / LAN)' + #13#10;

  { ── Build the final message ─────────────────────────────────────────── }
  if (issues = '') and (skipped = '') then
  begin
    MsgBox(
      'SanjINSIGHT is installed and ready!' + #13#10#13#10 +
      'Drivers installed:' + #13#10 +
      summary + #13#10 +
      builtin,
      mbInformation, MB_OK);
  end
  else if issues = '' then
  begin
    MsgBox(
      'SanjINSIGHT is installed and ready!' + #13#10#13#10 +
      'Drivers installed:' + #13#10 +
      summary + #13#10 +
      builtin + #13#10 +
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
    msg := msg + #13#10 + builtin + #13#10 +
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
