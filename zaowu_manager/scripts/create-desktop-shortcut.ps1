$ErrorActionPreference = 'Stop'
$binary = Join-Path $PSScriptRoot 'ZaowuGrowthManager.exe'
if (-not (Test-Path $binary)) { throw 'Run this script from the packaged application directory.' }
$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcut = $shell.CreateShortcut((Join-Path $desktop 'ZAOWU Business Manager.lnk'))
$shortcut.TargetPath = $binary
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = 'ZAOWU AI Business Manager'
$shortcut.Save()
