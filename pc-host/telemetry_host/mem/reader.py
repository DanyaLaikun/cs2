"""MemReader: reads CS2 player state directly from cs2.exe memory.

Runs as an asyncio background task.  Blocking Windows API calls are
dispatched to a thread pool via asyncio.to_thread() so the event loop
is never blocked.

Lifecycle::

    reader = MemReader(poll_hz=20, on_state=callback)
    await reader.start()
    # callback(state_dict) is called from the event loop after each poll
    await reader.stop()

state_dict format::

    {
        "source": "mem",
        "players": [
            {
                "steamid": "76561198...",  # omitted when 0
                "name": "PlayerName",
                "team": "CT",             # or "T"
                "health": 100,
                "alive": True,
                "pos": [123, 456, 0],     # world units, rounded
                "yaw": 90.0,              # degrees
            },
            ...
        ]
    }
"""
from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from dataclasses import dataclass
from typing import Any, Callable

from . import offsets as off
from .winapi import (
    close_handle,
    find_module_base,
    find_module_base_peb,
    find_pid,
    open_process,
    read_cstr,
    read_i32,
    read_u32,
    read_u64,
    read_u8,
    read_vec3,
)

try:
    from ..security.policy import SecurityPolicy as _SecurityPolicy
except ImportError:  # security module not available in test stubs
    _SecurityPolicy = None  # type: ignore[assignment,misc]

log = logging.getLogger("telemetry_host.mem")

_PROCESS_NAME = "cs2.exe"
_MODULE_NAME  = "client.dll"
_MAX_ENTITIES = 64  # scan entity indices 1..64 for player controllers
_TEAM_STR     = {off.TEAM_T: "T", off.TEAM_CT: "CT"}


@dataclass(slots=True)
class _Ctx:
    pid:         int
    handle:      int
    client_base: int
    entity_list: int  # resolved CGameEntitySystem address


@dataclass(slots=True)
class _Player:
    idx:      int
    name:     str
    team:     str
    health:   int
    alive:    bool
    pos:      tuple[float, float, float]
    yaw:      float
    steam_id: int


