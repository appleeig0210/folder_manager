#!/usr/bin/env python3
"""啟動 FastAPI 後端並以 pywebview 或瀏覽器開啟 Web UI。"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FOLDER_MANAGE = ROOT / "folder_manage"
FRONTEND_DIST = ROOT / "frontend" / "dist"
DEFAULT_PORT = 8765


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _wait_for_server(port: int, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_in_use(port):
            return True
        time.sleep(0.2)
    return False


def start_backend(port: int) -> subprocess.Popen:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(FOLDER_MANAGE)
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(FOLDER_MANAGE),
        env=env,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="People Folder Manager Web Shell")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--browser-only", action="store_true", help="僅開啟瀏覽器，不用 pywebview")
    args = parser.parse_args()

    proc: subprocess.Popen | None = None
    if not _port_in_use(args.port):
        proc = start_backend(args.port)
        if not _wait_for_server(args.port):
            proc.kill()
            print("Backend failed to start.", file=sys.stderr)
            return 1

    if FRONTEND_DIST.exists():
        url = f"http://127.0.0.1:{args.port}/"
    else:
        url = "http://127.0.0.1:5173/"
        print("frontend/dist 不存在 — 請先執行 `npm run build` 或 `npm run dev`。")

    if args.browser_only:
        webbrowser.open(url)
        print(f"已開啟 {url}")
        try:
            while proc is None or proc.poll() is None:
                time.sleep(1)
        except KeyboardInterrupt:
            if proc:
                proc.terminate()
        return 0

    try:
        import webview
    except ImportError:
        webbrowser.open(url)
        print(f"pywebview 未安裝，已改以瀏覽器開啟：{url}")
        try:
            while proc is None or proc.poll() is None:
                time.sleep(1)
        except KeyboardInterrupt:
            if proc:
                proc.terminate()
        return 0

    window = webview.create_window("人物資料夾管理器", url, width=1400, height=900, min_size=(900, 600))
    webview.start()
    if proc:
        proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
