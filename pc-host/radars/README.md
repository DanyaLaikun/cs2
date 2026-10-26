# Radar images

The host serves these to the app at `GET /radar/<image>.png`. Without them the app draws a calibrated grid instead.

They're Valve assets from your own CS2 install, so they aren't committed to the repo. Export them, and refresh the calibration in `maps.json`, with:

```powershell
cd pc-host
python -m telemetry_host extract-radars
```

This reads `game\csgo\pak01_dir.vpk` and doesn't modify anything in the game. It decodes every `panorama/images/overheadmaps/*_radar_*.vtex_c`, including the `_lower` levels of Nuke, Vertigo and Train, into a PNG here. It also rewrites `maps.json` from the game's `resource/overviews/*.txt` and lists anything that changed. Run it again after a CS2 update that reworks a map.

New images are picked up without restarting the host. A changed `maps.json` needs a restart.

To use images from somewhere else, drop them in this folder. For `de_dust2`, the host accepts `de_dust2.png`, `de_dust2_radar.png` or `de_dust2_radar_psd.png`, and `.jpg` and `.webp` work too.
