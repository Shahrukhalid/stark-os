; Windows installer for STARK OS (Inno Setup 6). Built by .github/workflows/desktop.yml.
#define AppVersion GetEnv("STARK_VERSION")
[Setup]
AppId={{6B3E2C5A-8F1D-4E7B-9A2C-5D4F3E1B7C9A}
AppName=STARK OS
AppVersion={#AppVersion}
AppPublisher=Shahrukh Khalid
AppPublisherURL=https://github.com/Shahrukhalid/stark-os
AppSupportURL=https://github.com/Shahrukhalid/stark-os/issues
AppUpdatesURL=https://github.com/Shahrukhalid/stark-os/releases/latest
DefaultDirName={localappdata}\Programs\STARK OS
DefaultGroupName=STARK OS
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=STARK-OS-Windows-Setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\STARK OS.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Files]
Source: "..\dist\STARK OS\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\STARK OS"; Filename: "{app}\STARK OS.exe"
Name: "{autodesktop}\STARK OS"; Filename: "{app}\STARK OS.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\STARK OS.exe"; Description: "Start STARK OS"; Flags: nowait postinstall skipifsilent
