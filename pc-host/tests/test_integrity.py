"""Tests for the integrity guard module (telemetry_host.security.integrity).

Coverage
--------
hash_fnv64 / verify_bytes      — pure-Python algorithm and DLL path
FunctionSeal                   — bytecode sealing and tamper detection
seal_audit_system / verify     — audit_system-specific seal lifecycle
reg_read_dword                 — minimum-privilege registry reads (Windows)
query_privilege                — token privilege enumeration (Windows)
get_integrity_level            — mandatory label probe (Windows)
run_independent_audit          — out-of-process subprocess fallback
cross_verify_audit_system      — divergence detection
dll_available / dll_version    — DLL loader health

All tests that require Windows are skipped on non-Windows hosts.
DLL-dependent tests still pass via the pure-Python fallback paths.
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch


# ── FNV-1a hash ────────────────────────────────────────────────────────────────

class TestHashFnv64(unittest.TestCase):

    def _h(self, data: bytes) -> int:
        from telemetry_host.security.integrity import hash_fnv64
        return hash_fnv64(data)

    def test_empty_returns_offset_basis(self):
        self.assertEqual(self._h(b""), 14695981039346656037)

    def test_same_input_same_output(self):
        self.assertEqual(self._h(b"hello"), self._h(b"hello"))

    def test_different_inputs_differ(self):
        self.assertNotEqual(self._h(b"foo"), self._h(b"bar"))

    def test_result_fits_in_64_bits(self):
        self.assertLess(self._h(b"x" * 1000), 2**64)

    def test_single_byte_differs_from_empty(self):
        self.assertNotEqual(self._h(b"\x00"), self._h(b""))

    def test_byte_order_matters(self):
        self.assertNotEqual(self._h(b"ab"), self._h(b"ba"))


# ── verify_bytes ───────────────────────────────────────────────────────────────

class TestVerifyBytes(unittest.TestCase):

    def _h(self, data: bytes) -> int:
        from telemetry_host.security.integrity import hash_fnv64
        return hash_fnv64(data)

    def test_correct_hash_returns_true(self):
        from telemetry_host.security.integrity import verify_bytes
        data = b"secure telemetry"
        self.assertTrue(verify_bytes(data, self._h(data)))

    def test_wrong_hash_returns_false(self):
        from telemetry_host.security.integrity import verify_bytes
        self.assertFalse(verify_bytes(b"data", 0))

    def test_altered_data_returns_false(self):
        from telemetry_host.security.integrity import verify_bytes
        original = b"original"
        h = self._h(original)
        self.assertFalse(verify_bytes(b"modified", h))

    def test_empty_correct_hash(self):
        from telemetry_host.security.integrity import verify_bytes
        self.assertTrue(verify_bytes(b"", self._h(b"")))


# ── FunctionSeal ───────────────────────────────────────────────────────────────

class TestFunctionSeal(unittest.TestCase):
    """Tests for FunctionSeal bytecode-tamper detection.

    Tamper simulation replaces __code__ using compatible (non-closure) functions
    so the assignment is accepted by the interpreter regardless of Python version.
    """

    def test_seal_and_verify_intact_does_not_raise(self):
        from telemetry_host.security.integrity import FunctionSeal

        def sample():
            return 42

        FunctionSeal(sample).verify()

    def test_is_intact_returns_true_for_unmodified(self):
        from telemetry_host.security.integrity import FunctionSeal

        def sample():
            return 42

        self.assertTrue(FunctionSeal(sample).is_intact())

    def test_tampered_code_raises_integrity_error(self):
        from telemetry_host.security.integrity import FunctionSeal, IntegrityError

        def fn():
            return 42

        def replacement():
            return 99

        seal = FunctionSeal(fn)
        fn.__code__ = replacement.__code__
        with self.assertRaises(IntegrityError):
            seal.verify()

    def test_is_intact_returns_false_after_tamper(self):
        from telemetry_host.security.integrity import FunctionSeal

        def fn():
            return 1

        def replacement():
            return 2

        seal = FunctionSeal(fn)
        fn.__code__ = replacement.__code__
        self.assertFalse(seal.is_intact())

    def test_sealed_hash_is_stable_across_instances(self):
        from telemetry_host.security.integrity import FunctionSeal

        def fn():
            return 42

        self.assertEqual(FunctionSeal(fn).sealed_hash, FunctionSeal(fn).sealed_hash)

    def test_different_functions_different_hash(self):
        """Functions with genuinely different instruction sequences must hash differently."""
        from telemetry_host.security.integrity import FunctionSeal

        def fn_a():
            x = 1
            return x

        def fn_b():
            x = 1
            y = 2
            return x + y

        self.assertNotEqual(FunctionSeal(fn_a).sealed_hash, FunctionSeal(fn_b).sealed_hash)

    def test_fn_name_in_integrity_error_message(self):
        from telemetry_host.security.integrity import FunctionSeal, IntegrityError

        def my_special_fn():
            return 0

        def other():
            return 1

        seal = FunctionSeal(my_special_fn)
        my_special_fn.__code__ = other.__code__
        with self.assertRaises(IntegrityError) as ctx:
            seal.verify()
        self.assertIn("my_special_fn", str(ctx.exception))


# ── audit_system seal ─────────────────────────────────────────────────────────

class TestAuditSystemSeal(unittest.TestCase):

    def test_seal_returns_function_seal_instance(self):
        from telemetry_host.security.integrity import seal_audit_system, FunctionSeal
        seal = seal_audit_system()
        self.assertIsInstance(seal, FunctionSeal)

    def test_verify_ok_after_seal(self):
        from telemetry_host.security.integrity import seal_audit_system, verify_audit_system
        seal_audit_system()
        status = verify_audit_system()
        self.assertTrue(status.ok, f"Expected ok=True, got: {status.detail}")

    def test_verify_fails_without_prior_seal(self):
        import telemetry_host.security.integrity as ig
        saved = ig._audit_system_seal
        ig._audit_system_seal = None
        try:
            status = ig.verify_audit_system()
            self.assertFalse(status.ok)
        finally:
            ig._audit_system_seal = saved

    def test_verify_detects_simulated_tamper(self):
        from telemetry_host.security.integrity import (
            seal_audit_system, verify_audit_system, IntegrityError
        )
        import telemetry_host.security.integrity as ig

        seal = seal_audit_system()
        with patch.object(seal, "verify", side_effect=IntegrityError("injected tamper")):
            ig._audit_system_seal = seal
            status = verify_audit_system()

        self.assertFalse(status.ok)
        self.assertIn("injected tamper", status.detail)

    def test_verify_returns_integrity_status(self):
        from telemetry_host.security.integrity import seal_audit_system, verify_audit_system, IntegrityStatus
        seal_audit_system()
        self.assertIsInstance(verify_audit_system(), IntegrityStatus)

    def test_status_detail_non_empty_on_success(self):
        from telemetry_host.security.integrity import seal_audit_system, verify_audit_system
        seal_audit_system()
        status = verify_audit_system()
        if status.ok:
            self.assertGreater(len(status.detail), 0)


# ── Registry (minimum privilege) ──────────────────────────────────────────────

class TestRegReadDword(unittest.TestCase):

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_known_key_returns_int_or_none(self):
        from telemetry_host.security.integrity import reg_read_dword, HKLM
        result = reg_read_dword(
            HKLM,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
            "CurrentMajorVersionNumber",
        )
        self.assertIn(type(result), (int, type(None)))

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_known_key_value_is_positive(self):
        from telemetry_host.security.integrity import reg_read_dword, HKLM
        result = reg_read_dword(
            HKLM,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
            "CurrentMajorVersionNumber",
        )
        if result is not None:
            self.assertGreater(result, 0)

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_nonexistent_key_returns_none(self):
        from telemetry_host.security.integrity import reg_read_dword, HKLM
        self.assertIsNone(reg_read_dword(HKLM, r"SOFTWARE\__no_such_key_xyz__", "Val"))

    @unittest.skipIf(sys.platform == "win32", "non-Windows stub test")
    def test_non_windows_always_returns_none(self):
        from telemetry_host.security.integrity import reg_read_dword, HKLM
        self.assertIsNone(reg_read_dword(HKLM, r"SYSTEM\whatever", "Val"))


# ── Token privilege query ─────────────────────────────────────────────────────

class TestQueryPrivilege(unittest.TestCase):

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_sedebug_returns_valid_state(self):
        from telemetry_host.security.integrity import query_privilege
        result = query_privilege("SeDebugPrivilege")
        self.assertIn(result, (None, 0, 1, 2))

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_seshutdown_returns_valid_state(self):
        from telemetry_host.security.integrity import query_privilege
        result = query_privilege("SeShutdownPrivilege")
        self.assertIn(result, (None, 0, 1, 2))

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_unknown_privilege_returns_none_or_zero(self):
        from telemetry_host.security.integrity import query_privilege
        result = query_privilege("SeNonExistentPrivilege99XYZ")
        # LookupPrivilegeValue will fail → IG_ERR_SYSTEM → None
        self.assertIsNone(result)


# ── Process integrity level ────────────────────────────────────────────────────

class TestGetIntegrityLevel(unittest.TestCase):

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_returns_none_or_known_level(self):
        from telemetry_host.security.integrity import (
            get_integrity_level,
            INTEGRITY_LOW, INTEGRITY_MEDIUM, INTEGRITY_HIGH, INTEGRITY_SYSTEM,
        )
        level = get_integrity_level()
        if level is None:
            return  # DLL not built — acceptable
        self.assertIn(level & 0xF000,
                      {INTEGRITY_LOW, INTEGRITY_MEDIUM, INTEGRITY_HIGH, INTEGRITY_SYSTEM})

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_name_is_string_when_not_none(self):
        from telemetry_host.security.integrity import integrity_level_name
        name = integrity_level_name()
        if name is not None:
            self.assertIsInstance(name, str)


# ── Out-of-process audit ───────────────────────────────────────────────────────

class TestOutOfProcessAudit(unittest.TestCase):

    def test_run_independent_audit_returns_dict_or_none(self):
        from telemetry_host.security.integrity import run_independent_audit
        result = run_independent_audit()
        if result is None:
            # Script not found or subprocess failed — skip
            self.skipTest("out-of-process audit unavailable in this environment")
        self.assertIsInstance(result, dict)

    def test_result_has_expected_keys(self):
        from telemetry_host.security.integrity import run_independent_audit
        result = run_independent_audit()
        if result is None:
            self.skipTest("out-of-process audit unavailable")
        for key in ("secure_boot", "hvci_configured", "vbs_configured",
                    "credential_guard", "sedebug_privilege"):
            self.assertIn(key, result, f"key {key!r} missing from audit result")

    def test_result_values_are_bool_or_none(self):
        from telemetry_host.security.integrity import run_independent_audit
        result = run_independent_audit()
        if result is None:
            self.skipTest("out-of-process audit unavailable")
        for k, v in result.items():
            self.assertIn(type(v), (bool, type(None)),
                          f"key {k!r} has unexpected type {type(v)}")

    def test_missing_script_returns_none(self):
        from telemetry_host.security.integrity import run_independent_audit
        from pathlib import Path
        result = run_independent_audit(script_path=Path("/nonexistent/script.py"))
        self.assertIsNone(result)


# ── Cross-verification ────────────────────────────────────────────────────────

class TestCrossVerifyAuditSystem(unittest.TestCase):

    def test_returns_integrity_status(self):
        from telemetry_host.security.integrity import cross_verify_audit_system, IntegrityStatus
        status = cross_verify_audit_system()
        self.assertIsInstance(status, IntegrityStatus)

    def test_ok_when_results_match(self):
        from telemetry_host.security.integrity import cross_verify_audit_system
        from telemetry_host.security.sysaudit import SystemSecurityProfile
        fake = SystemSecurityProfile(
            secure_boot=None, hvci_configured=None, vbs_configured=None,
            credential_guard=None, sedebug_privilege=None,
        )
        with patch("telemetry_host.security.integrity.run_independent_audit",
                   return_value=fake.as_dict()), \
             patch("telemetry_host.security.sysaudit.audit_system", return_value=fake):
            status = cross_verify_audit_system()
        self.assertTrue(status.ok)

    def test_fail_when_results_diverge(self):
        from telemetry_host.security.integrity import cross_verify_audit_system
        from telemetry_host.security.sysaudit import SystemSecurityProfile

        in_proc = SystemSecurityProfile(
            secure_boot=True, hvci_configured=None, vbs_configured=None,
            credential_guard=None, sedebug_privilege=None,
        )
        out_proc = dict(in_proc.as_dict())
        out_proc["secure_boot"] = False   # forced divergence

        with patch("telemetry_host.security.integrity.run_independent_audit",
                   return_value=out_proc), \
             patch("telemetry_host.security.sysaudit.audit_system", return_value=in_proc):
            status = cross_verify_audit_system()

        self.assertFalse(status.ok)
        self.assertIn("secure_boot", status.detail)

    def test_fail_when_child_unavailable(self):
        from telemetry_host.security.integrity import cross_verify_audit_system
        with patch("telemetry_host.security.integrity.run_independent_audit",
                   return_value=None):
            status = cross_verify_audit_system()
        self.assertFalse(status.ok)
        self.assertIn("failed", status.detail)

    def test_detail_mentions_divergent_keys(self):
        from telemetry_host.security.integrity import cross_verify_audit_system
        from telemetry_host.security.sysaudit import SystemSecurityProfile

        in_p = SystemSecurityProfile(
            secure_boot=True, hvci_configured=True, vbs_configured=None,
            credential_guard=None, sedebug_privilege=None,
        )
        out_p = dict(in_p.as_dict())
        out_p["hvci_configured"] = False

        with patch("telemetry_host.security.integrity.run_independent_audit",
                   return_value=out_p), \
             patch("telemetry_host.security.sysaudit.audit_system", return_value=in_p):
            status = cross_verify_audit_system()

        self.assertFalse(status.ok)
        self.assertIn("hvci_configured", status.detail)


# ── DLL availability and version ──────────────────────────────────────────────

class TestDllMeta(unittest.TestCase):

    def test_dll_available_returns_bool(self):
        from telemetry_host.security.integrity import dll_available
        self.assertIsInstance(dll_available(), bool)

    def test_dll_version_is_string_or_none(self):
        from telemetry_host.security.integrity import dll_version
        v = dll_version()
        if v is not None:
            self.assertIsInstance(v, str)
            self.assertGreater(len(v), 0)

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_dll_version_format_when_loaded(self):
        from telemetry_host.security.integrity import dll_version
        v = dll_version()
        if v is None:
            self.skipTest("DLL not built")
        parts = v.split(".")
        self.assertEqual(len(parts), 3)
        for p in parts:
            self.assertTrue(p.isdigit(), f"Version part {p!r} is not a digit")


# ── Public __init__ exports ───────────────────────────────────────────────────

class TestPublicExports(unittest.TestCase):

    def test_all_symbols_importable_from_security(self):
        names = [
            "FunctionSeal", "IntegrityError", "IntegrityStatus",
            "seal_audit_system", "verify_audit_system",
            "cross_verify_audit_system", "dll_available",
        ]
        from telemetry_host import security
        for name in names:
            self.assertTrue(hasattr(security, name), f"{name!r} not in telemetry_host.security")

    def test_integrity_error_is_exception(self):
        from telemetry_host.security import IntegrityError
        self.assertTrue(issubclass(IntegrityError, Exception))


if __name__ == "__main__":
    unittest.main()
