"""FACEIT Game Integrity compliance — centralised security module.

Blocks any operations incompatible with the FACEIT Anti-Cheat (AC) system:

* Detects when FACEIT AC is running in the environment.
* Disables process-memory reading while FACEIT AC is active.
* Logs every security event to a structured event log.
* Triggers safe shutdown of the MemReader when a conflict is found.
* Enforces a per-operation policy so no single function bypasses the gate.

Usage::

    from telemetry_host.security import SecurityPolicy

    policy = SecurityPolicy()
    await policy.start()          # begins periodic environment scans
    ...
    await policy.stop()
"""
from __future__ import annotations

from .events import EventKind, SecurityEvent, SecurityEventLog
from .integrity import (
    FunctionSeal,
    IntegrityError,
    IntegrityStatus,
    cross_verify_audit_system,
    dll_available,
    seal_audit_system,
    verify_audit_system,
)
from .policy import SecurityPolicy
from .sysaudit import SystemSecurityProfile, audit_system

__all__ = [
    "SecurityPolicy",
    "SecurityEventLog",
    "SecurityEvent",
    "EventKind",
    "SystemSecurityProfile",
    "audit_system",
    # integrity guard
    "FunctionSeal",
    "IntegrityError",
    "IntegrityStatus",
    "seal_audit_system",
    "verify_audit_system",
    "cross_verify_audit_system",
    "dll_available",
]
