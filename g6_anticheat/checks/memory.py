"""Memory scanner for the running game process (Windows only).

Looks for the two classic signs of a DLL-injection / manual-map cheat:

  1. "Ghost modules" - a module is listed in the process's module table
     (so Windows knows a DLL was LoadLibrary'd there) but the file no
     longer exists on disk. Loaders frequently delete the DLL right
     after injecting it so disk scanners find nothing.

  2. Private executable memory not backed by any file ("manual mapping").
     Legit DLLs/EXEs show up as MEM_IMAGE regions backed by a file on
     disk. A cheat that manually maps itself into memory (to dodge
     LoadLibrary hooks) shows up as MEM_PRIVATE, executable, with no
     backing file. If it also still has an intact "MZ" header at the
     start of the region, that's a very strong signal.

Caveat we surface in every finding of type 2: FiveM's own scripting
runtime (Lua/JS/CLR resources) legitimately JITs code into private
executable memory inside FiveM_GTAProcess.exe. We filter out CEF/NUI
helper processes and use a size threshold to cut down noise, but this
signal alone is a lead to investigate, not proof of a cheat.
"""
import ctypes
import os
from ctypes import wintypes

import psutil

from ..config import GAME_PROCESS_NAMES, IS_WINDOWS
from .base import CheckResult, Finding, Severity

MEM_COMMIT = 0x1000
MEM_PRIVATE = 0x20000
MEM_IMAGE = 0x1000000

PAGE_EXECUTE = 0x10
PAGE_EXECUTE_READ = 0x20
PAGE_EXECUTE_READWRITE = 0x40
PAGE_EXECUTE_WRITECOPY = 0x80
EXEC_PROTECT_FLAGS = (
    PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY
)

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
LIST_MODULES_ALL = 0x03

MIN_REGION_SIZE = 0x8000  # 32KB - filters out tiny JIT thunks
MAX_REGIONS_REPORTED = 5
USERSPACE_LIMIT = 0x7FFFFFFEFFFF


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


def _load_winapi():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)

    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

    kernel32.VirtualQueryEx.restype = ctypes.c_size_t
    kernel32.VirtualQueryEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.POINTER(MEMORY_BASIC_INFORMATION),
        ctypes.c_size_t,
    ]

    kernel32.ReadProcessMemory.restype = wintypes.BOOL
    kernel32.ReadProcessMemory.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    psapi.EnumProcessModulesEx.restype = wintypes.BOOL
    psapi.EnumProcessModulesEx.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.HMODULE),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.DWORD,
    ]

    psapi.GetModuleFileNameExW.restype = wintypes.DWORD
    psapi.GetModuleFileNameExW.argtypes = [
        wintypes.HANDLE,
        wintypes.HMODULE,
        wintypes.LPWSTR,
        wintypes.DWORD,
    ]

    return kernel32, psapi


def _is_helper_process(cmdline: list[str]) -> bool:
    joined = " ".join(cmdline or [])
    return "--type=" in joined  # CEF/NUI subprocess (renderer, gpu-process, ...)


