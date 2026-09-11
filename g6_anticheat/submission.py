"""Validation of scan reports submitted by a verification client.

Everything here arrives over the network from a machine you do not
control, so nothing in the payload is trusted: severities are recomputed
from their label, the risk score is recalculated server-side, strings are
truncated, and evidence is flattened to scalars.
"""
from .checks.base import Severity
from .engine import risk_label, score_findings

MAX_FINDINGS = 200
MAX_CHECKS = 40
MAX_TITLE = 300
MAX_DETAIL = 2000
MAX_EVIDENCE_KEYS = 20
MAX_EVIDENCE_VALUE = 500
MAX_LABEL = 80

VALID_SEVERITIES = {s.name: s.value for s in Severity}
VALID_CHECK_NAMES = {
    "processes", "memory", "drivers", "autoruns", "filesystem", "fivem_integrity", "network",
}


class InvalidSubmission(ValueError):
    pass


def _text(value, limit: int, field: str) -> str:
    if not isinstance(value, str):
        raise InvalidSubmission(f"{field} must be a string")
    return value.strip()[:limit]


def _clean_evidence(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, value in list(raw.items())[:MAX_EVIDENCE_KEYS]:
        if not isinstance(key, str):
            continue
        if isinstance(value, bool) or isinstance(value, int):
            out[key[:60]] = value
        elif isinstance(value, str):
            out[key[:60]] = value[:MAX_EVIDENCE_VALUE]
    return out


def _clean_finding(raw) -> dict:
    if not isinstance(raw, dict):
        raise InvalidSubmission("each finding must be an object")

    label = raw.get("severity_label")
    if label not in VALID_SEVERITIES:
        raise InvalidSubmission(f"unknown severity_label: {label!r}")

    check = raw.get("check")
    if check not in VALID_CHECK_NAMES:
        raise InvalidSubmission(f"unknown check: {check!r}")

    return {
        "check": check,
        "title": _text(raw.get("title"), MAX_TITLE, "title"),
        "detail": _text(raw.get("detail"), MAX_DETAIL, "detail"),
        # Recomputed from the label - a client cannot inflate its own score.
        "severity": VALID_SEVERITIES[label],
        "severity_label": label,
        "evidence": _clean_evidence(raw.get("evidence")),
    }


def _clean_check_status(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    if name not in VALID_CHECK_NAMES:
        return None
    skip_reason = raw.get("skip_reason")
    return {
        "name": name,
        "ran": bool(raw.get("ran")),
        "skip_reason": skip_reason[:200] if isinstance(skip_reason, str) else None,
    }


def clean_report(payload) -> dict:
    """Return a sanitised report, or raise InvalidSubmission."""
    if not isinstance(payload, dict):
        raise InvalidSubmission("payload must be a JSON object")

    raw_findings = payload.get("findings")
    if not isinstance(raw_findings, list):
        raise InvalidSubmission("findings must be a list")
    if len(raw_findings) > MAX_FINDINGS:
        raise InvalidSubmission(f"too many findings (max {MAX_FINDINGS})")

    findings = [_clean_finding(f) for f in raw_findings]

    raw_checks = payload.get("checks")
    checks = []
    if isinstance(raw_checks, list):
        for raw in raw_checks[:MAX_CHECKS]:
            cleaned = _clean_check_status(raw)
            if cleaned:
                checks.append(cleaned)

    score = score_findings(findings)
    client_platform = payload.get("platform")
    client_label = payload.get("client_label")

    return {
        "profile": "remote",
        "platform": _text(client_platform, 40, "platform") if isinstance(client_platform, str) else "unknown",
        "client_label": _text(client_label, MAX_LABEL, "client_label") if isinstance(client_label, str) else None,
        "game_running": bool(payload.get("game_running")),
        "risk_score": score,
        "risk_label": risk_label(score),
        "findings": findings,
        "checks": checks,
    }
