"""Minimal WebSocket client, used by tools/ws_probe.py and the test-suite (not by the host itself)."""
from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Any
from urllib.parse import urlsplit

from .websocket import OP_CLOSE, OP_PING, OP_PONG, OP_TEXT, accept_key, encode_frame, read_frame


class HandshakeError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"handshake failed: HTTP {status} {detail}".strip())
        self.status = status


class WebSocketClient:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer

    @classmethod
    async def connect(cls, url: str, timeout: float = 5.0) -> WebSocketClient:
        parts = urlsplit(url)
        host = parts.hostname or "127.0.0.1"
        port = parts.port or 80
        target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        writer.write(
            (
                f"GET {target} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
                f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
            ).encode("ascii")
        )
        head = (await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout)).decode("latin-1")
        status_line, *header_lines = head.strip().split("\r\n")
        status = int(status_line.split(" ")[1])
        headers = {k.strip().lower(): v.strip() for k, _, v in (h.partition(":") for h in header_lines)}
        if status != 101:
            writer.close()
            raise HandshakeError(status, status_line)
        if headers.get("sec-websocket-accept") != accept_key(key):
            writer.close()
            raise HandshakeError(status, "bad Sec-WebSocket-Accept")
        return cls(reader, writer)

    async def recv(self) -> str | None:
        """Next text message, or None once the server closes."""
        while True:
            frame = await read_frame(self._reader, max_payload=16 * 1024 * 1024, require_mask=False)
            if frame.opcode == OP_TEXT:
                return frame.payload.decode("utf-8")
            if frame.opcode == OP_PING:
                self._writer.write(encode_frame(OP_PONG, frame.payload, mask=os.urandom(4)))
            elif frame.opcode == OP_CLOSE:
                return None

    async def recv_json(self, timeout: float = 5.0) -> dict[str, Any] | None:
        text = await asyncio.wait_for(self.recv(), timeout)
        return None if text is None else json.loads(text)

    async def ping(self, payload: bytes = b"hi") -> None:
        self._writer.write(encode_frame(OP_PING, payload, mask=os.urandom(4)))
        await self._writer.drain()

    async def close(self) -> None:
        try:
            self._writer.write(encode_frame(OP_CLOSE, (1000).to_bytes(2, "big"), mask=os.urandom(4)))
            await self._writer.drain()
        except (ConnectionError, OSError):
            pass
        self._writer.close()
