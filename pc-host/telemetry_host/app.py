"""Wires the pipeline together: GSI receiver -> normalizer -> state hub -> WebSocket bridge.

Optional mem reader path (--mem-read / config mem.enabled=true):
  MemReader polls cs2.exe entity list at mem.poll_hz and calls _on_mem_state.
  When augment_gsi=True the memory positions are merged into the latest GSI state
  so weapon/round data is preserved; when False the raw memory state is published.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from .bridge.server import RADAR_TYPES, BridgeServer
from .config import Config
from .gsi.maps import MapCatalog
from .gsi.normalizer import normalize
from .gsi.receiver import GsiReceiver
from .hub import StateHub
from .security import SecurityPolicy

log = logging.getLogger("telemetry_host")

WEB_DIR = Path(__file__).resolve().parent / "web"


def _merge_mem_positions(gsi_state: dict[str, Any], mem_players: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge mem players into gsi_state.

    - GSI players that match a mem entry (by steamid, then name) get their
      pos/yaw/health/alive updated from memory.
    - Mem players with no GSI counterpart are appended directly (GSI only
      reports the local player, so all opponents come exclusively from memory).
    """
    if not mem_players:
        return gsi_state

    by_sid: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    for mp in mem_players:
        sid = mp.get("steamid")
        if sid:
            by_sid[sid] = mp
        n = (mp.get("name") or "").lower()
        if n:
            by_name[n] = mp

    matched_mem_keys: set[str] = set()

    def _update(gp: dict[str, Any]) -> dict[str, Any]:
        # GSI stores the steamid under "id", not "steamid"; try both.
        gp_sid = gp.get("steamid") or gp.get("id") or ""
        mp = by_sid.get(gp_sid) or by_name.get((gp.get("name") or "").lower())
        if not mp:
            return gp
        matched_mem_keys.add(mp.get("steamid") or (mp.get("name") or "").lower())
        out = dict(gp)
        for k in ("pos", "yaw", "hp"):  # update position/heading and health from mem
            if k in mp:
                out[k] = mp[k]
        return out

    updated_gsi = [_update(p) for p in gsi_state.get("players", [])]

    # Append mem-only players (opponents — GSI never reports them in a live match).
    # Each entry needs "id" so the Android's Player(val id: String) can deserialize.
    for mp in mem_players:
        match_key = mp.get("steamid") or (mp.get("name") or "").lower()
        if match_key not in matched_mem_keys:
            mem_id = mp.get("steamid") or f"mem_{(mp.get('name') or 'unknown').lower()}"
            updated_gsi.append({
                "id":   mem_id,
                "team": mp.get("team", ""),
                "hp":   mp.get("hp", 0),
                "pos":  mp.get("pos", [0, 0, 0]),
                "yaw":  mp.get("yaw", 0.0),
                **({"name": mp["name"]} if mp.get("name") else {}),
                **({"steamid": mp["steamid"]} if mp.get("steamid") else {}),
            })

    return {
        **gsi_state,
        "players": updated_gsi,
        "source": "gsi+mem",
    }


class TelemetryHost:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.maps = MapCatalog.load(cfg.maps_file)
        self.hub = StateHub()
        self.receiver = GsiReceiver(cfg.gsi, self._on_payload)
        self.bridge = BridgeServer(cfg.bridge, self.hub, radar_dir=cfg.radar_dir, web_dir=WEB_DIR)
        self._gsi_state: dict[str, Any] | None = None
        self._mem_reader = None
        self.security = SecurityPolicy()

        if cfg.mem.enabled:
            if sys.platform != "win32":
                log.warning("mem reader is Windows-only; ignoring mem.enabled=true")
            else:
                from .mem import MemReader
                self._mem_reader = MemReader(
                    poll_hz=cfg.mem.poll_hz,
                    on_state=self._on_mem_state,
                    security_policy=self.security,
                )
                self.security.register_conflict_handler(self._on_security_conflict)

    def _on_security_conflict(self) -> None:
        """Invoked synchronously by SecurityPolicy when FACEIT AC is detected."""
        log.warning("Security: FACEIT AC detected — stopping mem reader for compliance")
        if self._mem_reader:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._mem_reader.stop())
            else:
                asyncio.run(self._mem_reader.stop())

    def _on_payload(self, payload: dict[str, Any]) -> None:
        state = normalize(payload, self.maps)
        self._gsi_state = state
        # When the mem reader is active it publishes merged states, so skip the
        # raw GSI publish here — it has no opponent positions and causes flickering.
        if not self._mem_reader:
            self.hub.publish(state)

    def _on_mem_state(self, mem_state: dict[str, Any]) -> None:
        mem_players: list[dict] = mem_state.get("players", [])
        if self._gsi_state and self.cfg.mem.augment_gsi:
            merged = _merge_mem_positions(self._gsi_state, mem_players)
            self.hub.publish(merged)
        elif not self._gsi_state:
            self.hub.publish(mem_state)
        # If gsi_state exists and augment_gsi=False: mem publishes stand-alone
        elif not self.cfg.mem.augment_gsi:
            self.hub.publish(mem_state)

    async def start(self) -> None:
        await self.security.start()
        await self.receiver.start()
        try:
            await self.bridge.start()
        except BaseException:
            await self.receiver.stop()
            await self.security.stop()
            raise
        if self._mem_reader:
            await self._mem_reader.start()

    async def stop(self) -> None:
        if self._mem_reader:
            await self._mem_reader.stop()
        await self.bridge.stop()
        await self.receiver.stop()
        await self.security.stop()


async def run(cfg: Config) -> None:
    host = TelemetryHost(cfg)
    await host.start()
    _log_banner(host)
    stats = asyncio.create_task(_log_stats(host))
    adb = asyncio.create_task(_adb_loop(host.bridge.port))
    try:
        await asyncio.Event().wait()  # run until cancelled (Ctrl+C)
    finally:
        adb.cancel()
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
    log.info("Security       FACEIT compliance guard active  (scan every %.0fs)", host.security.SCAN_INTERVAL_S)
    if host._mem_reader:
        log.info("Mem reader     enabled @ %.0f Hz  augment_gsi=%s  (Windows cs2.exe)", cfg.mem.poll_hz, cfg.mem.augment_gsi)


async def _adb_loop(port: int, interval: float = 60.0) -> None:
    """Run `adb reverse` once immediately, then every minute to restore the tunnel after USB re-plug."""
    while True:
        try:
            proc = await asyncio.create_subprocess_exec(
                "adb", "reverse", f"tcp:{port}", f"tcp:{port}",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=5.0)
            if proc.returncode == 0:
                log.debug("adb reverse tcp:%d tcp:%d OK", port, port)
        except (FileNotFoundError, OSError):
            return  # adb not installed — no point retrying
        except asyncio.TimeoutError:
            pass
        await asyncio.sleep(interval)


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
