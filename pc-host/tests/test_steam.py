import json
import tempfile
import unittest
from pathlib import Path

from telemetry_host.config import load_config
from telemetry_host.steam import CFG_TEMPLATE, ensure_config_with_token, find_cs2_dir, parse_vdf, render_cfg

LIBRARY_FOLDERS = r'''
"libraryfolders"
{
	"0"
	{
		"path"		"C:\\Program Files (x86)\\Steam"
		"apps" { "570" "1" }
	}
	"1"
	{
		"path"		"D:\\Games\\SteamLibrary"
		"apps"
		{
			"730"		"73942306339"
		}
	}
}
'''


class VdfTest(unittest.TestCase):
    def test_libraryfolders(self):
        data = parse_vdf(LIBRARY_FOLDERS)["libraryfolders"]
        self.assertEqual(data["1"]["path"], r"D:\Games\SteamLibrary")
        self.assertIn("730", data["1"]["apps"])

    def test_cfg_template_is_valid_and_complete(self):
        doc = parse_vdf(CFG_TEMPLATE.read_text(encoding="utf-8"))
        (name, body), = doc.items()
        self.assertTrue(name.startswith("CS2 Telemetry"))
        self.assertEqual(body["uri"], "http://127.0.0.1:3000/gsi")
        self.assertEqual(body["auth"]["token"], "CHANGE_ME")
        for key in ("provider", "map", "round", "player_position", "allplayers_position", "allgrenades", "bomb"):
            self.assertEqual(body["data"][key], "1", key)

    def test_unbalanced_rejected(self):
        with self.assertRaises(ValueError):
            parse_vdf('"a" { "b" "c"')

    def test_render_cfg(self):
        text = render_cfg(CFG_TEMPLATE.read_text(encoding="utf-8"), uri="http://127.0.0.1:3100/gsi", token="abc_-123")
        body = next(iter(parse_vdf(text).values()))
        self.assertEqual((body["uri"], body["auth"]["token"]), ("http://127.0.0.1:3100/gsi", "abc_-123"))


class InstallTest(unittest.TestCase):
    def test_token_generated_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            self.assertTrue(ensure_config_with_token(path))
            token = json.loads(path.read_text())["gsi"]["token"]
            self.assertGreaterEqual(len(token), 24)
            self.assertFalse(ensure_config_with_token(path))
            self.assertEqual(load_config(path).gsi.token, token)

    def test_find_cs2_in_secondary_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, library = Path(tmp) / "Steam", Path(tmp) / "Lib"
            (root / "steamapps").mkdir(parents=True)
            game = library / "steamapps" / "common" / "Counter-Strike Global Offensive"
            (game / "game" / "csgo" / "cfg").mkdir(parents=True)
            vdf = LIBRARY_FOLDERS.replace(r"D:\\Games\\SteamLibrary", str(library).replace("\\", "\\\\"))
            (root / "steamapps" / "libraryfolders.vdf").write_text(vdf)
            self.assertEqual(find_cs2_dir(root), game)


class ConfigTest(unittest.TestCase):
    def test_overrides_and_relative_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"_comment": "x", "bridge": {"port": 9001}, "radar_dir": "imgs"}))
            cfg = load_config(path, {"bridge.host": "0.0.0.0", "gsi.port": None})
            self.assertEqual((cfg.bridge.port, cfg.bridge.host, cfg.gsi.port), (9001, "0.0.0.0", 3000))
            self.assertEqual(cfg.radar_dir, (Path(tmp) / "imgs").resolve())

    def test_invalid_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"bridge": {"port": "abc"}}))
            with self.assertRaises(ValueError):
                load_config(path)
            path.write_text(json.dumps({"bridge": {"max_hz": 0}}))
            with self.assertRaises(ValueError):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
