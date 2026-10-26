"""Host configuration: defaults, config.json loading and command-line overrides."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

HOST_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = HOST_ROOT / "config.json"
EXAMPLE_CONFIG_PATH = HOST_ROOT / "config.example.json"


@dataclass
class GsiConfig:
    """Where CS2 posts Game State Integration payloads. Keep it on loopback."""

    host: str = "127.0.0.1"
    port: int = 3000
    token: str = ""
    max_body_bytes: int = 2 * 1024 * 1024


@dataclass
class BridgeConfig:
    """The WebSocket endpoint dashboard clients reach through `adb reverse` or USB tethering."""

    host: str = "127.0.0.1"
    port: int = 8090
    token: str = ""
    max_hz: float = 30.0
    heartbeat_sec: float = 2.0
    max_clients: int = 8
    max_buffered_bytes: int = 512 * 1024


@dataclass
class Config:
    gsi: GsiConfig = field(default_factory=GsiConfig)
    bridge: BridgeConfig = field(default_factory=BridgeConfig)
    radar_dir: Path = HOST_ROOT / "radars"
    maps_file: Path = HOST_ROOT / "maps.json"
    log_level: str = "INFO"


_TOP_LEVEL_KEYS = {"gsi", "bridge", "radar_dir", "maps_file", "log_level"}


def load_config(path: Path | None = None, overrides: dict[str, Any] | None = None) -> Config:
    """Load config.json (missing file = defaults) and apply dotted overrides such as {"bridge.port": 9000}.

    Relative paths inside the file resolve against the file's own directory.
    """
    path = path or DEFAULT_CONFIG_PATH
    raw: dict[str, Any] = {}
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: top level must be a JSON object")
    base = path.resolve().parent

    cfg = Config()
    _apply(cfg.gsi, raw.get("gsi", {}), "gsi")
    _apply(cfg.bridge, raw.get("bridge", {}), "bridge")
    if "radar_dir" in raw:
        cfg.radar_dir = _resolve(base, raw["radar_dir"])
    if "maps_file" in raw:
        cfg.maps_file = _resolve(base, raw["maps_file"])
    if "log_level" in raw:
        cfg.log_level = str(raw["log_level"]).upper()
    for key in raw:
        if key not in _TOP_LEVEL_KEYS and not key.startswith("_"):
            log.warning("config: ignoring unknown key %r", key)

    for dotted, value in (overrides or {}).items():
        if value is None:
            continue
        if dotted == "log_level":
            cfg.log_level = str(value).upper()
            continue
        section, _, name = dotted.partition(".")
        _apply(getattr(cfg, section), {name: value}, section)

    _validate(cfg)
    return cfg


def _apply(target: Any, values: Any, section: str) -> None:
    if not isinstance(values, dict):
        raise ValueError(f"config: '{section}' must be an object")
    known = {f.name for f in fields(target)}
    for key, value in values.items():
        if key.startswith("_"):
            continue
        if key not in known:
            log.warning("config: ignoring unknown key %s.%s", section, key)
            continue
        current = getattr(target, key)
        try:
            setattr(target, key, type(current)(value))
        except (TypeError, ValueError):
            raise ValueError(f"config: {section}.{key} must be a {type(current).__name__}") from None


def _resolve(base: Path, value: Any) -> Path:
    p = Path(str(value))
    return p if p.is_absolute() else (base / p).resolve()


def _validate(cfg: Config) -> None:
    for name, port in (("gsi.port", cfg.gsi.port), ("bridge.port", cfg.bridge.port)):
        if not 0 <= port <= 65535:
            raise ValueError(f"config: {name} must be between 0 and 65535")
    if cfg.bridge.max_hz <= 0:
        raise ValueError("config: bridge.max_hz must be positive")
    if cfg.bridge.heartbeat_sec <= 0:
        raise ValueError("config: bridge.heartbeat_sec must be positive")
    if cfg.bridge.max_clients < 1:
        raise ValueError("config: bridge.max_clients must be at least 1")
