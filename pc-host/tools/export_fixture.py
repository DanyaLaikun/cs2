"""Write a real host `state` message to the Android unit-test resources, so both sides test one schema.

    python tools/export_fixture.py
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOST_ROOT))
sys.path.insert(0, str(HOST_ROOT / "tools"))

from simulate_gsi import FREEZE, Match  # noqa: E402
from telemetry_host.gsi.maps import MapCatalog  # noqa: E402
from telemetry_host.gsi.normalizer import normalize  # noqa: E402
from telemetry_host.hub import StateHub  # noqa: E402

TARGET = HOST_ROOT.parent / "android-client" / "app" / "src" / "test" / "resources" / "state_spectator.json"


def main() -> int:
    random.seed(7)
    match = Match("spectator", token="")
    while match.clock < FREEZE + 26:  # mid-round: smoke deployed, molotov burning
        match.tick(0.05)
    hub = StateHub()
    hub.publish(normalize(match.payload(), MapCatalog.load(HOST_ROOT / "maps.json")))
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(json.loads(hub.message), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
