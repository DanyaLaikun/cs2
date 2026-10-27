"""Windows system security feature audit.

Probes read-only registry keys and Win32 token APIs to report which
kernel-level protection mechanisms are active on this machine.

The information supplements the FACEIT compliance check with a broader
picture of the host security posture:

    * Secure Boot      — UEFI firmware verified bootchain
    * HVCI             — Hypervisor-Protected Code Integrity (Memory Integrity)
    * VBS              — Virtualization-Based Security
    * Credential Guard — LSA credential isolation in VTL-1
    * SeDebugPrivilege — whether the running token can call OpenProcess
                         with PROCESS_ALL_ACCESS on arbitrary processes

All probes are non-destructive reads; no handles are opened to other
processes and no memory is modified.  Returns a SystemSecurityProfile;
individual fields are None when a query cannot be completed (non-Windows,
access denied, registry key absent).

Usage::

    profile = audit_system()
    print(profile.summary())
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SystemSecurityProfile:
    """Snapshot of Windows security feature availability on the host."""

    secure_boot:      Optional[bool]
    hvci_configured:  Optional[bool]
    vbs_configured:   Optional[bool]
    credential_guard: Optional[bool]
    sedebug_privilege: Optional[bool]

    @property
    def is_hardened(self) -> bool:
        """True when at least one key kernel isolation feature is configured."""
        return bool(
            self.hvci_configured
            or self.vbs_configured
            or self.secure_boot
        )

    def summary(self) -> str:
        """Single-line human-readable summary suitable for log output."""
        def _fmt(name: str, val: Optional[bool]) -> str:
            return f"{name}={'on' if val else ('off' if val is False else '?')}"

        return " | ".join([
            _fmt("SecureBoot",      self.secure_boot),
            _fmt("HVCI",            self.hvci_configured),
            _fmt("VBS",             self.vbs_configured),
            _fmt("CredentialGuard", self.credential_guard),
            _fmt("SeDebug",         self.sedebug_privilege),
        ])

    def as_dict(self) -> dict:
        return {
            "secure_boot":       self.secure_boot,
            "hvci_configured":   self.hvci_configured,
            "vbs_configured":    self.vbs_configured,
            "credential_guard":  self.credential_guard,
            "sedebug_privilege": self.sedebug_privilege,
        }


# ── Registry helpers ───────────────────────────────────────────────────────────

def _reg_dword(key_path: str, value_name: str) -> Optional[bool]:
    """Read a DWORD from HKLM.  Returns True/False or None on any error."""
    try:
        import winreg  # only available on Windows
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as k:
            val, _ = winreg.QueryValueEx(k, value_name)
            return bool(int(val))
    except OSError:
        return None
    except Exception:
        return None


def _check_secure_boot() -> Optional[bool]:
    return _reg_dword(
        r"SYSTEM\CurrentControlSet\Control\SecureBoot\State",
        "UEFISecureBootEnabled",
    )


def _check_hvci() -> Optional[bool]:
    return _reg_dword(
        r"SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios"
        r"\HypervisorEnforcedCodeIntegrity",
        "Enabled",
    )


def _check_vbs() -> Optional[bool]:
    return _reg_dword(
        r"SYSTEM\CurrentControlSet\Control\DeviceGuard",
        "EnableVirtualizationBasedSecurity",
    )


def _check_credential_guard() -> Optional[bool]:
    return _reg_dword(
        r"SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\CredentialGuard",
        "Enabled",
    )


# ── SeDebugPrivilege probe ─────────────────────────────────────────────────────

def _check_sedebug() -> Optional[bool]:
    """Return True if the current process token holds SeDebugPrivilege (enabled).

    Uses OpenProcessToken + GetTokenInformation(TokenPrivileges) +
    LookupPrivilegeValue — all read-only, no elevation needed to query.
    """
    try:
        import ctypes
        import ctypes.wintypes as wt

        _adv = ctypes.windll.advapi32  # type: ignore[attr-defined]
        _k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

        TOKEN_QUERY          = 0x0008
        TokenPrivileges      = 3
        SE_PRIVILEGE_ENABLED = 0x00000002

        class _LUID(ctypes.Structure):
            _fields_ = [("LowPart", wt.DWORD), ("HighPart", wt.LONG)]

        class _LUID_AND_ATTR(ctypes.Structure):
            _fields_ = [("Luid", _LUID), ("Attributes", wt.DWORD)]

        h_token = wt.HANDLE()
        if not _adv.OpenProcessToken(
            _k32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(h_token)
        ):
            return None

        try:
            needed = wt.DWORD(0)
            _adv.GetTokenInformation(
                h_token, TokenPrivileges, None, 0, ctypes.byref(needed)
            )
            if not needed.value:
                return None

            buf = ctypes.create_string_buffer(needed.value)
            if not _adv.GetTokenInformation(
                h_token, TokenPrivileges, buf, needed, ctypes.byref(needed)
            ):
                return None

            count = ctypes.cast(buf, ctypes.POINTER(wt.DWORD))[0]
            entry_size   = ctypes.sizeof(_LUID_AND_ATTR)
            privs_offset = ctypes.sizeof(wt.DWORD)

            debug_luid = _LUID()
            if not _adv.LookupPrivilegeValueW(
                None, "SeDebugPrivilege", ctypes.byref(debug_luid)
            ):
                return None

            for i in range(count):
                off = privs_offset + i * entry_size
                entry = _LUID_AND_ATTR.from_buffer_copy(buf[off: off + entry_size])
                if (
                    entry.Luid.LowPart  == debug_luid.LowPart
                    and entry.Luid.HighPart == debug_luid.HighPart
                ):
                    return bool(entry.Attributes & SE_PRIVILEGE_ENABLED)

            return False  # privilege not present in token

        finally:
            _k32.CloseHandle(h_token)

    except Exception:
        return None


# ── Public API ─────────────────────────────────────────────────────────────────

def audit_system() -> SystemSecurityProfile:
    """Probe the system and return a SystemSecurityProfile.

    Safe to call on any platform; all fields are None on non-Windows hosts.
    """
    if sys.platform != "win32":
        return SystemSecurityProfile(
            secure_boot=None,
            hvci_configured=None,
            vbs_configured=None,
            credential_guard=None,
            sedebug_privilege=None,
        )

    return SystemSecurityProfile(
        secure_boot=_check_secure_boot(),
        hvci_configured=_check_hvci(),
        vbs_configured=_check_vbs(),
        credential_guard=_check_credential_guard(),
        sedebug_privilege=_check_sedebug(),
    )
