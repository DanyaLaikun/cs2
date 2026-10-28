"""Latest-value store between the GSI receiver (producer) and the WebSocket bridge (consumer)."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any


class StateHub:
    """Holds the newest normalized state, pre-serialized once for every client.

    A live dashboard only cares about the newest state, so publishing never queues: it replaces
    the current message and raises `changed`. The bridge decides when to flush (rate limiting),
    and identical consecutive states are not re-broadcast.
    """

    def __init__(self) -> None:
        # Created lazily on first use so construction never depends on an
        # ambient event loop (asyncio.Event() needs a running loop on Py<3.10).
        self._changed = None
        self.seq = 0
        self.payloads = 0
        self._body: str | None = None
        self._message: str | None = None
        self._last_gsi: float | None = None

    @property
    def changed(self) -> asyncio.Event:
        if self._changed is None:
            self._changed = asyncio.Event()
        return self._changed

    def publish(self, state: dict[str, Any]) -> bool:
        """Store a new state; returns False when it is identical to the current one."""
        self.payloads += 1
        self._last_gsi = time.monotonic()
        body = json.dumps(state, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        if body == self._body:
            return False
        self.seq += 1
        self._body = body
        # "t" first: lets streaming JSON decoders pick the message type without buffering.
        self._message = f'{{"t":"state","seq":{self.seq},"d":{body}}}'
        self.changed.set()
        return True

    @property
    def message(self) -> str | None:
        return self._message

    def gsi_age(self) -> float | None:
        """Seconds since the game last posted anything, or None if it never has."""
        return None if self._last_gsi is None else time.monotonic() - self._last_gsi
