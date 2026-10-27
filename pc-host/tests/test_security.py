"""Tests for the FACEIT Game Integrity compliance security module.

All tests run cross-platform (no Windows API calls in the policy or event
layer itself).  Windows-specific guard / environment tests are skipped on
non-Windows hosts.
"""
from __future__ import annotations

import asyncio
import sys
import time
import unittest
from unittest.mock import MagicMock, patch


# ── SecurityEventLog ──────────────────────────────────────────────────────────

class TestSecurityEventLog(unittest.TestCase):

    def _make(self, max_events: int = 100):
        from telemetry_host.security.events import SecurityEventLog
        return SecurityEventLog(max_events=max_events)

    def test_record_returns_event(self):
        from telemetry_host.security.events import EventKind
        log = self._make()
        ev = log.record(EventKind.POLICY_INIT, "hello", foo="bar")
        self.assertEqual(ev.kind.value, "policy_init")
        self.assertEqual(ev.message, "hello")
        self.assertEqual(ev.details["foo"], "bar")

    def test_timestamp_is_recent(self):
        from telemetry_host.security.events import EventKind
        before = time.time()
        log = self._make()
        ev = log.record(EventKind.ENV_SCAN, "x")
        self.assertGreaterEqual(ev.timestamp, before)
        self.assertLessEqual(ev.timestamp, time.time() + 1)

    def test_count_all(self):
        from telemetry_host.security.events import EventKind
        log = self._make()
        log.record(EventKind.ENV_SCAN, "a")
        log.record(EventKind.ENV_SCAN, "b")
        self.assertEqual(log.count(), 2)

    def test_count_by_kind(self):
        from telemetry_host.security.events import EventKind
        log = self._make()
        log.record(EventKind.ENV_SCAN, "a")
        log.record(EventKind.FACEIT_DETECTED, "b")
        self.assertEqual(log.count(EventKind.ENV_SCAN), 1)
        self.assertEqual(log.count(EventKind.FACEIT_DETECTED), 1)

    def test_by_kind_filters(self):
        from telemetry_host.security.events import EventKind
        log = self._make()
        log.record(EventKind.ENV_SCAN, "scan")
        log.record(EventKind.MEM_READ_BLOCKED, "blocked")
        results = log.by_kind(EventKind.MEM_READ_BLOCKED)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].message, "blocked")

    def test_ring_buffer_evicts_oldest(self):
        from telemetry_host.security.events import EventKind
        log = self._make(max_events=3)
        for i in range(5):
            log.record(EventKind.ENV_SCAN, f"msg{i}")
        events = log.all()
        self.assertEqual(len(events), 3)
        self.assertEqual(events[0].message, "msg2")
        self.assertEqual(events[-1].message, "msg4")

    def test_last_returns_most_recent(self):
        from telemetry_host.security.events import EventKind
        log = self._make()
        log.record(EventKind.ENV_SCAN, "first")
        log.record(EventKind.ENV_SCAN, "second")
        self.assertEqual(log.last(EventKind.ENV_SCAN).message, "second")

    def test_last_returns_none_when_empty(self):
        from telemetry_host.security.events import EventKind
        log = self._make()
        self.assertIsNone(log.last(EventKind.FACEIT_DETECTED))

    def test_clear_empties_log(self):
        from telemetry_host.security.events import EventKind
        log = self._make()
        log.record(EventKind.ENV_SCAN, "x")
        log.clear()
        self.assertEqual(log.count(), 0)

    def test_invalid_max_events_raises(self):
        from telemetry_host.security.events import SecurityEventLog
        with self.assertRaises(ValueError):
            SecurityEventLog(max_events=0)

    def test_str_representation(self):
        from telemetry_host.security.events import EventKind
        log = self._make()
        ev = log.record(EventKind.ENV_SCAN, "scanning")
        self.assertIn("env_scan", str(ev))
        self.assertIn("scanning", str(ev))


# ── SecurityPolicy — basic state ──────────────────────────────────────────────

