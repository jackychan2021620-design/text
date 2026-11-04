$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path '.venv\Scripts\python.exe')) { throw 'Run scripts\setup-windows.ps1 first.' }
& '.venv\Scripts\python.exe' -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; packaging stopped.' }
& '.venv\Scripts\python.exe' -m PyInstaller --noconfirm --clean --windowed --onedir --name ZaowuGrowthManager --hidden-import keyring.backends.Windows launch.py
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
Copy-Item 'README.md' 'dist\ZaowuGrowthManager\README.md'
Copy-Item 'docs' 'dist\ZaowuGrowthManager\docs' -Recurse -Force
Copy-Item 'scripts\create-desktop-shortcut.ps1' 'dist\ZaowuGrowthManager\create-desktop-shortcut.ps1'
Write-Host 'Built dist\ZaowuGrowthManager\ZaowuGrowthManager.exe. Keep the entire folder together.'
Write-Host 'Launch the EXE on Windows and perform docs\ACCEPTANCE.md before distributing.'
