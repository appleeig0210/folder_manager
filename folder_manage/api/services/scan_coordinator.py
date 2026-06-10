from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Coroutine, Optional, TypeVar

T = TypeVar("T")


class ScanCoordinator:
    """Wraps thread pools for background scan/thumbnail work."""

    def __init__(self, scan_workers: int = 2, thumb_workers: int = 4):
        self.scan_executor = ThreadPoolExecutor(max_workers=scan_workers)
        self.thumb_executor = ThreadPoolExecutor(max_workers=thumb_workers)

    def submit_scan(self, fn: Callable[..., T], *args: Any, **kwargs: Any):
        return self.scan_executor.submit(fn, *args, **kwargs)

    def submit_thumb(self, fn: Callable[..., T], *args: Any, **kwargs: Any):
        return self.thumb_executor.submit(fn, *args, **kwargs)

    async def run_in_scan_pool(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.scan_executor, lambda: fn(*args, **kwargs))

    async def run_in_thumb_pool(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.thumb_executor, lambda: fn(*args, **kwargs))

    def shutdown(self) -> None:
        self.scan_executor.shutdown(wait=False, cancel_futures=True)
        self.thumb_executor.shutdown(wait=False, cancel_futures=True)
