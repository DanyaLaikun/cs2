"""CS2 Source 2 memory offsets — client.dll build 14192 (October 23 2026).

HOW TO UPDATE after a CS2 patch
================================
1. Download the latest output from https://github.com/a2x/cs2-dumper/tree/main/output
2. From offsets.json: update CLIENT["dwEntityList"] and CLIENT["dwLocalPlayerController"].
3. From client_dll.json → classes: update field offsets in CONTROLLER, PAWN, SCENE_NODE.
4. Run `python -m telemetry_host --mem-read --log-level DEBUG` and look for
   "entity list pointer is null" or zero-health/zero-position readings — those
   indicate a stale offset.

The game does NOT need to be restarted; the reader detects a new PID on its own.
"""
from __future__ import annotations

# ── client.dll absolute offsets ───────────────────────────────────────────────
# Dereference once: entity_list_addr = read_u64(handle, client_base + CLIENT[key])
# Source: https://github.com/a2x/cs2-dumper main (14192, Oct 23 2026)
CLIENT: dict[str, int] = {
    "dwEntityList":            0x271C8B8,  # → CGameEntitySystem*
    "dwLocalPlayerController": 0x253EEF8,  # → C_CSPlayerController* (local client)
}

# ── C_CSPlayerController (inherits CBasePlayerController → C_BaseEntity) ──────
CONTROLLER: dict[str, int] = {
    "m_iTeamNum":      0x3E7,  # uint8  2=Terrorist  3=CT  (C_BaseEntity)
    "m_iszPlayerName": 0x6FC,  # char[128]  (CBasePlayerController)
    "m_hPlayerPawn":   0x92C,  # uint32  CHandle<C_CSPlayerPawn>  (CCSPlayerController)
    "m_iSteamID":      0x788,  # uint64  SteamID64  (CBasePlayerController)
}

# ── C_CSPlayerPawn (inherits C_BaseEntity) ────────────────────────────────────
PAWN: dict[str, int] = {
    "m_pGameSceneNode": 0x330,  # CGameSceneNode*  (C_BaseEntity)
    "m_iHealth":        0x34C,  # int32  (C_BaseEntity)
    "m_lifeState":      0x354,  # uint8  0=alive  (C_BaseEntity)
    "m_angEyeAngles":   0x3600, # QAngle float[3]: pitch, yaw, roll  (C_CSPlayerPawn)
}

# ── CGameSceneNode ─────────────────────────────────────────────────────────────
SCENE_NODE: dict[str, int] = {
    "m_vecAbsOrigin": 0xC8,  # Vector float[3]: x, y, z world units
}

# ── CGameEntitySystem / CConcreteEntityList chunk layout ──────────────────────
ENTITY_LIST: dict[str, int] = {
    # Offset within CGameEntitySystem where the array of chunk pointers starts.
    "chunks_base_offset": 0x10,
    # Each chunk pointer occupies 8 bytes (64-bit pointer).
    "chunk_ptr_stride":   0x08,
    # Each slot within a chunk is a CEntityIdentity struct of this size.
    # Verified empirically for build 14192: m_pObject sits at the very start
    # of each identity, so the struct effectively occupies 0x70 bytes per slot.
    "entry_size":         0x70,
    # Offset within CEntityIdentity where the actual entity pointer (C_BaseEntity*) lives.
    # Build 14192: entity ptr is at offset 0x00 (first field of CEntityIdentity).
    "entity_ptr_offset":  0x00,
    # Number of entity slots per chunk.
    "chunk_capacity":     512,
}

# ── Team constants ─────────────────────────────────────────────────────────────
TEAM_T:  int = 2
TEAM_CT: int = 3
