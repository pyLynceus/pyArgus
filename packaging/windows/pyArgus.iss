; Inno Setup 6 installer for pyArgus. Build the onedir bundle first
; (see pyArgus.spec header), then:
;
;   ISCC.exe packaging\windows\pyArgus.iss
;
; Per-user, no elevation: the tool is one person's instrument, not a
; machine-wide service. Signed nothing.

#define AppName "pyArgus"
#define AppVersion "0.1.0"
#define AppExe "pyArgus.exe"

[Setup]
AppId={{9DBB96F0-9015-4808-83F1-8255C8306485}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Platinum Geomatics
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
Compression=lzma2
SolidCompression=yes
OutputDir=..\..\dist-installer
OutputBaseFilename={#AppName}-{#AppVersion}-setup
SetupIconFile=..\..\pyargus\assets\pyArgus.ico
UninstallDisplayIcon={app}\{#AppExe}

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\..\dist\pyArgus\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
