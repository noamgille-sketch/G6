"""Authentication for the dashboard.

Accounts live in the G6_USERS environment variable, as JSON mapping a
username to a password hash:

    G6_USERS={"noam": "pbkdf2:sha256:600000$...", "collegue": "..."}

They are deliberately NOT stored in the database or in a file in the
repo: on a hosted deployment the filesystem is often wiped on redeploy,
and a hash committed to git is a hash leaked to anyone with repo access.

Generate a hash with:  python manage.py hash-password
"""
import json
import os
import time

from werkzeug.security import check_password_hash

# Compared against when the username does not exist, so a wrong username
# and a wrong password take the same time to answer.
_DUMMY_HASH = (
    "pbkdf2:sha256:600000$dummydummydummy$"
    "0000000000000000000000000000000000000000000000000000000000000000"
)

MAX_ATTEMPTS = 8
LOCKOUT_SECONDS = 300

_attempts: dict[str, list] = {}


def load_users() -> dict[str, str]:
    raw = os.environ.get("G6_USERS", "").strip()
    if not raw:
        return {}
    try:
        users = json.loads(raw)
    except ValueError:
        return {}
    return users if isinstance(users, dict) else {}


def auth_configured() -> bool:
    return bool(load_users())


def is_locked_out(ip: str) -> int:
    """Return remaining lockout seconds, 0 if not locked out."""
    record = _attempts.get(ip)
    if not record:
        return 0
    count, first_attempt = record
    if count < MAX_ATTEMPTS:
        return 0
    elapsed = time.time() - first_attempt
    if elapsed > LOCKOUT_SECONDS:
        _attempts.pop(ip, None)
        return 0
    return int(LOCKOUT_SECONDS - elapsed)


def _record_failure(ip: str):
    count, first_attempt = _attempts.get(ip, [0, time.time()])
    if time.time() - first_attempt > LOCKOUT_SECONDS:
        count, first_attempt = 0, time.time()
    _attempts[ip] = [count + 1, first_attempt]


def verify(username: str, password: str, ip: str = "-") -> bool:
    users = load_users()
    stored = users.get(username)

    if stored is None:
        check_password_hash(_DUMMY_HASH, password)
        _record_failure(ip)
        return False

    if check_password_hash(stored, password):
        _attempts.pop(ip, None)
        return True

    _record_failure(ip)
    return False
