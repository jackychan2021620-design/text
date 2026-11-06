$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
if ($env:OS -ne 'Windows_NT') { throw 'Windows required' }
& "$PSScriptRoot\setup-windows.ps1"
if ($LASTEXITCODE -ne 0) { throw 'Setup failed' }
$tesseract = $env:BOOK_WORKBENCH_TESSERACT
if (-not $tesseract) {
    $installed = Get-Command tesseract.exe -ErrorAction SilentlyContinue
    if ($installed) { $tesseract = $installed.Source }
    else { $tesseract = Join-Path $env:ProgramFiles 'Tesseract-OCR\tesseract.exe' }
}
if (-not (Test-Path $tesseract)) { throw 'Tesseract runtime missing; install Tesseract 5 first' }
$ocrRoot = Split-Path -Parent $tesseract
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --name BookWorkbench --collect-submodules keyring.backends --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineQuick --add-data ".ocr/tessdata;.ocr/tessdata" --add-data "resources;resources" --add-data "$ocrRoot;tesseract" launch.py
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed' }
Copy-Item README.md dist\BookWorkbench\README-source.md
Copy-Item docs\WINDOWS-QUICKSTART.txt dist\BookWorkbench\使用说明.txt
Copy-Item docs\THIRD-PARTY.txt dist\BookWorkbench\THIRD-PARTY.txt
$env:BOOK_WORKBENCH_DATA_DIR = Join-Path $env:TEMP ('book-workbench-smoke-' + [guid]::NewGuid())
try {
    # A real Windows platform startup (not the offscreen test plugin).
    Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    $process = Start-Process -FilePath '.\dist\BookWorkbench\BookWorkbench.exe' -ArgumentList '--smoke-test' -PassThru
    if (-not $process.WaitForExit(60000)) { $process.Kill(); throw 'Packaged smoke test timed out' }
    if ($process.ExitCode -ne 0) {
        $detail = Get-Content (Join-Path $env:BOOK_WORKBENCH_DATA_DIR 'startup-error.log') -Raw -ErrorAction SilentlyContinue
        throw ('Packaged startup failed: ' + $detail)
    }
    & .\.venv\Scripts\python.exe scripts/check_packaged.py dist/BookWorkbench $env:BOOK_WORKBENCH_DATA_DIR 2>&1 | Tee-Object -Variable packageCheck
    if ($LASTEXITCODE -ne 0) { throw ('Packaged validation failed: ' + ($packageCheck -join "`n")) }
} finally { Remove-Item Env:BOOK_WORKBENCH_DATA_DIR -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force dist\downloads | Out-Null
Compress-Archive -Path dist\BookWorkbench -DestinationPath dist\downloads\BookWorkbench-1.1.7-Windows-x64-portable.zip -Force
$iscc = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
if (-not (Test-Path $iscc)) { throw 'Inno Setup 6 required' }
& $iscc scripts\installer.iss
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed' }
# Validate silent install into a temporary directory and run the installed app.
$installer = (Resolve-Path dist\installer\BookWorkbench-Setup-1.1.7-Windows-x64.exe).Path
$installRoot = Join-Path $env:TEMP ('中文安装路径-图书工作台-' + [guid]::NewGuid())
$process = Start-Process -FilePath $installer -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/DIR=`"$installRoot`"",'/TASKS=' -PassThru -Wait
if ($process.ExitCode -ne 0) { throw 'Installer execution failed' }
$env:BOOK_WORKBENCH_DATA_DIR = Join-Path $env:TEMP ('book-workbench-installed-data-' + [guid]::NewGuid())
try {
    $process = Start-Process -FilePath (Join-Path $installRoot 'BookWorkbench.exe') -ArgumentList '--smoke-test' -PassThru
    if (-not $process.WaitForExit(60000)) { $process.Kill(); throw 'Installed app smoke test timed out' }
    if ($process.ExitCode -ne 0) {
        $detail = Get-Content (Join-Path $env:BOOK_WORKBENCH_DATA_DIR 'startup-error.log') -Raw -ErrorAction SilentlyContinue
        throw ('Installed app startup failed: ' + $detail)
    }
    & .\.venv\Scripts\python.exe scripts/check_packaged.py $installRoot $env:BOOK_WORKBENCH_DATA_DIR --require-unicode 2>&1 | Tee-Object -Variable installCheck
    if ($LASTEXITCODE -ne 0) { throw ('Installed app validation failed: ' + ($installCheck -join "`n")) }
} finally { Remove-Item Env:BOOK_WORKBENCH_DATA_DIR -ErrorAction SilentlyContinue }
Copy-Item $installer dist\downloads\
Get-ChildItem dist\downloads\* | Get-FileHash -Algorithm SHA256 | ForEach-Object { "$($_.Hash.ToLower())  $([System.IO.Path]::GetFileName($_.Path))" } | Set-Content -Encoding ascii dist\downloads\SHA256SUMS.txt
Write-Host 'Windows installer and portable package built and smoke-tested. No Python or external OCR installation required for users.'
