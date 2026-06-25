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
pyinstaller --onefile --name api-server --paths . api/main.py `
  --hidden-import=api.deps `
  --hidden-import=api.routes.config `
  --hidden-import=api.routes.tree `
  --hidden-import=api.routes.preview `
  --hidden-import=api.routes.thumbnails `
  --hidden-import=api.routes.tags `
  --hidden-import=api.routes.files `
  --hidden-import=media_keyword_service `
  --hidden-import=folder_tags_migration `
  --hidden-import=tag_index_store `
  --hidden-import=app_paths `
  --hidden-import=exiftool_session `
  --hidden-import=media_path_filters `
  --hidden-import=people_data_store `
  --collect-submodules=uvicorn
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
