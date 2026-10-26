import json
import unittest

from telemetry_host.gsi.maps import MapCatalog
from telemetry_host.gsi.normalizer import normalize

from . import fixtures

MAPS = MapCatalog({
    "de_dust2": {"posX": -2476, "posY": 3239, "scale": 4.4},
    "de_nuke": {"posX": -3453, "posY": 2887, "scale": 7, "splitZ": -495},
})


class SpectatorFeedTest(unittest.TestCase):
    def setUp(self):
        self.state = normalize(fixtures.spectator_payload(), MAPS)
        self.players = {p["id"]: p for p in self.state["players"]}

    def test_mode_and_focus(self):
        self.assertEqual(self.state["mode"], "spectator")
        self.assertEqual(self.state["focus"], "76561198000000001")
        self.assertEqual(len(self.state["players"]), 2)

    def test_player_fields(self):
        p = self.players["76561198000000001"]
        self.assertEqual(p["pos"], [-277, -721, 96])
        self.assertEqual(p["yaw"], 90.0)  # forward +Y = north
        self.assertEqual(p["pitch"], 0.0)
        self.assertEqual((p["hp"], p["armor"], p["helmet"], p["money"]), (74, 100, True, 4750))
        self.assertEqual((p["roundKills"], p["roundHs"], p["roundDmg"]), (2, 1, 187))
        self.assertEqual((p["kills"], p["assists"], p["deaths"]), (12, 3, 8))
        self.assertEqual(p["activity"], "playing")

    def test_weapons_sorted_and_prefix_stripped(self):
        weapons = self.players["76561198000000001"]["weapons"]
        self.assertEqual([w["name"] for w in weapons], ["knife_t", "ak47", "flashbang"])
        ak = weapons[1]
        self.assertEqual((ak["state"], ak["clip"], ak["clipMax"], ak["reserve"]), ("active", 27, 30, 90))
        self.assertNotIn("clip", weapons[0])  # absent values are omitted, not null

    def test_dead_player_with_kit(self):
        ct = self.players["76561198000000010"]
        self.assertEqual((ct["hp"], ct["team"], ct["defuser"], ct["slot"]), (0, "CT", True, 6))
        self.assertEqual(ct["yaw"], 180.0)

    def test_map_scores_history_radar(self):
        m = self.state["map"]
        self.assertEqual((m["name"], m["round"], m["ct"]["score"], m["t"]["score"]), ("de_dust2", 11, 6, 5))
        self.assertEqual(m["ct"]["losses"], 1)
        self.assertEqual(m["history"], [
            {"r": 1, "w": "CT", "why": "elimination"},
            {"r": 2, "w": "T", "why": "bomb"},
            {"r": 3, "w": "CT", "why": "defuse"},
        ])
        self.assertEqual(m["radar"], {"posX": -2476.0, "posY": 3239.0, "scale": 4.4, "image": "de_dust2"})

    def test_bomb_phase_grenades(self):
        self.assertEqual(self.state["bomb"], {"state": "planted", "pos": [1176, 2359, 96], "countdown": 31.4})
        self.assertEqual(self.state["phase"], {"name": "bomb", "endsIn": 31.4})
        smoke, inferno = self.state["grenades"]
        self.assertEqual((smoke["type"], smoke["owner"], smoke["effect"]), ("smoke", "76561198000000010", 4.7))
        self.assertEqual(inferno["flames"], [[-1640, 2359, 0], [-1600, 2370, 0]])
        self.assertNotIn("pos", inferno)

    def test_output_is_compact_json(self):
        text = json.dumps(self.state)
        self.assertNotIn("null", text)


class OtherFeedsTest(unittest.TestCase):
    def test_player_feed_only_has_self(self):
        state = normalize(fixtures.player_payload(), MAPS)
        self.assertEqual(state["mode"], "player")
        self.assertEqual([p["id"] for p in state["players"]], ["76561198000000001"])
        self.assertNotIn("bomb", state)
        self.assertEqual(state["grenades"], [])

    def test_menu_feed(self):
        state = normalize(fixtures.menu_payload(), MAPS)
        self.assertEqual(state["mode"], "menu")
        self.assertNotIn("map", state)
        self.assertEqual(state["players"], [{"id": "76561198000000001", "name": "Kestrel", "activity": "menu"}])

    def test_garbage_values_are_dropped(self):
        payload = fixtures.player_payload()
        payload["player"]["position"] = "not, a, vector"
        payload["player"]["forward"] = "1, 2"
        payload["player"]["state"]["health"] = "NaN"
        payload["player"]["state"]["money"] = "1250"
        payload["map"]["name"] = "workshop/123456/de_nuke"
        state = normalize(payload, MAPS)
        p = state["players"][0]
        self.assertNotIn("pos", p)
        self.assertNotIn("yaw", p)
        self.assertNotIn("hp", p)
        self.assertEqual(p["money"], 1250)
        self.assertEqual(state["map"]["name"], "de_nuke")
        self.assertEqual(state["map"]["radar"]["splitZ"], -495.0)
        self.assertEqual(state["map"]["radar"]["lowerImage"], "de_nuke_lower")

    def test_unknown_map_has_no_radar(self):
        payload = fixtures.player_payload()
        payload["map"]["name"] = "de_custom"
        self.assertNotIn("radar", normalize(payload, MAPS)["map"])

    def test_empty_payload(self):
        self.assertEqual(normalize({}), {"mode": "menu", "players": [], "grenades": []})


class MapCatalogTest(unittest.TestCase):
    def test_invalid_entries_are_skipped(self):
        with self.assertLogs("telemetry_host.gsi.maps", "WARNING"):
            catalog = MapCatalog({"_comment": "x", "a": {"posX": 1}, "b": {"posX": 0, "posY": 0, "scale": 0}, "c": []})
        self.assertEqual(len(catalog), 0)

    def test_lookup_is_case_insensitive(self):
        self.assertIn("DE_DUST2", MAPS)
        self.assertIsNotNone(MAPS.lookup("De_Dust2"))


if __name__ == "__main__":
    unittest.main()
