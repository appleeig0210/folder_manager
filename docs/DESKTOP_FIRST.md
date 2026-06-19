# 桌面優先（Desktop First）

人物資料夾管理器 v2 以 **Tauri 桌面版** 為主要使用與開發目標。瀏覽器模式僅供 UI 開發與基本預覽，不保證功能完整。

## 平台矩陣

| 能力 | 桌面版（主要） | 瀏覽器版（次要） |
|------|----------------|------------------|
| 殼層 | Tauri + WebView2 | 純 React（Vite dev） |
| 啟動方式 | `npm run tauri:dev` / 安裝包 | `npm run dev` + 手動開 API |
| 媒體播放 | mpv 內嵌 → `asset://` → HTTP fallback | HTTP + faststart remux |
| 影片拖動 | 毫秒級（mpv / 本地 asset） | 較慢，依 Range 串流 |
| 原生對話框 | Tauri dialog | 瀏覽器 `prompt` / 受限 |
| 檔案拖出 | `tauri-plugin-drag` | 不支援 |
| 影片存幀 | 後端 ffmpeg | `<video>` canvas（受限） |
| API | sidecar `api-server`（正式版）或 dev python | 需自行執行 `python -m api.main` |

## 影片播放 fallback 鏈（桌面）

開啟 lightbox 影片時，依序嘗試：

1. **B2 — mpv 內嵌**（需系統安裝 mpv 或 `src-tauri/bin/mpv.exe`）
2. **A — Tauri `asset://` 本機直讀**
3. **HTTP — `/api/thumbnails/file` 串流**（終端可能出現 206）

UI 標題列會顯示播放模式標籤；DevTools Console 會印 `[播放診斷] …`。

### 如何確認走哪條路

| 標籤 / Console | 意義 | Python 終端 |
|----------------|------|-------------|
| `mpv 內嵌` | B2 成功 | 通常無 `thumbnails/file` |
| `本地 asset` | A 層 | 通常無 `thumbnails/file` |
| `HTTP 串流` | fallback | 有 `GET /api/thumbnails/file` |

工作管理員可見 `mpv.exe` 代表 B2 正在運行。

## 開發指令

### 桌面版（推薦）

```bash
npm install
npm run tauri:dev
```

會同時啟動 Vite、Python API、Tauri 視窗。

### 瀏覽器版（僅 UI / 基本功能）

```bash
# 終端 1
cd folder_manage && python -m api.main

# 終端 2
cd frontend && npm run dev
```

開啟 http://localhost:5173。頂部會顯示「功能受限」提示。

### mpv 安裝（Windows，B2 需要）

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_mpv.ps1
```

或 `winget install mpv`，或將 `mpv.exe` 放到 `src-tauri/bin/`。

## 程式碼分層

| 模組 | 職責 |
|------|------|
| `frontend/src/lib/platform.ts` | 平台判斷、功能旗標、scrub profile |
| `frontend/src/lib/mediaPlayback.ts` | `asset://` vs HTTP 來源解析 |
| `frontend/src/lib/mpvPlayer.ts` | B2 mpv invoke（僅桌面） |
| `frontend/src/lib/playbackDiagnostics.ts` | 播放模式標籤與說明 |
| `src-tauri/src/mpv/` | Win32 HWND + mpv IPC（僅 Windows） |

## 正式打包

見根目錄 [BUILD.md](../BUILD.md) 的 Tauri 打包章節。`pywebview` 啟動器為舊路徑，新功能以 Tauri 為準。

## 刻意不支援的範圍

- 瀏覽器版不提供 mpv、asset 協議、原生拖曳
- 不把本機資料夾管理器部署為雲端 Web 服務（本地路徑、sidecar 架構不適用）
- 不維護瀏覽器版與桌面版 100% 功能對等
