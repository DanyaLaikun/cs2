"""Windows process-integrity guard — C DLL wrapper and pure-Python layer.

Provides:
  * Registry reads with KEY_READ only (minimum privilege)
  * Token privilege queries (read-only, no elevation required)
  * Process integrity-level detection
  * FNV-1a 64-bit hash of arbitrary bytes
  * FunctionSeal — seals and verifies Python function bytecode against
    substitution, monkey-patching, or code-object replacement
  * cross_verify_audit_system — re-runs audit_system() in a child process
    and compares results to detect in-process result tampering

All public entry points degrade gracefully: when the DLL is absent or the
platform is not Windows every function returns a safe fallback value and no
exception propagates to the caller unless explicitly documented otherwise.

Usage::

    from telemetry_host.security.integrity import (
        seal_audit_system, verify_audit_system, cross_verify_audit_system,
        dll_available,
    )

    seal_audit_system()               # call once at startup
    status = verify_audit_system()    # call periodically
    if not status.ok:
        log.warning("INTEGRITY: %s", status.detail)

    xstatus = cross_verify_audit_system()
    if not xstatus.ok:
        log.warning("CROSS-VERIFY: %s", xstatus.detail)
"""
from __future__ import annotations

import ctypes
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ── Status codes (mirror DLL constants) ────────────────────────────────────────

IG_OK            = 0
IG_ERR_NOT_FOUND = 1
IG_ERR_ACCESS    = 2
IG_ERR_MISMATCH  = 3
IG_ERR_PARAM     = 4
IG_ERR_SYSTEM    = 5


class IntegrityError(Exception):
    """Raised when a FunctionSeal detects bytecode tampering."""


@dataclass
class IntegrityStatus:
    """Result of an integrity or cross-verification check."""
    ok:     bool
    detail: str = ""
    raw:    Optional[int] = None


# ── Root-key indices ────────────────────────────────────────────────────────────

HKLM = 0
HKCU = 1
HKCR = 2
HKU  = 3

# ── Integrity level constants ───────────────────────────────────────────────────

INTEGRITY_LOW    = 0x1000
INTEGRITY_MEDIUM = 0x2000
INTEGRITY_HIGH   = 0x3000
INTEGRITY_SYSTEM = 0x4000

_INTEGRITY_NAMES: dict[int, str] = {
    INTEGRITY_LOW:    "Low",
    INTEGRITY_MEDIUM: "Medium",
    INTEGRITY_HIGH:   "High",
    INTEGRITY_SYSTEM: "System",
}

# ── DLL loader ─────────────────────────────────────────────────────────────────

_DLL_NAME = "integrity_guard.dll"
_dll: Optional[ctypes.CDLL] = None
_dll_loaded: bool = False
_dll_error: str = ""

_SEARCH_DIRS = [
    Path(__file__).parent,                      # telemetry_host/security/
    Path(__file__).parents[1],                   # telemetry_host/
    Path(__file__).parents[2],                   # pc-host/
    Path(__file__).parents[3] / "security_dll" / "build" / "Release",
    Path(__file__).parents[3] / "security_dll" / "build",
]


def _load_dll() -> Optional[ctypes.CDLL]:
    global _dll, _dll_loaded, _dll_error
    if _dll_loaded:
        return _dll
    _dll_loaded = True

    if sys.platform != "win32":
        _dll_error = "non-Windows platform"
        return None

    for d in _SEARCH_DIRS:
        candidate = d / _DLL_NAME
        if candidate.is_file():
            try:
                lib = ctypes.CDLL(str(candidate))
                lib.ig_version.restype = ctypes.c_char_p
                lib.ig_version()          # smoke-test
                _dll = lib
                return _dll
            except OSError as exc:
                _dll_error = str(exc)

    _dll_error = f"{_DLL_NAME} not found; pure-Python fallbacks active"
    return None


def dll_available() -> bool:
    """Return True if the native DLL loaded successfully."""
    return _load_dll() is not None


def dll_version() -> Optional[str]:
    """Return the DLL version string, or None if not available."""
    lib = _load_dll()
    if lib is None:
        return None
    lib.ig_version.restype = ctypes.c_char_p
    raw = lib.ig_version()
    return raw.decode() if raw else None


# ── FNV-1a 64-bit hash ─────────────────────────────────────────────────────────

def hash_fnv64(data: bytes) -> int:
    """FNV-1a 64-bit hash.  Uses the DLL when available, else pure Python."""
    lib = _load_dll()
    if lib is not None:
        lib.ig_hash_fnv64.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
        lib.ig_hash_fnv64.restype  = ctypes.c_uint64
        return int(lib.ig_hash_fnv64(data, len(data)))
    # Pure-Python fallback — identical algorithm to the DLL
    h = 14695981039346656037
    for b in data:
        h = ((h ^ b) * 1099511628211) & 0xFFFF_FFFF_FFFF_FFFF
    return h


