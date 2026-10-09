; Offline, per-user Windows x64 installer. See docs/WINDOWS_INSTALLER.md.
; Compile with ISCC.exe /DStageDir=<prepared payload> pyArgus.iss.

#define AppName "pyArgus"
#define AppVersion "0.1.0"
#ifndef ReleaseDate
  #define ReleaseDate "2026-10-08"
#endif
#ifndef StageDir
  #define StageDir SourcePath + "..\..\build\installer-20261008\payload"
#endif
#ifndef InstallerOutputDir
  #define InstallerOutputDir SourcePath + "..\..\dist-installer\2026-10-08"
#endif

[Setup]
; Separate identity and default directory from the former Mapworks installer.
AppId={{88A25EB2-BA18-4722-A4CE-63D9EDC739AB}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion} ({#ReleaseDate})
AppPublisher=pyArgus contributors
AppPublisherURL=https://github.com/pyLynceus/pyArgus
AppSupportURL=https://github.com/pyLynceus/pyArgus
DefaultDirName={localappdata}\Programs\pyArgus-Codex
DefaultGroupName=pyArgus (Codex)
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible and not arm64
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
DisableProgramGroupPage=yes
AllowNoIcons=yes
Compression=lzma2
SolidCompression=yes
OutputDir={#InstallerOutputDir}
OutputBaseFilename=pyArgus-{#AppVersion}-{#ReleaseDate}-windows-x64-setup
SetupIconFile=..\..\pyargus\assets\pyArgus.ico
UninstallDisplayIcon={app}\pyArgus.exe
UninstallDisplayName=pyArgus {#AppVersion} (Codex; {#ReleaseDate})
UninstallFilesDir={app}\Uninstall
LicenseFile={#StageDir}\LICENSE.txt
InfoAfterFile={#StageDir}\README.txt
VersionInfoVersion=0.1.0.1008
CloseApplications=no
RestartApplications=no
ChangesEnvironment=no
ChangesAssociations=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\pyArgus"; Filename: "{app}\pyArgus.exe"; WorkingDir: "{app}"
Name: "{group}\Watch the step-by-step tutorial"; Filename: "{app}\Training\Watch-pyArgus.html"
Name: "{group}\Getting started and guides"; Filename: "{app}\Getting-started.html"
Name: "{group}\Uninstall pyArgus"; Filename: "{uninstallexe}"
Name: "{autodesktop}\pyArgus (Codex)"; Filename: "{app}\pyArgus.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\pyArgus.exe"; Description: "Launch pyArgus"; Flags: nowait postinstall skipifsilent
Filename: "{app}\Training\Watch-pyArgus.html"; Description: "Watch the step-by-step tutorial"; Flags: shellexec postinstall skipifsilent unchecked
