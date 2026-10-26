import asyncio
import os
import unittest

from telemetry_host.net.websocket import (
    OP_PING,
    OP_TEXT,
    WebSocketError,
    accept_key,
    apply_mask,
    encode_frame,
    is_valid_client_key,
    read_frame,
)


def reader_with(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


class HandshakeTest(unittest.TestCase):
    def test_accept_key_matches_rfc6455_example(self):
        self.assertEqual(accept_key("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_client_key_validation(self):
        self.assertTrue(is_valid_client_key("dGhlIHNhbXBsZSBub25jZQ=="))
        self.assertFalse(is_valid_client_key("short"))
        self.assertFalse(is_valid_client_key("not base64 at all!!"))


class FramingTest(unittest.IsolatedAsyncioTestCase):
    async def test_round_trip_all_length_encodings(self):
        for size in (0, 1, 125, 126, 65535, 65536, 200_000):
            payload = os.urandom(size)
            for mask in (None, os.urandom(4)):
                frame = await read_frame(
                    reader_with(encode_frame(OP_TEXT, payload, mask=mask)), max_payload=1 << 20, require_mask=mask is not None
                )
                self.assertEqual((frame.fin, frame.opcode, frame.payload), (True, OP_TEXT, payload), (size, mask))

    def test_mask_matches_naive_xor(self):
        data, mask = os.urandom(1001), os.urandom(4)
        self.assertEqual(apply_mask(data, mask), bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
        self.assertEqual(apply_mask(apply_mask(data, mask), mask), data)

    async def test_unmasked_client_frame_rejected(self):
        with self.assertRaises(WebSocketError) as ctx:
            await read_frame(reader_with(encode_frame(OP_TEXT, b"hi")), max_payload=100, require_mask=True)
        self.assertEqual(ctx.exception.code, 1002)

    async def test_oversized_frame_rejected(self):
        with self.assertRaises(WebSocketError) as ctx:
            await read_frame(reader_with(encode_frame(OP_TEXT, b"x" * 200, mask=b"abcd")), max_payload=100, require_mask=True)
        self.assertEqual(ctx.exception.code, 1009)

    async def test_fragmented_control_frame_rejected(self):
        with self.assertRaises(WebSocketError):
            await read_frame(reader_with(encode_frame(OP_PING, b"", fin=False, mask=b"abcd")), max_payload=100, require_mask=True)


if __name__ == "__main__":
    unittest.main()
