"""Scan profiles.

A scan run for yourself ("local") can look at everything. A scan run by
someone else who accepted a verification link ("remote") is deliberately
narrower: it only looks at what is relevant to a FiveM cheat, and it
anonymises anything that could identify the person or their files.

Every privacy decision lives here so it can be read in one place - both
by you and by the person you send the link to.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ScanProfile:
    name: str
    redact_paths: bool
    scan_documents: bool
    include_network: bool
    include_command_lines: bool


LOCAL = ScanProfile(
    name="local",
    redact_paths=False,
    scan_documents=True,
    include_network=True,
    include_command_lines=True,
)

REMOTE = ScanProfile(
    name="remote",
    redact_paths=True,
    scan_documents=False,
    include_network=False,
    include_command_lines=False,
)

BY_NAME = {p.name: p for p in (LOCAL, REMOTE)}

# Shown verbatim to the person who opens a verification link, and printed
# by the client before it sends anything. Keep these two lists truthful:
# if you add a check that collects something else, say it here.
REMOTE_COLLECTS = [
    "Names of running processes that match known cheat/injector keywords",
    "Loaded kernel drivers matching the vulnerable-driver blocklist (BYOVD)",
    "Suspicious file names in Desktop / Downloads / Temp (names only, never contents)",
    "Files added or modified in the FiveM plugins folder",
    "Signs of code injected into the FiveM/GTA5 process (memory regions, not their contents)",
    "The operating system name and the display name typed by the person scanning",
]

REMOTE_NEVER_COLLECTS = [
    "The contents of any file, ever",
    "Documents folder, pictures, browser data, passwords, messages",
    "Windows username or computer name (paths are anonymised to %USERPROFILE%)",
    "Network connections, IP addresses, or which servers are played on",
    "Screenshots, keystrokes, webcam, microphone",
    "Anything at all outside the checks listed above",
]
