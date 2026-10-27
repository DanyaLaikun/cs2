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
from .policy import SecurityPolicy

__all__ = [
    "SecurityPolicy",
    "SecurityEventLog",
    "SecurityEvent",
    "EventKind",
]
