#ifndef Payload
  #define Payload "..\output\Local-Library-Release"
#endif
#ifndef Prerequisites
  #define Prerequisites "..\.cache\release-tools"
#endif

[Setup]
AppId={{3BD5A436-7156-4B9D-B87D-112BA51CCFAB}
AppName=PaperVault
AppVersion=0.5.0
AppVerName=PaperVault v0.5
DefaultDirName={localappdata}\Programs\PaperVault
DefaultGroupName=PaperVault
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
OutputDir=..\output\Library-Installer
OutputBaseFilename=PaperVault-Setup-0.5.0
SetupIconFile=..\.cache\Library.ico
UninstallDisplayIcon={app}\Library.exe
WizardStyle=modern
Compression=lzma2/fast
SolidCompression=no
DiskSpanning=no
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
UninstallDisplayName=PaperVault
VersionInfoVersion=0.5.0.0
VersionInfoProductName=PaperVault
InfoBeforeFile=release-info.txt

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: startupicon; Description: "Start PaperVault automatically when Windows starts"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "{#Payload}\*"; DestDir: "{app}"; Excludes: "*.pdb,*.map,*.pyc,*.pyo,\app\.cache\*,\data\*,Library.user.json"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Prerequisites}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; Flags: dontcopy

[InstallDelete]
Type: files; Name: "{group}\Library.lnk"
Type: files; Name: "{autodesktop}\Library.lnk"

[Icons]
Name: "{group}\PaperVault"; Filename: "{app}\Library.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\PaperVault"; Filename: "{app}\Library.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\PaperVault"; Filename: "{app}\Library.exe"; Parameters: "--startup"; WorkingDir: "{app}"; Tasks: startupicon

[Run]
Filename: "{app}\Library.exe"; Description: "Open PaperVault"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\Library.exe"; Parameters: "--quit --wait"; Flags: runhidden waituntilterminated; RunOnceId: StopLibrary

[Code]
function WebViewAvailable: Boolean;
var Version: String;
begin
  Result := (RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM32, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM64, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
end;

function InitializeSetup: Boolean;
var Release: Cardinal;
begin
  Result := RegQueryDWordValue(HKLM32, 'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full', 'Release', Release) and (Release >= 461808);
  if not Result then MsgBox('PaperVault requires .NET Framework 4.7.2 or newer. Install the Microsoft runtime, then run setup again.', mbError, MB_OK);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var ExitCode: Integer;
begin
  Result := '';
  if FileExists(ExpandConstant('{app}\Library.exe')) then begin
    if not Exec(ExpandConstant('{app}\Library.exe'), '--quit --wait', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then begin
      Result := 'Close PaperVault and try setup again.';
      Exit;
    end;
    if ExitCode <> 0 then begin
      Result := 'PaperVault is still closing. Wait for indexing to stop, then retry setup.';
      Exit;
    end;
  end;
  if not WebViewAvailable then begin
    ExtractTemporaryFile('MicrosoftEdgeWebView2RuntimeInstallerX64.exe');
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      Result := 'The bundled Microsoft WebView2 installer could not start. No internet download is needed; try setup again.'
    else if not WebViewAvailable then
      Result := 'Microsoft WebView2 installation did not complete (code ' + IntToStr(ExitCode) + '). Restart Windows and run setup again.';
  end;
end;