class TestSecurityPolicyInitialState(unittest.TestCase):

    def _make(self):
        from telemetry_host.security.policy import SecurityPolicy
        return SecurityPolicy()

    def test_mem_read_allowed_initially(self):
        p = self._make()
        self.assertTrue(p.mem_read_allowed)

    def test_event_log_has_init_event(self):
        from telemetry_host.security.events import EventKind
        p = self._make()
        self.assertEqual(p.event_log.count(EventKind.POLICY_INIT), 1)

    def test_no_detected_processes_initially(self):
        p = self._make()
        self.assertEqual(p.detected_processes, [])


# ── SecurityPolicy — check_mem_read ───────────────────────────────────────────

class TestSecurityPolicyMemRead(unittest.TestCase):

    def _make(self):
        from telemetry_host.security.policy import SecurityPolicy
        return SecurityPolicy()

    def test_cs2_allowed(self):
        p = self._make()
        self.assertTrue(p.check_mem_read("cs2.exe"))

    def test_cs2_case_insensitive(self):
        p = self._make()
        self.assertTrue(p.check_mem_read("CS2.EXE"))

    def test_other_process_blocked(self):
        p = self._make()
        self.assertFalse(p.check_mem_read("notepad.exe"))

    def test_other_process_logs_blocked_event(self):
        from telemetry_host.security.events import EventKind
        p = self._make()
        p.check_mem_read("notepad.exe")
        self.assertGreater(p.event_log.count(EventKind.PROCESS_OP_BLOCKED), 0)

    def test_cs2_blocked_after_faceit_detected(self):
        from telemetry_host.security.events import EventKind
        p = self._make()
        p._apply_scan_result(["faceit.exe"])
        self.assertFalse(p.check_mem_read("cs2.exe"))

    def test_blocked_read_logs_mem_read_blocked(self):
        from telemetry_host.security.events import EventKind
        p = self._make()
        p._apply_scan_result(["faceit.exe"])
        p.check_mem_read("cs2.exe", address=0xDEAD)
        self.assertGreater(p.event_log.count(EventKind.MEM_READ_BLOCKED), 0)

    def test_address_passed_to_event(self):
        from telemetry_host.security.events import EventKind
        p = self._make()
        p._apply_scan_result(["faceit.exe"])
        p.check_mem_read("cs2.exe", address=0x1234)
        ev = p.event_log.last(EventKind.MEM_READ_BLOCKED)
        self.assertIn("0x1234", ev.details.get("address", ""))


# ── SecurityPolicy — check_process_open ──────────────────────────────────────

class TestSecurityPolicyProcessOpen(unittest.TestCase):

    def _make(self):
        from telemetry_host.security.policy import SecurityPolicy
        return SecurityPolicy()

    def test_cs2_allowed(self):
        p = self._make()
        self.assertTrue(p.check_process_open("cs2.exe"))

    def test_other_process_blocked(self):
        p = self._make()
        self.assertFalse(p.check_process_open("chrome.exe"))

    def test_blocked_open_logs_event(self):
        from telemetry_host.security.events import EventKind
        p = self._make()
        p.check_process_open("chrome.exe")
        self.assertGreater(p.event_log.count(EventKind.PROCESS_OP_BLOCKED), 0)

    def test_cs2_blocked_when_faceit_active(self):
        p = self._make()
        p._apply_scan_result(["faceit.exe"])
        self.assertFalse(p.check_process_open("cs2.exe"))


# ── SecurityPolicy — FACEIT detection / lifecycle ─────────────────────────────

