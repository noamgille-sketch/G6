"""Filesystem scanner.

Walks a short list of common "cheat lives here" folders (Desktop,
Downloads, Documents, temp) looking for files whose name matches known
suspicious patterns, and hashes small executables/DLLs to check against
the local sha256 blocklist in data/signatures.json.

This is intentionally shallow (depth-limited, size-limited) - it is not
a full antivirus scan, just a quick heuristic pass.
"""
import hashlib
import os

from ..config import IS_WINDOWS
from ..profile import ScanProfile
from ..signatures import file_name_is_suspicious, sha256_lookup
from .base import CheckResult, Finding, Severity

MAX_DEPTH = 3
MAX_FILES_SCANNED = 20_000
MAX_HASH_BYTES = 200 * 1024 * 1024  # skip hashing anything bigger than this
HASHABLE_EXTS = {".exe", ".dll", ".asi", ".sys"}


def _target_dirs(profile: ScanProfile) -> list[str]:
    if IS_WINDOWS:
        home = os.environ.get("USERPROFILE", os.path.expanduser("~"))
        temp = os.environ.get("TEMP", os.path.join(home, "AppData", "Local", "Temp"))
        dirs = [os.path.join(home, "Desktop"), os.path.join(home, "Downloads"), temp]
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


def run(profile: ScanProfile) -> CheckResult:
    findings: list[Finding] = []
    scanned = 0

    for root_dir in _target_dirs(profile):
        if not os.path.isdir(root_dir):
            continue

        base_depth = root_dir.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root_dir):
            depth = dirpath.rstrip(os.sep).count(os.sep) - base_depth
            if depth >= MAX_DEPTH:
                dirnames[:] = []

            for fname in filenames:
                scanned += 1
                if scanned > MAX_FILES_SCANNED:
                    break
                full_path = os.path.join(dirpath, fname)
                ext = os.path.splitext(fname)[1].lower()

                name_hit = file_name_is_suspicious(fname)
                digest = None
                blocklist_label = None
                if ext in HASHABLE_EXTS:
                    digest = _sha256(full_path)
                    if digest:
                        blocklist_label = sha256_lookup(digest)

                if blocklist_label:
                    findings.append(
                        Finding(
                            check="filesystem",
                            title=f"Known-bad file found: {fname}",
                            detail=(
                                f"'{full_path}' matches a hash on the blocklist "
                                f"(labelled '{blocklist_label}')."
                            ),
                            severity=Severity.CRITICAL,
                            evidence={"path": full_path, "sha256": digest, "label": blocklist_label},
                        )
                    )
                elif name_hit:
                    findings.append(
                        Finding(
                            check="filesystem",
                            title=f"Suspicious file name: {fname}",
                            detail=f"'{full_path}' matches a known cheat/loader naming pattern.",
                            severity=Severity.LOW,
                            evidence={"path": full_path, "sha256": digest},
                        )
                    )
            if scanned > MAX_FILES_SCANNED:
                break

    return CheckResult("filesystem", ran=True, skip_reason=None, findings=findings)
