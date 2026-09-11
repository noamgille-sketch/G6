from dataclasses import dataclass, field
from enum import IntEnum


class Severity(IntEnum):
    INFO = 0
    LOW = 10
    MEDIUM = 30
    HIGH = 60
    CRITICAL = 100

    @property
    def label(self) -> str:
        return self.name


@dataclass
class Finding:
    check: str
    title: str
    detail: str
    severity: Severity
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "check": self.check,
            "title": self.title,
            "detail": self.detail,
            "severity": self.severity.value,
            "severity_label": self.severity.label,
            "evidence": self.evidence,
        }


@dataclass
class CheckResult:
    name: str
    ran: bool
    skip_reason: str | None
    findings: list[Finding] = field(default_factory=list)
