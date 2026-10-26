"""asyncio TCP server that tracks its connections, so shutdown never stalls on idle keep-alive sockets."""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

log = logging.getLogger(__name__)

Handler = Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]


class TcpServer:
    def __init__(self, handler: Handler, host: str, port: int, *, name: str, limit: int = 64 * 1024) -> None:
        self._handler = handler
        self._host = host
        self._port = port
        self._name = name
        self._limit = limit
        self._server: asyncio.Server | None = None
        self._writers: set[asyncio.StreamWriter] = set()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._on_connection, self._host, self._port, limit=self._limit)

    @property
    def port(self) -> int:
        if self._server is None or not self._server.sockets:
            raise RuntimeError(f"{self._name} server is not running")
        return self._server.sockets[0].getsockname()[1]

    @property
    def host(self) -> str:
        return self._host

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        for writer in tuple(self._writers):
            writer.close()
        await self._server.wait_closed()
        self._server = None

    async def _on_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.add(writer)
        try:
            await self._handler(reader, writer)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        except Exception:
            log.exception("%s: unhandled error serving %s", self._name, writer.get_extra_info("peername"))
        finally:
            self._writers.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass
