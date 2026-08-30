; Inno Setup script for FrameLabs
; ---------------------------------------------------------------
; Produces a single FrameLabsSetup.exe that gives users the full
; installer experience: welcome screen, choose install folder,
; install, then optional desktop shortcut / start menu / taskbar pin.
;
; SETUP:
;   1. Install Inno Setup (free): https://jrsoftware.org/isdl.php
;   2. Build FrameLabs first (build_exe.bat) so dist\FrameLabs\ exists.
;   3. Open this file in the Inno Setup Compiler (or right-click ->
;      Compile) from the repo root.
;   4. Output lands in installer_output\FrameLabsSetup.exe
;
; That single file is what you hand out for download -- double-click,
; wizard runs, done. No zip, no manual copying.
; ---------------------------------------------------------------

#define MyAppName "FrameLabs"
#define MyAppVersion "0.1.0-alpha"
#define MyAppPublisher "FrameLabs"
#define MyAppExeName "FrameLabs.exe"

[Setup]
AppId={{8F4E1B2A-6C3D-4A9E-9F1B-3D7A2C5E9B10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Lets the user pick the install folder (this is the wizard page you want)
DisableDirPage=no
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
OutputDir=installer_output
OutputBaseFilename=FrameLabsSetup
SetupIconFile=FrameLabs_icon.ico
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
; Shown on the wizard's welcome page so installers make it clear
; this is early/unstable software before the user commits to install.
InfoBeforeFile=alpha_notice.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "taskbaricon"; Description: "&Pin to taskbar"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

; Pulls in the ENTIRE onedir build output (exe + all its bundled
; dependencies/resources) that PyInstaller produced.
[Files]
Source: "dist\FrameLabs\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Offers to launch the app right after install finishes
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  // Pin to taskbar if the user checked that box. Requires Windows 10+;
  // uses the shell verb since there's no direct Inno Setup API for it.
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('taskbaricon') then
  begin
    Exec('powershell.exe',
      '-NoProfile -Command "$s = (New-Object -COM Shell.Application).Namespace((Split-Path ''' + ExpandConstant('{app}\{#MyAppExeName}') + '''));' +
      '$f = $s.ParseName(''' + ExpandConstant('{#MyAppExeName}') + ''');' +
      '$f.InvokeVerb(''taskbarpin'')"',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;
