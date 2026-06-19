# 人物資料夾管理器 v2 — 建置指南

**桌面優先**：主要使用與開發路徑為 Tauri 桌面版。平台策略與功能矩陣見 [docs/DESKTOP_FIRST.md](docs/DESKTOP_FIRST.md)。

架構：**FastAPI 後端** + **React 前端** + **Tauri 殼層**（WebView2）。

## 環境需求

- Python 3.10+
- Node.js 20+
- Rust 1.77+ — Tauri 桌面版需要
- （可選）mpv — B2 內嵌影片播放，見 `scripts/install_mpv.ps1`
- **ExifTool** — 媒體檔 Keywords 讀寫。開發時可安裝並加入 PATH；正式打包時 `npm run sidecar:win` / `sidecar:mac` 會一併下載至 `src-tauri/bin/exiftool/`，並複製到 sidecar 同目錄。

## 快速開始（桌面版 · 推薦）

```bash
npm install
npm install --prefix frontend
npm run tauri:dev
```

會啟動 Vite、Python API（8765）、Tauri 視窗。影片播放優先 mpv → `asset://` → HTTP。

## 瀏覽器開發模式（次要）

僅供 UI 調試，功能受限（無 mpv、無 asset、無原生拖曳）：

```bash
# 終端 1
cd folder_manage && pip install -r requirements.txt && python -m api.main

# 終端 2
cd frontend && npm install && npm run dev
```

瀏覽器開啟 http://localhost:5173。頂部會顯示功能受限提示。

或使用根目錄（需 `npm install` 安裝 concurrently）：

```bash
npm run dev
```

## Tauri 正式打包

1. 安裝 [Rust](https://rustup.rs/) 與 [Tauri 先決條件](https://v2.tauri.app/start/prerequisites/)
2. 產生圖示：

```bash
npm run icons
```

3. 建置 Python API sidecar：

Windows：

```powershell
npm run sidecar:win
```

macOS：

```bash
npm run sidecar:mac
```

4. 建置安裝包：

```bash
npm run tauri:build
```

輸出位於 `src-tauri/target/release/bundle/`。

### macOS 注意事項

- Intel / Apple Silicon 需分別建置對應 sidecar。
- 未簽章的 `.app`/`.dmg` 首次開啟可能需在系統安全性設定中允許。
- `tauri-plugin-drag` 支援 macOS 原生拖出檔案。

## 舊版啟動器（pywebview）

仍可使用，但新功能（mpv、asset 協議、診斷標籤）以 **Tauri** 為準：

```bash
cd frontend && npm run build
pip install pywebview
python scripts/launch_app.py
```

## 舊版 CustomTkinter

```bash
cd folder_manage
python people_folder_manager.py
```

## API 端點摘要

| 端點 | 說明 |
|------|------|
| `GET /api/config` | 讀取設定 |
| `POST /api/config/root` | 設定主資料夾 |
| `GET /api/tree` | 樹狀結構 |
| `GET /api/preview/entries` | 子資料夾預覽 |
| `GET /api/preview/media` | 媒體預覽 |
| `GET /api/preview/tagged-media` | 標籤篩選媒體（依左側選取範圍） |
| `GET /api/thumbnails/entry` | 子資料夾縮圖 |
| `PATCH /api/tags/filter` | 篩選與排序 |
| `POST /api/tags/invalidate` | 清除媒體標籤快取 |
| `POST /api/files/*` | 檔案操作 |

## 手動測試清單（桌面版）

- [ ] `npm run tauri:dev` 啟動無誤
- [ ] 設定主資料夾並刷新樹狀欄
- [ ] 子資料夾卡片預覽與雙擊進入媒體
- [ ] 影片 lightbox：標籤顯示 `mpv 內嵌` 或 `本地 asset`
- [ ] 全片 / 精細拖動條可操作，關閉 lightbox 與應用不卡住
- [ ] 標籤 OR 篩選（左側樹 + 右側媒體）、媒體類型篩選
- [ ] 媒體右鍵添加 Keywords，移動後標籤仍保留
- [ ] 多選與批次轉移/刪除
- [ ] 原生拖出檔案（Tauri）
- [ ] 標籤 JSON/CSV 匯入匯出