def verify_bytes(data: bytes, expected_hash: int) -> bool:
    """Return True if FNV-1a-64(data) == expected_hash."""
    lib = _load_dll()
    if lib is not None:
        lib.ig_verify_bytes.argtypes = [
            ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint64
        ]
        lib.ig_verify_bytes.restype = ctypes.c_int32
        return lib.ig_verify_bytes(data, len(data), expected_hash) == IG_OK
    return hash_fnv64(data) == expected_hash


# ── Registry reads (KEY_READ only) ─────────────────────────────────────────────

def reg_read_dword(root: int, subkey: str, value_name: str) -> Optional[int]:
    """Read a REG_DWORD using KEY_READ only (minimum privilege).

    Returns the integer value or None on any error (key absent, access denied,
    wrong type, or non-Windows platform).
    """
    lib = _load_dll()
    if lib is not None:
        lib.ig_reg_read_dword.argtypes = [
            ctypes.c_uint32, ctypes.c_wchar_p,
            ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32),
        ]
        lib.ig_reg_read_dword.restype = ctypes.c_int32
        out = ctypes.c_uint32(0)
        rc  = lib.ig_reg_read_dword(root, subkey, value_name, ctypes.byref(out))
        return out.value if rc == IG_OK else None

    # Pure-Python fallback
    if sys.platform != "win32":
        return None
    try:
        import winreg
        _roots = [
            winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER,
            winreg.HKEY_CLASSES_ROOT,  winreg.HKEY_USERS,
        ]
        with winreg.OpenKey(_roots[root], subkey, 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, value_name)
            return int(val)
    except OSError:
        return None


# ── Token privilege query ──────────────────────────────────────────────────────

def query_privilege(privilege_name: str) -> Optional[int]:
    """Query a privilege in the current process token.

    Returns:
      0 — privilege not present in the token
      1 — present but disabled
      2 — present and enabled
      None — DLL not available or API error
    """
    lib = _load_dll()
    if lib is None:
        return None
    lib.ig_query_privilege.argtypes = [
        ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32)
    ]
    lib.ig_query_privilege.restype = ctypes.c_int32
    out = ctypes.c_uint32(0)
    rc  = lib.ig_query_privilege(privilege_name, ctypes.byref(out))
    return int(out.value) if rc == IG_OK else None


# ── Process integrity level ────────────────────────────────────────────────────

def get_integrity_level() -> Optional[int]:
    """Return the mandatory integrity level of the current process, or None.

    0x1000 = Low, 0x2000 = Medium, 0x3000 = High, 0x4000 = System.
    """
    lib = _load_dll()
    if lib is None:
        return None
    lib.ig_get_integrity_level.argtypes = [ctypes.POINTER(ctypes.c_uint32)]
    lib.ig_get_integrity_level.restype  = ctypes.c_int32
    out = ctypes.c_uint32(0)
    rc  = lib.ig_get_integrity_level(ctypes.byref(out))
    return int(out.value) if rc == IG_OK else None


def integrity_level_name() -> Optional[str]:
    """Return a human-readable integrity level name, or None."""
    level = get_integrity_level()
    if level is None:
        return None
    return _INTEGRITY_NAMES.get(level & 0xF000, f"0x{level:04x}")


# ── FunctionSeal — bytecode-level tamper detection ────────────────────────────

def _get_bytecode(fn: types.FunctionType) -> bytes:
    """Build a canonical byte serialization of a function's code object.

    Includes co_code plus the constant and name tables, so swaps that keep the
    instruction stream identical but change constants (e.g. ``return 42`` →
    ``return 99``) are still detected — those values live in co_consts, not
    co_code.
    """
    c = fn.__code__
    parts = [bytes(c.co_code)]
    for const in c.co_consts:
        if isinstance(const, types.CodeType):
            continue  # nested code objects carry their own identity
        try:
            parts.append(repr(const).encode("utf-8"))
        except Exception:
            parts.append(b"")
    parts.extend(name.encode("utf-8") for name in c.co_names)
    return b"\x00".join(parts) or b"\x00"


class FunctionSeal:
    """Records the FNV-1a hash of a Python function's bytecode at creation time
    and can verify that the bytecode has not changed since.

    What it detects:
      * Replacement of fn.__code__ with a different code object
        (monkey-patching, hot-patching via ctypes frame manipulation)
      * Byte-level mutation of co_code through ctypes memory writes
      * Swapping the function binding at the original module level
        (detected when the caller re-fetches the function and seals again)

    Usage::

        seal = FunctionSeal(audit_system)
        # ... some time later ...
        seal.verify()   # raises IntegrityError if bytecode changed
    """

    def __init__(self, fn: types.FunctionType) -> None:
        self._fn        = fn
        self._fn_name   = fn.__qualname__
        bytecode        = _get_bytecode(fn)
        self._sealed_hash: int = hash_fnv64(bytecode)
        self._sealed_len: int  = len(bytecode)

    def verify(self) -> None:
        """Raise IntegrityError if the function's bytecode has changed."""
        current = _get_bytecode(self._fn)
        if len(current) != self._sealed_len:
            raise IntegrityError(
                f"Function {self._fn_name!r} bytecode length changed: "
                f"expected {self._sealed_len}, got {len(current)}"
            )
        if not verify_bytes(current, self._sealed_hash):
            raise IntegrityError(
                f"Function {self._fn_name!r} bytecode hash mismatch — "
                "possible tampering detected"
            )

    def is_intact(self) -> bool:
        """Return True when the function is unmodified (no exception)."""
        try:
            self.verify()
            return True
        except IntegrityError:
            return False

    @property
    def sealed_hash(self) -> int:
        return self._sealed_hash


