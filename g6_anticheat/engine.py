import psutil

from . import db
from .checks import autoruns, drivers, filesystem, fivem_integrity, memory, network, processes
from .checks.base import CheckResult
from .config import GAME_PROCESS_NAMES

CHECK_MODULES = [processes, memory, drivers, autoruns, filesystem, fivem_integrity, network]

# Risk score = sum of finding severities, capped at 100.
RISK_CAP = 100


def _risk_label(score: int) -> str:
    if score == 0:
        return "Clean"
    if score < 20:
        return "Low"
    if score < 50:
        return "Suspicious"
    if score < 80:
        return "High risk"
    return "Critical"


def _game_is_running() -> bool:
    try:
        for p in psutil.process_iter(["name"]):
            if (p.info.get("name") or "").lower() in GAME_PROCESS_NAMES:
                return True
    except Exception:
        pass
    return False


def run_scan() -> dict:
    db.init_db()
    scan_id = db.create_scan()

    total_score = 0
    all_findings = []

    for module in CHECK_MODULES:
        try:
            result: CheckResult = module.run()
        except Exception as exc:  # a single check must never crash the whole scan
            result = CheckResult(name=getattr(module, "__name__", "unknown"), ran=False, skip_reason=f"crashed: {exc}")

        db.set_check_status(scan_id, result.name, result.ran, result.skip_reason)

        for finding in result.findings:
            fdict = finding.to_dict()
            db.add_finding(scan_id, fdict)
            total_score += finding.severity.value
            all_findings.append(fdict)

    risk_score = min(total_score, RISK_CAP)
    risk_label = _risk_label(risk_score)
    game_running = _game_is_running()

    db.finish_scan(scan_id, risk_score, risk_label, game_running)

    return {
        "scan_id": scan_id,
        "risk_score": risk_score,
        "risk_label": risk_label,
        "game_running": game_running,
        "findings": all_findings,
    }
