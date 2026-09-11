"""Path/identity redaction used by the remote scan profile."""
import os
import re

from .profile import ScanProfile


def _home_and_user() -> tuple[str, str]:
    home = os.path.expanduser("~")
    return home, os.path.basename(home.rstrip(os.sep))


def redact_path(path: str | None, profile: ScanProfile) -> str | None:
    """Replace the user's home directory and username with placeholders."""
    if not path or not profile.redact_paths:
        return path

    home, user = _home_and_user()
    out = path

    if home and out.lower().startswith(home.lower()):
        out = "%USERPROFILE%" + out[len(home):]

    if user and len(user) >= 2:
        out = re.sub(re.escape(user), "<user>", out, flags=re.IGNORECASE)

    return out


def redact_evidence(evidence: dict, profile: ScanProfile) -> dict:
    """Redact every path-ish value in a finding's evidence dict."""
    if not profile.redact_paths:
        return evidence

    out = {}
    for key, value in evidence.items():
        if key in ("cmdline",) and not profile.include_command_lines:
            continue
        out[key] = redact_path(value, profile) if isinstance(value, str) else value
    return out
