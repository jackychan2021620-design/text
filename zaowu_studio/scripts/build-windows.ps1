$ErrorActionPreference = 'Stop'
trap {
    $message = $_.Exception.Message.Replace('%', '%25').Replace("`r", '%0D').Replace("`n", '%0A')
    Write-Host ('::error title=Windows package check::' + $message)
    exit 1
}
Set-Location (Split-Path $PSScriptRoot -Parent)
$python = '.venv\Scripts\python.exe'
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; build stopped.' }
& $python scripts\make_icon.py
if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed.' }
& $python -m PyInstaller --noconfirm --clean --windowed --onedir --name ZaowuContentStudio --icon resources\brand.ico --add-data 'resources;resources' --hidden-import keyring.backends.Windows launch.py
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
$env:QT_QPA_PLATFORM = 'offscreen'
$env:ZAOWU_STUDIO_DATA_DIR = Join-Path ([IO.Path]::GetTempPath()) ('zaowu-studio-smoke-' + [Guid]::NewGuid().ToString('N'))
try {
    $process = Start-Process -FilePath 'dist\ZaowuContentStudio\ZaowuContentStudio.exe' -ArgumentList '--smoke-test' -PassThru
    if (-not $process.WaitForExit(60000)) { $process.Kill(); throw 'Packaged application smoke test timed out.' }
    if ($process.ExitCode -ne 0) { throw 'Packaged application smoke test failed.' }
    if (-not (Test-Path (Join-Path $env:ZAOWU_STUDIO_DATA_DIR 'studio.sqlite3'))) { throw 'Packaged application did not initialize its database.' }
    $isolation = Start-Process -FilePath 'dist\ZaowuContentStudio\ZaowuContentStudio.exe' -ArgumentList '--import-isolation-smoke-test' -PassThru
    if (-not $isolation.WaitForExit(30000)) { $isolation.Kill(); throw 'Browser isolation check timed out.' }
    if ($isolation.ExitCode -ne 0) { throw 'A hung browser blocked the main application.' }
    $browser = Start-Process -FilePath 'dist\ZaowuContentStudio\ZaowuContentStudio.exe' -ArgumentList '--browser-smoke-test' -PassThru
    if (-not $browser.WaitForExit(60000)) { $browser.Kill(); throw 'Bundled browser smoke test timed out.' }
    if ($browser.ExitCode -ne 0) {
        $details = Join-Path $env:ZAOWU_STUDIO_DATA_DIR 'browser-smoke-result.json'
        $reason = if (Test-Path $details) { Get-Content $details -Raw } else { 'Renderer did not initialize.' }
        throw ('Bundled browser could not read the offline note fixture: ' + $reason)
    }
} finally {
    Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    if (Test-Path $env:ZAOWU_STUDIO_DATA_DIR) { Remove-Item $env:ZAOWU_STUDIO_DATA_DIR -Recurse -Force }
    Remove-Item Env:ZAOWU_STUDIO_DATA_DIR -ErrorAction SilentlyContinue
}
$compiler = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
if (-not (Test-Path $compiler)) { throw 'Install Inno Setup 6 to create the Windows installer.' }
& $compiler 'scripts\installer.iss' 2>&1 | Tee-Object -Variable compilerOutput
if ($LASTEXITCODE -ne 0) { throw ('Installer compilation failed: ' + (($compilerOutput | Select-Object -Last 12) -join ' ')) }
Write-Host 'Installer available in dist\installer\ZaowuContentStudio-Setup-0.3.1.exe'
$installDir = Join-Path ([IO.Path]::GetTempPath()) ('zaowu-install-check-' + [Guid]::NewGuid().ToString('N'))
$setupArgs = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', ('/DIR="' + $installDir + '"'))
$setup = Start-Process -FilePath 'dist\installer\ZaowuContentStudio-Setup-0.3.1.exe' -ArgumentList $setupArgs -PassThru
if (-not $setup.WaitForExit(90000)) { $setup.Kill(); throw 'Installer smoke test timed out.' }
if ($setup.ExitCode -ne 0) { throw 'Installer returned an error.' }
$installedExe = Join-Path $installDir 'ZaowuContentStudio.exe'
if (-not (Test-Path $installedExe)) { throw 'Installer did not create the application executable.' }
$env:QT_QPA_PLATFORM = 'offscreen'
$env:ZAOWU_STUDIO_DATA_DIR = Join-Path ([IO.Path]::GetTempPath()) ('zaowu-installed-data-' + [Guid]::NewGuid().ToString('N'))
try {
    $installed = Start-Process -FilePath $installedExe -ArgumentList '--smoke-test' -PassThru
    if (-not $installed.WaitForExit(60000)) { $installed.Kill(); throw 'Installed application timed out.' }
    if ($installed.ExitCode -ne 0) { throw 'Installed application failed to start.' }
    $isolationInstalled = Start-Process -FilePath $installedExe -ArgumentList '--import-isolation-smoke-test' -PassThru
    if (-not $isolationInstalled.WaitForExit(30000)) { $isolationInstalled.Kill(); throw 'Installed isolation check timed out.' }
    if ($isolationInstalled.ExitCode -ne 0) { throw 'Installed application could not recover from a hung browser.' }
    $installedBrowser = Start-Process -FilePath $installedExe -ArgumentList '--browser-smoke-test' -PassThru
    if (-not $installedBrowser.WaitForExit(60000)) { $installedBrowser.Kill(); throw 'Installed browser timed out.' }
    if ($installedBrowser.ExitCode -ne 0) {
        $details = Join-Path $env:ZAOWU_STUDIO_DATA_DIR 'browser-smoke-result.json'
        $reason = if (Test-Path $details) { Get-Content $details -Raw } else { 'Renderer did not initialize.' }
        throw ('Installed browser note-extraction check failed: ' + $reason)
    }
} finally {
    Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    if (Test-Path $env:ZAOWU_STUDIO_DATA_DIR) { Remove-Item $env:ZAOWU_STUDIO_DATA_DIR -Recurse -Force }
    Remove-Item Env:ZAOWU_STUDIO_DATA_DIR -ErrorAction SilentlyContinue
}
$uninstall = Start-Process -FilePath (Join-Path $installDir 'unins000.exe') -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -PassThru
if (-not $uninstall.WaitForExit(90000)) { $uninstall.Kill(); throw 'Uninstall smoke test timed out.' }
if ($uninstall.ExitCode -ne 0) { throw 'Uninstall smoke test failed.' }
Write-Host 'Installed application and silent uninstall checks passed.'
