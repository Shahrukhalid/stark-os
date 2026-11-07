; Windows installer for STARK AI (Inno Setup 6). Built by .github/workflows/desktop.yml.
#define AppVersion GetEnv("STARK_VERSION")
[Setup]
AppId={{6B3E2C5A-8F1D-4E7B-9A2C-5D4F3E1B7C9A}
AppName=STARK AI
AppVersion={#AppVersion}
AppPublisher=Shahrukh Khalid
AppPublisherURL=https://github.com/Shahrukhalid/stark-ai
AppSupportURL=https://github.com/Shahrukhalid/stark-ai/issues
AppUpdatesURL=https://github.com/Shahrukhalid/stark-ai/releases/latest
DefaultDirName={localappdata}\Programs\STARK AI
DefaultGroupName=STARK AI
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=STARK-AI-Windows-Setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\STARK AI.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Files]
Source: "..\dist\STARK AI\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[InstallDelete]
; Before the rename the app was called STARK OS: remove its program file and shortcuts (your data is kept).
Type: files; Name: "{app}\STARK OS.exe"
Type: files; Name: "{group}\STARK OS.lnk"
Type: files; Name: "{autodesktop}\STARK OS.lnk"

[Icons]
Name: "{group}\STARK AI"; Filename: "{app}\STARK AI.exe"
Name: "{autodesktop}\STARK AI"; Filename: "{app}\STARK AI.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\STARK AI.exe"; Description: "Start STARK AI"; Flags: nowait postinstall skipifsilent
