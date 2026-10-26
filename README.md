# CS2 Telemetry Dashboard

A second-screen tactical dashboard for Counter-Strike 2. The game's official **Game State Integration** (GSI) feed goes to a small host service on your PC, which streams it over a USB cable to an Android app. The app shows a live minimap, scores, economy and player status.

Nothing touches the game except Valve's supported mechanism, a `gamestate_integration_*.cfg` file in the game's `cfg` folder. There's no memory reading, no injected code and no modified files. The game decides what to send.

## What you'll see, and when

GSI is designed so that it can't give a player an advantage, and the dashboard shows exactly what the game sends:

| Situation | What the game sends | Dashboard |
|---|---|---|
| **Playing a match** | Your own player only: position, health, armor, money, weapons, stats, plus map, score and round phase | Your marker on the minimap, your status card, score and round history |
| **Spectating, GOTV, casting, demo playback** | All ten players, bomb, grenades, phase timers | Full tactical minimap, both rosters, team economy |
| **Menus** | Provider and player name | "In menus" |

The app labels which feed it's showing.

## Architecture

```
 Windows PC                                                            Android device
┌──────────────────────────────────────────────────────────┐          ┌──────────────────────────────┐
│  CS2 ──HTTP POST (GSI JSON, auth token)──┐               │          │  TelemetryClient (OkHttp WS) │
│                                          ▼               │          │   reconnect + ping/pong      │
│  pc-host (Python, stdlib only, asyncio)                  │   USB    │            │ StateFlow     │
│   GsiReceiver :3000 ─► normalize() ─► StateHub ─► Bridge ├─adb─────►│  DashboardViewModel          │
│                    validate/compact   latest-wins  :8090 │ reverse  │   ├ TacticalMinimap (Canvas) │
│                                                    /ws   │          │   │  interpolated at vsync   │
│                                          /radar/*.png    │          │   └ panels (score, economy…) │
└──────────────────────────────────────────────────────────┘          └──────────────────────────────┘
```

- **GSI receiver** (`pc-host/telemetry_host/gsi/`): a keep-alive HTTP endpoint bound to loopback. It checks the token in constant time, caps body size, and answers in about 0.5 ms (the game waits for each response before sending again).
- **Normalizer**: turns the game's loose JSON (`"x, y, z"` strings, numbers sent as strings, nested slots) into a compact, typed model. Absent values are omitted.
- **State hub and bridge**: keep only the newest state. Each state is serialized once and the same frame goes to every client. Updates are rate-limited (30 Hz default) and identical states are dropped. Slow clients have frames skipped rather than queued, and a stalled client is disconnected.
- **Android client**: a connection manager with capped backoff and dead-link detection. The minimap interpolates between updates so motion is smooth at the display's refresh rate. It redraws only the draw phase (no recomposition) and allocates nothing per frame.

## Repository layout

```
pc-host/                         Python 3.10+ host, no third-party packages
  telemetry_host/
    gsi/receiver.py              GSI HTTP endpoint
    gsi/normalizer.py            raw GSI -> protocol state
    gsi/maps.py                  world -> radar calibration
    bridge/server.py             WebSocket fan-out, radar images, /health, monitor page
    net/                         HTTP/1.1 + RFC 6455 WebSocket on asyncio streams
    hub.py, app.py, config.py    wiring
    steam.py                     finds CS2 via Steam libraries, installs the cfg
    gamefiles.py                 reads radar textures and map calibration from the game's VPK
    web/index.html               browser monitor for checking the stream on the PC
  cfg/gamestate_integration_cs2telemetry.cfg   GSI config template
  maps.json                      radar calibration per map
  radars/                        radar PNGs (`python -m telemetry_host extract-radars`)
  tools/simulate_gsi.py          synthetic match feed, for testing without the game
  tools/ws_probe.py              print the WebSocket stream in a terminal
  tools/export_fixture.py        refresh the Android test fixture from real host output
  tests/                         unittest suite (unit and end-to-end)
android-client/                  Kotlin + Jetpack Compose app (minSdk 26)
  app/src/main/java/dev/cs2telemetry/
    data/net/TelemetryClient.kt  WebSocket connection manager
    data/model/Protocol.kt       wire models (kotlinx.serialization)
    data/radar/                  radar image loading (hardware bitmaps)
    ui/minimap/                  Canvas renderer, interpolation, projection, viewport
    ui/dashboard/                screen, panels, ViewModel
scripts/usb-bridge.ps1           sets up `adb reverse` and re-applies it after replugs
docs/SETUP.md                    step-by-step setup and troubleshooting
docs/PROTOCOL.md                 WebSocket protocol and state schema
```

## Quick start

```powershell
cd pc-host
python -m telemetry_host install-cfg    # creates config.json with a token and writes the cfg into CS2
python -m telemetry_host extract-radars # radar images + calibration from your own game files
python -m telemetry_host                # start the host
adb reverse tcp:8090 tcp:8090           # in another terminal, with the phone plugged in
```

Then restart CS2, open the app, and open `http://127.0.0.1:8090/` on the PC to watch the same stream in a browser. The full walkthrough, including building the app, radar images, USB tethering and troubleshooting, is in [docs/SETUP.md](docs/SETUP.md).

## Tests

```powershell
cd pc-host
python -m unittest discover -s tests -t .
```

```powershell
cd android-client
.\gradlew test        # once the Gradle wrapper exists (see docs/SETUP.md)
```