# ── Module-level seal for audit_system ────────────────────────────────────────

_audit_system_seal: Optional[FunctionSeal] = None


def seal_audit_system() -> FunctionSeal:
    """Capture the current bytecode of audit_system.  Call once at startup."""
    global _audit_system_seal
    from . import sysaudit as _sa
    _audit_system_seal = FunctionSeal(_sa.audit_system)
    return _audit_system_seal


def verify_audit_system() -> IntegrityStatus:
    """Verify audit_system bytecode against the sealed baseline.

    Returns IntegrityStatus(ok=True) when intact.
    Returns IntegrityStatus(ok=False) if not yet sealed or if tampered.
    """
    if _audit_system_seal is None:
        return IntegrityStatus(
            ok=False,
            detail="audit_system not sealed — call seal_audit_system() first",
        )
    try:
        _audit_system_seal.verify()
        return IntegrityStatus(ok=True, detail="audit_system bytecode intact")
    except IntegrityError as exc:
        return IntegrityStatus(ok=False, detail=str(exc))


# ── Out-of-process audit ───────────────────────────────────────────────────────

_OUTOFPROC_SCRIPT = Path(__file__).parents[2] / "tools" / "outofproc_audit.py"


def _run_via_dll(python_exe: str, script_path: Path) -> Optional[str]:
    """Use ig_run_outofprocess_audit to spawn a child process."""
    import ctypes as _ct
    lib = _load_dll()
    if lib is None:
        return None
    try:
        lib.ig_run_outofprocess_audit.argtypes = [
            _ct.c_wchar_p, _ct.c_wchar_p,
            _ct.c_char_p, _ct.c_uint32,
            _ct.POINTER(_ct.c_uint32),
        ]
        lib.ig_run_outofprocess_audit.restype = _ct.c_int32
        buf       = _ct.create_string_buffer(8192)
        exit_code = _ct.c_uint32(0)
        rc = lib.ig_run_outofprocess_audit(
            str(python_exe), str(script_path),
            buf, 8192, _ct.byref(exit_code)
        )
        if rc == IG_OK and exit_code.value == 0:
            return buf.value.decode(errors="replace")
    except Exception:
        pass
    return None


def run_independent_audit(
    python_exe: Optional[str] = None,
    script_path: Optional[Path] = None,
    timeout_s: float = 15.0,
) -> Optional[dict]:
    """Run audit_system() in a separate process and return its JSON result.

    Uses ig_run_outofprocess_audit (DLL) when available; falls back to
    subprocess.run.  Returns None if the child fails or the output cannot
    be parsed as JSON.
    """
    import json
    import subprocess

    if python_exe is None:
        python_exe = sys.executable
    if script_path is None:
        script_path = _OUTOFPROC_SCRIPT

    if not Path(script_path).is_file():
        return None

    # --- DLL path ---
    if sys.platform == "win32":
        raw = _run_via_dll(str(python_exe), Path(script_path))
        if raw is not None:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass

    # --- Pure-Python fallback ---
    try:
        result = subprocess.run(
            [str(python_exe), str(script_path)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        pass
    return None


def cross_verify_audit_system() -> IntegrityStatus:
    """Compare in-process audit_system() with an independently spawned child.

    Returns IntegrityStatus(ok=True)  when both results agree.
    Returns IntegrityStatus(ok=False) when values differ — possible tampering.
    Returns IntegrityStatus(ok=False, detail="…failed…") when the child could
    not be launched (out-of-process audit unavailable).
    """
    from . import sysaudit as _sa

    in_proc  = _sa.audit_system().as_dict()
    out_proc = run_independent_audit()

    if out_proc is None:
        return IntegrityStatus(
            ok=False,
            detail="out-of-process audit failed — cannot cross-verify",
        )

    mismatches = [k for k in in_proc if in_proc.get(k) != out_proc.get(k)]
    if mismatches:
        return IntegrityStatus(
            ok=False,
            detail=(
                f"Result divergence for {mismatches}; "
                "possible in-process tampering or environment change"
            ),
        )
    return IntegrityStatus(ok=True, detail="In-process and out-of-process results agree")
