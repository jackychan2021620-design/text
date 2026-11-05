param([Parameter(Mandatory=$true)][string]$Packages,[Parameter(Mandatory=$true)][string]$Expanded)
$ErrorActionPreference = 'Stop'
$report = [ordered]@{ status='not_completed'; scanned_at_utc=[DateTime]::UtcNow.ToString('o'); scans=@(); signatures=@(); files=@(); scope='Microsoft Defender only; not a Chrome Safe Browsing clearance or safety guarantee.' }
$logRoot = (Get-Location).Path
try {
    $targets = @((Resolve-Path $Packages).Path,(Resolve-Path $Expanded).Path)
    foreach ($file in Get-ChildItem $targets[0] -File) {
        $report.files += [ordered]@{name=$file.Name;sha256=(Get-FileHash $file.FullName -Algorithm SHA256).Hash.ToLower()}
    }
    foreach ($file in @((Join-Path $targets[0] 'BookWorkbench-Setup-1.1.3-Windows-x64.exe'),(Join-Path $targets[1] 'BookWorkbench.exe'))) {
        $sig = Get-AuthenticodeSignature $file
        $report.signatures += [ordered]@{name=[IO.Path]::GetFileName($file);status=$sig.Status.ToString()}
    }
    if ((Get-Service WinDefend).Status -ne 'Running') { Start-Service WinDefend }
    try { Update-MpSignature } catch { $report.signature_update_warning=$_.Exception.Message }
    $state = Get-MpComputerStatus
    if (-not $state.AntivirusEnabled -or -not $state.AMServiceEnabled -or $state.AntivirusSignatureLastUpdated -lt (Get-Date).AddDays(-7)) { throw 'Active Defender with current signatures is required before uploading the program.' }
    $report.engine_version=$state.AMEngineVersion
    $report.signature_version=$state.AntivirusSignatureVersion
    $report.signature_updated_utc=$state.AntivirusSignatureLastUpdated.ToUniversalTime().ToString('o')
    $scanner = Get-ChildItem (Join-Path $env:ProgramData 'Microsoft\Windows Defender\Platform\*\MpCmdRun.exe') -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
    if ($scanner) { $scanner=$scanner.FullName } else { $scanner=Join-Path $env:ProgramFiles 'Windows Defender\MpCmdRun.exe' }
    if ((Get-AuthenticodeSignature $scanner).Status -ne 'Valid') { throw 'Defender scanner signature is invalid' }
    $start=Get-Date
    for ($i=0; $i -lt $targets.Count; $i++) {
        & $scanner -Scan -ScanType 3 -File $targets[$i] -DisableRemediation 2>&1 | Tee-Object -FilePath (Join-Path $logRoot "defender-scan-$i.txt")
        $code=$LASTEXITCODE
        $report.scans += [ordered]@{target=$(if ($i -eq 0) {'installer_and_zip'} else {'expanded_application'});exit_code=$code}
        if ($code -ne 0) { throw "Defender detection or scan error (exit $code); program upload blocked." }
    }
    if (@(Get-MpThreatDetection | Where-Object {$_.InitialDetectionTime -ge $start.AddSeconds(-5)}).Count -gt 0) { throw 'Threat detection recorded during scan; program upload blocked.' }
    $report.status='no_threat_detected_by_defender'
    Write-Host '::notice title=Package scan::Defender completed package and expanded-file scans without detection. This does not clear a Chrome warning.'
} catch {
    $report.error=$_.Exception.Message
    Write-Host ('::error title=Package scan::' + $report.error.Replace('%','%25').Replace("`r",'%0D').Replace("`n",'%0A'))
    throw
} finally {
    $out = Join-Path $logRoot 'defender-scan-report.json'
    $report | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 $out
    if ($report.status -eq 'no_threat_detected_by_defender') { Copy-Item $out (Join-Path $targets[0] 'Defender-scan-report.json') }
}
