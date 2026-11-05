$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
if (-not $IsWindows -and $env:OS -ne 'Windows_NT') { throw 'Windows required' }
& "$PSScriptRoot\setup-windows.ps1"
if ($LASTEXITCODE -ne 0) { throw 'Setup failed' }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --name BookWorkbench --collect-all PySide6 --add-data ".ocr/tessdata;.ocr/tessdata" launch.py
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed' }
$env:BOOK_WORKBENCH_DATA_DIR = Join-Path $env:TEMP ('book-workbench-smoke-' + [guid]::NewGuid())
try {
    $process = Start-Process -FilePath '.\dist\BookWorkbench\BookWorkbench.exe' -ArgumentList '--smoke-test' -PassThru
    if (-not $process.WaitForExit(30000)) { $process.Kill(); throw 'Packaged smoke test timed out' }
    if ($process.ExitCode -ne 0) { throw 'Packaged startup failed' }
} finally { Remove-Item Env:BOOK_WORKBENCH_DATA_DIR -ErrorAction SilentlyContinue }
Write-Host 'Distribute entire dist/BookWorkbench directory. Tesseract OCR is an external prerequisite.'
