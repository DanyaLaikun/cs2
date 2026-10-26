"""Replay a synthetic CS2 match into the GSI receiver, to exercise the pipeline without the game.

    python tools/simulate_gsi.py                  # spectator feed (full radar) at 20 Hz
    python tools/simulate_gsi.py --mode player    # what a live player's own client sends
    python tools/simulate_gsi.py --duration 10    # stop after 10 seconds

Payloads mimic the real GSI shape: "x, y, z" vector strings, steamid keys, full state per post.
The token defaults to gsi.token from pc-host/config.json.
"""
from __future__ import annotations

import argparse
import http.client
import json
import math
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

HOST_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOST_ROOT))

from telemetry_host.config import DEFAULT_CONFIG_PATH, load_config  # noqa: E402

# de_dust2 calibration (see maps.json); routes are authored in radar pixels for readability.
POS_X, POS_Y, SCALE = -2476.0, 3239.0, 4.4
T_ROUTES = [
    [(420, 860), (640, 760), (760, 600), (880, 420), (830, 230)],  # long A
    [(420, 860), (460, 640), (470, 480), (640, 380), (800, 240)],  # mid to short A
    [(420, 860), (230, 600), (160, 420), (180, 220)],              # B tunnels
    [(420, 860), (300, 640), (370, 450), (470, 360)],              # lower tunnels
    [(440, 870), (650, 770), (770, 610), (890, 430), (840, 250)],  # long A, second
]
CT_ROUTES = [
    [(650, 250), (820, 220), (900, 320), (880, 520)],              # A site to long
    [(650, 250), (720, 300), (620, 380)],                          # short A
    [(650, 250), (470, 320), (300, 250), (180, 200)],              # rotate B
    [(650, 250), (480, 420), (470, 560)],                          # mid doors
    [(650, 250), (420, 180), (220, 180), (260, 280)],              # B via CT
]
T_NAMES = ["Kestrel", "Vanta", "Moro", "Ditch", "Pillar"]
CT_NAMES = ["Halcyon", "Brisk", "Oslo", "Quill", "Ember"]
T_GUNS = ["weapon_ak47", "weapon_ak47", "weapon_galilar", "weapon_ak47", "weapon_awp"]
CT_GUNS = ["weapon_m4a1_silencer", "weapon_m4a1", "weapon_famas", "weapon_awp", "weapon_m4a1"]
SPEED = 230.0  # world units per second, close to rifle run speed
FREEZE, LIVE, OVER, BOMB_TIMER = 8.0, 75.0, 5.0, 40.0


def world(px: float, py: float) -> tuple[float, float]:
    return POS_X + px * SCALE, POS_Y - py * SCALE


def vec(x: float, y: float, z: float, digits: int = 2) -> str:
    return f"{x:.{digits}f}, {y:.{digits}f}, {z:.{digits}f}"


@dataclass
class Bot:
    sid: str
    name: str
    team: str
    slot: int
    gun: str
    route: list[tuple[float, float]]
    progress: float = 0.0
    hp: int = 100
    armor: int = 100
    money: int = 800
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    round_kills: int = 0
    round_dmg: int = 0
    die_at: float | None = None
    x: float = 0.0
    y: float = 0.0
    yaw: float = 0.0
    sweep: float = field(default_factory=lambda: random.uniform(0, math.tau))

    def reset_round(self) -> None:
        self.progress = random.uniform(0, 30)
        self.hp, self.armor, self.round_kills, self.round_dmg = 100, 100, 0, 0
        self.die_at = random.uniform(15, LIVE - 5) if random.random() < 0.45 else None
        self.x, self.y = world(*self.route[0])

    def step(self, t_live: float, dt: float) -> None:
        if self.hp <= 0:
            return
        if self.die_at is not None and t_live > self.die_at:
            self.hp = 0
            self.deaths += 1
            return
        if self.die_at is not None and t_live > self.die_at - 4 and self.hp > 35:
            self.hp -= random.randint(0, 6)
        self.progress += SPEED * dt
        points = [world(*p) for p in self.route]
        lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
        total = sum(lengths)
        d = self.progress % (2 * total)
        forward = d <= total
        d = d if forward else 2 * total - d  # walk the route back and forth
        for (a, b), seg in zip(zip(points, points[1:]), lengths):
            if d <= seg:
                f = d / seg
                self.x, self.y = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
                heading = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) + (0 if forward else 180)
                break
            d -= seg
        else:
            heading = self.yaw
        self.sweep += dt * 1.7
        self.yaw = heading + 35 * math.sin(self.sweep)