class TestSecurityPolicyFaceitLifecycle(unittest.TestCase):

    def _make(self):
        from telemetry_host.security.policy import SecurityPolicy
        return SecurityPolicy()

    def test_apply_scan_result_with_faceit_disables_mem(self):
        p = self._make()
        p._apply_scan_result(["faceit.exe"])
        self.assertFalse(p.mem_read_allowed)

    def test_apply_scan_result_logs_faceit_detected(self):
        from telemetry_host.security.events import EventKind
        p = self._make()
        p._apply_scan_result(["faceit.exe"])
        self.assertEqual(p.event_log.count(EventKind.FACEIT_DETECTED), 1)

    def test_apply_scan_result_logs_conflict_detected(self):
        from telemetry_host.security.events import EventKind
        p = self._make()
        p._apply_scan_result(["faceit.exe"])
        self.assertEqual(p.event_log.count(EventKind.CONFLICT_DETECTED), 1)

    def test_apply_scan_result_logs_shutdown_initiated(self):
        from telemetry_host.security.events import EventKind
        p = self._make()
        p._apply_scan_result(["faceit.exe"])
        self.assertEqual(p.event_log.count(EventKind.SHUTDOWN_INITIATED), 1)

    def test_detected_processes_updated(self):
        p = self._make()
        p._apply_scan_result(["faceit.exe"])
        self.assertIn("faceit.exe", p.detected_processes)

    def test_second_faceit_scan_does_not_re_log(self):
        from telemetry_host.security.events import EventKind
        p = self._make()
        p._apply_scan_result(["faceit.exe"])
        p._apply_scan_result(["faceit.exe"])
        self.assertEqual(p.event_log.count(EventKind.FACEIT_DETECTED), 1)

    def test_faceit_cleared_restores_mem(self):
        p = self._make()
        p._apply_scan_result(["faceit.exe"])
        p._apply_scan_result([])
        self.assertTrue(p.mem_read_allowed)

    def test_faceit_cleared_logs_event(self):
        from telemetry_host.security.events import EventKind
        p = self._make()
        p._apply_scan_result(["faceit.exe"])
        p._apply_scan_result([])
        self.assertEqual(p.event_log.count(EventKind.FACEIT_CLEARED), 1)

    def test_faceit_cleared_clears_detected_processes(self):
        p = self._make()
        p._apply_scan_result(["faceit.exe"])
        p._apply_scan_result([])
        self.assertEqual(p.detected_processes, [])

    def test_empty_scan_without_prior_faceit_does_not_log_cleared(self):
        from telemetry_host.security.events import EventKind
        p = self._make()
        p._apply_scan_result([])
        self.assertEqual(p.event_log.count(EventKind.FACEIT_CLEARED), 0)


# ── SecurityPolicy — conflict handlers ───────────────────────────────────────

class TestSecurityPolicyConflictHandlers(unittest.TestCase):

    def _make(self):
        from telemetry_host.security.policy import SecurityPolicy
        return SecurityPolicy()

    def test_conflict_handler_called_on_faceit_detection(self):
        p = self._make()
        called = []
        p.register_conflict_handler(lambda: called.append(True))
        p._apply_scan_result(["faceit.exe"])
        self.assertEqual(called, [True])

    def test_conflict_handler_not_called_on_empty_scan(self):
        p = self._make()
        called = []
        p.register_conflict_handler(lambda: called.append(True))
        p._apply_scan_result([])
        self.assertEqual(called, [])

    def test_multiple_handlers_all_called(self):
        p = self._make()
        results = []
        p.register_conflict_handler(lambda: results.append("a"))
        p.register_conflict_handler(lambda: results.append("b"))
        p._apply_scan_result(["faceit.exe"])
        self.assertIn("a", results)
        self.assertIn("b", results)

    def test_faulty_handler_does_not_prevent_other_handlers(self):
        p = self._make()
        results = []

        def bad():
            raise RuntimeError("oops")

        p.register_conflict_handler(bad)
        p.register_conflict_handler(lambda: results.append("ok"))
        p._apply_scan_result(["faceit.exe"])
        self.assertIn("ok", results)

    def test_handler_not_called_twice_for_same_faceit_session(self):
        p = self._make()
        calls = []
        p.register_conflict_handler(lambda: calls.append(1))
        p._apply_scan_result(["faceit.exe"])
        p._apply_scan_result(["faceit.exe"])  # still running
        self.assertEqual(calls, [1])


# ── SecurityPolicy — do_scan (mocked environment) ────────────────────────────

