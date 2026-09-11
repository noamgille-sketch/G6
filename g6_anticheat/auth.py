"""Authentication for the dashboard.

Accounts come from an environment variable, never from the database or a
file in the repo: a hosted filesystem is usually wiped on redeploy, and a
credential committed to git is a credential leaked to anyone with repo
access.

Two forms, both accepted:

    G6_ACCOUNTS=noam:motdepasse,collegue:autremotdepasse
        Simple. Passwords are hashed when the app starts, but they sit in
        plain text in the host's environment settings - so use a password
        you don't use anywhere else.

    G6_USERS={"noam": "pbkdf2:sha256:600000$...", ...}
        Better. Only the hash ever leaves your machine. Needs Python once,
        to run:  python manage.py hash-password

G6_USERS wins when both are set.
"""
import json
import os
import time

from werkzeug.security import check_password_hash, generate_password_hash

# Compared against when the username does not exist, so a wrong username
# and a wrong password take the same time to answer.
_DUMMY_HASH = (
    "pbkdf2:sha256:600000$dummydummydummy$"
    "0000000000000000000000000000000000000000000000000000000000000000"
)

MAX_ATTEMPTS = 8
LOCKOUT_SECONDS = 300

_attempts: dict[str, list] = {}


_accounts_cache: dict[str, str] = {}
_accounts_source: str | None = None


def _parse_plain_accounts(raw: str) -> dict[str, str]:
    """user:password,user2:password2 -> {user: hash}. Hashed once at startup."""
    global _accounts_cache, _accounts_source

    if _accounts_source == raw:
        return _accounts_cache

    users = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        name, password = pair.split(":", 1)
        name, password = name.strip(), password.strip()
        if name and password:
            users[name] = generate_password_hash(password)

    _accounts_cache = users
    _accounts_source = raw
    return users


def load_users() -> dict[str, str]:
    raw = os.environ.get("G6_USERS", "").strip()
    if raw:
        try:
            users = json.loads(raw)
        except ValueError:
            return {}
        return users if isinstance(users, dict) else {}

    plain = os.environ.get("G6_ACCOUNTS", "").strip()
    if plain:
        return _parse_plain_accounts(plain)

    return {}


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
