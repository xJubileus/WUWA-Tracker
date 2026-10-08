#define AppName "WUWA Tracker"
#define AppVer "1.3.0"
#define AppExe "WUWA Tracker.exe"

[Setup]
AppId={{B6B2E6F4-5D9B-4C58-9F30-3C7F1A2D8E11}
AppName={#AppName}
AppVersion={#AppVer}
AppPublisher=Jubileus
AppCopyright=Copyright (c) 2026 Jubileus
VersionInfoVersion=1.3.0.0
VersionInfoCompany=Jubileus
VersionInfoDescription=WUWA Tracker Setup
VersionInfoProductName=WUWA Tracker
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline dialog
OutputDir=Output
OutputBaseFilename=WUWA-Tracker-Embedded-Setup
SetupIconFile=wuwa.ico
UninstallDisplayIcon={app}\app\wuwa.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "build_emb\stage\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\wuwa_app.py"""; WorkingDir: "{app}\app"; IconFilename: "{app}\app\wuwa.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\wuwa_app.py"""; WorkingDir: "{app}\app"; IconFilename: "{app}\app\wuwa.ico"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "WUWA Tracker"; Flags: dontcreatekey uninsdeletevalue

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\wuwa_app.py"""; WorkingDir: "{app}\app"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\wuwa_app.py"""; WorkingDir: "{app}\app"; Flags: nowait; Check: IsUpdate

[Code]
function WebView2Installed: Boolean;
var v: String;
begin
  Result := False;
  if RegQueryStringValue(HKLM32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v) and (v <> '') and (v <> '0.0.0.0') then Result := True
  else if RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v) and (v <> '') and (v <> '0.0.0.0') then Result := True;
end;

function IsUpdate: Boolean;
begin
  Result := ExpandConstant('{param:update|0}') = '1';
end;

function InitializeSetup: Boolean;
begin
  Result := True;
  if not WebView2Installed then
    MsgBox('The Microsoft WebView2 Runtime was not found. WUWA Tracker needs it to run.' + #13#10 +
           'It is preinstalled on most Windows 10/11 systems. If the app does not start after setup, install it from:' + #13#10 +
           'https://go.microsoft.com/fwlink/p/?LinkId=2124703', mbInformation, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    if MsgBox('Also delete your saved progress and task list?', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{userappdata}\WuWaTracker'), True, True, True);
end;
