param([Parameter(Mandatory=$true)][string]$Received)
$ErrorActionPreference = 'Stop'
$reportDir = Join-Path $env:GITHUB_WORKSPACE 'security-report'
New-Item -ItemType Directory -Force $reportDir | Out-Null
$report = [ordered]@{
    status = 'not_completed'
    artifact_id = '13401944459'
    source_run_id = '42001014433'
    source_artifact_digest = 'sha256:7d926dd38c8e0a5b1958143910cb4e3e81c8b506594f4dcabd7eb2c963aa89d7'
    checked_at_utc = [DateTime]::UtcNow.ToString('o')
    files = @()
    signatures = @()
    scans = @()
    warning = 'This scan does not determine Chrome Safe Browsing classification or guarantee safety. The downloaded program is never executed.'
}
try {
    $receivedPath = (Resolve-Path $Received).Path
    $sums = @{}
    Get-Content (Join-Path $receivedPath 'SHA256SUMS.txt') | ForEach-Object {
        if ($_ -match '^([0-9a-fA-F]{64})\s+(.+)$') { $sums[$Matches[2].Trim()] = $Matches[1].ToLower() }
    }
    foreach ($name in @('BookWorkbench-Setup-1.1.1-Windows-x64.exe','BookWorkbench-1.1.1-Windows-x64-portable.zip')) {
        $file = Join-Path $receivedPath $name
        $hash = (Get-FileHash $file -Algorithm SHA256).Hash.ToLower()
        if (-not $sums.ContainsKey($name) -or $hash -ne $sums[$name]) { throw "Original package checksum mismatch: $name" }
        $report.files += [ordered]@{ name=$name; sha256=$hash; bytes=(Get-Item $file).Length }
    }
    # Scan the original files and their expanded contents. Do not run the sample.
    $scanRoot = Join-Path $env:ProgramData ('BookWorkbench-audit-' + [guid]::NewGuid())
    $originalRoot = Join-Path $scanRoot 'original'
    $expandedRoot = Join-Path $scanRoot 'expanded'
    New-Item -ItemType Directory -Force $originalRoot,$expandedRoot | Out-Null
    Copy-Item (Join-Path $receivedPath '*') $originalRoot
    Expand-Archive -LiteralPath (Join-Path $originalRoot 'BookWorkbench-1.1.1-Windows-x64-portable.zip') -DestinationPath $expandedRoot
    $exe = Join-Path $expandedRoot 'BookWorkbench\BookWorkbench.exe'
    foreach ($file in @((Join-Path $originalRoot 'BookWorkbench-Setup-1.1.1-Windows-x64.exe'),$exe)) {
        $sig = Get-AuthenticodeSignature -LiteralPath $file
        $report.signatures += [ordered]@{ name=[IO.Path]::GetFileName($file); sha256=(Get-FileHash $file -Algorithm SHA256).Hash.ToLower(); status=$sig.Status.ToString(); signer=$(if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { $null }) }
    }
    $service = Get-Service WinDefend
    if ($service.Status -ne 'Running') { Start-Service WinDefend }
    $state = Get-MpComputerStatus
    if (-not $state.AMServiceEnabled -or -not $state.AntivirusEnabled) { throw 'Microsoft Defender antivirus service is not active; no scan result can be claimed.' }
    try { Update-MpSignature } catch { $report.signature_update_warning = $_.Exception.Message }
    $state = Get-MpComputerStatus
    $report.defender = [ordered]@{
        service_enabled=$state.AMServiceEnabled
        antivirus_enabled=$state.AntivirusEnabled
        engine_version=$state.AMEngineVersion
        product_version=$state.AMProductVersion
        signature_version=$state.AntivirusSignatureVersion
        signature_updated_utc=$state.AntivirusSignatureLastUpdated.ToUniversalTime().ToString('o')
    }
    if ($state.AntivirusSignatureLastUpdated -lt (Get-Date).AddDays(-7)) { throw 'Defender signatures are older than seven days; scan is not accepted.' }
    $scanner = Get-ChildItem (Join-Path $env:ProgramData 'Microsoft\Windows Defender\Platform\*\MpCmdRun.exe') -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
    if ($scanner) { $scanner = $scanner.FullName } else { $scanner = Join-Path $env:ProgramFiles 'Windows Defender\MpCmdRun.exe' }
    if (-not (Test-Path $scanner)) { throw 'Microsoft Defender scanner executable is unavailable.' }
    $scannerSignature = Get-AuthenticodeSignature -LiteralPath $scanner
    if ($scannerSignature.Status -ne 'Valid') { throw 'Scanner signature validation failed; refusing to use an unverified scanner.' }
    & $scanner -? 2>&1 | Out-File (Join-Path $reportDir 'scanner-help.txt') -Encoding utf8
    $helpText = Get-Content (Join-Path $reportDir 'scanner-help.txt') -Raw
    if ($helpText -notmatch 'DisableRemediation') { throw 'Scanner does not document the required read-only custom scan mode.' }
    $started = Get-Date
    foreach ($target in @($originalRoot,$expandedRoot)) {
        $name = Split-Path $target -Leaf
        # This flag disables remediation only for this custom scan, not antivirus
        # protection. MpCmdRun documents that this mode ignores file exclusions
        # and scans archives, so a cached CI exclusion cannot produce a false pass.
        & $scanner -Scan -ScanType 3 -File $target -DisableRemediation 2>&1 | Tee-Object -FilePath (Join-Path $reportDir ($name + '-scan.txt'))
        $scanExit = $LASTEXITCODE
        $report.scans += [ordered]@{ target=$name; exit_code=$scanExit; completed_at_utc=[DateTime]::UtcNow.ToString('o') }
        if ($scanExit -ne 0) {
            $report.status = 'detection_or_scan_error'
            $detail = (Get-Content (Join-Path $reportDir ($name + '-scan.txt')) -Tail 35) -join "`n"
            throw "Defender did not return a clean scan (exit $scanExit). $detail"
        }
    }
    $detections = @(Get-MpThreatDetection -ErrorAction Stop | Where-Object { $_.InitialDetectionTime -ge $started.AddSeconds(-5) })
    $report.recent_detections = @($detections | Select-Object ThreatID,InitialDetectionTime,ActionSuccess,Resources)
    if ($detections.Count -gt 0) { $report.status = 'detected'; throw 'Defender recorded one or more threat detections during the audit.' }
    $report.status = 'no_threat_detected_by_defender'
    Write-Host '::notice title=Exact artifact scan::Original v1.1.1 checksums match. Microsoft Defender completed both archive and extracted-file scans without detection. This does not clear the Chrome warning.'
} catch {
    $report.error = $_.Exception.Message
    $message = $report.error.Replace('%','%25').Replace("`r",'%0D').Replace("`n",'%0A')
    Write-Host "::error title=Artifact security audit::$message"
    throw
} finally {
    $report | ConvertTo-Json -Depth 12 | Set-Content -Encoding utf8 (Join-Path $reportDir 'report.json')
    $summary = @('# Original V1.1.1 artifact security audit', '', "Status: **$($report.status)**", '', 'Original artifact: 13401944459 / source run: 42001014433', '', 'No downloaded program was executed.', '', '## Files and SHA256')
    foreach ($entry in $report.files) { $summary += ('- ' + $entry.name + ': `' + $entry.sha256 + '`') }
    $summary += @('', '## Authenticode')
    foreach ($entry in $report.signatures) { $summary += ('- ' + $entry.name + ': **' + $entry.status + '**') }
    $summary += @('', '## Defender', '```json', ($report.defender | ConvertTo-Json -Depth 4), '```', '', '## Scans', '```json', (ConvertTo-Json -InputObject @($report.scans) -Depth 5), '```', '', $report.warning)
    if ($report.error) { $summary += @('', '## Audit error', '```text', $report.error, '```') }
    $summary -join "`n" | Set-Content -Encoding utf8 (Join-Path $reportDir 'report.md')
    Get-Content (Join-Path $reportDir 'report.md') -Raw | Out-File -FilePath $env:GITHUB_STEP_SUMMARY -Encoding utf8 -Append
}
