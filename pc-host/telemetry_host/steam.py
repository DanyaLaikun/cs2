"""Locate the CS2 install and write the Game State Integration cfg into it."""
from __future__ import annotations

import json
import re
import secrets
import sys
from pathlib import Path
from typing import Any

from .config import EXAMPLE_CONFIG_PATH, HOST_ROOT, load_config

CS2_APP_ID = "730"
CFG_TEMPLATE = HOST_ROOT / "cfg" / "gamestate_integration_cs2telemetry.cfg"

_VDF_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|(\{)|(\})|(//[^\n]*)|([^\s{}"]+)')


def parse_vdf(text: str) -> dict[str, Any]:
    """Parse Valve KeyValues text (libraryfolders.vdf, GSI cfg files) into nested dicts."""
    root: dict[str, Any] = {}
    stack = [root]
    key: str | None = None
    for match in _VDF_TOKEN.finditer(text):
        quoted, open_brace, close_brace, comment, bare = match.groups()
        if comment is not None:
            continue
        if open_brace:
            if key is None:
                raise ValueError("unexpected '{'")
            child: dict[str, Any] = {}
            stack[-1][key] = child
            stack.append(child)
            key = None
        elif close_brace:
            if len(stack) == 1 or key is not None:
                raise ValueError("unexpected '}'")
            stack.pop()
        else:
            token = re.sub(r"\\(.)", r"\1", quoted) if quoted is not None else bare
            if key is None:
                key = token
            else:
                stack[-1][key] = token
                key = None
    if len(stack) != 1 or key is not None:
        raise ValueError("unbalanced KeyValues document")
    return root


def find_steam_root() -> Path | None:
    candidates: list[Path] = []
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                candidates.append(Path(winreg.QueryValueEx(key, "SteamPath")[0]))
        except OSError:
            pass
        candidates.append(Path(r"C:\Program Files (x86)\Steam"))
    else:
        home = Path.home()
        candidates += [home / ".steam" / "steam", home / ".local" / "share" / "Steam"]
    return next((c for c in candidates if (c / "steamapps").is_dir()), None)


def find_cs2_dir(steam_root: Path | None = None) -> Path | None:
    """Return the 'Counter-Strike Global Offensive' install folder, searching every Steam library."""
    root = steam_root or find_steam_root()
    if root is None:
        return None
    with_cs2: list[Path] = []
    others: list[Path] = [root]
    try:
        data = parse_vdf((root / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        data = {}
    folders = data.get("libraryfolders") or data.get("LibraryFolders") or {}
    for entry in folders.values():
        if isinstance(entry, dict) and "path" in entry:
            apps = entry.get("apps")
            (with_cs2 if isinstance(apps, dict) and CS2_APP_ID in apps else others).append(Path(entry["path"]))
    for library in with_cs2 + others:
        game = library / "steamapps" / "common" / "Counter-Strike Global Offensive"
        if (game / "game" / "csgo").is_dir():
            return game
    return None


def render_cfg(template: str, *, uri: str, token: str) -> str:
    text = re.sub(r'("uri"\s+")[^"]*(")', lambda m: m.group(1) + uri + m.group(2), template, count=1)
    return re.sub(r'("token"\s+")[^"]*(")', lambda m: m.group(1) + token + m.group(2), text, count=1)


def ensure_config_with_token(config_path: Path) -> bool:
    """Create config.json from the example if needed and make sure it has a GSI token. Returns True if written."""
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
    elif EXAMPLE_CONFIG_PATH.exists():
        data = json.loads(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"))
    else:
        data = {}
    gsi = data.setdefault("gsi", {})
    created = not config_path.exists()
    if not gsi.get("token"):
        gsi["token"] = secrets.token_urlsafe(24)
        created = True
    if created:
        config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return created


def install_cfg(config_path: Path, *, cs2_dir: Path | None = None, print_only: bool = False) -> int:
    if ensure_config_with_token(config_path):
        print(f"Saved GSI token to {config_path}")
    cfg = load_config(config_path)
    host = "127.0.0.1" if cfg.gsi.host in ("0.0.0.0", "::", "") else cfg.gsi.host
    text = render_cfg(CFG_TEMPLATE.read_text(encoding="utf-8"), uri=f"http://{host}:{cfg.gsi.port}/gsi", token=cfg.gsi.token)
    if print_only:
        print(text)
        return 0

    game = cs2_dir or find_cs2_dir()
    if game is None:
        print("Could not find CS2. Pass --cs2-dir \"<...>\\steamapps\\common\\Counter-Strike Global Offensive\"", file=sys.stderr)
        return 1
    cfg_dir = game / "game" / "csgo" / "cfg"
    if not cfg_dir.is_dir():
        print(f"{cfg_dir} does not exist - is --cs2-dir the 'Counter-Strike Global Offensive' folder?", file=sys.stderr)
        return 1
    destination = cfg_dir / CFG_TEMPLATE.name
    destination.write_text(text, encoding="utf-8")
    print(f"Wrote {destination}")
    print("Restart CS2 so it loads the integration, then start the host: python -m telemetry_host")
    return 0