class Match:
    def __init__(self, mode: str, token: str) -> None:
        self.mode = mode
        self.token = token
        self.bots = [Bot(f"7656119800000000{i + 1}", T_NAMES[i], "T", i + 1, T_GUNS[i], T_ROUTES[i]) for i in range(5)]
        self.bots += [Bot(f"7656119800000001{i}", CT_NAMES[i], "CT", (i + 6) % 10, CT_GUNS[i], CT_ROUTES[i]) for i in range(5)]
        self.round = 0
        self.score = {"CT": 0, "T": 0}
        self.losses = {"CT": 0, "T": 0}
        self.history: dict[str, str] = {}
        self.clock = 0.0
        self.bomb_state = "carried"
        self.bomb_pos: tuple[float, float, float] | None = None
        self.plant_time: float | None = None
        self.winner: tuple[str, str] | None = None
        self.focus_index = 0
        self._new_round()

    def _new_round(self) -> None:
        self.clock = 0.0
        self.bomb_state, self.bomb_pos, self.plant_time, self.winner = "carried", None, None, None
        for bot in self.bots:
            bot.reset_round()
            bot.money = min(16000, bot.money + random.choice((1400, 1900, 3250)))

    @property
    def phase(self) -> str:
        if self.clock < FREEZE:
            return "freezetime"
        if self.winner is None:
            return "live"
        return "over"

    def tick(self, dt: float) -> None:
        self.clock += dt
        t_live = self.clock - FREEZE
        if self.phase == "live":
            for bot in self.bots:
                bot.step(t_live, dt)
            carrier = self.bots[0]
            if self.bomb_state == "carried" and carrier.hp > 0 and t_live > 30:
                self.bomb_state, self.bomb_pos, self.plant_time = "planted", (carrier.x, carrier.y, 96.0), t_live
            if self.bomb_state == "planted" and t_live - self.plant_time >= BOMB_TIMER:
                self.bomb_state = "exploded"
                self._end_round("T", "t_win_bomb")
            elif t_live >= LIVE:
                self._end_round("CT", "ct_win_time")
        elif self.phase == "over" and self.clock - self.end_clock >= OVER:
            self.round += 1
            self._new_round()
        self.focus_index = int(self.clock // 8) % len(self.bots)

    def _end_round(self, team: str, reason: str) -> None:
        self.winner = (team, reason)
        self.end_clock = self.clock
        self.score[team] += 1
        loser = "T" if team == "CT" else "CT"
        self.losses[team], self.losses[loser] = 0, min(4, self.losses[loser] + 1)
        self.history[str(self.round + 1)] = reason

    # --- payload ----------------------------------------------------------------------------------

    def payload(self) -> dict[str, Any]:
        focus = self.bots[0] if self.mode == "player" else self.bots[self.focus_index]
        provider_id = focus.sid if self.mode == "player" else "76561198999999999"
        body: dict[str, Any] = {
            "provider": {"name": "Counter-Strike: Global Offensive", "appid": 730, "version": 14100,
                         "steamid": provider_id, "timestamp": int(time.time())},
            "map": {
                "mode": "competitive", "name": "de_dust2", "phase": "live", "round": self.round,
                "team_ct": self._team("CT"), "team_t": self._team("T"),
                "num_matches_to_win_series": 0, "round_wins": dict(self.history),
            },
            "round": {"phase": self.phase, **({"bomb": self.bomb_state} if self.bomb_state != "carried" else {}),
                      **({"win_team": self.winner[0]} if self.winner else {})},
            "player": {"steamid": focus.sid, "activity": "playing", **self._player(focus)},
            "auth": {"token": self.token},
        }
        if self.mode == "spectator":
            body["allplayers"] = {b.sid: self._player(b) for b in self.bots}
            body["phase_countdowns"] = {"phase": self.phase, "phase_ends_in": f"{self._phase_left():.1f}"}
            body["bomb"] = self._bomb()
            body["grenades"] = self._grenades()
        return body

    def _team(self, side: str) -> dict[str, Any]:
        return {"score": self.score[side], "consecutive_round_losses": self.losses[side],
                "timeouts_remaining": 1, "matches_won_this_series": 0}

    def _player(self, b: Bot) -> dict[str, Any]:
        alive = b.hp > 0
        weapons: dict[str, Any] = {"weapon_0": {"name": "weapon_knife" if b.team == "CT" else "weapon_knife_t",
                                                "paintkit": "default", "type": "Knife", "state": "holstered"}}
        if alive:
            pistol = "weapon_usp_silencer" if b.team == "CT" else "weapon_glock"
            weapons["weapon_1"] = {"name": pistol, "paintkit": "default", "type": "Pistol", "state": "holstered",
                                   "ammo_clip": 12, "ammo_clip_max": 12, "ammo_reserve": 24}
            weapons["weapon_2"] = {"name": b.gun, "paintkit": "default", "type": "Rifle", "state": "active",
                                   "ammo_clip": 25, "ammo_clip_max": 30, "ammo_reserve": 90}
            weapons["weapon_3"] = {"name": "weapon_flashbang", "paintkit": "default", "type": "Grenade",
                                   "state": "holstered", "ammo_reserve": 2}
            if b is self.bots[0] and self.bomb_state == "carried":
                weapons["weapon_4"] = {"name": "weapon_c4", "paintkit": "default", "type": "C4", "state": "holstered"}
        rad = math.radians(b.yaw)
        state = {"health": b.hp, "armor": b.armor if alive else 0, "helmet": alive, "flashed": 0, "smoked": 0,
                 "burning": 0, "money": b.money, "round_kills": b.round_kills, "round_killhs": 0,
                 "round_totaldmg": b.round_dmg, "equip_value": 5200 if alive else 0}
        if b.team == "CT" and alive and b.slot % 2 == 0:
            state["defusekit"] = True
        return {
            "name": b.name, "observer_slot": b.slot, "team": b.team, "state": state,
            "match_stats": {"kills": b.kills, "assists": b.assists, "deaths": b.deaths, "mvps": 0, "score": b.kills * 2},
            "weapons": weapons,
            "position": vec(b.x, b.y, 96.0), "forward": vec(math.cos(rad), math.sin(rad), 0.0, 3),
        }

    def _phase_left(self) -> float:
        if self.phase == "freezetime":
            return FREEZE - self.clock
        if self.phase == "live":
            if self.bomb_state == "planted":
                return BOMB_TIMER - (self.clock - FREEZE - self.plant_time)
            return LIVE - (self.clock - FREEZE)
        return max(0.0, OVER - (self.clock - self.end_clock))

    def _bomb(self) -> dict[str, Any]:
        if self.bomb_state == "carried":
            c = self.bots[0]
            if c.hp > 0:
                return {"state": "carried", "position": vec(c.x, c.y, 96.0), "player": c.sid}
            return {"state": "dropped", "position": vec(c.x, c.y, 96.0)}
        x, y, z = self.bomb_pos
        bomb = {"state": self.bomb_state, "position": vec(x, y, z)}
        if self.bomb_state == "planted":
            bomb["countdown"] = f"{self._phase_left():.1f}"
        return bomb

    def _grenades(self) -> dict[str, Any]:
        t = self.clock - FREEZE
        out: dict[str, Any] = {}
        if self.phase != "live":
            return out
        mid = world(470, 480)
        if 10 <= t < 30:  # CT smoke into mid: 1.5 s flight, then a deployed cloud
            owner = self.bots[8]
            start = world(480, 420)
            if t < 11.5:
                f = (t - 10) / 1.5
                pos = (start[0] + (mid[0] - start[0]) * f, start[1] + (mid[1] - start[1]) * f, 120 + 80 * math.sin(f * math.pi))
                out["101"] = {"owner": int(owner.sid), "position": vec(*pos), "velocity": "0.00, 0.00, 0.00",
                              "lifetime": f"{t - 10:.1f}", "type": "smoke", "effecttime": "0.0"}
            else:
                out["101"] = {"owner": int(owner.sid), "position": vec(mid[0], mid[1], 0.0), "velocity": "0.00, 0.00, 0.00",
                              "lifetime": f"{t - 10:.1f}", "type": "smoke", "effecttime": f"{t - 11.5:.1f}"}
        if 22 <= t < 29:  # T molotov on B site
            cx, cy = world(185, 215)
            flames = {f"flame_{i}": vec(cx + 70 * math.cos(i * 0.9), cy + 70 * math.sin(i * 0.9), 0.0) for i in range(7)}
            out["102"] = {"owner": int(self.bots[2].sid), "lifetime": f"{t - 22:.1f}", "type": "inferno", "flames": flames}
        return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=None, help="GSI endpoint (default: from config.json)")
    parser.add_argument("--token", default=None, help="GSI auth token (default: gsi.token from config.json)")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--mode", choices=["spectator", "player"], default="spectator")
    parser.add_argument("--hz", type=float, default=20.0, help="payloads per second (default 20)")
    parser.add_argument("--duration", type=float, default=0.0, help="seconds to run, 0 = forever")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    random.seed(args.seed)
    cfg = load_config(args.config)
    url = urlsplit(args.url or f"http://127.0.0.1:{cfg.gsi.port}/gsi")
    match = Match(args.mode, args.token if args.token is not None else cfg.gsi.token)
    interval = 1.0 / args.hz
    conn: http.client.HTTPConnection | None = None
    started = last_report = time.monotonic()
    sent = failed = 0
    print(f"Simulating a {args.mode} feed on de_dust2 -> {url.geturl()} at {args.hz:g} Hz (Ctrl+C to stop)")

    try:
        while not args.duration or time.monotonic() - started < args.duration:
            tick_start = time.monotonic()
            match.tick(interval)
            body = json.dumps(match.payload()).encode("utf-8")
            try:
                conn = conn or http.client.HTTPConnection(url.hostname, url.port or 80, timeout=2)
                conn.request("POST", url.path or "/", body, {"Content-Type": "application/json"})
                response = conn.getresponse()
                response.read()
                if response.status != 200:
                    failed += 1
                    print(f"host answered HTTP {response.status} (wrong token?)")
                else:
                    sent += 1
            except OSError as exc:
                failed += 1
                conn = None
                print(f"post failed: {exc} - is the host running?")
                time.sleep(1.0)
            if time.monotonic() - last_report >= 5:
                last_report = time.monotonic()
                print(f"round {match.round + 1} {match.phase:<10} score CT {match.score['CT']}-{match.score['T']} T"
                      f" | sent {sent}, failed {failed}")
            time.sleep(max(0.0, interval - (time.monotonic() - tick_start)))
    except KeyboardInterrupt:
        pass
    print(f"done: sent {sent}, failed {failed}")
    return 0 if sent else 1


if __name__ == "__main__":
    sys.exit(main())