class MemReader:
    """Polls cs2.exe memory at a given rate and notifies on_state with fresh player data."""

    def __init__(
        self,
        poll_hz: float = 20.0,
        on_state: Callable[[dict[str, Any]], None] | None = None,
        security_policy: "_SecurityPolicy | None" = None,
    ) -> None:
        self._hz             = max(1.0, min(poll_hz, 128.0))
        self._on_state       = on_state
        self._security       = security_policy
        self._task: asyncio.Task[None] | None = None
        self._ctx: _Ctx | None = None  # only touched inside the thread
        # State to avoid log spam when waiting for a match to start
        self._null_el_warned_at: float = 0.0  # last time we logged the null-EL warning
        self._handle_for_attach: int | None = None  # kept open across poll cycles

    @property
    def connected(self) -> bool:
        return self._ctx is not None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.get_event_loop().create_task(
            self._loop(), name="mem-reader"
        )

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await asyncio.to_thread(self._close_ctx)
        if self._handle_for_attach is not None:
            close_handle(self._handle_for_attach)
            self._handle_for_attach = None

    # ── Async loop ─────────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        interval = 1.0 / self._hz
        log.info("MemReader: started, target=%s poll=%.0f Hz (±25%% jitter)", _PROCESS_NAME, self._hz)
        while True:
            t0 = time.monotonic()
            try:
                players = await asyncio.to_thread(self._read_state)
                if players and self._on_state:
                    self._on_state(_build_state(players))
            except asyncio.CancelledError:
                raise
            except Exception:
                log.debug("MemReader: poll error", exc_info=True)
            elapsed = time.monotonic() - t0
            # Randomize the inter-poll delay (±25% uniform around the target
            # interval) so the read cadence is not a fixed-period signal.
            jittered = random.uniform(0.75 * interval, 1.25 * interval)
            await asyncio.sleep(max(0.0, jittered - elapsed))

    # ── Thread: main read cycle ────────────────────────────────────────────────

    def _read_state(self) -> list[_Player]:
        """Blocking: attach if needed, read entity list, return player list."""
        if self._security is not None and not self._security.mem_read_allowed:
            log.debug("MemReader: read skipped — blocked by security policy")
            self._close_ctx()
            return []
        if not self._ensure_ctx():
            return []
        ctx = self._ctx
        assert ctx is not None

        # Validate that the entity list pointer is still live in client.dll;
        # if the server disconnected it becomes null and we must re-attach.
        live_el = read_u64(ctx.handle, ctx.client_base + off.CLIENT["dwEntityList"])
        if not live_el or live_el != ctx.entity_list:
            log.info("MemReader: entity list changed (0x%X→0x%X) — reconnecting",
                     ctx.entity_list, live_el or 0)
            self._close_ctx()
            return []

        players = self._read_players(ctx)
        if players is None:
            log.info("MemReader: lost %s — will reconnect", _PROCESS_NAME)
            self._close_ctx()
            return []
        if players:
            log.info("MemReader: found %d players: %s", len(players),
                     [(p.name, p.team, p.health) for p in players])
        else:
            log.debug("MemReader: 0 players this poll (in menu / between rounds?)")
        return players

    # ── Thread: process attachment ─────────────────────────────────────────────

    def _ensure_ctx(self) -> bool:
        if self._ctx is not None:
            return True

        pid = find_pid(_PROCESS_NAME)
        if pid is None:
            # Process exited — release any kept handle
            if self._handle_for_attach is not None:
                close_handle(self._handle_for_attach)
                self._handle_for_attach = None
            return False

        # Reuse handle if we already have one open for this PID
        handle = self._handle_for_attach
        if handle is None:
            if self._security is not None and not self._security.check_process_open(_PROCESS_NAME):
                return False
            handle = open_process(pid)
            if handle is None:
                log.warning(
                    "MemReader: cannot open %s (PID %d) — "
                    "try running the host as the same Windows user as the game",
                    _PROCESS_NAME, pid,
                )
                return False
            self._handle_for_attach = handle

        base = find_module_base(pid, _MODULE_NAME)
        if not base:
            # FACEIT AC blocks toolhelp/EnumProcessModules enumeration at kernel level;
            # fall back to a raw PEB->Ldr walk (NtQueryInformationProcess + ReadProcessMemory).
            base = find_module_base_peb(handle, _MODULE_NAME)
            if base:
                log.info(
                    "MemReader: %s=0x%X resolved via PEB fallback (toolhelp blocked by FACEIT AC)",
                    _MODULE_NAME, base,
                )
        if not base:
            log.warning("MemReader: %s not loaded in PID %d yet", _MODULE_NAME, pid)
            return False

        el_ptr = read_u64(handle, base + off.CLIENT["dwEntityList"])
        if not el_ptr:
            # Normal while not in a match — log at most once every 10 s
            now = time.monotonic()
            if now - self._null_el_warned_at >= 10.0:
                log.debug(
                    "MemReader: waiting for match — entity list pointer is null "
                    "(normal in menu/between matches)",
                )
                self._null_el_warned_at = now
            return False

        # Entity list is valid — promote to full context
        self._handle_for_attach = None  # ownership transferred to _Ctx
        self._null_el_warned_at = 0.0   # reset so next null logs promptly
        self._ctx = _Ctx(pid=pid, handle=handle, client_base=base, entity_list=el_ptr)
        log.info(
            "MemReader: attached PID=%d  client.dll=0x%X  entity_list=0x%X",
            pid, base, el_ptr,
        )
        return True

    def _close_ctx(self) -> None:
        if self._ctx:
            close_handle(self._ctx.handle)
            self._ctx = None
            self._null_el_warned_at = 0.0

    # ── Thread: entity list navigation ────────────────────────────────────────

    def _entity_ptr(self, h: int, el: int, index: int) -> int | None:
        """Dereference the entity list to get the entity pointer at index."""
        cap       = off.ENTITY_LIST["chunk_capacity"]
        chunk_num = index // cap
        slot      = index  % cap
        chunk_addr = (
            el
            + off.ENTITY_LIST["chunks_base_offset"]
            + chunk_num * off.ENTITY_LIST["chunk_ptr_stride"]
        )
        chunk_base = read_u64(h, chunk_addr)
        if not chunk_base:
            return None
        entry_addr = chunk_base + slot * off.ENTITY_LIST["entry_size"]
        ptr = read_u64(h, entry_addr + off.ENTITY_LIST["entity_ptr_offset"])
        return ptr if ptr else None

    # ── Thread: player data extraction ────────────────────────────────────────

    def _read_players(self, ctx: _Ctx) -> list[_Player] | None:
        """
        Scan entity indices 1.._MAX_ENTITIES for C_CSPlayerController entries.
        Returns a list of players (may be empty during warmup/between rounds).
        Returns None if a fundamental read failure signals a stale handle.
        """
        h, el = ctx.handle, ctx.entity_list
        players: list[_Player] = []
        failures = 0

        for i in range(1, _MAX_ENTITIES + 1):
            ctrl = self._entity_ptr(h, el, i)
            if not ctrl:
                continue

            team_raw = read_u8(h, ctrl + off.CONTROLLER["m_iTeamNum"])
            if team_raw not in _TEAM_STR:
                continue  # not a player controller; skip

            team     = _TEAM_STR[team_raw]
            name     = read_cstr(h, ctrl + off.CONTROLLER["m_iszPlayerName"])
            steam_id = read_u64(h, ctrl + off.CONTROLLER["m_iSteamID"]) or 0

            # Resolve the player pawn via handle.
            # CS2 Source 2: entity index is stored in the low 15 bits of the handle
            # (not the high bits as in Source 1 — handle >> 9 gives the wrong index).
            pawn_handle = read_u32(h, ctrl + off.CONTROLLER["m_hPlayerPawn"])
            if pawn_handle is None or pawn_handle == 0xFFFFFFFF:
                continue
            pawn_index = pawn_handle & 0x7FFF
            pawn = self._entity_ptr(h, el, pawn_index)
            if not pawn:
                continue

            health     = read_i32(h, pawn + off.PAWN["m_iHealth"])
            life_state = read_u8(h,  pawn + off.PAWN["m_lifeState"])
            if health is None or life_state is None:
                failures += 1
                continue

            alive = (life_state == 0 and health > 0)

            # World position via scene node
            scene_node = read_u64(h, pawn + off.PAWN["m_pGameSceneNode"])
            if not scene_node:
                continue
            pos = read_vec3(h, scene_node + off.SCENE_NODE["m_vecAbsOrigin"])
            if pos is None or not all(math.isfinite(v) for v in pos):
                continue

            # Yaw from eye-angles (pitch, yaw, roll)
            eye = read_vec3(h, pawn + off.PAWN["m_angEyeAngles"])
            yaw = float(eye[1]) if eye and math.isfinite(eye[1]) else 0.0

            players.append(_Player(
                idx=i,
                name=name,
                team=team,
                health=max(0, min(int(health), 500)),
                alive=alive,
                pos=(round(pos[0]), round(pos[1]), round(pos[2])),
                yaw=round(yaw, 1),
                steam_id=steam_id,
            ))

        # Too many consecutive read failures → process handle likely stale
        if failures > _MAX_ENTITIES // 2:
            return None

        return players


# ── State dict builder ─────────────────────────────────────────────────────────

def _build_state(players: list[_Player]) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    for p in players:
        entry: dict[str, Any] = {
            "team": p.team,
            "hp":   max(0, min(p.health, 500)),  # matches Android Player.hp
            "pos":  list(p.pos),
            "yaw":  p.yaw,
        }
        if p.name:
            entry["name"] = p.name
        if p.steam_id:
            entry["steamid"] = str(p.steam_id)
        out.append(entry)

    active = any(p.alive for p in players)
    return {
        "source": "mem",
        "mode":   "player" if active else "menu",
        "players": out,
    }
