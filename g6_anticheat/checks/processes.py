"""Process scanner - cross platform (uses psutil).

Flags:
  - process names/command lines matching known cheat/injector patterns
  - processes running from suspicious locations (Temp/Downloads) while a
    game process is active
  - duplicate/renamed copies of well known injector tools
"""
import os

import psutil

from ..config import GAME_PROCESS_NAMES
from ..signatures import process_name_is_suspicious
from .base import CheckResult, Finding, Severity

SUSPICIOUS_DIRS = ("temp", "downloads", "appdata\\local\\temp")


def _is_game_running(procs) -> bool:
    return any(p.info["name"] and p.info["name"].lower() in GAME_PROCESS_NAMES for p in procs)


def run() -> CheckResult:
    findings: list[Finding] = []
    try:
        procs = list(psutil.process_iter(["pid", "name", "exe", "cmdline"]))
    except Exception as exc:  # pragma: no cover - defensive
        return CheckResult("processes", ran=False, skip_reason=str(exc))

    game_running = _is_game_running(procs)

    for p in procs:
        name = p.info.get("name") or ""
        exe = p.info.get("exe") or ""
        cmdline = " ".join(p.info.get("cmdline") or [])

        pattern = process_name_is_suspicious(name)
        if pattern:
            findings.append(
                Finding(
                    check="processes",
                    title=f"Suspicious process name: {name}",
                    detail=(
                        f"Process '{name}' (pid {p.info['pid']}) matches known "
                        f"cheat/injector keyword '{pattern}'."
                    ),
                    severity=Severity.HIGH if game_running else Severity.MEDIUM,
                    evidence={"pid": p.info["pid"], "name": name, "exe": exe},
                )
            )
            continue

        if pattern is None and cmdline:
            cmd_pattern = process_name_is_suspicious(cmdline)
            if cmd_pattern:
                findings.append(
                    Finding(
                        check="processes",
                        title=f"Suspicious command line for {name or exe}",
                        detail=(
                            f"Command line of pid {p.info['pid']} contains "
                            f"keyword '{cmd_pattern}'."
                        ),
                        severity=Severity.MEDIUM,
                        evidence={"pid": p.info["pid"], "cmdline": cmdline},
                    )
                )

        if game_running and exe:
            exe_l = exe.lower()
            if any(d in exe_l for d in SUSPICIOUS_DIRS) and name.lower() not in GAME_PROCESS_NAMES:
                findings.append(
                    Finding(
                        check="processes",
                        title=f"Process launched from a temp/downloads folder: {name}",
                        detail=(
                            f"'{name}' (pid {p.info['pid']}) is running from '{exe}' "
                            "while the game is active. Legit tools rarely run from "
                            "Temp/Downloads - this is a common pattern for cheat "
                            "loaders and injectors."
                        ),
                        severity=Severity.LOW,
                        evidence={"pid": p.info["pid"], "exe": exe},
                    )
                )

    return CheckResult("processes", ran=True, skip_reason=None, findings=findings)
