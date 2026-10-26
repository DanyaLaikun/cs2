"""Small shared helpers."""
from __future__ import annotations

import logging
import time


class RateLimitedLogger:
    """Logs a given message key at most once per interval, so a misbehaving peer cannot flood the console."""

    def __init__(self, logger: logging.Logger, interval: float = 10.0) -> None:
        self._logger = logger
        self._interval = interval
        self._last: dict[str, float] = {}
        self._suppressed: dict[str, int] = {}

    def log(self, level: int, key: str, msg: str, *args: object, exc_info: bool = False) -> None:
        now = time.monotonic()
        last = self._last.get(key)
        if last is not None and now - last < self._interval:
            self._suppressed[key] = self._suppressed.get(key, 0) + 1
            return
        suppressed = self._suppressed.pop(key, 0)
        if suppressed:
            msg = f"{msg} (+{suppressed} similar suppressed)"
        self._last[key] = now
        self._logger.log(level, msg, *args, exc_info=exc_info)

    def warning(self, key: str, msg: str, *args: object, exc_info: bool = False) -> None:
        self.log(logging.WARNING, key, msg, *args, exc_info=exc_info)

    def error(self, key: str, msg: str, *args: object, exc_info: bool = False) -> None:
        self.log(logging.ERROR, key, msg, *args, exc_info=exc_info)
