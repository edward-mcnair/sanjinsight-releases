; installer/sanjinsight.iss
; Inno Setup 6 script for SanjINSIGHT
;
; Produces: SanjINSIGHT-Setup-1.0.0.exe
;
; Requirements:
;   - Inno Setup 6  https://jrsoftware.org/isinfo.php
;   - PyInstaller output already in ..\dist\SanjINSIGHT\
;
; Run:  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" sanjinsight.iss

#define AppName      "SanjINSIGHT"
#define AppVersion   "1.0.0"
#define AppPublisher "Microsanj, LLC"
#define AppURL       "https://microsanj.com"
#define AppExeName   "SanjINSIGHT.exe"
#define AppCopyright "Copyright (c) 2026 Microsanj, LLC"

; Output installer filename
#define InstallerName "SanjINSIGHT-Setup-" + AppVersion

[Setup]
; ── Identity ──────────────────────────────────────────────────────────────────
AppId               = {{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName             = {#AppName}
AppVersion          = {#AppVersion}
AppVerName          = {#AppName} {#AppVersion}
AppPublisher        = {#AppPublisher}
AppPublisherURL     = {#AppURL}
AppSupportURL       = https://microsanj.com/support
AppUpdatesURL       = https://github.com/edward-mcnair/sanjinsight/releases
AppCopyright        = {#AppCopyright}

; ── Install location ──────────────────────────────────────────────────────────
; Installs to C:\Program Files\Microsanj\SanjINSIGHT\
DefaultDirName      = {autopf}\Microsanj\{#AppName}
DefaultGroupName    = Microsanj\{#AppName}
AllowNoIcons        = no

; ── Output ────────────────────────────────────────────────────────────────────
OutputDir           = ..\installer_output
OutputBaseFilename  = {#InstallerName}
SetupIconFile       = assets\sanjinsight.ico

; ── Compression ───────────────────────────────────────────────────────────────
Compression         = lzma2/ultra64
SolidCompression    = yes
LZMANumBlockThreads = 4

; ── Appearance ────────────────────────────────────────────────────────────────
WizardStyle         = modern
WizardSizePercent   = 110
DisableWelcomePage  = no
; Optional: custom header image (493x58 pixels, BMP)
; WizardImageFile   = assets\installer_banner.bmp
; WizardSmallImageFile = assets\installer_icon.bmp

; ── Privileges ────────────────────────────────────────────────────────────────
; PrivilegesRequired = admin  ensures install to Program Files
PrivilegesRequired  = admin
PrivilegesRequiredOverridesAllowed = commandline

; ── Version detection (upgrade handling) ─────────────────────────────────────
; Inno Setup reads AppId to detect an existing installation.
; If found, it upgrades in place — user settings preserved.
VersionInfoVersion          = {#AppVersion}.0
VersionInfoCompany          = {#AppPublisher}
VersionInfoDescription      = {#AppName} Setup
VersionInfoTextVersion      = {#AppVersion}
VersionInfoCopyright        = {#AppCopyright}
VersionInfoProductName      = {#AppName}
VersionInfoProductVersion   = {#AppVersion}.0

; ── Uninstall ─────────────────────────────────────────────────────────────────
UninstallDisplayIcon    = {app}\{#AppExeName}
UninstallDisplayName    = {#AppName} {#AppVersion}
; Keep user data (sessions, preferences) on uninstall — only remove app files
; User data lives in %USERPROFILE%\microsanj_sessions\ and %USERPROFILE%\.microsanj\

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; Let user choose whether to create a desktop shortcut
Name: "desktopicon";  Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; ── Main application bundle (PyInstaller output) ─────────────────────────────
Source: "..\dist\SanjINSIGHT\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

; ── User-editable config (don't overwrite if it already exists) ───────────────
; This preserves the user's COM ports / driver settings on upgrade.
Source: "..\dist\SanjINSIGHT\config.yaml"; DestDir: "{app}"; \
    Flags: ignoreversion onlyifdoesntexist

; ── Installation guide ────────────────────────────────────────────────────────
Source: "..\README_INSTALL.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Start menu shortcut
Name: "{group}\{#AppName}";          Filename: "{app}\{#AppExeName}"; \
    IconFilename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

; Desktop shortcut (optional — only if user chose it in Tasks)
Name: "{autodesktop}\{#AppName}";    Filename: "{app}\{#AppExeName}"; \
    IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; Offer to launch the app after installation completes
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up __pycache__ and log files on uninstall (not user data)
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\logs"

[Code]
// ── Upgrade detection ────────────────────────────────────────────────────────
// If an older version is installed, show a message and offer to uninstall first.
// Inno Setup handles in-place upgrades automatically via AppId, but this gives
// a cleaner experience for major version jumps.

function GetUninstallString(): String;
var
  sUnInstPath: String;
  sUnInstallString: String;
begin
  sUnInstPath := ExpandConstant(
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#emit SetupSetting("AppId")}_is1');
  sUnInstallString := '';
  if not RegQueryStringValue(HKLM, sUnInstPath, 'UninstallString', sUnInstallString) then
    RegQueryStringValue(HKCU, sUnInstPath, 'UninstallString', sUnInstallString);
  Result := sUnInstallString;
end;

function IsUpgrade(): Boolean;
begin
  Result := (GetUninstallString() <> '');
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if IsUpgrade() then begin
    // In-place upgrade — no special action needed, just inform the user
    // Inno Setup will overwrite app files while preserving config.yaml
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then begin
    // Create the logs directory so the app can write to it on first launch
    ForceDirectories(ExpandConstant('{app}\logs'));
    // Create the profiles/user directory for user-created profiles
    ForceDirectories(ExpandConstant('{app}\profiles\user'));
  end;
end;
