# Download and install ExifTool next to the Tauri sidecar binaries.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$DestDir = Join-Path $Root "src-tauri/bin/exiftool"
New-Item -ItemType Directory -Force -Path $DestDir | Out-Null

function Test-ZipFile {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $false }
    if ((Get-Item $Path).Length -lt 1MB) { return $false }
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    return $bytes.Length -ge 2 -and $bytes[0] -eq 0x50 -and $bytes[1] -eq 0x4B
}

function Copy-ExistingExifTool {
    param([string]$SourceDir)
    if (-not (Test-Path (Join-Path $SourceDir "exiftool.exe"))) {
        return $false
    }
    Write-Host "Using existing ExifTool from $SourceDir"
    Get-ChildItem -Path $SourceDir | Copy-Item -Destination $DestDir -Recurse -Force
    $TargetExe = Join-Path $DestDir "exiftool.exe"
    if (-not (Test-Path $TargetExe)) {
        $KExe = Join-Path $DestDir "exiftool(-k).exe"
        if (Test-Path $KExe) {
            Copy-Item $KExe $TargetExe -Force
        }
    }
    return (Test-Path $TargetExe)
}

$Version = "13.59"
$Arch = if ([Environment]::Is64BitOperatingSystem) { "64" } else { "32" }
$ZipPath = Join-Path $env:TEMP "exiftool-$Version`_$Arch.zip"
$DownloadUrl = "https://sourceforge.net/projects/exiftool/files/exiftool-$Version`_$Arch.zip/download"

Write-Host "Downloading ExifTool $Version ($Arch-bit)..."
if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
    curl.exe -fsSL -o $ZipPath $DownloadUrl
} else {
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $ZipPath -MaximumRedirection 10
}

if (-not (Test-ZipFile $ZipPath)) {
    Write-Warning "ExifTool download failed or returned an invalid archive."
    $fallbackDirs = @(
        (Join-Path $env:LOCALAPPDATA "Programs/ExifTool"),
        (Join-Path ${env:ProgramFiles} "ExifTool"),
        (Join-Path ${env:ProgramFiles(x86)} "ExifTool")
    )
    $cmd = Get-Command exiftool.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        $fallbackDirs = @($cmd.Source | Split-Path -Parent) + $fallbackDirs
    }
    foreach ($dir in $fallbackDirs) {
        if ($dir -and (Copy-ExistingExifTool $dir)) {
            Write-Host "ExifTool installed to $DestDir"
            exit 0
        }
    }
    Write-Error "Could not download ExifTool and no local installation was found. Install with: winget install ExifTool"
}

$ExtractDir = Join-Path $env:TEMP "exiftool-$Version`_$Arch"
if (Test-Path $ExtractDir) {
    Remove-Item -Recurse -Force $ExtractDir
}
Expand-Archive -Path $ZipPath -DestinationPath $ExtractDir -Force

$WinDir = Get-ChildItem -Path $ExtractDir -Directory | Select-Object -First 1
if (-not $WinDir) {
    Write-Error "Unexpected ExifTool archive layout"
}

Copy-Item -Path (Join-Path $WinDir.FullName "*") -Destination $DestDir -Recurse -Force
$KExe = Join-Path $DestDir "exiftool(-k).exe"
$TargetExe = Join-Path $DestDir "exiftool.exe"
if (Test-Path $KExe) {
    Copy-Item $KExe $TargetExe -Force
}

if (-not (Test-Path $TargetExe)) {
    Write-Error "ExifTool executable not found after install"
}

Write-Host "ExifTool installed to $DestDir"
