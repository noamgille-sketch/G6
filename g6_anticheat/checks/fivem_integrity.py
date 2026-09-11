"""FiveM plugin folder integrity check.

FiveM loads .asi/.dll plugins from
%LOCALAPPDATA%\\FiveM\\FiveM.app\\plugins. That folder is a favourite
drop point for "ASI mod menus" since FiveM will load anything sitting
there for you.

We don't ship a fixed allowlist (we have no reliable public list of
"every legitimate FiveM plugin hash"). Instead we keep a baseline in the
local database: the first time this runs, every file found is recorded
as trusted. On every later run, a brand-new file or a changed hash on an
existing file is flagged - because that's exactly what happens when a
mod menu drops itself in there after the fact.
"""
import hashlib
import os

from .. import db
from ..config import IS_WINDOWS
from ..profile import ScanProfile
from .base import CheckResult, Finding, Severity

PLUGIN_EXTS = {".asi", ".dll"}


def _plugins_dir() -> str | None:
    if not IS_WINDOWS:
        return None
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        return None
    return os.path.join(local_appdata, "FiveM", "FiveM.app", "plugins")


def _sha256(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def run(profile: ScanProfile) -> CheckResult:
    plugins_dir = _plugins_dir()
    if not plugins_dir:
        return CheckResult("fivem_integrity", ran=False, skip_reason="Windows only / FiveM not found")
    if not os.path.isdir(plugins_dir):
        return CheckResult("fivem_integrity", ran=False, skip_reason="FiveM plugins folder not found")

    findings: list[Finding] = []

    if not profile.use_baseline:
        # One-shot scan: nothing to compare against, so report what is there
        # and let whoever reads it judge. Named cheats in this folder are
        # caught separately by the cheat_scan check.
        for fname in sorted(os.listdir(plugins_dir)):
            if os.path.splitext(fname)[1].lower() not in PLUGIN_EXTS:
                continue
            full_path = os.path.join(plugins_dir, fname)
            digest = _sha256(full_path)
            findings.append(
                Finding(
                    check="fivem_integrity",
                    title=f"Plugin FiveM installé : {fname}",
                    detail=(
                        f"'{full_path}' est chargé par FiveM au lancement. FiveM "
                        "charge tout ce qui se trouve dans ce dossier, c'est le point "
                        "d'entrée habituel des menus ASI. Vérifie que tu reconnais "
                        "ce plugin."
                    ),
                    severity=Severity.INFO,
                    evidence={"path": full_path, "sha256": digest},
                )
            )
        return CheckResult("fivem_integrity", ran=True, skip_reason=None, findings=findings)

    is_first_run = db.baseline_count() == 0

    for fname in os.listdir(plugins_dir):
        ext = os.path.splitext(fname)[1].lower()
        if ext not in PLUGIN_EXTS:
            continue

        full_path = os.path.join(plugins_dir, fname)
        digest = _sha256(full_path)
        if not digest:
            continue

        known_hash = db.get_baseline_hash(full_path)

        if known_hash is None:
            db.upsert_baseline(full_path, digest)
            if not is_first_run:
                findings.append(
                    Finding(
                        check="fivem_integrity",
                        title=f"New FiveM plugin appeared: {fname}",
                        detail=(
                            f"'{full_path}' showed up in the plugins folder since "
                            "the last scan. If you didn't install this yourself, "
                            "treat it as suspicious - this is the standard way ASI "
                            "mod menus get loaded by FiveM."
                        ),
                        severity=Severity.MEDIUM,
                        evidence={"path": full_path, "sha256": digest},
                    )
                )
        elif known_hash != digest:
            db.upsert_baseline(full_path, digest)
            findings.append(
                Finding(
                    check="fivem_integrity",
                    title=f"FiveM plugin changed: {fname}",
                    detail=(
                        f"'{full_path}' has a different hash than last time we "
                        "recorded it. Either you updated it yourself, or it was "
                        "swapped/tampered with."
                    ),
                    severity=Severity.HIGH,
                    evidence={"path": full_path, "sha256": digest, "previous_sha256": known_hash},
                )
            )

    return CheckResult("fivem_integrity", ran=True, skip_reason=None, findings=findings)
