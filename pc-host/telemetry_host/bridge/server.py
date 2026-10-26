"""WebSocket bridge: fans the latest normalized state out to dashboard clients.

One port serves everything a client needs, so a single `adb reverse` covers it:
  GET /ws                 WebSocket stream: hello, state and hb messages (docs/PROTOCOL.md)
  GET /radar/<image>.png  radar images from the configured radar directory
  GET /health             JSON status for scripts
  GET /                   browser monitor page for checking the stream on the PC
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import re
from pathlib import Path
from typing import Any, Coroutine

from .. import PROTOCOL_VERSION, __version__
from ..config import BridgeConfig
from ..hub import StateHub
from ..net.http import HttpError, Request, read_request, send_response
from ..net.tcp import TcpServer
from ..net.websocket import OP_TEXT, WebSocketConnection, accept_key, encode_frame, is_valid_client_key

log = logging.getLogger(__name__)

_RADAR_PATH = re.compile(r"^/radar/([a-z0-9_]{1,64})\.png$")
# Accept the names Source 2 Viewer exports (de_dust2_radar_psd.png) as well as plain ones.
_RADAR_SUFFIXES = ("", "_radar", "_radar_psd")
RADAR_TYPES = {".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


class BridgeServer:
    def __init__(self, cfg: BridgeConfig, hub: StateHub, *, radar_dir: Path, web_dir: Path | None = None) -> None:
        self._cfg = cfg
        self._hub = hub
        self._radar_dir = radar_dir
        self._web_dir = web_dir
        self._server = TcpServer(self._serve, cfg.host, cfg.port, name="bridge")
        self._clients: set[WebSocketConnection] = set()
        self._tasks: list[asyncio.Task[None]] = []
        self._background: set[asyncio.Task[Any]] = set()
        self._radar_cache: dict[Path, tuple[float, bytes]] = {}
        self._stall_limit = max(10, int(cfg.max_hz * 5))  # ~5 s of frames skipped in a row
        self.frames_sent = 0
        self.frames_dropped = 0

    async def start(self) -> None:
        await self._server.start()
        self._tasks = [
            asyncio.create_task(self._broadcast_loop(), name="bridge-broadcast"),
            asyncio.create_task(self._heartbeat_loop(), name="bridge-heartbeat"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        await asyncio.gather(*(c.close(1001, "host shutting down") for c in tuple(self._clients)), return_exceptions=True)
        await self._server.stop()

    @property
    def port(self) -> int:
        return self._server.port

    @property
    def client_count(self) -> int:
        return len(self._clients)

    # --- connection handling ----------------------------------------------------------------------

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while True:
            try:
                request = await read_request(reader, max_body=8 * 1024)
                if request is None:
                    return
                if "websocket" in request.header_tokens("upgrade"):
                    await self._serve_websocket(request, reader, writer)
                    return
                if not await self._serve_http(request, writer):
                    return
            except HttpError as exc:
                await send_response(
                    writer,
                    exc.status,
                    exc.message.encode("utf-8"),
                    content_type="text/plain; charset=utf-8",
                    keep_alive=False,
                    extra_headers=exc.headers,
                )
                return

    async def _serve_websocket(self, request: Request, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if request.method != "GET":
            raise HttpError(405)
        if request.headers.get("sec-websocket-version") != "13":
            raise HttpError(426, "WebSocket version 13 required", {"Sec-WebSocket-Version": "13"})
        key = request.headers.get("sec-websocket-key", "")
        if not is_valid_client_key(key) or "upgrade" not in request.header_tokens("connection"):
            raise HttpError(400, "invalid WebSocket handshake")
        if self._cfg.token and not hmac.compare_digest(
            request.query.get("token", "").encode("utf-8"), self._cfg.token.encode("utf-8")
        ):
            raise HttpError(401, "bridge token required (?token=...)")
        if len(self._clients) >= self._cfg.max_clients:
            raise HttpError(503, "too many clients")

        writer.write(
            b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: " + accept_key(key).encode("ascii") + b"\r\n\r\n"
        )
        conn = WebSocketConnection(reader, writer)
        self._clients.add(conn)
        log.info("bridge: client connected %s (%d active)", _peer(conn.peer), len(self._clients))
        conn.send_text(self._hello())
        if self._hub.message is not None:
            conn.send_text(self._hub.message)  # newcomers get the current picture immediately
        try:
            await conn.serve()
        finally:
            self._clients.discard(conn)
            log.info("bridge: client disconnected %s (%d active)", _peer(conn.peer), len(self._clients))

    async def _serve_http(self, request: Request, writer: asyncio.StreamWriter) -> bool:
        if request.method != "GET":
            raise HttpError(405)
        status, body, content_type = 404, b"not found", "text/plain; charset=utf-8"
        headers = {"Cache-Control": "no-cache"}
        path = request.path

        if path == "/health":
            status, content_type = 200, "application/json"
            body = json.dumps(self._health()).encode("utf-8")
        elif match := _RADAR_PATH.match(path):
            found = await self._load_radar(match.group(1))
            if found is not None:
                status, (body, content_type) = 200, found
                headers["Cache-Control"] = "max-age=300"
            else:
                body = f"no radar image for {match.group(1)} in {self._radar_dir}".encode("utf-8")
        elif path in ("/", "/index.html") and self._web_dir is not None:
            page = self._web_dir / "index.html"
            if page.is_file():
                status, content_type = 200, "text/html; charset=utf-8"
                body = await asyncio.to_thread(page.read_bytes)

        await send_response(
            writer, status, body, content_type=content_type, keep_alive=request.keep_alive, extra_headers=headers
        )
        return request.keep_alive

    async def _load_radar(self, stem: str) -> tuple[bytes, str] | None:
        for suffix in _RADAR_SUFFIXES:
            for ext, content_type in RADAR_TYPES.items():
                path = self._radar_dir / f"{stem}{suffix}{ext}"
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                cached = self._radar_cache.get(path)
                if cached is None or cached[0] != mtime:
                    cached = (mtime, await asyncio.to_thread(path.read_bytes))
                    self._radar_cache[path] = cached
                return cached[1], content_type
        return None

    # --- streaming --------------------------------------------------------------------------------

    async def _broadcast_loop(self) -> None:
        loop = asyncio.get_running_loop()
        min_interval = 1.0 / self._cfg.max_hz
        next_allowed = 0.0
        while True:
            await self._hub.changed.wait()
            delay = next_allowed - loop.time()
            if delay > 0:
                # Coalesce: states published while we wait simply replace the pending message.
                await asyncio.sleep(delay)
            self._hub.changed.clear()
            next_allowed = loop.time() + min_interval
            message = self._hub.message
            if message is not None:
                self._broadcast(message)

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self._cfg.heartbeat_sec)
            age = self._hub.gsi_age()
            self._broadcast(
                json.dumps(
                    {
                        "t": "hb",
                        "seq": self._hub.seq,
                        "gsiAge": None if age is None else round(age, 2),
                        "clients": len(self._clients),
                    },
                    separators=(",", ":"),
                )
            )

    def _broadcast(self, text: str) -> None:
        if not self._clients:
            return
        frame = encode_frame(OP_TEXT, text.encode("utf-8"))  # encoded once, shared by every client
        for conn in tuple(self._clients):
            if conn.closed:
                continue
            if conn.buffered_bytes > self._cfg.max_buffered_bytes:
                # Never block on a slow reader: skip this frame, a newer one will follow.
                conn.congested += 1
                self.frames_dropped += 1
                if conn.congested == self._stall_limit:
                    log.warning("bridge: closing %s, client stopped reading", _peer(conn.peer))
                    self._spawn(conn.close(1013, "client too slow"))
                continue
            conn.congested = 0
            conn.send_frame(frame)
            self.frames_sent += 1

    def _spawn(self, coro: Coroutine[Any, Any, Any]) -> None:
        task = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    def _hello(self) -> str:
        return json.dumps(
            {
                "t": "hello",
                "v": PROTOCOL_VERSION,
                "server": f"cs2-telemetry-host/{__version__}",
                "hb": self._cfg.heartbeat_sec,
                "maxHz": self._cfg.max_hz,
            },
            separators=(",", ":"),
        )

    def _health(self) -> dict[str, Any]:
        age = self._hub.gsi_age()
        return {
            "status": "ok",
            "version": __version__,
            "clients": len(self._clients),
            "seq": self._hub.seq,
            "gsiPayloads": self._hub.payloads,
            "gsiAge": None if age is None else round(age, 2),
            "framesSent": self.frames_sent,
            "framesDropped": self.frames_dropped,
        }


def _peer(peer: Any) -> str:
    if isinstance(peer, tuple) and len(peer) >= 2:
        return f"{peer[0]}:{peer[1]}"
    return str(peer)
