"""Command line: `python -m telemetry_host [options]` runs the host; `install-cfg` sets up the game side."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from . import __version__
from .config import DEFAULT_CONFIG_PATH, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m telemetry_host",
        description="CS2 Game State Integration -> WebSocket telemetry bridge for the Android dashboard.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="config file (default: %(default)s)")
    parser.add_argument("--gsi-port", type=int, help="port CS2 posts GSI payloads to")
    parser.add_argument("--bridge-host", help="interface for the WebSocket bridge (0.0.0.0 for USB tethering / LAN)")
    parser.add_argument("--bridge-port", type=int, help="WebSocket bridge port")
    parser.add_argument("--max-hz", type=float, help="upper bound on state frames per second per client")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    install = sub.add_parser("install-cfg", help="write gamestate_integration_cs2telemetry.cfg into the CS2 cfg folder")
    install.add_argument("--cs2-dir", type=Path, help="the 'Counter-Strike Global Offensive' folder (auto-detected)")
    install.add_argument("--print", dest="print_only", action="store_true", help="print the cfg instead of writing it")
    radars = sub.add_parser("extract-radars", help="export radar images and map calibration from your CS2 install")
    radars.add_argument("--cs2-dir", type=Path, help="the 'Counter-Strike Global Offensive' folder (auto-detected)")
    radars.add_argument("--no-calibration", action="store_true", help="only write images, leave maps.json alone")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")

    if args.command == "install-cfg":
        from .steam import install_cfg

        return install_cfg(args.config, cs2_dir=args.cs2_dir, print_only=args.print_only)

    if args.command == "extract-radars":
        from .gamefiles import extract_radars

        paths = load_config(args.config)
        return extract_radars(paths.radar_dir, paths.maps_file, cs2_dir=args.cs2_dir, update_maps=not args.no_calibration)

    try:
        cfg = load_config(
            args.config,
            {
                "gsi.port": args.gsi_port,
                "bridge.host": args.bridge_host,
                "bridge.port": args.bridge_port,
                "bridge.max_hz": args.max_hz,
                "log_level": args.log_level,
            },
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    logging.getLogger().setLevel(cfg.log_level)

    from .app import run

    try:
        asyncio.run(run(cfg))
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        print(f"error: {exc}\nIs another instance already running, or the port taken? See --gsi-port / --bridge-port.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
