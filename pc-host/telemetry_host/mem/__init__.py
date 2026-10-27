"""CS2 process memory reader — Windows-only supplement to GSI.

Reads player positions, health, and team directly from cs2.exe memory.
Disabled automatically on non-Windows platforms.

Usage::

    from telemetry_host.mem import MemReader
    reader = MemReader(poll_hz=20, on_state=callback)
    await reader.start()
    …
    await reader.stop()
"""
from __future__ import annotations

import sys

if sys.platform == "win32":
    from .reader import MemReader

    __all__ = ["MemReader"]
else:
    __all__ = []
