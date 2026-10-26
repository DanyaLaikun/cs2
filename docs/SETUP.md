# Setup and deployment guide

This takes about 15 minutes the first time. The order:

1. [Prerequisites](#1-prerequisites)
2. [Start the PC host](#2-start-the-pc-host)
3. [Enable Game State Integration in CS2](#3-enable-game-state-integration-in-cs2)
4. [Radar images (optional)](#4-radar-images-optional)
5. [Build and install the Android app](#5-build-and-install-the-android-app)
6. [Connect the phone over USB](#6-connect-the-phone-over-usb)
7. [Run a session](#7-run-a-session)
8. [Alternative: USB tethering or Wi-Fi](#8-alternative-usb-tethering-or-wi-fi)
9. [Testing without the game](#9-testing-without-the-game)
10. [Tuning latency and load](#10-tuning-latency-and-load)
11. [Troubleshooting](#11-troubleshooting)
12. [Security and removal](#12-security-and-removal)

---

## 1. Prerequisites

| On | Needed | Notes |
|---|---|---|
| PC | Windows 10/11 with CS2 | Linux works too, but paths below are for Windows |
| PC | Python 3.10 or newer | Standard library only, nothing to `pip install`. Developed on 3.14 |
| PC | Android Studio Ladybug (2024.2) or newer | Builds the app and installs the Android SDK, including `adb` |
| Phone or tablet | Android 8.0 (API 26) or newer | Developer options and USB debugging enabled (section 6) |
| Both | A USB data cable | Some cables only carry power. If `adb devices` shows nothing, try another one |

To use `adb` from any terminal, add Platform-Tools to `PATH`. Android Studio installs it under `%LOCALAPPDATA%\Android\Sdk\platform-tools`:

```powershell
$env:Path += ";$env:LOCALAPPDATA\Android\Sdk\platform-tools"   # this terminal only
adb version
```

## 2. Start the PC host

```powershell
cd pc-host
python -m telemetry_host install-cfg     # step 3 explains what this does
python -m telemetry_host
```

You should see:

```
GSI receiver   http://127.0.0.1:3000/gsi   (auth token set)
Bridge         ws://127.0.0.1:8090/ws   monitor: http://127.0.0.1:8090/
Maps           11 calibrated (...\maps.json)
Radar images   0 in ...\radars
USB tunnel     adb reverse tcp:8090 tcp:8090
```

Leave it running. Stop it with `Ctrl+C`. Useful options:

```powershell
python -m telemetry_host --help
python -m telemetry_host --bridge-port 9000 --max-hz 20 --log-level DEBUG
```

All settings live in `pc-host/config.json`, which is created from `config.example.json`:

| Key | Default | Meaning |
|---|---|---|
| `gsi.host` / `gsi.port` | `127.0.0.1` / `3000` | Where CS2 posts. Keep it on loopback |
| `gsi.token` | generated | Must match `auth.token` in the cfg file. Payloads without it are rejected |
| `bridge.host` / `bridge.port` | `127.0.0.1` / `8090` | Where the app connects. Use `0.0.0.0` only for tethering or Wi-Fi |
| `bridge.token` | empty | When set, clients must connect with `?token=...` (the app has a field for it) |
| `bridge.max_hz` | `30` | Maximum state frames per second sent to each client |
| `bridge.heartbeat_sec` | `2.0` | Heartbeat interval, used for "game feed live/idle" status |
| `radar_dir`, `maps_file` | `radars`, `maps.json` | Relative to the config file |

## 3. Enable Game State Integration in CS2

CS2 loads every `gamestate_integration_*.cfg` in its `cfg` folder at startup and posts game state to the `uri` in each one. This is Valve's supported integration point, used by tournament HUDs and RGB peripherals.

**Automatic (recommended):**

```powershell
python -m telemetry_host install-cfg
```

This creates `config.json` with a random token if it doesn't exist yet. It then finds CS2 in any of your Steam libraries (it reads `libraryfolders.vdf`) and writes `gamestate_integration_cs2telemetry.cfg` with the matching URI and token. Options:

```powershell
python -m telemetry_host install-cfg --print                          # show the cfg, write nothing
python -m telemetry_host install-cfg --cs2-dir "D:\SteamLibrary\steamapps\common\Counter-Strike Global Offensive"
```

**Manual:** copy `pc-host/cfg/gamestate_integration_cs2telemetry.cfg` to

```
<Steam library>\steamapps\common\Counter-Strike Global Offensive\game\csgo\cfg\
```

then replace `CHANGE_ME` with `gsi.token` from `config.json`. If you changed `gsi.port`, update `uri` too.

**Restart CS2.** The cfg is only read at launch. Once you load into a map (or the main menu), the host logs:

```
GSI: first payload from Counter-Strike: Global Offensive (appid 730)
```

CS2 still reports its provider name as "Counter-Strike: Global Offensive". That's expected.

## 4. Radar images (optional)

The app draws a calibrated grid when it has no radar image, so positions are correct either way. Images make the map readable. They're Valve assets from your own install, so they aren't in this repo. Export them from your game files with one command:

```powershell
python -m telemetry_host extract-radars
```

This reads `game\csgo\pak01_dir.vpk` and doesn't change it. It decodes every radar texture (`panorama/images/overheadmaps/*.vtex_c`, including the `_lower` levels of Nuke, Vertigo and Train) into `pc-host/radars/*.png`, which takes about 5 seconds. It also regenerates `pc-host/maps.json` from the game's own calibration files (`resource/overviews/<map>.txt`) and prints any values that changed. Run it again after a CS2 update that reworks a map, then restart the host.

The host serves the images to the app over the same USB tunnel (`GET /radar/<map>.png`), so they never have to be packed into the APK. Maps without calibration still stream, they just have no minimap.

## 5. Build and install the Android app

**Android Studio (recommended)**

1. **File → Open** and choose the `android-client` folder of your clone. Accept the Gradle sync. Android Studio downloads Gradle 8.11.1 and the dependencies.
2. Connect the device (section 6) and select it in the device dropdown.
3. Press **Run ▶**. The app installs and starts.

**Command line.** This needs JDK 17 in `JAVA_HOME`, and `local.properties` must point at an Android SDK with platform 35 (`sdk.dir=...`). If `gradlew.bat` is missing, regenerate it with `gradle wrapper --gradle-version 8.11.1`. Then:

```powershell
cd android-client
.\gradlew installDebug        # build and install on the connected device
.\gradlew test                # JVM unit tests
.\gradlew assembleRelease     # minified build, signed with the debug key for sideloading
```

Toolchain: AGP 8.7.3, Kotlin 2.1.0, Compose BOM 2024.12.01, OkHttp 4.12, kotlinx.serialization 1.7.3, compile/target SDK 35, JDK 17 (Android Studio's bundled JDK works).

## 6. Connect the phone over USB

1. On the phone, open **Settings → About phone** and tap **Build number** seven times to enable Developer options.
2. Turn on **Settings → System → Developer options → USB debugging**.
3. Plug in the cable and accept the **Allow USB debugging?** prompt. Tick *Always allow from this computer*.
4. Check the connection:

   ```powershell
   adb devices
   # List of devices attached
   # R58N123ABC      device
   ```

5. Open the tunnel:

   ```powershell
   adb reverse tcp:8090 tcp:8090
   adb reverse --list          # should show tcp:8090 tcp:8090
   ```

**Why `reverse` and not `forward`:** the app is the client and the PC runs the server. `adb reverse` makes `127.0.0.1:8090` on the phone reach `127.0.0.1:8090` on the PC. `adb forward` works the other way, PC to phone, and would only help if the phone were the server.

The mapping is lost whenever the cable is replugged or adb restarts. `scripts/usb-bridge.ps1 -Watch` checks every few seconds and re-applies it:

```powershell
.\scripts\usb-bridge.ps1 -Watch              # keep the tunnel alive
.\scripts\usb-bridge.ps1 -Serial R58N123ABC  # pick a device when several are connected
.\scripts\usb-bridge.ps1 -Remove             # tear the tunnel down
```

If Windows refuses to run local scripts because of the execution policy, you can either run `adb reverse` directly as above, or start the script with a one-off policy override for that process (`powershell -ExecutionPolicy Bypass -File .\scripts\usb-bridge.ps1 -Watch`). Use the override only if you're comfortable with it.

## 7. Run a session

Start things in any order. Each piece reconnects on its own:

1. `python -m telemetry_host` (PC)
2. `.\scripts\usb-bridge.ps1 -Watch` or `adb reverse tcp:8090 tcp:8090` (PC)
3. Launch CS2 (after the cfg is installed)
4. Open **CS2 Telemetry** on the phone. The default endpoint is `127.0.0.1:8090`; tap the address in the top bar to change it.

The status bar tells you where the chain stands:

| Status bar | Meaning |
|---|---|
| `OFFLINE · No route to host: is adb reverse active?` | The tunnel is missing. Run step 2 |
| `OFFLINE · Tunnel is up but the host is not answering` | The tunnel is fine but the host isn't running |
| `LINKED · no game data yet` | Phone and host are connected, but CS2 hasn't posted yet. See section 3 |
| `LINKED · game feed idle for 40s` | CS2 has stopped sending, for example because it was closed |
| `LINKED · Game feed live` | Everything is working |

The screen stays on while the app is open, and the link pauses when the app goes to the background. The layout adapts: landscape puts the map on the left and details on the right, portrait stacks them. On the minimap:

- **Pinch** to zoom and **drag** to pan.
- **Double-tap** to reset the view.
- **FOLLOW** keeps the focused player centered.
- **LEVEL** switches between floors on Nuke and Vertigo.

## 8. Alternative: USB tethering or Wi-Fi

Use this when adb isn't an option. The phone then connects to the PC's IP address instead of `127.0.0.1`.

1. Choose a bridge token and add it to `config.json` under `bridge.token`.
2. Start the host listening on all interfaces:

   ```powershell
   python -m telemetry_host --bridge-host 0.0.0.0
   ```

3. Turn on **Settings → Network → Hotspot & tethering → USB tethering** on the phone. Windows adds a "Remote NDIS" network adapter. Find the PC's address on it with `ipconfig`, for example `192.168.42.129`.
4. Allow the port through Windows Firewall from an **elevated** PowerShell. Keep the rule to the local subnet:

   ```powershell
   New-NetFirewallRule -DisplayName "CS2 Telemetry bridge" -Direction Inbound -Protocol TCP -LocalPort 8090 -RemoteAddress LocalSubnet -Action Allow
   ```

5. In the app, tap the endpoint, enter the PC's IP, port `8090` and the token, then tap **Connect**.

**Watch out:** with USB tethering on, Windows may start routing internet traffic, including the game's, through the phone's mobile data. Turn off mobile data on the phone, or make sure the PC's main adapter has the lower interface metric. `adb reverse` doesn't have this problem, which is one reason it's the default.

## 9. Testing without the game

The host comes with a match simulator. It walks ten bots around de_dust2 with rounds, a bomb plant, a smoke and a molotov.

```powershell
cd pc-host
python -m telemetry_host                          # terminal 1
python tools/simulate_gsi.py                      # terminal 2: spectator feed, full radar
python tools/simulate_gsi.py --mode player        # or: what a live player's client sends
```

To check the stream without the phone:

- Open `http://127.0.0.1:8090/` in a browser on the PC to see a live radar, the roster and the raw state.
- Run `python tools/ws_probe.py` for one line per message with rate and size, or add `--raw --count 1` to dump a full message.
- Run `curl http://127.0.0.1:8090/health` to get counters (`gsiAge`, `framesSent`, `framesDropped`).

Automated tests:

```powershell
python -m unittest discover -s tests -t .   # pc-host: normalizer, framing, cfg, end-to-end pipeline
.\gradlew test                              # android-client: protocol, interpolation, projection, client
```

If you change the protocol, run `python tools/export_fixture.py`. It regenerates the Android test fixture from real host output, so both sides keep testing the same schema.

## 10. Tuning latency and load

| Stage | Typical | Setting |
|---|---|---|
| CS2 → host | Up to `throttle` + `buffer` after a change | In the cfg: `"throttle" "0.05"` (about 20 updates/s) and `"buffer" "0.0"`. Use `0.1` for lighter load, `0.0` for as fast as the game allows |
| Host processing | ~0.5 ms per payload | — |
| Host → app | At most one frame per `1 / max_hz` (33 ms at 30 Hz) | `bridge.max_hz` |
| USB tunnel | 1-3 ms | — |
| App smoothing | About one update interval (~50 ms at 20 Hz) | Built into `TrackSet`; markers glide instead of jumping |

A full 10-player spectator state is about 7 KB, so 20 Hz is roughly 140 KB/s, a small fraction of USB 2.0 bandwidth. On the host, each payload takes about half a millisecond to process. The game only serializes the components listed in the cfg's `data` block. If you never spectate, you can set the `allplayers_*`, `allgrenades`, `bomb` and `phase_countdowns` lines to `"0"`.

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| Host log: `rejected payload with a missing or wrong auth token` | The cfg token doesn't match `config.json`. Re-run `install-cfg` and restart CS2 |
| No `first payload` line after launching CS2 | The cfg is in the wrong folder (it must be `...\game\csgo\cfg\`, not `...\csgo\cfg\`), CS2 wasn't restarted, or `uri` doesn't match `gsi.port` |
| `error: ... address already in use` | Another program uses 3000 or 8090. Use `--gsi-port` (then re-run `install-cfg`) or `--bridge-port` (then change the port in the app and `adb reverse`) |
| `adb devices` shows `unauthorized` | Accept the prompt on the phone. If it never appears, revoke USB debugging authorizations and replug |
| `adb devices` is empty | Use a data cable, try another USB port, and set the phone's USB mode to "File transfer" |
| App: `Host rejected the bridge token` | Enter the same `bridge.token` in the app's endpoint dialog |
| Minimap shows only you | You're in a live match, so that's all GSI sends. Spectate or open a demo for the full picture |
| Markers sit off the walls | The map's calibration in `maps.json` is out of date. Copy `pos_x`, `pos_y` and `scale` from its overview file |
| "No radar image for de_x" | Export that map's radar into `pc-host/radars/` (section 4) |
| Markers stutter | Lower `throttle` in the cfg, or check `framesDropped` in `/health`. Drops mean the phone isn't reading fast enough |

## 12. Security and removal

- The GSI receiver listens on `127.0.0.1` only and requires the token, so other machines can't feed it fake state. Other local programs can't either, unless they know the token.
- The bridge listens on `127.0.0.1` by default. Over `adb reverse`, only the authorized USB device can reach it. When you bind it to `0.0.0.0`, set `bridge.token` and keep the firewall rule restricted to the local subnet.
- Payloads are size-capped (2 MB) and validated field by field. Malformed input is rejected or dropped, and log messages about it are rate-limited.
- Nothing is sent to the internet, and `config.json` (which holds the token) is git-ignored.

**To remove everything:** delete `gamestate_integration_cs2telemetry.cfg` from the CS2 `cfg` folder, uninstall the app, and run `adb reverse --remove tcp:8090`. If you created the tethering firewall rule, remove it with `Remove-NetFirewallRule -DisplayName "CS2 Telemetry bridge"`.
