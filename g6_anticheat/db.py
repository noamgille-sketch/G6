import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    risk_score INTEGER,
    risk_label TEXT,
    game_running INTEGER DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'local',
    client_label TEXT
);

CREATE TABLE IF NOT EXISTS verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL UNIQUE,
    label TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    submitted_at TEXT,
    client_label TEXT,
    client_platform TEXT,
    scan_id INTEGER REFERENCES scans(id)
);

CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    "check" TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    severity INTEGER NOT NULL,
    severity_label TEXT NOT NULL,
    evidence TEXT
);

CREATE TABLE IF NOT EXISTS check_status (
    scan_id INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    ran INTEGER NOT NULL,
    skip_reason TEXT,
    PRIMARY KEY (scan_id, name)
);

CREATE TABLE IF NOT EXISTS file_baseline (
    path TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(scans)")}
        for column, ddl in (("source", "TEXT NOT NULL DEFAULT 'local'"), ("client_label", "TEXT")):
            if column not in existing:
                conn.execute(f"ALTER TABLE scans ADD COLUMN {column} {ddl}")


def create_scan(source: str = "local", client_label: str | None = None) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO scans (started_at, source, client_label) VALUES (?, ?, ?)",
            (_now(), source, client_label),
        )
        return cur.lastrowid


def finish_scan(scan_id: int, risk_score: int, risk_label: str, game_running: bool):
    with get_connection() as conn:
        conn.execute(
            "UPDATE scans SET finished_at = ?, risk_score = ?, risk_label = ?, game_running = ? WHERE id = ?",
            (_now(), risk_score, risk_label, int(game_running), scan_id),
        )


def add_finding(scan_id: int, finding_dict: dict):
    with get_connection() as conn:
        conn.execute(
            'INSERT INTO findings (scan_id, "check", title, detail, severity, severity_label, evidence) '
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                scan_id,
                finding_dict["check"],
                finding_dict["title"],
                finding_dict["detail"],
                finding_dict["severity"],
                finding_dict["severity_label"],
                json.dumps(finding_dict.get("evidence") or {}),
            ),
        )


def set_check_status(scan_id: int, name: str, ran: bool, skip_reason: str | None):
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO check_status (scan_id, name, ran, skip_reason) VALUES (?, ?, ?, ?)",
            (scan_id, name, int(ran), skip_reason),
        )


def list_scans(limit: int = 50):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM scans ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_scan(scan_id: int):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
        return dict(row) if row else None


def get_findings(scan_id: int):
    with get_connection() as conn:
        rows = conn.execute(
            'SELECT * FROM findings WHERE scan_id = ? ORDER BY severity DESC, id ASC', (scan_id,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["evidence"] = json.loads(d["evidence"] or "{}")
            out.append(d)
        return out


def get_check_statuses(scan_id: int):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM check_status WHERE scan_id = ?", (scan_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def create_verification(token: str, label: str | None, note: str | None, expires_at: str | None) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO verifications (token, label, note, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (token, label, note, _now(), expires_at),
        )
        return cur.lastrowid


def list_verifications(limit: int = 50):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM verifications ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_verification_by_token(token: str):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM verifications WHERE token = ?", (token,)).fetchone()
        return dict(row) if row else None


def get_verification(verification_id: int):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM verifications WHERE id = ?", (verification_id,)).fetchone()
        return dict(row) if row else None


def complete_verification(token: str, scan_id: int, client_label: str | None, client_platform: str | None):
    with get_connection() as conn:
        conn.execute(
            "UPDATE verifications SET status = 'completed', submitted_at = ?, scan_id = ?, "
            "client_label = ?, client_platform = ? WHERE token = ?",
            (_now(), scan_id, client_label, client_platform, token),
        )


def revoke_verification(verification_id: int):
    with get_connection() as conn:
        conn.execute(
            "UPDATE verifications SET status = 'revoked' WHERE id = ? AND status = 'pending'",
            (verification_id,),
        )


def baseline_count() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM file_baseline").fetchone()
        return row["c"] if row else 0


def get_baseline_hash(path: str) -> str | None:
    with get_connection() as conn:
        row = conn.execute("SELECT sha256 FROM file_baseline WHERE path = ?", (path,)).fetchone()
        return row["sha256"] if row else None


def upsert_baseline(path: str, sha256: str):
    now = _now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO file_baseline (path, sha256, first_seen, last_seen)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET sha256 = excluded.sha256, last_seen = excluded.last_seen
            """,
            (path, sha256, now, now),
        )
