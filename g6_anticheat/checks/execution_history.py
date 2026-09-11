"""What was RUN on this PC - even if the file was deleted afterwards.

This is the check that matters most for a screenshare-style verification.
Finding a cheat sitting on disk only catches the careless; anyone who
deletes it before the scan walks away clean. Windows, however, keeps
several records of every program that has ever executed, and deleting
the file does not remove them:

  Prefetch      C:\\Windows\\Prefetch\\NAME.EXE-HASH.pf, written the first
                time a program runs. Needs admin to list.
  BAM           Background Activity Moderator, in the SYSTEM hive. Holds
                full paths with last-run timestamps. Needs admin.
  UserAssist    Programs launched through Explorer, ROT13-encoded in the
                user's own hive. No admin needed.
  MUICache      Display names of executables that have run. No admin.
  Recycle Bin   $I metadata files still name what was deleted, and when.

PRIVACY: these records list everything the person has ever run, which is
genuinely sensitive. So nothing here is ever reported wholesale - every
entry is matched against the cheat signatures first, and only matches
become findings. The scan reports how many entries it looked at, never
what they were.

NOT IMPLEMENTED: Amcache, ShimCache and the USN journal hold the same
kind of evidence but need offline hive/raw-NTFS parsing. They are listed
in the skip reasons rather than silently ignored.
"""
import os
import struct

from .. import cheats
from ..config import IS_WINDOWS
from ..profile import ScanProfile
from ..signatures import file_name_is_suspicious
from .base import CheckResult, Finding, Severity

MAX_ENTRIES = 20_000


def _match(name: str, source: str):
    """Return (family_match, generic_hit) for one executable name."""
    if not name:
        return None, False
    base = os.path.basename(name.replace("\\", "/").rstrip("/"))
    match = cheats.match_name(base, source)
    if match:
        return match, False
    return None, file_name_is_suspicious(base)


# --- individual artifact readers ---------------------------------------


def _read_prefetch():
    """Names of executables with a prefetch file. Admin required to list."""
    folder = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Prefetch")
    if not os.path.isdir(folder):
        return [], "dossier Prefetch introuvable"
    try:
        entries = []
        for fname in os.listdir(folder):
            if not fname.lower().endswith(".pf"):
                continue
            # NAME.EXE-1A2B3C4D.pf  ->  NAME.EXE
            entries.append(fname.rsplit("-", 1)[0])
        return entries, None
    except PermissionError:
        return [], "accès refusé (lancer en administrateur)"
    except OSError as exc:
        return [], str(exc)


def _read_bam():
    """Full paths of executed programs, from the BAM registry key."""
    import winreg

    roots = [
        r"SYSTEM\CurrentControlSet\Services\bam\State\UserSettings",
        r"SYSTEM\CurrentControlSet\Services\bam\UserSettings",
    ]
    entries = []
    opened = False

    for root in roots:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root) as key:
                opened = True
                i = 0
                while True:
                    try:
                        sid = winreg.EnumKey(key, i)
                        i += 1
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(key, sid) as sid_key:
                            j = 0
                            while True:
                                try:
                                    name, _, _ = winreg.EnumValue(sid_key, j)
                                    j += 1
                                except OSError:
                                    break
                                if "\\" in name:
                                    entries.append(name)
                    except OSError:
                        continue
        except PermissionError:
            return [], "accès refusé (lancer en administrateur)"
        except OSError:
            continue

    if not opened:
        return [], "clé BAM inaccessible (lancer en administrateur)"
    return entries, None


def _read_userassist():
    """Explorer-launched programs, ROT13-encoded in the user hive."""
    import codecs
    import winreg

    base = r"Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist"
    entries = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as key:
            i = 0
            while True:
                try:
                    guid = winreg.EnumKey(key, i)
                    i += 1
                except OSError:
                    break
                try:
                    with winreg.OpenKey(key, guid + r"\Count") as count_key:
                        j = 0
                        while True:
                            try:
                                name, _, _ = winreg.EnumValue(count_key, j)
                                j += 1
                            except OSError:
                                break
                            entries.append(codecs.decode(name, "rot_13"))
                except OSError:
                    continue
    except OSError as exc:
        return [], str(exc)
    return entries, None


def _read_muicache():
    import winreg

    paths = [
        r"Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\MuiCache",
        r"Software\Microsoft\Windows\ShellNoRoam\MUICache",
    ]
    entries = []
    found = False
    for path in paths:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                found = True
                i = 0
                while True:
                    try:
                        name, _, _ = winreg.EnumValue(key, i)
                        i += 1
                    except OSError:
                        break
                    if "\\" in name:
                        entries.append(name)
        except OSError:
            continue
    if not found:
        return [], "MUICache introuvable"
    return entries, None


