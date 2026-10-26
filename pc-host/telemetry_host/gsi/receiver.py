"""HTTP endpoint that CS2 posts Game State Integration payloads to.

The game sends one POST at a time and waits for a 2xx before sending the next, so the
handler stays fast: parse, authenticate, hand off, answer. Requests carry the token from the
cfg file in `auth.token`; anything else on the machine posting here without it is refused.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
from typing import Any, Callable

from ..config import GsiConfig
from ..net.http import HttpError, Request, read_request, send_response
from ..net.tcp import TcpServer
from ..util import RateLimitedLogger

log = logging.getLogger(__name__)

PayloadHandler = Callable[[dict[str, Any]], None]


class GsiReceiver:
    def __init__(self, cfg: GsiConfig, on_payload: PayloadHandler) -> None:
        self._cfg = cfg
        self._on_payload = on_payload
        self._server = TcpServer(self._serve, cfg.host, cfg.port, name="gsi")
        self._limited = RateLimitedLogger(log)
        self._greeted = False
        self.accepted = 0
        self.rejected = 0

    async def start(self) -> None:
        await self._server.start()

    async def stop(self) -> None:
        await self._server.stop()

    @property
    def port(self) -> int:
        return self._server.port

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while True:
            try:
                request = await read_request(reader, max_body=self._cfg.max_body_bytes)
            except HttpError as exc:
                self.rejected += 1
                self._limited.warning("malformed", "GSI: rejected request: %s", exc)
                await send_response(writer, exc.status, keep_alive=False)
                return
            if request is None:
                return
            status = self._handle(request)
            await send_response(writer, status, keep_alive=request.keep_alive)
            if not request.keep_alive:
                return

    def _handle(self, request: Request) -> int:
        if request.method == "GET":
            return 200  # lets you check the port in a browser
        if request.method != "POST":
            return 405
        try:
            payload = json.loads(request.body)
        except ValueError:
            self.rejected += 1
            self._limited.warning("json", "GSI: body is not valid JSON")
            return 400
        if not isinstance(payload, dict):
            self.rejected += 1
            return 400
        if not self._authorized(payload):
            self.rejected += 1
            self._limited.warning("auth", "GSI: rejected payload with a missing or wrong auth token")
            return 401

        self.accepted += 1
        if not self._greeted:
            self._greeted = True
            provider = payload.get("provider") or {}
            log.info("GSI: first payload from %s (appid %s)", provider.get("name", "unknown"), provider.get("appid", "?"))
        try:
            self._on_payload(payload)
        except Exception:
            # Still answer 200: a 5xx would only make the game resend the same payload.
            self._limited.error("handler", "GSI: failed to process payload", exc_info=True)
        return 200

    def _authorized(self, payload: dict[str, Any]) -> bool:
        expected = self._cfg.token
        if not expected:
            return True
        auth = payload.get("auth")
        token = auth.get("token") if isinstance(auth, dict) else None
        return isinstance(token, str) and hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8"))
