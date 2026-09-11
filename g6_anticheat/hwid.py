"""A stable, one-way fingerprint of the machine being scanned.

Echo AC links scans of the same person by hardware ID, which is what
catches someone coming back under a new name. That is useful, but a raw
hardware ID is an identifier you cannot take back once collected.

So the fingerprint here is hashed before it ever leaves the machine: the
dashboard can tell "this is the same PC as verification #12" and nothing
else. It cannot be reversed into a serial number, and it is useless to
anyone who does not already hold a scan to compare it against.

The salt is fixed and public on purpose - a random salt would produce a
different value on every scan, which defeats the whole point.
"""
import hashlib
import os
import subprocess

from .config import IS_WINDOWS

SALT = "g6guard-machine-fingerprint-v1"


def _machine_guid() -> str | None:
    """Windows installation GUID, stable until Windows is reinstalled."""
    if not IS_WINDOWS:
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0),
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(value)
    except OSError:
        return None


def _volume_serial() -> str | None:
    """Serial of the system volume - survives a Windows reinstall."""
    if not IS_WINDOWS:
        return None
    try:
        out = subprocess.run(
            ["cmd", "/c", "vol", os.environ.get("SystemDrive", "C:")],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        for line in out.splitlines():
            if "-" in line and any(c.isdigit() for c in line):
                return line.strip().split()[-1]
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def fingerprint() -> str:
    """A 16-character anonymous identifier for this machine."""
    parts = [p for p in (_machine_guid(), _volume_serial()) if p]

    if not parts:
        # Nothing stable available: fall back to the hostname so repeated
        # scans of the same machine still line up.
        parts = [os.environ.get("COMPUTERNAME") or os.uname().nodename]

    digest = hashlib.sha256((SALT + "|".join(parts)).encode("utf-8")).hexdigest()
    return digest[:16]
