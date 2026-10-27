"""Unit tests for the mem reader module (platform-independent where possible)."""
from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch


# ── Offset / config tests (run everywhere) ─────────────────────────────────────

class TestOffsets(unittest.TestCase):
    def test_imports(self):
        from telemetry_host.mem import offsets as off
        self.assertIn("dwEntityList", off.CLIENT)
        self.assertIn("dwLocalPlayerController", off.CLIENT)
        self.assertIn("m_iTeamNum", off.CONTROLLER)
        self.assertIn("m_iszPlayerName", off.CONTROLLER)
        self.assertIn("m_hPlayerPawn", off.CONTROLLER)
        self.assertIn("m_pGameSceneNode", off.PAWN)
        self.assertIn("m_iHealth", off.PAWN)
        self.assertIn("m_lifeState", off.PAWN)
        self.assertIn("m_vecAbsOrigin", off.SCENE_NODE)

    def test_entity_list_constants_are_sane(self):
        from telemetry_host.mem import offsets as off
        el = off.ENTITY_LIST
        self.assertGreater(el["chunk_capacity"], 0)
        self.assertGreater(el["entry_size"], 0)
        self.assertGreaterEqual(el["entity_ptr_offset"], 0)
        # Entity ptr offset must fit inside an entry
        self.assertLess(el["entity_ptr_offset"] + 8, el["entry_size"])

    def test_team_constants(self):
        from telemetry_host.mem import offsets as off
        self.assertNotEqual(off.TEAM_T, off.TEAM_CT)
        self.assertIn(off.TEAM_T, (2, 3))
        self.assertIn(off.TEAM_CT, (2, 3))


class TestConfig(unittest.TestCase):
    def test_mem_config_defaults(self):
        from telemetry_host.config import MemConfig
        cfg = MemConfig()
        self.assertFalse(cfg.enabled)
        self.assertGreater(cfg.poll_hz, 0)
        self.assertTrue(cfg.augment_gsi)

    def test_load_config_with_mem_section(self):
        from telemetry_host.config import load_config
        cfg = load_config(overrides={"mem.enabled": True, "mem.poll_hz": 30.0})
        self.assertTrue(cfg.mem.enabled)
        self.assertEqual(cfg.mem.poll_hz, 30.0)

    def test_invalid_poll_hz_raises(self):
        from telemetry_host.config import load_config
        with self.assertRaises(ValueError):
            load_config(overrides={"mem.poll_hz": -1})

    def test_mem_config_in_full_config(self):
        from telemetry_host.config import Config
        cfg = Config()
        self.assertIsNotNone(cfg.mem)


# ── Merge function test ────────────────────────────────────────────────────────

class TestMergePositions(unittest.TestCase):
    def _merge(self, gsi_state, mem_players):
        from telemetry_host.app import _merge_mem_positions
        return _merge_mem_positions(gsi_state, mem_players)

    def test_positions_overridden_by_steamid(self):
        gsi = {
            "mode": "player",
            "players": [
                {"steamid": "111", "name": "Alice", "team": "CT", "health": 100,
                 "pos": [0, 0, 0], "yaw": 0.0, "weapons": {"w_0": "ak47"}},
            ],
        }
        mem = [{"steamid": "111", "name": "Alice", "team": "CT", "health": 85,
                "alive": True, "pos": [500, 300, 64], "yaw": 180.0}]
        out = self._merge(gsi, mem)
        p = out["players"][0]
        self.assertEqual(p["pos"], [500, 300, 64])
        self.assertEqual(p["yaw"], 180.0)
        self.assertEqual(p["health"], 85)
        self.assertTrue(p["alive"])
        # GSI weapon data must be preserved
        self.assertIn("weapons", p)
        self.assertEqual(out["source"], "gsi+mem")

    def test_positions_overridden_by_name_fallback(self):
        gsi = {
            "players": [
                {"name": "Bob", "team": "T", "health": 100, "pos": [0, 0, 0]},
            ],
        }
        mem = [{"name": "bob", "team": "T", "health": 60, "alive": True,
                "pos": [200, 100, 0], "yaw": 45.0}]
        out = self._merge(gsi, mem)
        p = out["players"][0]
        self.assertEqual(p["pos"], [200, 100, 0])
        self.assertEqual(p["health"], 60)

    def test_unmatched_gsi_player_unchanged(self):
        gsi = {
            "players": [
                {"steamid": "999", "name": "Ghost", "pos": [1, 2, 3], "health": 50},
            ],
        }
        mem = [{"steamid": "111", "name": "Other", "pos": [0, 0, 0]}]
        out = self._merge(gsi, mem)
        p = out["players"][0]
        self.assertEqual(p["pos"], [1, 2, 3])
        self.assertEqual(p["health"], 50)

    def test_empty_mem_returns_gsi_unchanged(self):
        gsi = {"mode": "player", "players": [{"pos": [1, 2, 3]}]}
        out = self._merge(gsi, [])
        self.assertEqual(out["players"][0]["pos"], [1, 2, 3])

    def test_original_gsi_state_not_mutated(self):
        gsi = {"players": [{"steamid": "1", "pos": [0, 0, 0], "health": 100}]}
        mem = [{"steamid": "1", "pos": [5, 5, 5], "health": 50}]
        _ = self._merge(gsi, mem)
        self.assertEqual(gsi["players"][0]["pos"], [0, 0, 0])
        self.assertEqual(gsi["players"][0]["health"], 100)


