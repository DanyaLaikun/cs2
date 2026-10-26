"""End-to-end: GSI POST -> receiver -> normalizer -> hub -> bridge -> WebSocket client, on ephemeral ports."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from telemetry_host.app import TelemetryHost
from telemetry_host.config import BridgeConfig, Config, GsiConfig
from telemetry_host.net.wsclient import HandshakeError, WebSocketClient

from . import fixtures

PNG = b"\x89PNG\r\n\x1a\nfake-radar"


async def http(port: int, method: str, path: str, body: bytes = b"", *, keep_open=None) -> tuple[int, bytes]:
    reader, writer = keep_open or await asyncio.open_connection("127.0.0.1", port)
    writer.write(
        f"{method} {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n\r\n".encode() + body
    )
    await writer.drain()
    head = (await reader.readuntil(b"\r\n\r\n")).decode("latin-1")
    status = int(head.split(" ")[1])
    length = next(int(line.split(":")[1]) for line in head.split("\r\n") if line.lower().startswith("content-length"))
    data = await reader.readexactly(length)
    if keep_open is None:
        writer.close()
    return status, data


class PipelineTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        (tmp / "radars").mkdir()
        (tmp / "radars" / "de_dust2_radar_psd.png").write_bytes(PNG)
        (tmp / "maps.json").write_text(json.dumps({"de_dust2": {"posX": -2476, "posY": 3239, "scale": 4.4}}))
        self.cfg = Config(
            gsi=GsiConfig(port=0, token=fixtures.TOKEN),
            bridge=BridgeConfig(port=0, max_hz=50, heartbeat_sec=0.2),
            radar_dir=tmp / "radars",
            maps_file=tmp / "maps.json",
        )
        self.host = await self.start_host(self.cfg)

    async def start_host(self, cfg):
        host = TelemetryHost(cfg)
        await host.start()
        self.addAsyncCleanup(host.stop)
        return host

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def ws_url(self, host=None, query=""):
        return f"ws://127.0.0.1:{(host or self.host).bridge.port}/ws{query}"

    async def post(self, payload, **kw):
        return await http(self.host.receiver.port, "POST", "/gsi", json.dumps(payload).encode(), **kw)

    async def next_of(self, client, kind, timeout=3.0):
        async def wait():
            while True:
                msg = await client.recv_json(timeout)
                if msg is None:
                    self.fail("server closed the stream")
                if msg["t"] == kind:
                    return msg
        return await asyncio.wait_for(wait(), timeout)

    async def test_state_reaches_websocket_client(self):
        client = await WebSocketClient.connect(self.ws_url())
        hello = await client.recv_json()
        self.assertEqual((hello["t"], hello["v"]), ("hello", 1))

        status, _ = await self.post(fixtures.spectator_payload())
        self.assertEqual(status, 200)
        msg = await self.next_of(client, "state")
        self.assertEqual(msg["seq"], 1)
        state = msg["d"]
        self.assertEqual((state["mode"], state["map"]["name"]), ("spectator", "de_dust2"))
        self.assertEqual(state["map"]["radar"]["image"], "de_dust2")
        self.assertEqual(len(state["players"]), 2)
        await client.close()

    async def test_late_joiner_gets_current_state(self):
        await self.post(fixtures.player_payload())
        client = await WebSocketClient.connect(self.ws_url())
        await client.recv_json()  # hello
        msg = await client.recv_json()
        self.assertEqual((msg["t"], msg["d"]["mode"]), ("state", "player"))
        await client.close()

    async def test_wrong_token_is_rejected(self):
        status, _ = await self.post(fixtures.spectator_payload(token="nope"))
        self.assertEqual(status, 401)
        payload = fixtures.spectator_payload()
        del payload["auth"]
        status, _ = await self.post(payload)
        self.assertEqual(status, 401)
        self.assertEqual(self.host.hub.seq, 0)

    async def test_bad_json_is_rejected(self):
        status, _ = await http(self.host.receiver.port, "POST", "/gsi", b"{not json")
        self.assertEqual(status, 400)

    async def test_keep_alive_posts_on_one_connection(self):
        conn = await asyncio.open_connection("127.0.0.1", self.host.receiver.port)
        for round_no in range(3):
            payload = fixtures.player_payload()
            payload["map"]["round"] = round_no
            status, _ = await self.post(payload, keep_open=conn)
            self.assertEqual(status, 200)
        conn[1].close()
        self.assertEqual(self.host.hub.seq, 3)

    async def test_identical_states_are_not_rebroadcast(self):
        for _ in range(3):
            await self.post(fixtures.player_payload())
        self.assertEqual((self.host.hub.payloads, self.host.hub.seq), (3, 1))

    async def test_bursts_are_coalesced_to_latest(self):
        client = await WebSocketClient.connect(self.ws_url())
        await client.recv_json()  # hello
        for round_no in range(40):  # one burst, no awaits in between: only the newest may go out
            self.host.hub.publish({"mode": "player", "map": {"round": round_no}})
        msg = await self.next_of(client, "state")
        self.assertEqual((msg["seq"], msg["d"]["map"]["round"]), (40, 39))
        await client.close()

    async def test_broadcast_rate_is_limited(self):
        cfg = Config(gsi=GsiConfig(port=0), bridge=BridgeConfig(port=0, max_hz=5),
                     radar_dir=self.cfg.radar_dir, maps_file=self.cfg.maps_file)
        host = await self.start_host(cfg)
        client = await WebSocketClient.connect(self.ws_url(host))
        await client.recv_json()
        host.hub.publish({"n": 1})
        await self.next_of(client, "state")
        started = asyncio.get_running_loop().time()
        host.hub.publish({"n": 2})
        await self.next_of(client, "state")
        self.assertGreaterEqual(asyncio.get_running_loop().time() - started, 0.15)  # 5 Hz = 200 ms spacing
        await client.close()

    async def test_heartbeat_reports_gsi_age(self):
        client = await WebSocketClient.connect(self.ws_url())
        hb = await self.next_of(client, "hb")
        self.assertIsNone(hb["gsiAge"])
        await self.post(fixtures.player_payload())
        hb = await self.next_of(client, "hb")
        self.assertLess(hb["gsiAge"], 1.0)
        self.assertEqual(hb["clients"], 1)
        await client.close()

    async def test_ping_is_answered_and_stream_continues(self):
        client = await WebSocketClient.connect(self.ws_url())
        await client.recv_json()
        await client.ping()
        await self.post(fixtures.player_payload())
        self.assertEqual((await self.next_of(client, "state"))["d"]["mode"], "player")
        await client.close()

    async def test_radar_images_and_health(self):
        port = self.host.bridge.port
        self.assertEqual(await http(port, "GET", "/radar/de_dust2.png"), (200, PNG))
        self.assertEqual((await http(port, "GET", "/radar/de_nuke.png"))[0], 404)
        self.assertEqual((await http(port, "GET", "/radar/..%2Fmaps.png"))[0], 404)
        status, body = await http(port, "GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "ok")
        status, body = await http(port, "GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"<canvas", body)

    async def test_bridge_token_is_enforced(self):
        cfg = Config(gsi=GsiConfig(port=0), bridge=BridgeConfig(port=0, token="s3cret"),
                     radar_dir=self.cfg.radar_dir, maps_file=self.cfg.maps_file)
        host = await self.start_host(cfg)
        with self.assertRaises(HandshakeError) as ctx:
            await WebSocketClient.connect(self.ws_url(host))
        self.assertEqual(ctx.exception.status, 401)
        client = await WebSocketClient.connect(self.ws_url(host, "?token=s3cret"))
        self.assertEqual((await client.recv_json())["t"], "hello")
        await client.close()

    async def test_client_limit(self):
        cfg = Config(gsi=GsiConfig(port=0), bridge=BridgeConfig(port=0, max_clients=1),
                     radar_dir=self.cfg.radar_dir, maps_file=self.cfg.maps_file)
        host = await self.start_host(cfg)
        first = await WebSocketClient.connect(self.ws_url(host))
        await first.recv_json()
        with self.assertRaises(HandshakeError) as ctx:
            await WebSocketClient.connect(self.ws_url(host))
        self.assertEqual(ctx.exception.status, 503)
        await first.close()


if __name__ == "__main__":
    unittest.main()
