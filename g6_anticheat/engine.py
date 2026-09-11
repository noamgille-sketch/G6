import platform

import psutil

from . import db, hwid, profile as profiles
from .checks import (
    autoruns, cheat_scan, drivers, execution_history, filesystem, fivem_integrity,
    memory, network, processes, tampering,
)
from .checks.base import CheckResult, Severity
from .config import GAME_PROCESS_NAMES
from .privacy import redact_evidence, redact_path

CHECK_MODULES = [
    cheat_scan, execution_history, tampering, memory, drivers, fivem_integrity,
    processes, filesystem, autoruns, network,
]

# Final verdict shown at the top of the dashboard.
VERDICT_CHEAT = "CHEAT DETECTE"
VERDICT_SUSPECT = "SUSPECT"
VERDICT_CLEAN = "LEGIT"

# Risk score = sum of finding severities, capped at 100.
RISK_CAP = 100


def risk_label(score: int) -> str:
    if score == 0:
        return "Clean"
    if score < 20:
        return "Low"
    if score < 50:
        return "Suspicious"
    if score < 80:
        return "High risk"
    return "Critical"


def score_findings(findings: list[dict]) -> int:
    return min(sum(f["severity"] for f in findings), RISK_CAP)


def detected_cheats(findings: list[dict]) -> list[str]:
    """Names of the cheat families identified, strongest evidence first."""
    by_family: dict[str, str] = {}
    for f in findings:
        family = f.get("evidence", {}).get("cheat_family")
        if not family:
            continue
        strength = f["evidence"].get("strength", "MODERATE")
        rank = {"CONFIRMED": 0, "STRONG": 1, "MODERATE": 2}
        if family not in by_family or rank.get(strength, 3) < rank.get(by_family[family], 3):
            by_family[family] = strength

    order = {"CONFIRMED": 0, "STRONG": 1, "MODERATE": 2}
    return sorted(by_family, key=lambda f: (order.get(by_family[f], 3), f))


def verdict_for(findings: list[dict]) -> tuple[str, str]:
    """Return (verdict, explanation) - the plain-language answer."""
    families = detected_cheats(findings)
    conclusive = [
        f for f in findings
        if f.get("evidence", {}).get("strength") in ("CONFIRMED", "STRONG")
    ]

    if families and conclusive:
        names = ", ".join(families)
        return VERDICT_CHEAT, f"Cheat identifié sur cette machine : {names}."

    if families:
        names = ", ".join(families)
        return VERDICT_SUSPECT, (
            f"Des noms correspondant à {names} ont été trouvés, mais ils sont trop "
            "communs pour être une preuve. À vérifier manuellement."
        )

    if any(f["severity"] >= Severity.HIGH for f in findings):
        return VERDICT_SUSPECT, (
            "Aucun cheat connu identifié par son nom, mais des comportements typiques "
            "d'un cheat ont été détectés (code injecté, driver vulnérable...). "
            "Un cheat renommé ou privé donne exactement ce résultat."
        )

    if findings:
        return VERDICT_CLEAN, (
            "Aucun cheat connu trouvé. Quelques éléments mineurs à regarder, "
            "rien qui ressemble à un cheat."
        )

    return VERDICT_CLEAN, (
        "Aucun cheat connu trouvé et aucun comportement suspect. "
        "Attention : cela ne prouve pas l'absence totale de cheat - un cheat "
        "kernel-mode bien fait peut rester invisible pour ce type de scan."
    )


def _game_is_running() -> bool:
    try:
        for p in psutil.process_iter(["name"]):
            if (p.info.get("name") or "").lower() in GAME_PROCESS_NAMES:
                return True
    except Exception:
        pass
    return False


def collect_findings(profile: profiles.ScanProfile) -> tuple[list[dict], list[dict]]:
    """Run every check and return (findings, check statuses) as plain dicts.

    Redaction is applied here, centrally, so no individual check can leak a
    path by forgetting to call the helper.
    """
    findings: list[dict] = []
    statuses: list[dict] = []

    for module in CHECK_MODULES:
        try:
            result: CheckResult = module.run(profile)
        except Exception as exc:  # a single check must never crash the whole scan
            result = CheckResult(
                name=getattr(module, "__name__", "unknown").rsplit(".", 1)[-1],
                ran=False,
                skip_reason=f"crashed: {exc}",
            )

        statuses.append({"name": result.name, "ran": result.ran, "skip_reason": result.skip_reason})

        for finding in result.findings:
            fdict = finding.to_dict()
            fdict["title"] = redact_path(fdict["title"], profile)
            fdict["detail"] = redact_path(fdict["detail"], profile)
            fdict["evidence"] = redact_evidence(fdict["evidence"], profile)
            findings.append(fdict)

    return findings, statuses


def build_report(profile_name: str = "local") -> dict:
    """Run a scan and return the report without touching the database.

    This is what the verification client sends back: it never writes to the
    local dashboard database, it just produces the payload.
    """
    profile = profiles.BY_NAME[profile_name]
    findings, statuses = collect_findings(profile)
    score = score_findings(findings)
    verdict, explanation = verdict_for(findings)

    return {
        "profile": profile.name,
        "platform": platform.system() or "unknown",
        "machine_id": hwid.fingerprint(),
        "game_running": _game_is_running(),
        "risk_score": score,
        "risk_label": risk_label(score),
        "verdict": verdict,
        "verdict_detail": explanation,
        "detected_cheats": detected_cheats(findings),
        "findings": findings,
        "checks": statuses,
    }


def persist_report(report: dict, source: str = "local", client_label: str | None = None) -> int:
    """Write a report into the database and return the new scan id."""
    db.init_db()
    scan_id = db.create_scan(source=source, client_label=client_label,
                             machine_id=report.get("machine_id"))

    for status in report["checks"]:
        db.set_check_status(scan_id, status["name"], status["ran"], status["skip_reason"])

    for finding in report["findings"]:
        db.add_finding(scan_id, finding)

    db.finish_scan(
        scan_id,
        report["risk_score"],
        report["risk_label"],
        report["game_running"],
        verdict=report["verdict"],
        verdict_detail=report["verdict_detail"],
        detected_cheats=report["detected_cheats"],
    )
    return scan_id


def run_scan() -> dict:
    """Full local scan: run every check and store the result."""
    report = build_report("local")
    report["scan_id"] = persist_report(report, source="local")
    return report
