"""Minimal Windows API bindings for process memory reading via ctypes.

Wraps CreateToolhelp32Snapshot, Module32FirstW/NextW, OpenProcess,
and ReadProcessMemory. No third-party dependencies.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import sys

if sys.platform != "win32":
    raise ImportError("winapi is Windows-only")

_k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

PROCESS_VM_READ           = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPPROCESS        = 0x00000002
TH32CS_SNAPMODULE         = 0x00000008
TH32CS_SNAPMODULE32       = 0x00000010
_INVALID_HANDLE           = ctypes.c_void_p(-1).value


class _PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize",              wt.DWORD),
        ("cntUsage",            wt.DWORD),
        ("th32ProcessID",       wt.DWORD),
        ("th32DefaultHeapID",   ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID",        wt.DWORD),
        ("cntThreads",          wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase",      ctypes.c_long),
        ("dwFlags",             wt.DWORD),
        ("szExeFile",           ctypes.c_char * 260),
    ]


class _MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize",        wt.DWORD),
        ("th32ModuleID",  wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("GlblcntUsage",  wt.DWORD),
        ("ProccntUsage",  wt.DWORD),
        ("modBaseAddr",   ctypes.POINTER(wt.BYTE)),
        ("modBaseSize",   wt.DWORD),
        ("hModule",       wt.HMODULE),
        ("szModule",      ctypes.c_wchar * 256),
        ("szExePath",     ctypes.c_wchar * 260),
    ]


# ── Process enumeration ────────────────────────────────────────────────────────

def enum_process_names() -> list[str]:
    """Return lowercased exe names of every running process (one snapshot pass)."""
    snap = _k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == _INVALID_HANDLE:
        return []
    entry = _PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(_PROCESSENTRY32)
    names: list[str] = []
    try:
        if _k32.Process32First(snap, ctypes.byref(entry)):
            while True:
                names.append(entry.szExeFile.decode("utf-8", errors="replace").lower())
                if not _k32.Process32Next(snap, ctypes.byref(entry)):
                    break
    finally:
        _k32.CloseHandle(snap)
    return names


def find_pid(exe_name: str) -> int | None:
    """Return PID of the first process whose exe name matches (case-insensitive)."""
    snap = _k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == _INVALID_HANDLE:
        return None
    entry = _PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(_PROCESSENTRY32)
    target = exe_name.lower()
    try:
        if not _k32.Process32First(snap, ctypes.byref(entry)):
            return None
        while True:
            if entry.szExeFile.decode("utf-8", errors="replace").lower() == target:
                return int(entry.th32ProcessID)
            if not _k32.Process32Next(snap, ctypes.byref(entry)):
                return None
    finally:
        _k32.CloseHandle(snap)


def find_module_base(pid: int, module_name: str) -> int | None:
    """Return the base address of a loaded module inside process pid."""
    flags = TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32
    snap = _k32.CreateToolhelp32Snapshot(flags, pid)
    if snap == _INVALID_HANDLE:
        return None
    entry = _MODULEENTRY32W()
    entry.dwSize = ctypes.sizeof(_MODULEENTRY32W)
    target = module_name.lower()
    try:
        if not _k32.Module32FirstW(snap, ctypes.byref(entry)):
            return None
        while True:
            if entry.szModule.lower() == target:
                addr = ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value
                return addr or None
            if not _k32.Module32NextW(snap, ctypes.byref(entry)):
                return None
    finally:
        _k32.CloseHandle(snap)


# ── Handle management ──────────────────────────────────────────────────────────

def open_process(pid: int) -> int | None:
    """Open cs2.exe with VM-read rights. Returns a HANDLE or None."""
    h = _k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    return int(h) if h else None


def close_handle(h: int) -> None:
    _k32.CloseHandle(h)


# ── Memory reads ───────────────────────────────────────────────────────────────

def read_bytes(h: int, address: int, n: int) -> bytes | None:
    buf = ctypes.create_string_buffer(n)
    got = ctypes.c_size_t(0)
    ok = _k32.ReadProcessMemory(h, ctypes.c_void_p(address), buf, n, ctypes.byref(got))
    if not ok or got.value != n:
        return None
    return bytes(buf)


def read_u8(h: int, addr: int) -> int | None:
    b = read_bytes(h, addr, 1)
    return None if b is None else b[0]


def read_u32(h: int, addr: int) -> int | None:
    b = read_bytes(h, addr, 4)
    return None if b is None else struct.unpack_from("<I", b)[0]


def read_i32(h: int, addr: int) -> int | None:
    b = read_bytes(h, addr, 4)
    return None if b is None else struct.unpack_from("<i", b)[0]


def read_u64(h: int, addr: int) -> int | None:
    b = read_bytes(h, addr, 8)
    return None if b is None else struct.unpack_from("<Q", b)[0]


def read_f32(h: int, addr: int) -> float | None:
    b = read_bytes(h, addr, 4)
    return None if b is None else struct.unpack_from("<f", b)[0]


def read_vec3(h: int, addr: int) -> tuple[float, float, float] | None:
    b = read_bytes(h, addr, 12)
    if b is None:
        return None
    return struct.unpack_from("<fff", b)  # type: ignore[return-value]


def read_cstr(h: int, addr: int, max_len: int = 128) -> str:
    """Read a null-terminated UTF-8 string from process memory."""
    b = read_bytes(h, addr, max_len)
    if not b:
        return ""
    nul = b.find(b"\x00")
    raw = b[:nul] if nul >= 0 else b
    return raw.decode("utf-8", errors="replace").strip()
