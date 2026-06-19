from __future__ import annotations

import copy
import logging

from uvicorn.config import LOGGING_CONFIG


class SuppressThumbnailFile206Filter(logging.Filter):
    """Hide noisy 206 access-log lines for video range requests during scrubbing."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        if "/api/thumbnails/file" not in message:
            return True
        return "206" not in message and "Partial Content" not in message


def uvicorn_log_config() -> dict:
    config = copy.deepcopy(LOGGING_CONFIG)
    config.setdefault("filters", {})
    config["filters"]["suppress_thumbnail_206"] = {
        "()": "api.access_log.SuppressThumbnailFile206Filter",
    }
    config["handlers"]["access"]["filters"] = ["suppress_thumbnail_206"]
    return config
