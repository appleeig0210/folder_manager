# Diagnose api-server.exe: dual instance vs PyInstaller parent/child
# Usage: start the app first, then run:
#   powershell -ExecutionPolicy Bypass -File scripts/check_api_server.ps1

$ErrorActionPreference = "SilentlyContinue"
$ApiPort = 8765

function Get-ProcessBrief {
    param([int]$ProcessId)
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId"
    if (-not $proc) { return $null }
    $parentName = $null
    if ($proc.ParentProcessId -gt 0) {
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.ParentProcessId)"
        if ($parent) { $parentName = $parent.Name }
    }
    [PSCustomObject]@{
        PID         = $proc.ProcessId
        Name        = $proc.Name
        ParentPID   = $proc.ParentProcessId
        ParentName  = $parentName
        StartTime   = $proc.CreationDate
        CommandLine = $proc.CommandLine
    }
}

Write-Host "=== api-server.exe processes ===" -ForegroundColor Cyan
$apiProcs = @(Get-CimInstance Win32_Process -Filter "Name='api-server.exe'")
if ($apiProcs.Count -eq 0) {
    Write-Host "[WARN] No api-server.exe found. Start the app and run again." -ForegroundColor Yellow
}
else {
    Write-Host "Found $($apiProcs.Count) api-server.exe process(es)"
    foreach ($p in $apiProcs) {
        $brief = Get-ProcessBrief -ProcessId $p.ProcessId
        Write-Host ""
        Write-Host "PID $($brief.PID)"
        Write-Host "  Parent: $($brief.ParentPID) ($($brief.ParentName))"
        Write-Host "  Started: $($brief.StartTime)"
        if ($brief.CommandLine) {
            $cmd = $brief.CommandLine
            if ($cmd.Length -gt 160) { $cmd = $cmd.Substring(0, 160) + "..." }
            Write-Host "  Cmd: $cmd"
        }
    }

    $apiPids = $apiProcs | ForEach-Object { $_.ProcessId }
    $pyInstallerLike = $false
    foreach ($p in $apiProcs) {
        if ($apiPids -contains $p.ParentProcessId) {
            $pyInstallerLike = $true
            Write-Host ""
            Write-Host "[OK] PyInstaller chain: PID $($p.ParentProcessId) -> PID $($p.ProcessId)" -ForegroundColor Green
        }
    }
    if ((-not $pyInstallerLike) -and ($apiProcs.Count -gt 1)) {
        Write-Host ""
        Write-Host "[WARN] Multiple api-server without parent/child link - possible orphan" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "=== TCP $ApiPort LISTENING ===" -ForegroundColor Cyan
$listenLines = @(netstat -ano | Select-String ":$ApiPort\s+.*LISTENING")
if ($listenLines.Count -eq 0) {
    Write-Host "[WARN] Nothing listening on port $ApiPort" -ForegroundColor Yellow
}
else {
    $listenerPids = @()
    foreach ($line in $listenLines) {
        $text = ($line -replace '\s+', ' ').Trim()
        $listenerPid = ($text -split ' ')[-1]
        $listenerPids += $listenerPid
        $brief = Get-ProcessBrief -ProcessId ([int]$listenerPid)
        $procName = if ($brief) { $brief.Name } else { "unknown" }
        Write-Host "LISTENING PID=$listenerPid ($procName) $text"
    }
    $uniqueListeners = $listenerPids | Sort-Object -Unique
    Write-Host ""
    if ($uniqueListeners.Count -eq 1) {
        Write-Host "[OK] Only 1 PID listens on $ApiPort - single backend regardless of process count" -ForegroundColor Green
    }
    else {
        Write-Host "[ERROR] $($uniqueListeners.Count) PIDs listen on $ApiPort (abnormal)" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "=== TCP $ApiPort ESTABLISHED ===" -ForegroundColor Cyan
$connLines = @(netstat -ano | Select-String ":$ApiPort\s+.*ESTABLISHED")
if ($connLines.Count -eq 0) {
    Write-Host "(no established connections)"
}
else {
    foreach ($line in $connLines) {
        Write-Host $line.Line.Trim()
    }
}

Write-Host ""
Write-Host "=== How to read results ===" -ForegroundColor Cyan
Write-Host "2 api-server.exe + 1 LISTENING  => usually OK (PyInstaller or idle orphan)"
Write-Host "2 api-server.exe + parent chain  => normal PyInstaller onefile"
Write-Host "2 api-server.exe + 0 LISTENING  => backend failed or still starting"
Write-Host "orphan with high CPU, not LISTENING => safe to kill manually"
