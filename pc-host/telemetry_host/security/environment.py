"""Runtime environment scanner — detects FACEIT Anti-Cheat and similar platforms.

Only performs read-only process enumeration (CreateToolhelp32Snapshot with
TH32CS_SNAPPROCESS).  No handles are opened, no memory is accessed.
Returns an empty list on non-Windows platforms so callers need no guards.
"""
from __future__ import annotations

import sys

# Canonical lowercase exe names for FACEIT Anti-Cheat and its helper processes.
# Add future variants here; the scanner does a single-pass comparison.
FACEIT_PROCESSES: frozenset[str] = frozenset({
    "faceit.exe",
    "faceitclient.exe",
    "faceitbootstrapper.exe",
    "faceitservice.exe",
    "faceit_ac.exe",
    "faceitlauncher.exe",
})


def scan_running_processes() -> list[str]:
    """Return lowercased exe names of any running integrity-monitor processes.

    Performs one CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS) call and
    compares every entry against FACEIT_PROCESSES.  The snapshot is always
    closed, even on error.

    Returns an empty list on non-Windows platforms or when the snapshot fails.
    """
    if sys.platform != "win32":
        return []
    try:
        from ..mem.winapi import enum_process_names
        running = enum_process_names()
        return [name for name in running if name in FACEIT_PROCESSES]
    except ImportError:
        return []
    except OSError:
        return []


def is_integrity_monitor_active() -> bool:
    """Return True if at least one FACEIT AC process is running."""
    return bool(scan_running_processes())


def _scan_with_names(names: list[str]) -> list[str]:
    """Internal helper: filter *names* against FACEIT_PROCESSES (used in tests)."""
    return [n.lower() for n in names if n.lower() in FACEIT_PROCESSES]
