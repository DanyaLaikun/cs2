"""World-to-radar calibration per map (maps.json).

Values come from the game's own overview files (resource/overviews/<map>.txt inside
pak01_dir.vpk): `pos_x`/`pos_y` are the world coordinates of the radar image's top-left
corner and `scale` is world units per radar pixel on the 1024x1024 radar. Multi-level maps
add `splitZ`: positions below that height belong to the lower radar (`lowerImage`).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class MapCatalog:
    def __init__(self, entries: dict[str, Any]) -> None:
        self._radar: dict[str, dict[str, Any]] = {}
        for name, entry in entries.items():
            if name.startswith("_"):
                continue
            radar = _parse_entry(name, entry)
            if radar is not None:
                self._radar[name.lower()] = radar

    @classmethod
    def load(cls, path: Path) -> MapCatalog:
        if not path.exists():
            log.warning("maps: %s not found; the minimap will have no calibration", path)
            return cls({})
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path}: expected a JSON object of map entries")
        return cls(data)

    def lookup(self, map_name: str) -> dict[str, Any] | None:
        key = map_name.lower()
        exact = self._radar.get(key)
        if exact is not None:
            return exact
        # Prefix fallback for workshop variants: "de_mirage_ce" → "de_mirage".
        # Require an underscore boundary so "de_mi" does not match "de_mirage".
        best = max(
            (k for k in self._radar if key.startswith(k + "_")),
            key=len,
            default=None,
        )
        return self._radar[best] if best else None

    def __len__(self) -> int:
        return len(self._radar)

    def __contains__(self, map_name: object) -> bool:
        return isinstance(map_name, str) and map_name.lower() in self._radar


def _parse_entry(name: str, entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        log.warning("maps: ignoring %s (expected an object)", name)
        return None
    try:
        radar: dict[str, Any] = {
            "posX": float(entry["posX"]),
            "posY": float(entry["posY"]),
            "scale": float(entry["scale"]),
            "image": str(entry.get("image", name)),
        }
        if entry.get("splitZ") is not None:
            radar["splitZ"] = float(entry["splitZ"])
            radar["lowerImage"] = str(entry.get("lowerImage", f"{name}_lower"))
    except (KeyError, TypeError, ValueError):
        log.warning("maps: ignoring %s (needs numeric posX, posY and scale)", name)
        return None
    if radar["scale"] <= 0:
        log.warning("maps: ignoring %s (scale must be positive)", name)
        return None
    return radar
