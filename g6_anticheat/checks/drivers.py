"""Kernel driver scanner (Windows only).

Cheats that need kernel-mode access (to hide from user-mode anticheats,
read/write GTA5 memory undetected, etc.) almost always do it via
"Bring Your Own Vulnerable Driver" (BYOVD): they load a legitimately
signed but exploitable driver and abuse a bug in it to get kernel
read/write. Microsoft publishes a recommended driver blocklist for
exactly this reason - we ship a small excerpt of well known offenders
in data/signatures.json (vulnerable_driver_blocklist).

This check also flags drivers loaded from outside the standard
C:\\Windows\\System32\\drivers folder as lower-severity "worth a look",
since plenty of legitimate hardware/AV drivers live elsewhere too.
"""
import ctypes
import os
from ctypes import wintypes

from ..config import IS_WINDOWS
from ..signatures import driver_is_blocklisted, trusted_driver_dirs
from .base import CheckResult, Finding, Severity


def _load_winapi():
    psapi = ctypes.WinDLL("psapi", use_last_error=True)

    psapi.EnumDeviceDrivers.restype = wintypes.BOOL
    psapi.EnumDeviceDrivers.argtypes = [
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]

    psapi.GetDeviceDriverBaseNameW.restype = wintypes.DWORD
    psapi.GetDeviceDriverBaseNameW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR, wintypes.DWORD]

    psapi.GetDeviceDriverFileNameW.restype = wintypes.DWORD
    psapi.GetDeviceDriverFileNameW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR, wintypes.DWORD]

    return psapi


def run() -> CheckResult:
    if not IS_WINDOWS:
        return CheckResult("drivers", ran=False, skip_reason="Windows only")

    try:
        psapi = _load_winapi()
    except Exception as exc:
        return CheckResult("drivers", ran=False, skip_reason=f"could not load winapi: {exc}")

    findings: list[Finding] = []
    trusted_dirs = trusted_driver_dirs()

    count_guess = 2048
    bases = (ctypes.c_void_p * count_guess)()
    needed = wintypes.DWORD(0)

    ok = psapi.EnumDeviceDrivers(bases, ctypes.sizeof(bases), ctypes.byref(needed))
    if not ok:
        return CheckResult("drivers", ran=False, skip_reason="EnumDeviceDrivers failed")

    n = min(count_guess, needed.value // ctypes.sizeof(ctypes.c_void_p))

    for i in range(n):
        base = bases[i]
        if not base:
            continue

        name_buf = ctypes.create_unicode_buffer(260)
        path_buf = ctypes.create_unicode_buffer(260)
        psapi.GetDeviceDriverBaseNameW(base, name_buf, 260)
        psapi.GetDeviceDriverFileNameW(base, path_buf, 260)

        basename = name_buf.value or ""
        path = path_buf.value or ""

        if not basename:
            continue

        if driver_is_blocklisted(basename):
            findings.append(
                Finding(
                    check="drivers",
                    title=f"Known vulnerable driver loaded: {basename}",
                    detail=(
                        f"'{basename}' ({path or 'path unknown'}) is on the "
                        "vulnerable-driver blocklist. These drivers are legitimately "
                        "signed but contain bugs that let user-mode code get "
                        "kernel-level read/write - the standard technique cheats "
                        "and rootkits use to bypass anticheats. Its presence alone "
                        "is a strong red flag, even if nothing has exploited it yet."
                    ),
                    severity=Severity.CRITICAL,
                    evidence={"basename": basename, "path": path},
                )
            )
            continue

        if path:
            path_l = path.lower().replace("\\systemroot\\", "c:\\windows\\").replace("system32\\drivers", "system32\\drivers")
            in_trusted_dir = any(td in path_l for td in trusted_dirs)
            if not in_trusted_dir and basename.lower().endswith(".sys"):
                findings.append(
                    Finding(
                        check="drivers",
                        title=f"Driver loaded outside System32\\drivers: {basename}",
                        detail=(
                            f"'{basename}' is loaded from '{path}', outside the "
                            "standard drivers folder. Often this is a legitimate "
                            "GPU/audio/virtualization/AV driver - but it's also "
                            "where custom cheat kernel drivers get dropped. Worth "
                            "a manual look if you don't recognize it."
                        ),
                        severity=Severity.LOW,
                        evidence={"basename": basename, "path": path},
                    )
                )

    return CheckResult("drivers", ran=True, skip_reason=None, findings=findings)