def _scan_ghost_modules(kernel32, psapi, handle, pid, name) -> list[Finding]:
    findings: list[Finding] = []
    needed = wintypes.DWORD(0)
    count_guess = 1024
    buf = (wintypes.HMODULE * count_guess)()

    ok = psapi.EnumProcessModulesEx(
        handle, buf, ctypes.sizeof(buf), ctypes.byref(needed), LIST_MODULES_ALL
    )
    if not ok:
        return findings

    n = min(count_guess, needed.value // ctypes.sizeof(wintypes.HMODULE))
    for i in range(n):
        hmod = buf[i]
        path_buf = ctypes.create_unicode_buffer(260)
        length = psapi.GetModuleFileNameExW(handle, hmod, path_buf, 260)
        if not length:
            continue
        path = path_buf.value
        if path and not os.path.exists(path):
            findings.append(
                Finding(
                    check="memory",
                    title=f"Ghost module loaded in {name}",
                    detail=(
                        f"'{path}' is loaded as a module inside {name} (pid {pid}) "
                        "but the file no longer exists on disk. This is a classic "
                        "sign of an injector deleting its DLL right after loading it."
                    ),
                    severity=Severity.CRITICAL,
                    evidence={"pid": pid, "path": path},
                )
            )
    return findings


def _scan_private_exec_regions(kernel32, handle, pid, name) -> list[Finding]:
    findings: list[Finding] = []
    address = 0
    mbi = MEMORY_BASIC_INFORMATION()
    candidates = []

    iterations = 0
    while address < USERSPACE_LIMIT and iterations < 400_000:
        iterations += 1
        ret = kernel32.VirtualQueryEx(handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi))
        if not ret:
            address += 0x10000
            continue

        region_size = mbi.RegionSize or 0x1000
        is_exec = bool(mbi.Protect & EXEC_PROTECT_FLAGS)
        is_private = mbi.Type == MEM_PRIVATE
        is_committed = mbi.State == MEM_COMMIT

        if is_committed and is_private and is_exec and region_size >= MIN_REGION_SIZE:
            has_mz = False
            try:
                header = (ctypes.c_char * 2)()
                read = ctypes.c_size_t(0)
                if kernel32.ReadProcessMemory(handle, ctypes.c_void_p(address), header, 2, ctypes.byref(read)):
                    has_mz = bytes(header) == b"MZ"
            except Exception:
                pass
            candidates.append((region_size, address, has_mz))

        address += region_size

    candidates.sort(key=lambda c: (c[2], c[0]), reverse=True)
    for region_size, addr, has_mz in candidates[:MAX_REGIONS_REPORTED]:
        if has_mz:
            severity = Severity.HIGH
            title = f"Manually-mapped module suspected in {name}"
            detail = (
                f"Found a private, executable memory region at 0x{addr:x} "
                f"({region_size // 1024} KB) inside {name} (pid {pid}) that still "
                "has a valid 'MZ' PE header. Legit DLLs are file-backed (MEM_IMAGE); "
                "this region is not backed by any file - it was mapped directly "
                "into memory, which is exactly how most manual-map cheat loaders work."
            )
        else:
            severity = Severity.LOW
            title = f"Unbacked executable memory in {name}"
            detail = (
                f"Found a private, executable memory region at 0x{addr:x} "
                f"({region_size // 1024} KB) inside {name} (pid {pid}) with no "
                "backing file. This can be a manually-mapped cheat with its PE "
                "header wiped, OR a false positive from FiveM's own Lua/JS/CLR "
                "scripting runtime, which JITs code the same way. Treat as a lead, "
                "not proof - cross-check with the other findings in this scan."
            )
        findings.append(
            Finding(
                check="memory",
                title=title,
                detail=detail,
                severity=severity,
                evidence={"pid": pid, "address": hex(addr), "size": region_size},
            )
        )
    return findings


def run() -> CheckResult:
    if not IS_WINDOWS:
        return CheckResult("memory", ran=False, skip_reason="Windows only")

    try:
        kernel32, psapi = _load_winapi()
    except Exception as exc:
        return CheckResult("memory", ran=False, skip_reason=f"could not load winapi: {exc}")

    findings: list[Finding] = []
    ran_any = False

    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        name = (p.info.get("name") or "").lower()
        if name not in GAME_PROCESS_NAMES:
            continue
        if _is_helper_process(p.info.get("cmdline") or []):
            continue

        handle = kernel32.OpenProcess(
            PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, p.info["pid"]
        )
        if not handle:
            findings.append(
                Finding(
                    check="memory",
                    title=f"Could not open {p.info['name']} for inspection",
                    detail=(
                        "OpenProcess failed (access denied). Try running G6 Guard "
                        "as Administrator for a deeper scan."
                    ),
                    severity=Severity.INFO,
                    evidence={"pid": p.info["pid"]},
                )
            )
            continue

        ran_any = True
        try:
            findings.extend(_scan_ghost_modules(kernel32, psapi, handle, p.info["pid"], p.info["name"]))
            findings.extend(_scan_private_exec_regions(kernel32, handle, p.info["pid"], p.info["name"]))
        finally:
            kernel32.CloseHandle(handle)

    if not ran_any:
        return CheckResult("memory", ran=False, skip_reason="game not running")

    return CheckResult("memory", ran=True, skip_reason=None, findings=findings)
