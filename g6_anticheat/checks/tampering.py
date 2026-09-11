"""Signs that someone cleaned up before the scan.

Execution history is only useful if it is intact. Anyone who knows they
are about to be screenshared can wipe Prefetch, disable the service that
writes it, or empty the Recycle Bin - and a scan that only reads those
records would come back clean.

So this check looks at the records themselves rather than their content:
are they switched off, empty, or freshly wiped on a machine that is
obviously used? None of that proves cheating on its own, but a PC whose
forensic trail was cleared minutes before a verification is a finding in
its own right - and it is exactly what a human screenshare admin looks
for first.

Nothing here reads personal data: it is service states, registry flags,
file counts and timestamps.
"""
import os
import time

from ..config import IS_WINDOWS
from ..profile import ScanProfile
from .base import CheckResult, Finding, Severity

RECENT_SECONDS = 2 * 60 * 60  # "just before the scan"
LOW_PREFETCH_COUNT = 12


def _service_state(name: str) -> str | None:
    """Start type of a service, read from the registry (no admin needed)."""
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, rf"SYSTEM\CurrentControlSet\Services\{name}"
        ) as key:
            start, _ = winreg.QueryValueEx(key, "Start")
    except OSError:
        return None
    return {0: "boot", 1: "system", 2: "automatique", 3: "manuel", 4: "désactivé"}.get(start)


def _prefetch_enabled() -> int | None:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PrefetchParameters",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "EnablePrefetcher")
            return value
    except OSError:
        return None


def _prefetch_stats():
    """(file count, newest mtime) for the Prefetch folder."""
    folder = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Prefetch")
    try:
        files = [f for f in os.listdir(folder) if f.lower().endswith(".pf")]
    except (PermissionError, OSError):
        return None, None

    newest = None
    for fname in files:
        try:
            mtime = os.path.getmtime(os.path.join(folder, fname))
        except OSError:
            continue
        if newest is None or mtime > newest:
            newest = mtime
    return len(files), newest


def _recycle_bin_recently_emptied():
    """Modification time of the Recycle Bin folder, if we can see it."""
    root = os.path.join(os.environ.get("SystemDrive", "C:") + "\\", "$Recycle.Bin")
    if not os.path.isdir(root):
        return None
    newest = None
    try:
        for sid in os.listdir(root):
            folder = os.path.join(root, sid)
            try:
                mtime = os.path.getmtime(folder)
            except OSError:
                continue
            if newest is None or mtime > newest:
                newest = mtime
    except (PermissionError, OSError):
        return None
    return newest


def _ago(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"il y a {minutes} minute(s)"
    return f"il y a {minutes // 60} heure(s)"


def run(profile: ScanProfile) -> CheckResult:
    if not IS_WINDOWS:
        return CheckResult("tampering", ran=False, skip_reason="Windows uniquement")

    findings: list[Finding] = []
    now = time.time()

    # 1. Is Windows still recording what runs?
    enabled = _prefetch_enabled()
    if enabled == 0:
        findings.append(
            Finding(
                check="tampering",
                title="L'enregistrement des programmes exécutés est désactivé",
                detail=(
                    "EnablePrefetcher est réglé sur 0 : Windows n'écrit plus de "
                    "fichiers Prefetch. C'est un réglage que personne ne change par "
                    "hasard, et il a pour effet exact d'empêcher de savoir quels "
                    "programmes ont tourné sur ce PC."
                ),
                severity=Severity.HIGH,
                evidence={"EnablePrefetcher": enabled},
            )
        )

    sysmain = _service_state("SysMain")
    if sysmain == "désactivé":
        findings.append(
            Finding(
                check="tampering",
                title="Le service SysMain (Superfetch) est désactivé",
                detail=(
                    "SysMain alimente le Prefetch. Désactivé, l'historique des "
                    "programmes exécutés cesse d'être alimenté. Certains « guides "
                    "d'optimisation » conseillent de le couper, donc ce n'est pas "
                    "une preuve en soi — mais combiné au reste, c'est notable."
                ),
                severity=Severity.MEDIUM,
                evidence={"service": "SysMain", "démarrage": sysmain},
            )
        )

    eventlog = _service_state("EventLog")
    if eventlog == "désactivé":
        findings.append(
            Finding(
                check="tampering",
                title="Le journal d'événements Windows est désactivé",
                detail=(
                    "Le service EventLog est désactivé. C'est très inhabituel sur un "
                    "PC normal et cela supprime une source majeure de traces."
                ),
                severity=Severity.HIGH,
                evidence={"service": "EventLog", "démarrage": eventlog},
            )
        )

    # 2. Is the trail there but freshly wiped?
    count, newest = _prefetch_stats()
    if count is not None:
        if count == 0:
            findings.append(
                Finding(
                    check="tampering",
                    title="Le dossier Prefetch est vide",
                    detail=(
                        "Aucun fichier Prefetch sur ce PC. Sur une machine utilisée "
                        "normalement il y en a des centaines. Un dossier vide veut dire "
                        "qu'il a été effacé, ou que l'enregistrement est coupé depuis "
                        "longtemps."
                    ),
                    severity=Severity.HIGH,
                    evidence={"fichiers_prefetch": 0},
                )
            )
        elif count < LOW_PREFETCH_COUNT:
            findings.append(
                Finding(
                    check="tampering",
                    title=f"Le dossier Prefetch ne contient que {count} fichier(s)",
                    detail=(
                        f"Seulement {count} fichiers Prefetch. Une machine utilisée "
                        "quotidiennement en accumule des centaines. Un nombre aussi bas "
                        "suggère un effacement récent — ou une installation de Windows "
                        "toute neuve."
                    ),
                    severity=Severity.MEDIUM,
                    evidence={"fichiers_prefetch": count},
                )
            )

    emptied = _recycle_bin_recently_emptied()
    if emptied and (now - emptied) < RECENT_SECONDS:
        findings.append(
            Finding(
                check="tampering",
                title="La corbeille a été vidée juste avant le scan",
                detail=(
                    f"La corbeille a été modifiée {_ago(now - emptied)}. Vider sa "
                    "corbeille est banal — le faire juste avant une vérification l'est "
                    "moins. À recouper avec le reste des résultats."
                ),
                severity=Severity.MEDIUM,
                evidence={"dernière_modification": _ago(now - emptied)},
            )
        )

    if not findings:
        findings.append(
            Finding(
                check="tampering",
                title="Aucun signe de nettoyage détecté",
                detail=(
                    "L'historique d'exécution de Windows est actif et son contenu est "
                    "cohérent avec un PC utilisé normalement. Rien n'indique qu'on ait "
                    "cherché à effacer des traces avant ce scan."
                ),
                severity=Severity.INFO,
                evidence={"fichiers_prefetch": count if count is not None else "non lisible"},
            )
        )

    return CheckResult("tampering", ran=True, skip_reason=None, findings=findings)
