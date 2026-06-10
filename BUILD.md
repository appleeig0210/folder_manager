# 人物資料夾管理器 v2 — 建置指南

Web Shell 架構：**FastAPI 後端** + **React 前端** + **Tauri / pywebview 殼層**。

## 環境需求

- Python 3.10+
- Node.js 20+
- （可選）Rust 1.77+ — 僅 Tauri 原生打包需要

## 快速開始（開發）

```bash
# 1. 安裝 Python 依賴
cd folder_manage
pip install -r requirements.txt

# 2. 安裝前端依賴
cd ../frontend
npm install

# 3. 啟動後端與前端（兩個終端）
cd ../folder_manage
python -m api.main

cd ../frontend
npm run dev
```

瀏覽器開啟 http://localhost:5173（API 代理至 http://127.0.0.1:8765）。

或使用根目錄腳本（需先 `npm install` 於根目錄以安裝 concurrently）：

```bash
npm install
npm run dev
```

## 生產模式（pywebview 桌面視窗）

```bash
cd frontend && npm run build
cd ..
pip install pywebview
python scripts/launch_app.py
```

會啟動 API 並以原生 WebView 視窗開啟 `frontend/dist`。

## Tauri 原生打包（需 Rust）

1. 安裝 [Rust](https://rustup.rs/) 與 [Tauri 先決條件](https://v2.tauri.app/start/prerequisites/)
2. 安裝 Node 依賴並產生圖示：

```bash
npm install
npm install --prefix frontend
npm run icons
```

3. 建置 Python API sidecar（依平台）：

Windows：

```powershell
npm run sidecar:win
```

macOS：

```bash
npm run sidecar:mac
```

macOS 會依目前 Rust host triple 產生 Tauri 需要的 sidecar 名稱，例如：

- `src-tauri/bin/api-server-x86_64-apple-darwin`
- `src-tauri/bin/api-server-aarch64-apple-darwin`

4. 建置 Tauri：

```bash
npm run tauri:build
```

輸出位於 `src-tauri/target/release/bundle/`。

### macOS 注意事項

- Intel Mac 與 Apple Silicon 需要分別在對應 runner/機器上建置 sidecar。
- 本專案未設定 Apple Developer 簽章與 notarization；未簽章的 `.app`/`.dmg` 第一次開啟可能需要使用者在系統安全性設定中允許。
- `tauri-plugin-drag` 支援 macOS，因此新程式的原生拖出檔案功能可隨 Tauri 版使用。

## 舊版 CustomTkinter

原桌面版仍可使用：

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
| `GET /api/thumbnails/entry` | 子資料夾縮圖 |
| `PATCH /api/tags/filter` | 篩選與排序 |
| `POST /api/files/*` | 檔案操作 |

## 手動測試清單

- [ ] 設定主資料夾並刷新樹狀欄
- [ ] 子資料夾卡片預覽與雙擊進入媒體
- [ ] 麵包屑導覽與樹狀欄同步
- [ ] 標籤 OR 篩選、媒體類型篩選
- [ ] 多選（Ctrl/Shift）與批次轉移/刪除
- [ ] 媒體燈箱 ←→ 鍵盤切換
- [ ] 標籤 JSON/CSV 匯入匯出
- [ ] 200+ 媒體項目滾動流暢度
