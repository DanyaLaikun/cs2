"""Representative GSI payloads, shaped like what CS2 actually posts."""
from __future__ import annotations

import copy
from typing import Any

TOKEN = "test-token"

_FOCUS = {
    "steamid": "76561198000000001",
    "name": "Kestrel",
    "observer_slot": 1,
    "team": "T",
    "activity": "playing",
    "state": {
        "health": 74, "armor": 100, "helmet": True, "flashed": 0, "smoked": 0, "burning": 0,
        "money": 4750, "round_kills": 2, "round_killhs": 1, "round_totaldmg": 187, "equip_value": 5400,
    },
    "match_stats": {"kills": 12, "assists": 3, "deaths": 8, "mvps": 2, "score": 30},
    "weapons": {
        "weapon_2": {"name": "weapon_flashbang", "type": "Grenade", "state": "holstered", "ammo_reserve": 2},
        "weapon_0": {"name": "weapon_knife_t", "type": "Knife", "state": "holstered"},
        "weapon_1": {"name": "weapon_ak47", "type": "Rifle", "state": "active",
                     "ammo_clip": 27, "ammo_clip_max": 30, "ammo_reserve": 90},
    },
    "position": "-276.53, -721.10, 96.03",
    "forward": "0.000, 1.000, 0.000",
}

_CT = {
    "name": "Halcyon",
    "observer_slot": 6,
    "team": "CT",
    "state": {"health": 0, "armor": 0, "helmet": False, "flashed": 0, "money": 1200, "equip_value": 0, "defusekit": True},
    "match_stats": {"kills": 9, "assists": 1, "deaths": 11, "mvps": 0, "score": 21},
    "weapons": {},
    "position": "516.0, 2535.0, 0.0",
    "forward": "-1.0, 0.0, 0.0",
}

_MAP = {
    "mode": "competitive",
    "name": "de_dust2",
    "phase": "live",
    "round": 11,
    "team_ct": {"score": 6, "consecutive_round_losses": 1, "timeouts_remaining": 1, "matches_won_this_series": 0},
    "team_t": {"score": 5, "consecutive_round_losses": 0, "timeouts_remaining": 1, "matches_won_this_series": 0},
    "num_matches_to_win_series": 0,
    "round_wins": {"2": "t_win_bomb", "1": "ct_win_elimination", "3": "ct_win_defuse"},
}

_PROVIDER = {"name": "Counter-Strike: Global Offensive", "appid": 730, "version": 14100,
             "steamid": "76561198999999999", "timestamp": 1792727544}


def spectator_payload(token: str = TOKEN) -> dict[str, Any]:
    focus = {k: v for k, v in _FOCUS.items() if k not in ("steamid", "activity")}
    return copy.deepcopy({
        "provider": _PROVIDER,
        "map": _MAP,
        "round": {"phase": "live", "bomb": "planted"},
        "player": _FOCUS,
        "allplayers": {"76561198000000001": focus, "76561198000000010": _CT},
        "phase_countdowns": {"phase": "bomb", "phase_ends_in": "31.4"},
        "bomb": {"state": "planted", "position": "1176.0, 2359.0, 96.0", "countdown": "31.4"},
        "grenades": {
            "101": {"owner": 76561198000000010, "position": "-200.0, 1300.0, 0.0", "velocity": "0.0, 0.0, 0.0",
                    "lifetime": "6.2", "type": "smoke", "effecttime": "4.7"},
            "102": {"owner": 76561198000000001, "lifetime": "1.1", "type": "inferno",
                    "flames": {"flame_a": "-1640.0, 2359.0, 0.0", "flame_b": "-1600.5, 2370.2, 0.0"}},
        },
        "auth": {"token": token},
    })


def player_payload(token: str = TOKEN) -> dict[str, Any]:
    return copy.deepcopy({
        "provider": {**_PROVIDER, "steamid": _FOCUS["steamid"]},
        "map": _MAP,
        "round": {"phase": "live"},
        "player": _FOCUS,
        "auth": {"token": token},
    })


def menu_payload(token: str = TOKEN) -> dict[str, Any]:
    return copy.deepcopy({
        "provider": {**_PROVIDER, "steamid": _FOCUS["steamid"]},
        "player": {"steamid": _FOCUS["steamid"], "name": "Kestrel", "activity": "menu"},
        "auth": {"token": token},
    })
