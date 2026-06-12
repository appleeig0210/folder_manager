from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Ensure folder_manage is on sys.path when run as module or PyInstaller sidecar.
if getattr(sys, "frozen", False):
    _FOLDER_MANAGE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
else:
    _FOLDER_MANAGE = Path(__file__).resolve().parent.parent
if str(_FOLDER_MANAGE) not in sys.path:
    sys.path.insert(0, str(_FOLDER_MANAGE))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from api.deps import get_ctx
from api.routes import config, files, preview, tags, thumbnails, tree


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_ctx()
    yield
    get_ctx().shutdown()


app = FastAPI(title="People Folder Manager API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config.router)
app.include_router(tree.router)
app.include_router(preview.router)
app.include_router(thumbnails.router)
app.include_router(tags.router)
app.include_router(files.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.websocket("/ws/scan")
async def scan_ws(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"phase": "idle", "message": "pong"})
    except WebSocketDisconnect:
        pass


# Serve built frontend in production (must be last)
_FRONTEND_DIST = _FOLDER_MANAGE.parent / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")


def run():
    import uvicorn

    # 打包成 exe 時不能用字串模組路徑，否則 uvicorn 無法 import api.main。
    uvicorn.run(app, host="127.0.0.1", port=8765, reload=False)


def verify_ffmpeg() -> int:
    import subprocess

    from api.constants import APP_NAME
    from api.services.thumbnail_service import ThumbnailService

    service = ThumbnailService(APP_NAME)
    ffmpeg_path = service.ffmpeg_path
    if not ffmpeg_path:
        print("ffmpeg not found in sidecar bundle", file=sys.stderr)
        return 1

    result = subprocess.run(
        [ffmpeg_path, "-version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        print(f"ffmpeg failed to run: {ffmpeg_path}", file=sys.stderr)
        return 1

    version_line = (result.stdout or result.stderr or "").splitlines()[0:1]
    print(f"ffmpeg ok: {ffmpeg_path}")
    if version_line:
        print(version_line[0])
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--verify-ffmpeg":
        raise SystemExit(verify_ffmpeg())
    run()