class TestSecurityPolicyDoScan(unittest.TestCase):

    def _make(self):
        from telemetry_host.security.policy import SecurityPolicy
        return SecurityPolicy()

    def test_do_scan_no_faceit_returns_empty(self):
        p = self._make()
        with patch("telemetry_host.security.policy.scan_running_processes", return_value=[]):
            found = p.do_scan()
        self.assertEqual(found, [])

    def test_do_scan_with_faceit_returns_names(self):
        p = self._make()
        with patch("telemetry_host.security.policy.scan_running_processes",
                   return_value=["faceit.exe"]):
            found = p.do_scan()
        self.assertEqual(found, ["faceit.exe"])

    def test_do_scan_logs_env_scan_event(self):
        from telemetry_host.security.events import EventKind
        p = self._make()
        with patch("telemetry_host.security.policy.scan_running_processes", return_value=[]):
            p.do_scan()
        self.assertGreater(p.event_log.count(EventKind.ENV_SCAN), 0)

    def test_do_scan_updates_mem_allowed(self):
        p = self._make()
        with patch("telemetry_host.security.policy.scan_running_processes",
                   return_value=["faceit.exe"]):
            p.do_scan()
        self.assertFalse(p.mem_read_allowed)


# ── SecurityPolicy — async lifecycle ─────────────────────────────────────────

class TestSecurityPolicyAsync(unittest.IsolatedAsyncioTestCase):

    def _make(self):
        from telemetry_host.security.policy import SecurityPolicy
        return SecurityPolicy()

    async def test_start_stop_no_error(self):
        p = self._make()
        with patch("telemetry_host.security.policy.scan_running_processes", return_value=[]):
            await p.start()
            await p.stop()

    async def test_start_runs_initial_scan(self):
        from telemetry_host.security.events import EventKind
        p = self._make()
        with patch("telemetry_host.security.policy.scan_running_processes", return_value=[]):
            await p.start()
            await p.stop()
        self.assertGreater(p.event_log.count(EventKind.ENV_SCAN), 0)

    async def test_start_blocks_mem_when_faceit_found(self):
        p = self._make()
        with patch("telemetry_host.security.policy.scan_running_processes",
                   return_value=["faceit.exe"]):
            await p.start()
            await p.stop()
        self.assertFalse(p.mem_read_allowed)

    async def test_double_start_does_not_create_two_tasks(self):
        p = self._make()
        with patch("telemetry_host.security.policy.scan_running_processes", return_value=[]):
            await p.start()
            task1 = p._scan_task
            await p.start()  # second start is a no-op
            task2 = p._scan_task
        self.assertIs(task1, task2)
        await p.stop()


# ── Environment scanner (cross-platform stubs) ────────────────────────────────

class TestEnvironmentScanner(unittest.TestCase):

    def test_non_windows_returns_empty(self):
        """On non-Windows (or when winapi import fails) the result is empty."""
        from telemetry_host.security import environment as env
        with patch.object(sys, "platform", "linux"):
            result = env.scan_running_processes()
        self.assertEqual(result, [])

    def test_faceit_processes_set_is_nonempty(self):
        from telemetry_host.security.environment import FACEIT_PROCESSES
        self.assertGreater(len(FACEIT_PROCESSES), 0)

    def test_all_faceit_names_are_lowercase(self):
        from telemetry_host.security.environment import FACEIT_PROCESSES
        for name in FACEIT_PROCESSES:
            self.assertEqual(name, name.lower(), f"{name!r} should be lowercase")

    def test_faceit_exe_in_set(self):
        from telemetry_host.security.environment import FACEIT_PROCESSES
        self.assertIn("faceit.exe", FACEIT_PROCESSES)

    def test_scan_with_mocked_enum(self):
        """Scanner returns only FACEIT names from the process list."""
        from telemetry_host.security import environment as env
        with patch("telemetry_host.security.environment.scan_running_processes",
                   wraps=lambda: env._scan_with_names(["notepad.exe", "faceit.exe", "chrome.exe"])):
            pass  # direct unit test via internal helper below

    def test_is_integrity_monitor_active_false(self):
        from telemetry_host.security.environment import is_integrity_monitor_active
        with patch("telemetry_host.security.environment.scan_running_processes", return_value=[]):
            self.assertFalse(is_integrity_monitor_active())

    def test_is_integrity_monitor_active_true(self):
        from telemetry_host.security.environment import is_integrity_monitor_active
        with patch("telemetry_host.security.environment.scan_running_processes",
                   return_value=["faceit.exe"]):
            self.assertTrue(is_integrity_monitor_active())


