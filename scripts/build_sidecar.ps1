# 建置 Python API sidecar 供 Tauri 打包使用
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
& (Join-Path $Root "scripts/install_exiftool.ps1")

$FolderManage = Join-Path $Root "folder_manage"
$BinDir = Join-Path $Root "src-tauri\bin"
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null

Push-Location $FolderManage
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
# 用 spec 打包：絕對 pathex + 自動掃描頂層模組，與 macOS 建置一致，新增模組免維護。
pyinstaller --clean --noconfirm api-server.spec
Pop-Location

$ExifToolDest = Join-Path $BinDir "exiftool"
if (-not (Test-Path (Join-Path $ExifToolDest "exiftool.exe"))) {
    Write-Error "ExifTool not found at $ExifToolDest after install_exiftool.ps1"
}

$Built = Join-Path $FolderManage "dist\api-server.exe"
if (Test-Path $Built) {
    Copy-Item $Built (Join-Path $BinDir "api-server-x86_64-pc-windows-msvc.exe") -Force
    Write-Host "Sidecar copied to src-tauri/bin/"
} else {
    Write-Error "api-server.exe not found after PyInstaller build"
}
