#define AppVersion "1.1.5"
[Setup]
AppId={{472FEBC8-D684-44FA-A3B1-D79C35495111}
AppName=图书带货智能选品工作台
AppVersion={#AppVersion}
AppPublisher=BookWorkbench
DefaultDirName={localappdata}\Programs\BookWorkbench
DefaultGroupName=图书带货智能选品工作台
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=BookWorkbench-Setup-1.1.5-Windows-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\BookWorkbench.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"
[LangOptions]
LanguageName=简体中文
LanguageID=$0804
LanguageCodePage=936
[Messages]
SetupWindowTitle=安装 — %1
WelcomeLabel1=欢迎安装 [name]
WelcomeLabel2=本程序已内置 Python、Qt 和 OCR，无需另行安装。%n%n单击“下一步”继续。
ButtonNext=下一步(&N) >
ButtonBack=< 上一步(&B)
ButtonCancel=取消
ButtonInstall=安装(&I)
ButtonFinish=完成(&F)
SelectDirLabel3=程序安装在以下目录，经营资料保存在独立用户目录。
SelectTasksLabel2=请选择需要创建的快捷方式。
ReadyLabel1=准备安装
ReadyLabel2a=单击“安装”开始。
FinishedHeadingLabel=安装完成
FinishedLabel=[name] 已安装完成。
[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: checkedonce
[Files]
Source: "..\dist\BookWorkbench\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{autoprograms}\图书带货智能选品工作台"; Filename: "{app}\BookWorkbench.exe"
Name: "{autodesktop}\图书带货智能选品工作台"; Filename: "{app}\BookWorkbench.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\BookWorkbench.exe"; Description: "打开图书带货智能选品工作台"; Flags: nowait postinstall skipifsilent
