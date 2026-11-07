#define AppName "造物手作 AI 获客与内容运营工作台"
#define AppVersion "0.3.1"
[Setup]
AppId={{7AA9F1B9-4715-4F93-9086-148217D49119}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=造物手作
DefaultDirName={localappdata}\Programs\ZaowuContentStudio
DefaultGroupName=造物手作
OutputDir=..\dist\installer
OutputBaseFilename=ZaowuContentStudio-Setup-{#AppVersion}
SetupIconFile=..\resources\brand.ico
UninstallDisplayIcon={app}\ZaowuContentStudio.exe
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes
[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"
[LangOptions]
LanguageName=简体中文
LanguageID=$0804
LanguageCodePage=936
[Messages]
SetupAppTitle=安装
SetupWindowTitle=安装 — %1
WelcomeLabel1=欢迎安装 [name]
WelcomeLabel2=本向导将安装 [name/ver]。%n%n运行环境已经包含在安装包中，无需单独安装 Python。%n%n单击“下一步”继续。
ButtonNext=下一步(&N) >
ButtonBack=< 上一步(&B)
ButtonCancel=取消
ButtonInstall=安装(&I)
ButtonFinish=完成(&F)
SelectDirLabel3=程序将安装到以下文件夹。经营资料保存在独立用户目录，升级时保留。
SelectDirBrowseLabel=单击“下一步”继续，或单击“浏览”选择其他文件夹。
SelectTasksLabel2=请选择安装时需要执行的附加任务。
ReadyLabel1=准备安装
ReadyLabel2a=单击“安装”开始安装，或单击“上一步”检查设置。
FinishedHeadingLabel=安装完成
FinishedLabelNoIcons=[name] 已安装完成。
FinishedLabel=[name] 已安装完成，可以通过桌面图标或开始菜单打开。
[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："
[Files]
Source: "..\dist\ZaowuContentStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{autoprograms}\造物手作\内容运营工作台"; Filename: "{app}\ZaowuContentStudio.exe"
Name: "{autodesktop}\造物手作内容工作台"; Filename: "{app}\ZaowuContentStudio.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\ZaowuContentStudio.exe"; Description: "打开造物手作内容工作台"; Flags: nowait postinstall skipifsilent
[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'ZaowuContentStudio');
    if not UninstallSilent then
      if MsgBox('是否同时删除工作台资料、素材和备份？此操作不可恢复。选择“否”保留资料，方便以后重新安装。', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(ExpandConstant('{localappdata}\ZaowuContentStudio'), True, True, True);
  end;
end;