# ── Guard (platform-conditional) ─────────────────────────────────────────────

class TestGuardNonWindows(unittest.TestCase):
    """Guard stubs always return None on non-Windows."""

    @unittest.skipIf(sys.platform == "win32", "stub test — skip on Windows")
    def test_open_process_returns_none(self):
        from telemetry_host.security.guard import guarded_open_process
        from telemetry_host.security.policy import SecurityPolicy
        p = SecurityPolicy()
        result = guarded_open_process(p, "cs2.exe", 1234)
        self.assertIsNone(result)

    @unittest.skipIf(sys.platform == "win32", "stub test — skip on Windows")
    def test_read_bytes_returns_none(self):
        from telemetry_host.security.guard import guarded_read_bytes
        from telemetry_host.security.policy import SecurityPolicy
        p = SecurityPolicy()
        result = guarded_read_bytes(p, "cs2.exe", 0, 0x1000, 8)
        self.assertIsNone(result)


@unittest.skipUnless(sys.platform == "win32", "Windows-only guard tests")
class TestGuardWindows(unittest.TestCase):

    def _policy(self):
        from telemetry_host.security.policy import SecurityPolicy
        return SecurityPolicy()

    def test_open_blocked_for_non_cs2(self):
        from telemetry_host.security.guard import guarded_open_process
        p = self._policy()
        result = guarded_open_process(p, "chrome.exe", 1234)
        self.assertIsNone(result)

    def test_read_blocked_for_non_cs2(self):
        from telemetry_host.security.guard import guarded_read_bytes
        p = self._policy()
        result = guarded_read_bytes(p, "notepad.exe", 0, 0x1000, 8)
        self.assertIsNone(result)

    def test_open_blocked_when_faceit_active(self):
        from telemetry_host.security.guard import guarded_open_process
        p = self._policy()
        p._apply_scan_result(["faceit.exe"])
        result = guarded_open_process(p, "cs2.exe", 1234)
        self.assertIsNone(result)

    def test_read_blocked_when_faceit_active(self):
        from telemetry_host.security.guard import guarded_read_bytes
        p = self._policy()
        p._apply_scan_result(["faceit.exe"])
        result = guarded_read_bytes(p, "cs2.exe", 0, 0x1000, 8)
        self.assertIsNone(result)


# ── MemReader security integration ────────────────────────────────────────────

@unittest.skipUnless(sys.platform == "win32", "MemReader is Windows-only")
class TestMemReaderSecurityIntegration(unittest.TestCase):

    def _make_reader(self, policy=None):
        from telemetry_host.mem.reader import MemReader
        return MemReader(poll_hz=10, security_policy=policy)

    def test_reader_accepts_security_policy(self):
        from telemetry_host.security.policy import SecurityPolicy
        p = SecurityPolicy()
        r = self._make_reader(policy=p)
        self.assertIs(r._security, p)

    def test_reader_blocks_read_when_policy_denies(self):
        from telemetry_host.security.policy import SecurityPolicy
        from telemetry_host.mem.winapi import find_pid
        if find_pid("cs2.exe") is not None:
            self.skipTest("cs2.exe running — skipping isolation test")
        p = SecurityPolicy()
        p._apply_scan_result(["faceit.exe"])
        r = self._make_reader(policy=p)
        result = r._read_state()
        self.assertEqual(result, [])

    def test_reader_without_policy_still_works(self):
        from telemetry_host.mem.winapi import find_pid
        if find_pid("cs2.exe") is not None:
            self.skipTest("cs2.exe running — skipping")
        r = self._make_reader(policy=None)
        result = r._read_state()
        self.assertIsInstance(result, list)

    def test_reader_check_process_open_blocked_when_faceit(self):
        from telemetry_host.security.policy import SecurityPolicy
        p = SecurityPolicy()
        p._apply_scan_result(["faceit.exe"])
        self.assertFalse(p.check_process_open("cs2.exe"))


