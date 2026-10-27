# Bridge protocol (v1)

The host serves everything on one port (default `8090`), so a single `adb reverse` covers it.

| Endpoint | Purpose |
|---|---|
| `GET /ws` | WebSocket stream (RFC 6455, text frames, UTF-8 JSON). Add `?token=...` when `bridge.token` is set |
| `GET /radar/<image>.png` | Radar image for `map.radar.image` or `map.radar.lowerImage`. Returns 404 if none is installed |
| `GET /health` | `{"status","version","clients","seq","gsiPayloads","gsiAge","framesSent","framesDropped"}` |
| `GET /` | Browser monitor page |

## Messages

Every message is a JSON object, and its first key `t` gives the type. Clients should ignore types and fields they don't know. The host never expects data from clients; it only answers WebSocket pings and close frames.

### `hello`: sent once, right after the upgrade

```json
{"t":"hello","v":1,"server":"cs2-telemetry-host/1.0.0","hb":2.0,"maxHz":30.0}
```

`v` is the protocol version. A change that breaks compatibility increments it. Adding fields doesn't.

### `state`: the full current state

```json
{"t":"state","seq":1234,"d":{ ... }}
```

- `seq` increases by one for each distinct state (it resets when the host restarts). Identical consecutive states aren't re-sent.
- Every state is complete, never a delta, so a client that misses frames (or connects late) simply renders the next one. A new client receives the current state immediately after `hello`.
- At most `maxHz` states per second are sent. A burst is merged into its newest state.

### `hb`: heartbeat every `hb` seconds

```json
{"t":"hb","seq":1234,"gsiAge":0.42,"clients":1}
```

`gsiAge` is the number of seconds since CS2 last posted, or `null` if it hasn't posted since the host started. CS2 sends its own heartbeat every 10 s, so an age above ~15 s means the game has stopped sending.

## State (`d`)

Conventions:

- **Absent values are omitted, never `null`.** Clients must default every field.
- Positions are world units, rounded to integers, as `[x, y, z]`. Z points up.
- `yaw` is in degrees: 0 points along +X (east) and 90 along +Y (north). `pitch` is in degrees, positive looking up.
- Player and grenade owner IDs are SteamID64 strings.

| Field | Type | Notes |
|---|---|---|
| `mode` | `"menu"` \| `"player"` \| `"spectator"` | `spectator` when the game sent `allplayers` (spectators, GOTV, casters, demos, or a local/listen server you host); `player` in a live match, where GSI sends only your own player. `players` is never filtered by mode |
| `provider` | `{name, steamId, version, ts}` | `steamId` is the local client |
| `map` | object | Missing in menus |
| `map.name` | string | Workshop paths are trimmed to the map name |
| `map.mode`, `map.phase` | string | e.g. `competitive`; `warmup` / `live` / `intermission` / `gameover` |
| `map.round` | int | Completed rounds (0-based current round) |
| `map.ct`, `map.t` | `{score, name?, losses, timeouts, seriesWins}` | `losses` = consecutive round losses (loss-bonus counter) |
| `map.radar` | `{posX, posY, scale, image, splitZ?, lowerImage?}` | Missing for maps without calibration. Radar pixel = `((x - posX) / scale, (posY - y) / scale)` on a 1024 px image. Below `splitZ` use `lowerImage` |
| `map.history` | `[{r, w?, why}]` | Round number, winner (`CT` / `T`), reason (`elimination`, `bomb`, `defuse`, `time`, ...) |
| `round` | `{phase, bomb?, winTeam?}` | `freezetime` / `live` / `over`; `planted` / `exploded` / `defused` |
| `phase` | `{name, endsIn}` | Spectator only: `freezetime`, `live`, `bomb`, `defuse`, `over`, `warmup`, `timeout_ct`, `paused`, ... `endsIn` is in seconds |
| `focus` | string | The local player, or the player the spectator camera follows |
| `players` | `[Player]` | Only the focus player in `player` mode |
| `bomb` | `{state, pos?, carrier?, countdown?}` | Spectator only. `carried` / `dropped` / `planting` / `planted` / `defusing` / `defused` / `exploded` |
| `grenades` | `[Grenade]` | Spectator only |

**Player**

| Field | Type | Notes |
|---|---|---|
| `id`, `name`, `team`, `slot` | string, string, `CT`/`T`, int | `slot` is the observer slot; 0 means the tenth key |
| `hp`, `armor`, `helmet`, `defuser` | int, int, bool, bool | |
| `flashed`, `smoked`, `burning` | int 0-255 | Effect intensity |
| `money`, `equip` | int | Cash and value of carried equipment |
| `roundKills`, `roundHs`, `roundDmg` | int | Current round |
| `kills`, `assists`, `deaths`, `mvps`, `score` | int | Match totals |
| `pos`, `yaw`, `pitch` | `[x,y,z]`, float, float | Missing when the game doesn't provide them |
| `weapons` | `[{name, type, state, clip?, clipMax?, reserve?}]` | `name` without the `weapon_` prefix (`ak47`, `c4`); `state` is `active` / `holstered` / `reloading` |
| `activity` | string | Focus player only: `playing` / `menu` / `textinput` |

**Grenade**

| Field | Type | Notes |
|---|---|---|
| `id`, `type`, `owner` | string | `type` is `frag`, `flashbang`, `smoke`, `firebomb`, `decoy` or `inferno` |
| `pos` | `[x,y,z]` | Missing for `inferno`, which uses `flames` |
| `life` | float | Seconds since thrown |
| `effect` | float | Seconds since the smoke cloud deployed (0 while in flight) |
| `flames` | `[[x,y,z]]` | Burning cells of an `inferno` |

The schema is exercised on both sides: `pc-host/tests/test_normalizer.py` checks the host output, and `android-client/app/src/test/resources/state_spectator.json` (generated by `pc-host/tools/export_fixture.py`) is parsed by `ProtocolTest.kt`.
