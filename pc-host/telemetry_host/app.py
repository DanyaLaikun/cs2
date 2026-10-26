"""Wires the pipeline together: GSI receiver -> normalizer -> state hub -> WebSocket bridge."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from .bridge.server import RADAR_TYPES, BridgeServer
from .config import Config
from .gsi.maps import MapCatalog
from .gsi.normalizer import normalize
from .gsi.receiver import GsiReceiver
from .hub import StateHub

log = logging.getLogger("telemetry_host")

WEB_DIR = Path(__file__).resolve().parent / "web"


class TelemetryHost:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.maps = MapCatalog.load(cfg.maps_file)
        self.hub = StateHub()
        self.receiver = GsiReceiver(cfg.gsi, self._on_payload)
        self.bridge = BridgeServer(cfg.bridge, self.hub, radar_dir=cfg.radar_dir, web_dir=WEB_DIR)

    def _on_payload(self, payload: dict[str, Any]) -> None:
        self.hub.publish(normalize(payload, self.maps))

    async def start(self) -> None:
        await self.receiver.start()
        try:
            await self.bridge.start()
        except BaseException:
            await self.receiver.stop()
            raise

    async def stop(self) -> None:
        await self.bridge.stop()
        await self.receiver.stop()


async def run(cfg: Config) -> None:
    host = TelemetryHost(cfg)
    await host.start()
    _log_banner(host)
    stats = asyncio.create_task(_log_stats(host))
    try:
        await asyncio.Event().wait()  # run until cancelled (Ctrl+C)
    finally:
        stats.cancel()
        await host.stop()
        log.info("stopped")


def _log_banner(host: TelemetryHost) -> None:
    cfg = host.cfg
    bridge_host = "127.0.0.1" if cfg.bridge.host in ("0.0.0.0", "::", "") else cfg.bridge.host
    radars = sorted(p.name for p in cfg.radar_dir.glob("*") if p.suffix.lower() in RADAR_TYPES) if cfg.radar_dir.is_dir() else []
    log.info("GSI receiver   http://%s:%d/gsi   (auth token %s)", cfg.gsi.host, host.receiver.port,
             "set" if cfg.gsi.token else "NOT SET - any local process can post state")
    log.info("Bridge         ws://%s:%d/ws   monitor: http://%s:%d/", bridge_host, host.bridge.port, bridge_host, host.bridge.port)
    if cfg.bridge.host not in ("127.0.0.1", "localhost", "::1"):
        log.info("Bridge listens on %s (tethering/LAN mode)%s", cfg.bridge.host,
                 "" if cfg.bridge.token else " - consider setting bridge.token")
    log.info("Maps           %d calibrated (%s)", len(host.maps), cfg.maps_file)
    log.info("Radar images   %d in %s", len(radars), cfg.radar_dir)
    log.info("USB tunnel     adb reverse tcp:%d tcp:%d", host.bridge.port, host.bridge.port)


async def _log_stats(host: TelemetryHost, interval: float = 30.0) -> None:
    last, last_rate, last_clients = 0, 0.0, 0
    while True:
        await asyncio.sleep(interval)
        payloads, clients = host.hub.payloads, host.bridge.client_count
        rate = (payloads - last) / interval
        # Log while the game is sending, once when it stops, and when clients come or go.
        changed = rate > 0 or last_rate > 0 or clients != last_clients
        last, last_rate, last_clients = payloads, rate, clients
        if changed:
            log.info(
                "GSI %.1f msg/s | clients %d | frames sent %d, skipped %d",
                rate, host.bridge.client_count, host.bridge.frames_sent, host.bridge.frames_dropped,
            )
