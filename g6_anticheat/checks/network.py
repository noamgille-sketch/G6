"""Network connections of the game process - informational only.

We list established connections opened by the game process itself.
There is no reliable public IP blocklist for cheat C2/license servers,
so this check is purely informational: it surfaces raw-IP connections
on non-standard ports for you to eyeball, it does not accuse anything.
"""
import psutil

from ..config import GAME_PROCESS_NAMES
from ..profile import ScanProfile
from .base import CheckResult, Finding, Severity

FIVEM_KNOWN_PORTS = {30120, 30110, 40120, 443, 80}


def run(profile: ScanProfile) -> CheckResult:
    if not profile.include_network:
        return CheckResult("network", ran=False, skip_reason="disabled by privacy profile")

    findings: list[Finding] = []
    ran_any = False

    for p in psutil.process_iter(["pid", "name"]):
        name = (p.info.get("name") or "").lower()
        if name not in GAME_PROCESS_NAMES:
            continue

        try:
            conns = p.net_connections(kind="inet")
        except (psutil.AccessDenied, AttributeError):
            try:
                conns = p.connections(kind="inet")
            except Exception:
                continue
        except Exception:
            continue

        ran_any = True
        for c in conns:
            if c.status != psutil.CONN_ESTABLISHED or not c.raddr:
                continue
            port = c.raddr.port
            if port not in FIVEM_KNOWN_PORTS:
                findings.append(
                    Finding(
                        check="network",
                        title=f"Unusual outbound connection from {p.info['name']}",
                        detail=(
                            f"{p.info['name']} (pid {p.info['pid']}) has an established "
                            f"connection to {c.raddr.ip}:{port}. This is informational only "
                            "- plenty of legit FiveM servers/CDNs use non-standard ports. "
                            "Look it up if you don't recognize it."
                        ),
                        severity=Severity.INFO,
                        evidence={"pid": p.info["pid"], "remote": f"{c.raddr.ip}:{port}"},
                    )
                )

    if not ran_any:
        return CheckResult("network", ran=False, skip_reason="game not running")
    return CheckResult("network", ran=True, skip_reason=None, findings=findings)
