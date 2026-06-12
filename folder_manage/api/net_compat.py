from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)

# Windows WSA errors when the browser aborts range/stream requests.
_WIN_CLIENT_DISCONNECT_ERRORS = frozenset({10053, 10054})

_CLIENT_DISCONNECT_TYPES = (
    ConnectionResetError,
    BrokenPipeError,
    ConnectionAbortedError,
)

_handler_installed = False
_default_asyncio_exception_handler: asyncio.ExceptionHandler | None = None


def is_client_disconnect_error(exc: BaseException | None) -> bool:
    if exc is None:
        return False
    if isinstance(exc, _CLIENT_DISCONNECT_TYPES):
        return True
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) in _WIN_CLIENT_DISCONNECT_ERRORS:
        return True
    return False


def _asyncio_exception_handler(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
    if is_client_disconnect_error(context.get("exception")):
        logger.debug("Client disconnected during async I/O: %s", context.get("message"))
        return

    handler = _default_asyncio_exception_handler or loop.default_exception_handler
    handler(loop, context)


def install_client_disconnect_handling(loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Suppress noisy asyncio tracebacks when clients abort streaming connections."""
    global _handler_installed, _default_asyncio_exception_handler
    if _handler_installed:
        return

    target_loop = loop or asyncio.get_running_loop()
    _default_asyncio_exception_handler = target_loop.get_exception_handler()
    if _default_asyncio_exception_handler is None:
        _default_asyncio_exception_handler = target_loop.default_exception_handler
    target_loop.set_exception_handler(_asyncio_exception_handler)
    _handler_installed = True


class ClientDisconnectMiddleware:
    """Catch in-flight disconnect errors so they do not bubble up as 500s."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        try:
            await self.app(scope, receive, send)
        except _CLIENT_DISCONNECT_TYPES:
            logger.debug("Client disconnected during HTTP response")
        except OSError as exc:
            if sys.platform == "win32" and getattr(exc, "winerror", None) in _WIN_CLIENT_DISCONNECT_ERRORS:
                logger.debug("Client disconnected during HTTP response: %s", exc)
                return
            raise
