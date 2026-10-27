"""Policy-enforced wrappers around winapi process operations.

Provides thin guards that consult a SecurityPolicy before forwarding to the
underlying Windows API.  Non-Windows builds export no-op stubs so code that
imports from this module compiles everywhere.

Usage (Windows)::

    from telemetry_host.security.guard import guarded_open_process, guarded_read_bytes

    handle = guarded_open_process(policy, "cs2.exe", pid)
    if handle is None:
        return  # blocked or failed

    data = guarded_read_bytes(policy, "cs2.exe", handle, address, 8)
"""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .policy import SecurityPolicy


if sys.platform == "win32":
    from ..mem.winapi import open_process as _open_process
    from ..mem.winapi import read_bytes as _read_bytes

    def guarded_open_process(
        policy: "SecurityPolicy",
        process_name: str,
        pid: int,
    ) -> int | None:
        """Open *process_name* (PID *pid*) only if the policy permits it.

        Returns the Windows HANDLE on success, None when blocked or on error.
        """
        if not policy.check_process_open(process_name):
            return None
        return _open_process(pid)

    def guarded_read_bytes(
        policy: "SecurityPolicy",
        process_name: str,
        handle: int,
        address: int,
        size: int,
    ) -> bytes | None:
        """Read *size* bytes from *address* in *process_name* only if allowed.

        Returns the bytes on success, None when blocked or on read error.
        """
        if not policy.check_mem_read(process_name, address):
            return None
        return _read_bytes(handle, address, size)

else:
    # Non-Windows stubs — always return None (no memory access possible).

    def guarded_open_process(  # type: ignore[misc]
        policy: "SecurityPolicy",
        process_name: str,
        pid: int,
    ) -> None:
        return None

    def guarded_read_bytes(  # type: ignore[misc]
        policy: "SecurityPolicy",
        process_name: str,
        handle: int,
        address: int,
        size: int,
    ) -> None:
        return None
