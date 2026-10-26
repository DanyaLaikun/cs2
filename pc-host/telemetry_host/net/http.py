"""Minimal HTTP/1.1 request parsing and response writing on asyncio streams.

Just enough HTTP for two jobs: accepting the game's GSI POSTs (keep-alive, Content-Length
or chunked bodies) and the bridge's GET routes / WebSocket upgrade.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

REASONS = {
    101: "Switching Protocols",
    200: "OK",
    204: "No Content",
    400: "Bad Request",
    401: "Unauthorized",
    404: "Not Found",
    405: "Method Not Allowed",
    413: "Payload Too Large",
    426: "Upgrade Required",
    431: "Request Header Fields Too Large",
    500: "Internal Server Error",
    503: "Service Unavailable",
}


class HttpError(Exception):
    """A request we refuse; the connection is answered with `status` and then closed."""

    def __init__(self, status: int, message: str = "", headers: dict[str, str] | None = None) -> None:
        super().__init__(f"{status} {message}".strip())
        self.status = status
        self.message = message or REASONS.get(status, "")
        self.headers = headers or {}


@dataclass
class Request:
    method: str
    target: str
    version: str
    headers: dict[str, str] = field(default_factory=dict)  # lower-cased names
    body: bytes = b""

    @property
    def path(self) -> str:
        return urlsplit(self.target).path or "/"

    @property
    def query(self) -> dict[str, str]:
        return {k: v[-1] for k, v in parse_qs(urlsplit(self.target).query).items()}

    @property
    def keep_alive(self) -> bool:
        tokens = self.header_tokens("connection")
        if self.version == "HTTP/1.0":
            return "keep-alive" in tokens
        return "close" not in tokens

    def header_tokens(self, name: str) -> set[str]:
        return {t.strip().lower() for t in self.headers.get(name, "").split(",") if t.strip()}


async def read_request(reader: asyncio.StreamReader, *, max_body: int) -> Request | None:
    """Read one request. Returns None on a clean EOF between requests."""
    try:
        head = await reader.readuntil(b"\r\n\r\n")
    except asyncio.IncompleteReadError as exc:
        if exc.partial.strip():
            raise HttpError(400, "truncated request head") from None
        return None
    except asyncio.LimitOverrunError:
        raise HttpError(431) from None

    lines = head[:-4].decode("latin-1").split("\r\n")
    try:
        method, target, version = lines[0].split(" ", 2)
    except ValueError:
        raise HttpError(400, "malformed request line") from None
    if not version.startswith("HTTP/1."):
        raise HttpError(400, "unsupported HTTP version")

    headers: dict[str, str] = {}
    for line in lines[1:]:
        name, sep, value = line.partition(":")
        if not sep or not name.strip():
            raise HttpError(400, "malformed header")
        key = name.strip().lower()
        value = value.strip()
        headers[key] = f"{headers[key]}, {value}" if key in headers else value

    body = b""
    if "chunked" in headers.get("transfer-encoding", "").lower():
        body = await _read_chunked(reader, max_body)
    elif "content-length" in headers:
        try:
            length = int(headers["content-length"])
        except ValueError:
            raise HttpError(400, "bad Content-Length") from None
        if length < 0:
            raise HttpError(400, "bad Content-Length")
        if length > max_body:
            raise HttpError(413)
        body = await reader.readexactly(length)
    return Request(method.upper(), target, version, headers, body)


async def _read_chunked(reader: asyncio.StreamReader, max_body: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        line = await reader.readuntil(b"\r\n")
        try:
            size = int(line.split(b";", 1)[0].strip(), 16)
        except ValueError:
            raise HttpError(400, "bad chunk size") from None
        if size == 0:
            while await reader.readuntil(b"\r\n") != b"\r\n":  # discard trailers
                pass
            return b"".join(chunks)
        total += size
        if total > max_body:
            raise HttpError(413)
        chunks.append(await reader.readexactly(size))
        await reader.readexactly(2)


def build_response(
    status: int,
    body: bytes = b"",
    *,
    content_type: str | None = None,
    keep_alive: bool = True,
    extra_headers: dict[str, str] | None = None,
) -> bytes:
    headers = {"Content-Length": str(len(body)), "Connection": "keep-alive" if keep_alive else "close"}
    if content_type:
        headers["Content-Type"] = content_type
    if extra_headers:
        headers.update(extra_headers)
    head = f"HTTP/1.1 {status} {REASONS.get(status, 'Unknown')}\r\n"
    head += "".join(f"{k}: {v}\r\n" for k, v in headers.items())
    return head.encode("latin-1") + b"\r\n" + body


async def send_response(writer: asyncio.StreamWriter, status: int, body: bytes = b"", **kwargs: object) -> None:
    writer.write(build_response(status, body, **kwargs))  # type: ignore[arg-type]
    await writer.drain()
