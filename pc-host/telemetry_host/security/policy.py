"""Centralised security policy for FACEIT Game Integrity compliance.

Single source of truth for what the telemetry host is allowed to do at any
given moment.  Other modules query this object; they never read the environment
directly.

Lifecycle::

    policy = SecurityPolicy()
    policy.register_conflict_handler(my_async_stop_fn)
    await policy.start()   # initial scan + launches background scan loop
    ...
    await policy.stop()    # cancels background scan
"""
from __future__ import annotations

import asyncio
import logging
import sys
from typing import Callable

from .environment import scan_running_processes
from .events import EventKind, SecurityEventLog
from .sysaudit import SystemSecurityProfile, audit_system

log = logging.getLogger("telemetry_host.security")

# Only cs2.exe may be opened / read by the telemetry host.
_ALLOWED_TARGET: str = "cs2.exe"


class SecurityPolicy:
    """Gate-keeper that enforces FACEIT-compatible operation rules.

    Rules
    -----
    1. Memory of *any* process other than cs2.exe is always blocked.
    2. If FACEIT AC is detected in the environment, all memory access to
       cs2.exe is also blocked and registered conflict handlers are called.
    3. If FACEIT AC later exits, the restriction is lifted automatically and
       logged so the operator can decide whether to re-enable the mem reader.
    """

    SCAN_INTERVAL_S: float = 10.0

    def __init__(self) -> None:
        self._event_log = SecurityEventLog()
        self._mem_allowed = True
        self._faceit_procs: list[str] = []
        self._conflict_handlers: list[Callable[[], None]] = []
        self._scan_task: asyncio.Task[None] | None = None
        self._sys_profile: SystemSecurityProfile | None = None

        self._event_log.record(
            EventKind.POLICY_INIT,
            "Security policy initialised",
            platform=sys.platform,
            allowed_target=_ALLOWED_TARGET,
        )

    # ── Public properties ──────────────────────────────────────────────────────

    @property
    def mem_read_allowed(self) -> bool:
        """False when FACEIT AC is (or was recently) detected."""
        return self._mem_allowed

    @property
    def event_log(self) -> SecurityEventLog:
        return self._event_log

    @property
    def detected_processes(self) -> list[str]:
        """Integrity-monitor processes found in the last scan."""
        return list(self._faceit_procs)

    @property
    def system_profile(self) -> "SystemSecurityProfile | None":
        """Result of the last system security audit, or None before first start()."""
        return self._sys_profile

    # ── Policy checks (called by other modules) ────────────────────────────────

    def check_mem_read(self, process_name: str, address: int | None = None) -> bool:
        """Return True if reading memory from *process_name* is permitted.

        Logs a POLICY_VIOLATION and returns False when blocked so callers
        can bail out cleanly without raising.
        """
        lower = process_name.lower()
        if lower != _ALLOWED_TARGET:
            self._event_log.record(
                EventKind.PROCESS_OP_BLOCKED,
                f"Memory read of unauthorised target '{process_name}' blocked",
                process=process_name,
                address=hex(address) if address is not None else "N/A",
            )
            return False
        if not self._mem_allowed:
            self._event_log.record(
                EventKind.MEM_READ_BLOCKED,
                f"Memory read of '{process_name}' blocked — FACEIT AC active",
                process=process_name,
                address=hex(address) if address is not None else "N/A",
                faceit_procs=self._faceit_procs,
            )
            return False
        return True

    def check_process_open(self, process_name: str) -> bool:
        """Return True if opening a process handle for *process_name* is allowed."""
        lower = process_name.lower()
        if lower != _ALLOWED_TARGET:
            self._event_log.record(
                EventKind.PROCESS_OP_BLOCKED,
                f"OpenProcess for '{process_name}' blocked — not an authorised target",
                process=process_name,
            )
            return False
        if not self._mem_allowed:
            self._event_log.record(
                EventKind.PROCESS_OP_BLOCKED,
                f"OpenProcess for '{process_name}' blocked — FACEIT AC active",
                process=process_name,
                faceit_procs=self._faceit_procs,
            )
            return False
        return True

    # ── Conflict handlers ──────────────────────────────────────────────────────

    def register_conflict_handler(self, handler: Callable[[], None]) -> None:
        """Register a zero-argument callable invoked when a conflict is detected.

        Handlers are called synchronously in the scan thread / asyncio task.
        If a handler raises, the exception is logged and the remaining handlers
        still run.
        """
        self._conflict_handlers.append(handler)

    # ── Environment scanning ───────────────────────────────────────────────────

    def _apply_scan_result(self, found: list[str]) -> None:
        if found:
            if self._mem_allowed:
                self._faceit_procs = found
                self._mem_allowed = False
                self._event_log.record(
                    EventKind.FACEIT_DETECTED,
                    "FACEIT Anti-Cheat detected — disabling process-memory access",
                    processes=found,
                )
                self._event_log.record(
                    EventKind.CONFLICT_DETECTED,
                    "Compliance conflict: mem reader incompatible with FACEIT AC",
                    processes=found,
                )
                self._event_log.record(
                    EventKind.SHUTDOWN_INITIATED,
                    "Initiating safe shutdown of MemReader",
                )
                for h in list(self._conflict_handlers):
                    try:
                        h()
                    except Exception:
                        log.exception("Security: error in conflict handler %r", h)
        else:
            if not self._mem_allowed and self._faceit_procs:
                prev = self._faceit_procs
                self._faceit_procs = []
                self._mem_allowed = True
                self._event_log.record(
                    EventKind.FACEIT_CLEARED,
                    "FACEIT Anti-Cheat no longer detected — restrictions lifted",
                    previously_seen=prev,
                )

    def do_scan(self) -> list[str]:
        """Synchronously scan for integrity-monitor processes; update policy state.

        Returns the list of found process names (empty = none detected).
        This is the blocking half; callers on the event loop must use
        ``asyncio.to_thread(policy.do_scan)``.
        """
        found = scan_running_processes()
        self._event_log.record(
            EventKind.ENV_SCAN,
            "Environment scan completed",
            found=found,
            mem_allowed_after=self._mem_allowed if not found else False,
        )
        self._apply_scan_result(found)
        return found

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Run a system audit and initial process scan, then start the background loop."""
        profile = await asyncio.to_thread(audit_system)
        self._sys_profile = profile
        self._event_log.record(
            EventKind.SYS_AUDIT,
            f"System security audit: {profile.summary()}",
            **profile.as_dict(),
        )
        await asyncio.to_thread(self.do_scan)
        if self._scan_task is None or self._scan_task.done():
            self._scan_task = asyncio.get_event_loop().create_task(
                self._scan_loop(), name="security-scan"
            )

    async def stop(self) -> None:
        """Cancel the background scan loop and wait for it to finish."""
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
            self._scan_task = None

    async def _scan_loop(self) -> None:
        while True:
            await asyncio.sleep(self.SCAN_INTERVAL_S)
            try:
                await asyncio.to_thread(self.do_scan)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.debug("Security: scan error", exc_info=True)
