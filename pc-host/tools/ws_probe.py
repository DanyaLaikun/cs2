"""Watch the bridge's WebSocket stream from the PC, e.g. to confirm data flows before involving the phone.

    python tools/ws_probe.py                         # summary line per message
    python tools/ws_probe.py --raw --count 1         # dump one full message
    python tools/ws_probe.py --url ws://127.0.0.1:8090/ws?token=...
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telemetry_host.net.wsclient import WebSocketClient  # noqa: E402


async def probe(url: str, raw: bool, count: int) -> int:
    client = await WebSocketClient.connect(url)
    print(f"connected to {url}")
    received, started = 0, time.monotonic()
    try:
        while not count or received < count:
            text = await client.recv()
            if text is None:
                print("server closed the connection")
                return 1
            received += 1
            if raw:
                print(text)
                continue
            msg = json.loads(text)
            kind = msg.get("t")
            if kind == "state":
                d = msg["d"]
                game_map = d.get("map", {})
                rate = received / max(1e-6, time.monotonic() - started)
                print(f"state #{msg['seq']:<6} {d['mode']:<9} {game_map.get('name', '-'):<11} "
                      f"round {game_map.get('round', '-'):<3} players {len(d.get('players', [])):<2} "
                      f"grenades {len(d.get('grenades', [])):<2} {len(text):>6} B  {rate:5.1f} msg/s")
            else:
                print(f"{kind}: {text}")
    finally:
        await client.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="ws://127.0.0.1:8090/ws")
    parser.add_argument("--raw", action="store_true", help="print raw JSON messages")
    parser.add_argument("--count", type=int, default=0, help="stop after N messages (0 = forever)")
    args = parser.parse_args()
    try:
        return asyncio.run(probe(args.url, args.raw, args.count))
    except KeyboardInterrupt:
        return 0
    except OSError as exc:
        print(f"cannot connect: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
