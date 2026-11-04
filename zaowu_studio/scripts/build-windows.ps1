$ErrorActionPreference = 'Stop'
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
} finally {
    Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    if (Test-Path $env:ZAOWU_STUDIO_DATA_DIR) { Remove-Item $env:ZAOWU_STUDIO_DATA_DIR -Recurse -Force }
    Remove-Item Env:ZAOWU_STUDIO_DATA_DIR -ErrorAction SilentlyContinue
}
$compiler = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
if (-not (Test-Path $compiler)) { throw 'Install Inno Setup 6 to create the Windows installer.' }
& $compiler 'scripts\installer.iss'
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
Write-Host 'Installer available in dist\installer\ZaowuContentStudio-Setup-0.2.0.exe'
