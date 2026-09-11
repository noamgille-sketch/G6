"""Autorun / persistence scanner (Windows only).

Checks the classic Run/RunOnce registry keys and the Startup folders for
entries pointing at something matching our suspicious-file-name patterns
(injectors, loaders, spoofers, ...). This does not try to be a full
Autoruns clone - it targets the handful of locations cheat loaders
actually use to survive a reboot.
"""
import os

from ..config import IS_WINDOWS
from ..profile import ScanProfile
from ..signatures import file_name_is_suspicious
from .base import CheckResult, Finding, Severity

RUN_KEYS = [
    (r"HKEY_CURRENT_USER", r"Software\Microsoft\Windows\CurrentVersion\Run"),
    (r"HKEY_CURRENT_USER", r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
    (r"HKEY_LOCAL_MACHINE", r"Software\Microsoft\Windows\CurrentVersion\Run"),
    (r"HKEY_LOCAL_MACHINE", r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
]


def _iter_run_key_values():
    import winreg

    hive_map = {
        "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
        "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
    }
    for hive_name, subkey in RUN_KEYS:
        try:
            with winreg.OpenKey(hive_map[hive_name], subkey) as key:
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                        yield f"{hive_name}\\{subkey}", name, str(value)
                        i += 1
                    except OSError:
                        break
        except OSError:
            continue


def _iter_startup_folders():
    candidates = [
        os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup"),
        os.path.join(os.environ.get("PROGRAMDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup"),
    ]
    for folder in candidates:
        if folder and os.path.isdir(folder):
            for fname in os.listdir(folder):
                yield folder, fname, os.path.join(folder, fname)


def run(profile: ScanProfile) -> CheckResult:
    if not IS_WINDOWS:
        return CheckResult("autoruns", ran=False, skip_reason="Windows only")

    findings: list[Finding] = []

    try:
        for location, name, value in _iter_run_key_values():
            if file_name_is_suspicious(value) or file_name_is_suspicious(name):
                findings.append(
                    Finding(
                        check="autoruns",
                        title=f"Suspicious autorun entry: {name}",
                        detail=f"Registry value '{name}' under {location} = '{value}'.",
                        severity=Severity.MEDIUM,
                        evidence={"location": location, "name": name, "value": value},
                    )
                )
    except Exception as exc:
        return CheckResult("autoruns", ran=False, skip_reason=str(exc))

    try:
        for folder, fname, full_path in _iter_startup_folders():
            if file_name_is_suspicious(fname):
                findings.append(
                    Finding(
                        check="autoruns",
                        title=f"Suspicious file in Startup folder: {fname}",
                        detail=f"'{full_path}' is set to launch at logon.",
                        severity=Severity.MEDIUM,
                        evidence={"path": full_path},
                    )
                )
    except Exception:
        pass

    return CheckResult("autoruns", ran=True, skip_reason=None, findings=findings)
