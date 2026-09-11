"""Verification tokens that carry their own data, signed.

A free host gives you no permanent disk: the container is replaced when
the service sleeps, restarts or redeploys, and the database goes with it.
Tokens looked up in that database would die the same way - you would send
a link, the server would restart an hour later, and the link would 404
before the person ever opened it.

So the token IS the link's data, signed with the dashboard's secret key.
Validity is checked by verifying the signature, not by finding a row, and
a link keeps working across restarts.

The trade-off, stated plainly because it changes behaviour: single use is
enforced through the database, so if the database has been wiped a link
can be used again until it expires. Scan results are stored in the
database too, and are lost on a restart - which is the deal you accept
with free hosting.
"""
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SALT = "g6guard-verification-link"


def _serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt=SALT)


def make_token(secret_key: str, label: str | None, note: str | None) -> str:
    """Build a link token holding the name and note you typed."""
    return _serializer(secret_key).dumps({"l": label or "", "n": note or ""})


def read_token(secret_key: str, token: str, max_age_seconds: int) -> dict | None:
    """Return {"label", "note"} if the token is genuine and unexpired.

    None means the signature does not match (tampered, or from another
    dashboard) or the link is past its lifetime.
    """
    try:
        data = _serializer(secret_key).loads(token, max_age=max_age_seconds)
    except (BadSignature, SignatureExpired, ValueError):
        return None

    if not isinstance(data, dict):
        return None
    return {"label": data.get("l") or None, "note": data.get("n") or None}


def is_expired(secret_key: str, token: str, max_age_seconds: int) -> bool:
    """True only when the signature is valid but the link has aged out."""
    try:
        _serializer(secret_key).loads(token, max_age=max_age_seconds)
        return False
    except SignatureExpired:
        return True
    except (BadSignature, ValueError):
        return False
