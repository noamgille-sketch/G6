"""Named cheat detection - answers "which cheat is on this machine?".

Looks for artifacts belonging to a known cheat family in the places a
cheat actually lives: running processes, the folders people download and
unzip them into, and the FiveM plugins folder.

Only NAMES are read here. No file is ever opened, except to hash it when
a family declares real sample hashes to compare against.
"""
import hashlib
import os

import psutil

from .. import cheats
from ..config import IS_WINDOWS
from ..profile import ScanProfile
from .base import CheckResult, Finding, Severity

MAX_DEPTH = 3
MAX_ENTRIES = 40_000
HASHABLE_EXTS = {".exe", ".dll", ".asi", ".sys"}
MAX_HASH_BYTES = 100 * 1024 * 1024


def _scan_dirs(profile: ScanProfile) -> list[str]:
    if IS_WINDOWS:
        home = os.environ.get("USERPROFILE", os.path.expanduser("~"))
        local = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
        roaming = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
        dirs = [
            os.path.join(home, "Desktop"),
            os.path.join(home, "Downloads"),
            os.environ.get("TEMP", os.path.join(local, "Temp")),
            roaming,
            os.path.join(local, "FiveM"),
        ]
    else:
        home = os.path.expanduser("~")
        dirs = [os.path.join(home, "Desktop"), os.path.join(home, "Downloads")]

    if profile.scan_documents:
        dirs.append(os.path.join(home, "Documents"))
    return dirs


def _sha256(path: str) -> str | None:
    try:
        if os.path.getsize(path) > MAX_HASH_BYTES:
            return None
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _finding_for(match: cheats.CheatMatch, location: str) -> Finding:
    if match.strength == cheats.CONFIRMED:
        severity = Severity.CRITICAL
        detail = (
            f"Le fichier '{location}' correspond exactement au hash d'un échantillon "
            f"connu de {match.family}. C'est une identification certaine."
        )
    elif match.strength == cheats.STRONG:
        severity = Severity.CRITICAL
        detail = (
            f"'{location}' porte le nom du cheat {match.family} ({match.kind}). "
            "Ce nom est spécifique à ce cheat, il n'apparaît pas par hasard."
        )
    else:
        severity = Severity.HIGH
        detail = (
            f"'{location}' porte un nom utilisé par {match.family} ({match.kind}). "
            "Ce nom est court et pourrait appartenir à un autre logiciel - à confirmer."
        )

    return Finding(
        check="cheat_scan",
        title=f"{match.family} détecté ({match.where})",
        detail=detail,
        severity=severity,
        evidence={
            "cheat_family": match.family,
            "cheat_kind": match.kind,
            "strength": match.strength,
            "location": location,
        },
    )


def _scan_processes() -> list[Finding]:
    findings = []
    seen = set()
    for p in psutil.process_iter(["pid", "name"]):
        name = p.info.get("name") or ""
        match = cheats.match_name(name, "process")
        if match and (match.family, name) not in seen:
            seen.add((match.family, name))
            findings.append(_finding_for(match, name))
    return findings


def _scan_filesystem(profile: ScanProfile) -> list[Finding]:
    findings = []
    seen = set()
    entries = 0

    for root_dir in _scan_dirs(profile):
        if not os.path.isdir(root_dir):
            continue
        base_depth = root_dir.rstrip(os.sep).count(os.sep)

        for dirpath, dirnames, filenames in os.walk(root_dir):
            if entries > MAX_ENTRIES:
                break
            if dirpath.rstrip(os.sep).count(os.sep) - base_depth >= MAX_DEPTH:
                dirnames[:] = []

            for dirname in dirnames:
                entries += 1
                match = cheats.match_name(dirname, "dossier")
                if match and match.family not in seen:
                    seen.add(match.family)
                    findings.append(_finding_for(match, os.path.join(dirpath, dirname)))

            for fname in filenames:
                entries += 1
                full_path = os.path.join(dirpath, fname)

                match = cheats.match_name(fname, "fichier")
                if match and (match.family, fname) not in seen:
                    seen.add((match.family, fname))
                    findings.append(_finding_for(match, full_path))
                    continue

                if cheats.has_hashes() and os.path.splitext(fname)[1].lower() in HASHABLE_EXTS:
                    digest = _sha256(full_path)
                    hash_match = cheats.match_hash(digest) if digest else None
                    if hash_match and hash_match.family not in seen:
                        seen.add(hash_match.family)
                        findings.append(_finding_for(hash_match, full_path))

    return findings


def run(profile: ScanProfile) -> CheckResult:
    findings: list[Finding] = []
    try:
        findings.extend(_scan_processes())
    except Exception:
        pass
    findings.extend(_scan_filesystem(profile))
    return CheckResult("cheat_scan", ran=True, skip_reason=None, findings=findings)