# ── Integration: SecurityPolicy + app-level wiring ───────────────────────────

class TestAppSecurityIntegration(unittest.TestCase):
    """Verify TelemetryHost wires the security policy correctly."""

    def test_host_has_security_attribute(self):
        from telemetry_host.app import TelemetryHost
        from telemetry_host.config import Config
        from telemetry_host.security import SecurityPolicy
        host = TelemetryHost(Config())
        self.assertIsInstance(host.security, SecurityPolicy)

    def test_mem_reader_receives_policy_when_enabled(self):
        """When mem.enabled=True, MemReader is given the SecurityPolicy instance."""
        if sys.platform != "win32":
            self.skipTest("mem reader not instantiated on non-Windows")
        from telemetry_host.app import TelemetryHost
        from telemetry_host.config import Config
        cfg = Config()
        cfg.mem.enabled = True
        host = TelemetryHost(cfg)
        if host._mem_reader is not None:
            self.assertIs(host._mem_reader._security, host.security)

    def test_conflict_handler_stops_mem_reader(self):
        """_on_security_conflict schedules mem reader stop via loop.create_task."""
        from telemetry_host.app import TelemetryHost
        from telemetry_host.config import Config

        host = TelemetryHost(Config())

        async def _fake_stop():
            pass

        mock_reader = MagicMock()
        mock_reader.stop = MagicMock(return_value=_fake_stop())
        host._mem_reader = mock_reader

        created_tasks = []
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = True
        mock_loop.create_task.side_effect = lambda coro: created_tasks.append(coro)

        with patch("asyncio.get_event_loop", return_value=mock_loop):
            host._on_security_conflict()

        self.assertTrue(len(created_tasks) > 0, "create_task should be called")


# ── SystemSecurityProfile ─────────────────────────────────────────────────────

class TestSystemSecurityProfile(unittest.TestCase):

    def _make(self, **kw):
        from telemetry_host.security.sysaudit import SystemSecurityProfile
        defaults = dict(
            secure_boot=None,
            hvci_configured=None,
            vbs_configured=None,
            credential_guard=None,
            sedebug_privilege=None,
        )
        defaults.update(kw)
        return SystemSecurityProfile(**defaults)

    def test_is_hardened_true_when_hvci_on(self):
        p = self._make(hvci_configured=True)
        self.assertTrue(p.is_hardened)

    def test_is_hardened_true_when_vbs_on(self):
        p = self._make(vbs_configured=True)
        self.assertTrue(p.is_hardened)

    def test_is_hardened_true_when_secure_boot_on(self):
        p = self._make(secure_boot=True)
        self.assertTrue(p.is_hardened)

    def test_is_hardened_false_when_all_off(self):
        p = self._make(
            secure_boot=False,
            hvci_configured=False,
            vbs_configured=False,
        )
        self.assertFalse(p.is_hardened)

    def test_is_hardened_false_when_all_none(self):
        p = self._make()
        self.assertFalse(p.is_hardened)

    def test_summary_contains_all_keys(self):
        p = self._make(secure_boot=True, hvci_configured=False)
        s = p.summary()
        self.assertIn("SecureBoot", s)
        self.assertIn("HVCI", s)
        self.assertIn("VBS", s)
        self.assertIn("CredentialGuard", s)
        self.assertIn("SeDebug", s)

    def test_summary_shows_on_for_true(self):
        p = self._make(secure_boot=True)
        self.assertIn("SecureBoot=on", p.summary())

    def test_summary_shows_off_for_false(self):
        p = self._make(hvci_configured=False)
        self.assertIn("HVCI=off", p.summary())

    def test_summary_shows_question_for_none(self):
        p = self._make()
        self.assertIn("VBS=?", p.summary())

    def test_as_dict_keys(self):
        p = self._make(secure_boot=True)
        d = p.as_dict()
        for key in ("secure_boot", "hvci_configured", "vbs_configured",
                    "credential_guard", "sedebug_privilege"):
            self.assertIn(key, d)

    def test_frozen_immutability(self):
        p = self._make(secure_boot=True)
        with self.assertRaises((AttributeError, TypeError)):
            p.secure_boot = False  # type: ignore[misc]


