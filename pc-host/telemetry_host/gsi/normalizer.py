"""Turn raw CS2 Game State Integration payloads into the bridge's compact state model.

GSI posts the *full* state of every subscribed component on each update (plus `previously` /
`added` diffs, which we ignore), so normalization is a pure function of one payload. The game
encodes vectors as "x, y, z" strings and many numbers loosely; everything is validated here so
clients receive clean, typed JSON. Absent values are omitted rather than sent as null.
Output schema: docs/PROTOCOL.md.
"""
from __future__ import annotations

import math
from typing import Any

from .maps import MapCatalog


def normalize(payload: dict[str, Any], maps: MapCatalog | None = None) -> dict[str, Any]:
    provider = _obj(payload.get("provider"))
    raw_map = _obj(payload.get("map"))
    raw_player = _obj(payload.get("player"))
    raw_all = _obj(payload.get("allplayers"))

    players: dict[str, dict[str, Any]] = {}
    for steam_id, raw in raw_all.items():
        if isinstance(raw, dict):
            players[str(steam_id)] = _player(str(steam_id), raw)

    # `player` is the local player while playing, or whoever the spectator camera follows.
    focus = _str(raw_player.get("steamid"))
    if focus:
        own = _player(focus, raw_player)
        own["activity"] = _str(raw_player.get("activity"))
        merged = players.setdefault(focus, {})
        merged.update({k: v for k, v in own.items() if v is not None})

    if not raw_map:
        mode = "menu"
    elif raw_all:
        mode = "spectator"  # the game only sends allplayers to spectators, GOTV and casters
    else:
        mode = "player"

    return _compact(
        {
            "mode": mode,
            "provider": _provider(provider),
            "map": _map(raw_map, maps) if raw_map else None,
            "round": _round(_obj(payload.get("round"))),
            "phase": _phase(_obj(payload.get("phase_countdowns"))),
            "focus": focus,
            "players": list(players.values()),
            "bomb": _bomb(_obj(payload.get("bomb"))),
            "grenades": _grenades(_obj(payload.get("grenades"))),
        }
    )


# --- components -------------------------------------------------------------------------------


def _provider(raw: dict[str, Any]) -> dict[str, Any] | None:
    if not raw:
        return None
    return {
        "name": _str(raw.get("name")),
        "steamId": _str(raw.get("steamid")),
        "version": _int(raw.get("version")),
        "ts": _int(raw.get("timestamp")),
    }


def _map(raw: dict[str, Any], maps: MapCatalog | None) -> dict[str, Any]:
    full_name = _str(raw.get("name")) or ""
    name = full_name.replace("\\", "/").rsplit("/", 1)[-1]  # workshop maps arrive as workshop/<id>/<name>
    return {
        "name": name,
        "mode": _str(raw.get("mode")),
        "phase": _str(raw.get("phase")),
        "round": _int(raw.get("round")),
        "ct": _team(_obj(raw.get("team_ct"))),
        "t": _team(_obj(raw.get("team_t"))),
        "radar": maps.lookup(name) if maps is not None and name else None,
        "history": _history(_obj(raw.get("round_wins"))),
    }


def _team(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "score": _int(raw.get("score")),
        "name": _str(raw.get("name")),
        "losses": _int(raw.get("consecutive_round_losses")),
        "timeouts": _int(raw.get("timeouts_remaining")),
        "seriesWins": _int(raw.get("matches_won_this_series")),
    }


def _history(raw: dict[str, Any]) -> list[dict[str, Any]] | None:
    rounds = []
    for key, outcome in raw.items():
        number = _int(key)
        if number is None or not isinstance(outcome, str):
            continue
        outcome = outcome.lower()
        if outcome.startswith("ct_win_"):
            team, why = "CT", outcome[len("ct_win_"):]
        elif outcome.startswith("t_win_"):
            team, why = "T", outcome[len("t_win_"):]
        else:
            team, why = None, outcome
        rounds.append({"r": number, "w": team, "why": why})
    rounds.sort(key=lambda r: r["r"])
    return rounds or None


def _round(raw: dict[str, Any]) -> dict[str, Any] | None:
    if not raw:
        return None
    return {"phase": _str(raw.get("phase")), "bomb": _str(raw.get("bomb")), "winTeam": _side(raw.get("win_team"))}


def _phase(raw: dict[str, Any]) -> dict[str, Any] | None:
    if not raw:
        return None
    return {"name": _str(raw.get("phase")), "endsIn": _float(raw.get("phase_ends_in"))}


