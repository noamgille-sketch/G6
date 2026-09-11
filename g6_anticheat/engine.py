import platform

import psutil

from . import db, profile as profiles
from .checks import autoruns, drivers, filesystem, fivem_integrity, memory, network, processes
from .checks.base import CheckResult
from .config import GAME_PROCESS_NAMES
from .privacy import redact_evidence, redact_path

CHECK_MODULES = [processes, memory, drivers, autoruns, filesystem, fivem_integrity, network]

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

    return {
        "profile": profile.name,
        "platform": platform.system() or "unknown",
        "game_running": _game_is_running(),
        "risk_score": score,
        "risk_label": risk_label(score),
        "findings": findings,
        "checks": statuses,
    }


def persist_report(report: dict, source: str = "local", client_label: str | None = None) -> int:
    """Write a report into the database and return the new scan id."""
    db.init_db()
    scan_id = db.create_scan(source=source, client_label=client_label)

    for status in report["checks"]:
        db.set_check_status(scan_id, status["name"], status["ran"], status["skip_reason"])

    for finding in report["findings"]:
        db.add_finding(scan_id, finding)

    db.finish_scan(scan_id, report["risk_score"], report["risk_label"], report["game_running"])
    return scan_id


def run_scan() -> dict:
    """Full local scan: run every check and store the result."""
    report = build_report("local")
    report["scan_id"] = persist_report(report, source="local")
    return report
