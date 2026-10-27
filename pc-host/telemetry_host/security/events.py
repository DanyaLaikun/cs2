"""Structured security event logging for FACEIT Game Integrity compliance."""
from __future__ import annotations

import enum
import logging
import time
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger("telemetry_host.security")


class EventKind(enum.Enum):
    POLICY_INIT         = "policy_init"
    ENV_SCAN            = "env_scan"
    FACEIT_DETECTED     = "faceit_detected"
    FACEIT_CLEARED      = "faceit_cleared"
    MEM_READ_BLOCKED    = "mem_read_blocked"
    MEM_READER_STOPPED  = "mem_reader_stopped"
    PROCESS_OP_BLOCKED  = "process_op_blocked"
    CONFLICT_DETECTED   = "conflict_detected"
    SHUTDOWN_INITIATED  = "shutdown_initiated"
    POLICY_VIOLATION    = "policy_violation"


@dataclass
class SecurityEvent:
    kind:      EventKind
    message:   str
    timestamp: float            = field(default_factory=time.time)
    details:   dict[str, Any]   = field(default_factory=dict)

    def __str__(self) -> str:
        detail_str = f" | {self.details}" if self.details else ""
        return f"[{self.kind.value}] {self.message}{detail_str}"


class SecurityEventLog:
    """Thread-safe append-only ring buffer of security events.

    All writes also emit a Python log record so they appear in the normal
    application log alongside the structured store.
    """

    def __init__(self, max_events: int = 1_000) -> None:
        if max_events < 1:
            raise ValueError("max_events must be at least 1")
        self._events: list[SecurityEvent] = []
        self._max = max_events

    # ── Write ──────────────────────────────────────────────────────────────────

    def record(self, kind: EventKind, message: str, **details: Any) -> SecurityEvent:
        """Append an event; evicts the oldest when the buffer is full."""
        event = SecurityEvent(kind=kind, message=message, details=details)
        if len(self._events) >= self._max:
            self._events.pop(0)
        self._events.append(event)
        level = (
            logging.WARNING
            if kind in (
                EventKind.FACEIT_DETECTED,
                EventKind.MEM_READ_BLOCKED,
                EventKind.PROCESS_OP_BLOCKED,
                EventKind.CONFLICT_DETECTED,
                EventKind.SHUTDOWN_INITIATED,
                EventKind.POLICY_VIOLATION,
            )
            else logging.INFO
        )
        _log.log(level, "SECURITY [%s]: %s%s",
                 kind.value, message,
                 f" | {details}" if details else "")
        return event

    # ── Read ───────────────────────────────────────────────────────────────────

    def all(self) -> list[SecurityEvent]:
        return list(self._events)

    def by_kind(self, kind: EventKind) -> list[SecurityEvent]:
        return [e for e in self._events if e.kind == kind]

    def count(self, kind: EventKind | None = None) -> int:
        return len(self._events) if kind is None else len(self.by_kind(kind))

    def last(self, kind: EventKind | None = None) -> SecurityEvent | None:
        src = self.by_kind(kind) if kind is not None else self._events
        return src[-1] if src else None

    def clear(self) -> None:
        self._events.clear()