def _player(steam_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    state = _obj(raw.get("state"))
    stats = _obj(raw.get("match_stats"))
    yaw = pitch = None
    forward = _vec(raw.get("forward"))
    if forward:
        yaw, pitch = _angles(forward)
    return {
        "id": steam_id,
        "name": _str(raw.get("name")),
        "team": _side(raw.get("team")),
        "slot": _int(raw.get("observer_slot")),
        "hp": _int(state.get("health")),
        "armor": _int(state.get("armor")),
        "helmet": _bool(state.get("helmet")),
        "defuser": _bool(state.get("defusekit")),
        "flashed": _int(state.get("flashed")),
        "smoked": _int(state.get("smoked")),
        "burning": _int(state.get("burning")),
        "money": _int(state.get("money")),
        "equip": _int(state.get("equip_value")),
        "roundKills": _int(state.get("round_kills")),
        "roundHs": _int(state.get("round_killhs")),
        "roundDmg": _int(state.get("round_totaldmg")),
        "kills": _int(stats.get("kills")),
        "assists": _int(stats.get("assists")),
        "deaths": _int(stats.get("deaths")),
        "mvps": _int(stats.get("mvps")),
        "score": _int(stats.get("score")),
        "pos": _ivec(raw.get("position")),
        "yaw": yaw,
        "pitch": pitch,
        "weapons": _weapons(raw.get("weapons")),
    }


def _weapons(raw: Any) -> list[dict[str, Any]] | None:
    if not isinstance(raw, dict):
        return None
    out = []
    for slot in sorted(raw, key=_slot_index):
        weapon = raw[slot]
        if not isinstance(weapon, dict):
            continue
        name = _str(weapon.get("name")) or "unknown"
        out.append(
            {
                "name": name.removeprefix("weapon_"),
                "type": _str(weapon.get("type")),
                "state": _str(weapon.get("state")),
                "clip": _int(weapon.get("ammo_clip")),
                "clipMax": _int(weapon.get("ammo_clip_max")),
                "reserve": _int(weapon.get("ammo_reserve")),
            }
        )
    return out


def _slot_index(key: str) -> int:
    _, _, suffix = str(key).rpartition("_")
    return int(suffix) if suffix.isdigit() else 99


def _bomb(raw: dict[str, Any]) -> dict[str, Any] | None:
    if not raw:
        return None
    return {
        "state": _str(raw.get("state")),
        "pos": _ivec(raw.get("position")),
        "carrier": _str(raw.get("player")),
        "countdown": _float(raw.get("countdown")),
    }


def _grenades(raw: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for grenade_id, g in raw.items():
        if not isinstance(g, dict):
            continue
        flames = g.get("flames")
        out.append(
            {
                "id": str(grenade_id),
                "type": _str(g.get("type")),
                "owner": _str(g.get("owner")),
                "pos": _ivec(g.get("position")),
                "life": _float(g.get("lifetime")),
                "effect": _float(g.get("effecttime")),
                "flames": [v for v in map(_ivec, flames.values()) if v] if isinstance(flames, dict) else None,
            }
        )
    return out


# --- value coercion -----------------------------------------------------------------------------


def _compact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _compact(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_compact(v) for v in value]
    return value


def _obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _str(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)  # e.g. grenade owners arrive as bare steamid64 numbers
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    number = _number(value)
    return None if number is None else int(number)


def _float(value: Any, digits: int = 1) -> float | None:
    number = _number(value)
    return None if number is None else round(number, digits)


def _bool(value: Any) -> bool | None:
    return None if value is None else bool(value)


def _side(value: Any) -> str | None:
    return value if value in ("CT", "T") else None


def _vec(value: Any) -> list[float] | None:
    if not isinstance(value, str):
        return None
    parts = value.split(",")
    if len(parts) != 3:
        return None
    try:
        vec = [float(p) for p in parts]
    except ValueError:
        return None
    return vec if all(math.isfinite(c) for c in vec) else None


def _ivec(value: Any) -> list[int] | None:
    """Positions rounded to whole world units: ~0.2 radar px, plenty for a minimap, half the bytes."""
    vec = _vec(value)
    return [round(c) for c in vec] if vec else None


def _angles(forward: list[float]) -> tuple[float | None, float | None]:
    fx, fy, fz = forward
    if fx == 0 and fy == 0 and fz == 0:
        return None, None
    yaw = math.degrees(math.atan2(fy, fx))  # 0 = +X (east), 90 = +Y (north)
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, fz))))
    return round(yaw, 1), round(pitch, 1)