def _read_recycle_bin():
    """Original names of deleted files, from the $I metadata records."""
    entries = []
    reached = False

    for drive in ("C:", os.environ.get("SystemDrive", "C:")):
        root = os.path.join(drive + "\\", "$Recycle.Bin")
        if not os.path.isdir(root):
            continue
        try:
            sids = os.listdir(root)
        except (PermissionError, OSError):
            continue

        for sid in sids:
            folder = os.path.join(root, sid)
            try:
                names = os.listdir(folder)
            except (PermissionError, OSError):
                continue
            reached = True
            for fname in names:
                if not fname.startswith("$I"):
                    continue
                try:
                    with open(os.path.join(folder, fname), "rb") as fh:
                        blob = fh.read(1024)
                except OSError:
                    continue
                path = _parse_recycle_record(blob)
                if path:
                    entries.append(path)
        break

    if not reached:
        return [], "corbeille inaccessible"
    return entries, None


def _parse_recycle_record(blob: bytes) -> str | None:
    """Pull the original path out of a $I record (both known layouts)."""
    if len(blob) < 32:
        return None
    try:
        version = struct.unpack("<Q", blob[0:8])[0]
        if version == 2:
            length = struct.unpack("<I", blob[24:28])[0]
            raw = blob[28:28 + length * 2]
        else:
            raw = blob[24:24 + 520]
        return raw.decode("utf-16-le", errors="ignore").split("\x00")[0] or None
    except (struct.error, UnicodeDecodeError):
        return None


SOURCES = [
    ("Prefetch", _read_prefetch, "prefetch",
     "Windows écrit un fichier Prefetch la première fois qu'un programme s'exécute. "
     "Supprimer le programme n'efface pas cette trace."),
    ("BAM", _read_bam, "BAM",
     "Le registre BAM conserve le chemin complet des programmes exécutés, "
     "avec la date de dernier lancement."),
    ("UserAssist", _read_userassist, "UserAssist",
     "Le registre garde la trace des programmes lancés depuis l'explorateur."),
    ("MUICache", _read_muicache, "MUICache",
     "Le registre conserve le nom des exécutables ayant déjà tourné."),
    ("Corbeille", _read_recycle_bin, "corbeille",
     "Les fichiers supprimés laissent un enregistrement qui nomme le fichier d'origine."),
]


def run(profile: ScanProfile) -> CheckResult:
    if not IS_WINDOWS:
        return CheckResult("execution_history", ran=False, skip_reason="Windows uniquement")

    findings: list[Finding] = []
    examined = 0
    unavailable = []
    seen = set()

    for label, reader, source_word, explanation in SOURCES:
        try:
            entries, problem = reader()
        except Exception as exc:
            entries, problem = [], str(exc)

        if problem:
            unavailable.append(f"{label} : {problem}")
            continue

        for entry in entries[:MAX_ENTRIES]:
            examined += 1
            match, generic = _match(entry, source_word)
            base = os.path.basename(entry.replace("\\", "/").rstrip("/"))

            if match:
                key = (match.family, label)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    Finding(
                        check="execution_history",
                        title=f"{match.family} a été exécuté sur ce PC ({label})",
                        detail=(
                            f"« {base} » apparaît dans {label}. {explanation} "
                            f"Ce nom correspond au cheat {match.family} ({match.kind}). "
                            "Le fichier n'est peut-être plus sur le disque, mais il a bien tourné ici."
                        ),
                        severity=Severity.CRITICAL if match.is_conclusive else Severity.HIGH,
                        evidence={
                            "cheat_family": match.family,
                            "cheat_kind": match.kind,
                            "strength": match.strength,
                            "source": label,
                            "entry": entry,
                        },
                    )
                )
            elif generic:
                key = (base.lower(), label)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    Finding(
                        check="execution_history",
                        title=f"Programme au nom suspect exécuté : {base}",
                        detail=(
                            f"« {base} » apparaît dans {label} et son nom correspond à un "
                            f"schéma de cheat (injecteur, loader, spoofer...). {explanation}"
                        ),
                        severity=Severity.MEDIUM,
                        evidence={"source": label, "entry": entry},
                    )
                )

    if examined == 0 and unavailable:
        return CheckResult("execution_history", ran=False,
                           skip_reason="; ".join(unavailable[:3]))

    findings.append(
        Finding(
            check="execution_history",
            title=f"{examined} traces d'exécution analysées",
            detail=(
                f"{examined} entrées lues dans l'historique d'exécution de Windows "
                f"(Prefetch, BAM, UserAssist, MUICache, corbeille) et comparées à la "
                f"liste des cheats connus. Seules les correspondances sont remontées : "
                f"le reste de la liste n'est ni envoyé ni enregistré."
                + (f" Sources indisponibles : {'; '.join(unavailable)}." if unavailable else "")
                + " Amcache, ShimCache et le journal USN contiennent le même type de preuve "
                "mais ne sont pas encore analysés par cet outil."
            ),
            severity=Severity.INFO,
            evidence={"entrées_analysées": examined},
        )
    )

    return CheckResult("execution_history", ran=True, skip_reason=None, findings=findings)
