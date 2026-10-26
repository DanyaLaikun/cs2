"""RFC 6455 WebSocket framing and a server-side connection.

The bridge only pushes small text frames to a handful of local clients, so this keeps to the
core protocol: no extensions, no subprotocols. Client frames must be masked; server frames are not.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
from dataclasses import dataclass

OP_CONTINUATION = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WebSocketError(Exception):
    """Protocol violation; `code` is the close code to send to the peer."""

    def __init__(self, code: int, reason: str) -> None:
        super().__init__(f"{code} {reason}")
        self.code = code
        self.reason = reason


@dataclass
class Frame:
    fin: bool
    opcode: int
    payload: bytes


def accept_key(client_key: str) -> str:
    return base64.b64encode(hashlib.sha1(client_key.encode("ascii") + _GUID).digest()).decode("ascii")


def is_valid_client_key(key: str) -> bool:
    try:
        return len(base64.b64decode(key, validate=True)) == 16
    except (binascii.Error, ValueError):
        return False


def apply_mask(data: bytes, mask: bytes) -> bytes:
    """XOR `data` with the repeating 4-byte mask (big-int trick: fast without numpy)."""
    if not data:
        return b""
    n = len(data)
    key = (mask * (n // 4 + 1))[:n]
    return (int.from_bytes(data, "big") ^ int.from_bytes(key, "big")).to_bytes(n, "big")


def encode_frame(opcode: int, payload: bytes = b"", *, fin: bool = True, mask: bytes | None = None) -> bytes:
    header = bytearray([(0x80 if fin else 0) | opcode])
    n = len(payload)
    mask_bit = 0x80 if mask is not None else 0
    if n < 126:
        header.append(mask_bit | n)
    elif n < 1 << 16:
        header.append(mask_bit | 126)
        header += n.to_bytes(2, "big")
    else:
        header.append(mask_bit | 127)
        header += n.to_bytes(8, "big")
    if mask is not None:
        return bytes(header) + mask + apply_mask(payload, mask)
    return bytes(header) + payload


async def read_frame(reader: asyncio.StreamReader, *, max_payload: int, require_mask: bool) -> Frame:
    b0, b1 = await reader.readexactly(2)
    if b0 & 0x70:
        raise WebSocketError(1002, "reserved bits set (no extensions negotiated)")
    fin = bool(b0 & 0x80)
    opcode = b0 & 0x0F
    masked = bool(b1 & 0x80)
    length = b1 & 0x7F
    if length == 126:
        length = int.from_bytes(await reader.readexactly(2), "big")
    elif length == 127:
        length = int.from_bytes(await reader.readexactly(8), "big")
    if opcode >= 0x8 and (length > 125 or not fin):
        raise WebSocketError(1002, "invalid control frame")
    if require_mask and not masked:
        raise WebSocketError(1002, "client frames must be masked")
    if length > max_payload:
        raise WebSocketError(1009, "frame too large")
    mask = await reader.readexactly(4) if masked else None
    payload = await reader.readexactly(length)
    if mask is not None:
        payload = apply_mask(payload, mask)
    return Frame(fin, opcode, payload)


class WebSocketConnection:
    """Server side of an upgraded connection.

    Sending never awaits: frames go straight into the transport buffer and the bridge inspects
    `buffered_bytes` to skip frames for clients that fall behind (latest state wins).
    """

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *, max_message: int = 64 * 1024) -> None:
        self._reader = reader
        self._writer = writer
        self._max_message = max_message
        self.peer = writer.get_extra_info("peername")
        self.closed = False
        self.congested = 0  # consecutive frames skipped because the client is not reading

    @property
    def buffered_bytes(self) -> int:
        transport = self._writer.transport
        if transport is None or transport.is_closing():
            return 0
        return transport.get_write_buffer_size()

    def send_frame(self, frame: bytes) -> None:
        if self.closed or self._writer.is_closing():
            return
        self._writer.write(frame)

    def send_text(self, text: str) -> None:
        self.send_frame(encode_frame(OP_TEXT, text.encode("utf-8")))

    async def close(self, code: int = 1000, reason: str = "") -> None:
        if self.closed:
            return
        self.closed = True
        try:
            payload = code.to_bytes(2, "big") + reason.encode("utf-8")[:123]
            self._writer.write(encode_frame(OP_CLOSE, payload))
            await asyncio.wait_for(self._writer.drain(), timeout=1.0)
        except (ConnectionError, asyncio.TimeoutError, OSError):
            pass
        finally:
            self._writer.close()

    async def serve(self) -> None:
        """Read until the peer goes away: answer pings, honour the close handshake, ignore data."""
        fragments: list[bytes] = []
        fragment_size = 0
        in_message = False
        try:
            while True:
                frame = await read_frame(self._reader, max_payload=self._max_message, require_mask=True)
                op = frame.opcode
                if op == OP_PING:
                    self.send_frame(encode_frame(OP_PONG, frame.payload))
                elif op == OP_PONG:
                    pass
                elif op == OP_CLOSE:
                    code = int.from_bytes(frame.payload[:2], "big") if len(frame.payload) >= 2 else 1000
                    await self.close(code if 1000 <= code < 5000 else 1000)
                    return
                elif op in (OP_TEXT, OP_BINARY):
                    if in_message:
                        raise WebSocketError(1002, "expected continuation frame")
                    in_message = not frame.fin
                    fragments, fragment_size = [frame.payload], len(frame.payload)
                elif op == OP_CONTINUATION:
                    if not in_message:
                        raise WebSocketError(1002, "unexpected continuation frame")
                    fragment_size += len(frame.payload)
                    if fragment_size > self._max_message:
                        raise WebSocketError(1009, "message too large")
                    fragments.append(frame.payload)
                    in_message = not frame.fin
                else:
                    raise WebSocketError(1002, f"unknown opcode {op:#x}")
                # Clients have nothing to say on this protocol; completed messages are dropped.
                if not in_message:
                    fragments, fragment_size = [], 0
        except WebSocketError as exc:
            await self.close(exc.code, exc.reason)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            self.closed = True
            self._writer.close()
