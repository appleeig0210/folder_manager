# Install mpv for B2 native video playback (Windows)
# Usage: powershell -ExecutionPolicy Bypass -File scripts/install_mpv.ps1

$ErrorActionPreference = "Stop"

Write-Host "Checking for mpv..."
$existing = Get-Command mpv -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "mpv already on PATH: $($existing.Source)"
    exit 0
}

$bundled = Join-Path $PSScriptRoot "..\src-tauri\bin\mpv.exe"
if (Test-Path $bundled) {
    Write-Host "Bundled mpv found: $bundled"
    exit 0
}

Write-Host "Installing mpv via winget..."
winget install --id mpv.MPV -e --accept-source-agreements --accept-package-agreements

if ($LASTEXITCODE -ne 0) {
    Write-Error "winget install failed. Download mpv manually and place mpv.exe in src-tauri/bin/"
    exit 1
}

Write-Host "Done. Restart tauri:dev and open a video in the lightbox."