# ── Build state test ───────────────────────────────────────────────────────────

class TestBuildState(unittest.TestCase):
    def _build(self, players):
        from telemetry_host.mem.reader import _Player, _build_state
        return _build_state(players)

    def _make_player(self, **kw):
        from telemetry_host.mem.reader import _Player
        defaults = dict(idx=1, name="P", team="CT", health=100, alive=True,
                        pos=(0.0, 0.0, 0.0), yaw=0.0, steam_id=0)
        defaults.update(kw)
        return _Player(**defaults)

    def test_active_player_sets_mode_player(self):
        state = self._build([self._make_player(alive=True)])
        self.assertEqual(state["mode"], "player")

    def test_all_dead_sets_mode_menu(self):
        state = self._build([self._make_player(alive=False)])
        self.assertEqual(state["mode"], "menu")

    def test_steamid_omitted_when_zero(self):
        state = self._build([self._make_player(steam_id=0)])
        self.assertNotIn("steamid", state["players"][0])

    def test_steamid_present_when_nonzero(self):
        state = self._build([self._make_player(steam_id=76561198000000001)])
        self.assertEqual(state["players"][0]["steamid"], "76561198000000001")

    def test_name_omitted_when_empty(self):
        state = self._build([self._make_player(name="")])
        self.assertNotIn("name", state["players"][0])

    def test_source_is_mem(self):
        state = self._build([self._make_player()])
        self.assertEqual(state["source"], "mem")

    def test_all_required_fields_present(self):
        state = self._build([self._make_player()])
        p = state["players"][0]
        for field in ("team", "health", "alive", "pos", "yaw"):
            self.assertIn(field, p)

    def test_health_clamped_to_500(self):
        state = self._build([self._make_player(health=9999)])
        self.assertEqual(state["players"][0]["health"], 500)

    def test_negative_health_clamped_to_zero(self):
        state = self._build([self._make_player(health=-10)])
        self.assertEqual(state["players"][0]["health"], 0)


# ── Windows-only reader tests ──────────────────────────────────────────────────

@unittest.skipUnless(sys.platform == "win32", "MemReader is Windows-only")
class TestMemReaderWindows(unittest.TestCase):
    def test_import(self):
        from telemetry_host.mem import MemReader
        self.assertIsNotNone(MemReader)

    def test_instantiation(self):
        from telemetry_host.mem import MemReader
        r = MemReader(poll_hz=10)
        self.assertFalse(r.connected)

    def test_not_connected_when_game_absent(self):
        from telemetry_host.mem import MemReader
        from telemetry_host.mem.winapi import find_pid
        if find_pid("cs2.exe") is not None:
            self.skipTest("cs2.exe is running — skipping 'not connected' check")
        r = MemReader(poll_hz=10)
        # _read_state must return empty list (not crash) when game isn't running
        result = r._read_state()
        self.assertIsInstance(result, list)
        self.assertEqual(result, [])


# ── Non-Windows: graceful import ──────────────────────────────────────────────

@unittest.skipIf(sys.platform == "win32", "only for non-Windows")
class TestNonWindows(unittest.TestCase):
    def test_mem_package_exports_nothing_on_non_windows(self):
        import telemetry_host.mem as mem_pkg
        self.assertEqual(mem_pkg.__all__, [])

    def test_winapi_import_raises(self):
        with self.assertRaises(ImportError):
            import importlib
            import telemetry_host.mem.winapi as wa  # noqa: F401


if __name__ == "__main__":
    unittest.main()