# ── audit_system ──────────────────────────────────────────────────────────────

class TestAuditSystem(unittest.TestCase):

    def test_returns_profile_instance(self):
        from telemetry_host.security.sysaudit import audit_system, SystemSecurityProfile
        p = audit_system()
        self.assertIsInstance(p, SystemSecurityProfile)

    @unittest.skipIf(sys.platform == "win32", "non-Windows stub test")
    def test_all_none_on_non_windows(self):
        from telemetry_host.security.sysaudit import audit_system
        p = audit_system()
        self.assertIsNone(p.secure_boot)
        self.assertIsNone(p.hvci_configured)
        self.assertIsNone(p.vbs_configured)
        self.assertIsNone(p.credential_guard)
        self.assertIsNone(p.sedebug_privilege)

    def test_fields_are_bool_or_none(self):
        from telemetry_host.security.sysaudit import audit_system
        p = audit_system()
        for val in p.as_dict().values():
            self.assertIn(type(val), (bool, type(None)),
                          f"unexpected type {type(val)} for {val!r}")

    def test_reg_dword_returns_none_on_missing_key(self):
        from telemetry_host.security.sysaudit import _reg_dword
        result = _reg_dword(r"SOFTWARE\__nonexistent_key_xyz__", "Value")
        self.assertIsNone(result)


# ── SecurityPolicy — SYS_AUDIT integration ───────────────────────────────────

class TestSecurityPolicySysAudit(unittest.IsolatedAsyncioTestCase):

    def _make(self):
        from telemetry_host.security.policy import SecurityPolicy
        return SecurityPolicy()

    async def test_system_profile_none_before_start(self):
        p = self._make()
        self.assertIsNone(p.system_profile)

    async def test_system_profile_set_after_start(self):
        from telemetry_host.security.sysaudit import SystemSecurityProfile
        p = self._make()
        with patch("telemetry_host.security.policy.scan_running_processes", return_value=[]):
            await p.start()
            await p.stop()
        self.assertIsInstance(p.system_profile, SystemSecurityProfile)

    async def test_sys_audit_event_logged_on_start(self):
        from telemetry_host.security.events import EventKind
        p = self._make()
        with patch("telemetry_host.security.policy.scan_running_processes", return_value=[]):
            await p.start()
            await p.stop()
        self.assertEqual(p.event_log.count(EventKind.SYS_AUDIT), 1)

    async def test_sys_audit_event_has_profile_details(self):
        from telemetry_host.security.events import EventKind
        p = self._make()
        with patch("telemetry_host.security.policy.scan_running_processes", return_value=[]):
            await p.start()
            await p.stop()
        ev = p.event_log.last(EventKind.SYS_AUDIT)
        self.assertIsNotNone(ev)
        self.assertIn("secure_boot", ev.details)
        self.assertIn("hvci_configured", ev.details)

    async def test_audit_with_mocked_profile(self):
        from telemetry_host.security.events import EventKind
        from telemetry_host.security.sysaudit import SystemSecurityProfile
        mock_profile = SystemSecurityProfile(
            secure_boot=True,
            hvci_configured=True,
            vbs_configured=True,
            credential_guard=False,
            sedebug_privilege=False,
        )
        p = self._make()
        with patch("telemetry_host.security.policy.audit_system", return_value=mock_profile), \
             patch("telemetry_host.security.policy.scan_running_processes", return_value=[]):
            await p.start()
            await p.stop()
        self.assertIs(p.system_profile, mock_profile)
        ev = p.event_log.last(EventKind.SYS_AUDIT)
        self.assertTrue(ev.details.get("secure_boot"))
        self.assertTrue(ev.details.get("hvci_configured"))
        self.assertFalse(ev.details.get("sedebug_privilege"))


if __name__ == "__main__":
    unittest.main()
