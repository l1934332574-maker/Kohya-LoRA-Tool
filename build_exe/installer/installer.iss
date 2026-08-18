; ============================================================
; KohyaLoraTool 安装脚本（Inno Setup 6）
; 用法：build_exe\installer\installer.iss 由 build_installer.bat 调用
; 默认安装到用户文档目录 {userdocs}\KohyaLoraTool，避开 Program Files 权限问题
; ============================================================
#define MyAppName "KohyaLoraTool"
#define MyAppVersion "0.9.11"
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
; 允许用户选择安装位置（默认 auto 在非管理员安装时会跳过目录页，强制显示）
DisableDirPage=no
; 自动覆盖升级：记住上次安装目录，第二次装默认还是那个目录（同目录=覆盖旧文件）
UsePreviousAppDir=yes
; 安装前自动关闭正在运行的软件，避免 exe 被占用导致覆盖失败
CloseApplications=yes
RestartApplications=yes
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


;
;
; ============================================================
; 安装向导自定义说明页：装之前先看避坑提示
; ============================================================
[Code]
var
  AMDInfoPage: TWizardPage;

procedure InitializeWizard;
var
  lbl: TNewStaticText;
begin
  AMDInfoPage := CreateCustomPage(wpLicense, '安装前必看', '装之前花 10 秒看一下这里');
  lbl := TNewStaticText.Create(AMDInfoPage);
  lbl.Parent := AMDInfoPage.Surface;
  lbl.WordWrap := True;
  lbl.Left := 0;
  lbl.Top := 0;
  lbl.Width := AMDInfoPage.SurfaceWidth;
  lbl.Caption :=
    '● 推荐安装到默认位置（文档\KohyaLoraTool）或 D 盘等非系统盘。' + #13#10 + #13#10 +
    '● 不要装到 C:\Program Files 系统目录：' + #13#10 +
    '  那里需要管理员权限，容易遇到"权限不足 / 无法写入"的报错。' + #13#10 + #13#10 +
    '● 训练数据（图片 / 模型 / 日志）会自动存到 %APPDATA%\KohyaLoraTool，' + #13#10 +
    '  和安装位置无关，重装或卸载都不会丢失你的训练成果。' + #13#10 + #13#10 +
    '● 升级：检测到旧版本时会自动覆盖安装（保持默认安装目录即可），' + #13#10 +
    '  不用先卸载、不用删除旧文件夹，kohya 训练环境也会自动保留。' + #13#10 + #13#10 +
    '● 安装完成后首次运行，按左侧新手引导 ①②③④ 一步步来即可。';
end;
