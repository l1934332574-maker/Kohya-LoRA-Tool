; ============================================================
; KohyaLoraTool 安装脚本（Inno Setup 6）
; 用法：build_exe\installer\installer.iss 由 build_installer.bat 调用
; 默认安装到用户文档目录 {userdocs}\KohyaLoraTool，避开 Program Files 权限问题
; ============================================================
#define MyAppName "KohyaLoraTool"
#define MyAppVersion "1.0.0"
#define MyAppExeName "Kohya一键工具.exe"
#define MyAppDir "..\dist\Kohya一键工具"

[Setup]
AppId={{8E6F5C3A-2C4D-4E1B-9A5F-3D6B7C8D9E0F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=KohyaLoraTool
AppVerName={#MyAppName} {#MyAppVersion}
DefaultDirName={userdocs}\KohyaLoraTool
DefaultGroupName=KohyaLoraTool
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=.
OutputBaseFilename=Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
LicenseFile=..\..\LICENSE
; 卸载时保留用户数据（数据在 %APPDATA%\KohyaLoraTool，不在安装目录，不会误删）
#if FileExists("app.ico")
SetupIconFile=app.ico
#endif

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: unchecked
Name: "startmenu"; Description: "创建开始菜单快捷方式"; GroupDescription: "附加任务："; Flags: checkedonce
Name: "launch"; Description: "安装完成后立即启动软件"; GroupDescription: "附加任务："; Flags: checkedonce

[Files]
Source: "{#MyAppDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startmenu
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent; Tasks: launch
