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
        # Try each name variant in order: original, then spaces→underscores.
        # For each variant also try a prefix fallback ("de_mirage_ce" → "de_mirage").
        for key in _name_variants(map_name.lower()):
            hit = self._radar.get(key)
            if hit is not None:
                return hit
            best = max(
                (k for k in self._radar if key.startswith(k + "_")),
                key=len,
                default=None,
            )
            if best:
                return self._radar[best]
        return None

    def __len__(self) -> int:
        return len(self._radar)

    def __contains__(self, map_name: object) -> bool:
        return isinstance(map_name, str) and map_name.lower() in self._radar


def _name_variants(name: str) -> list[str]:
    """Return lookup keys to try: original, then with spaces replaced by underscores.

    Workshop map names sometimes use spaces instead of underscores
    (e.g. "de mirage" instead of "de_mirage").
    """
    normalised = name.replace(" ", "_")
    return [name] if name == normalised else [name, normalised]


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
