"""Base de données SQLite : schéma, accès et réglages."""

import json
import os
import secrets
import sqlite3

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'chef_prod', 'supply_chain')),
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS postes (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    token TEXT UNIQUE NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS operators (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS defects (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

-- Tout ce qui se passe sur une tablette est un événement. Les sessions
-- (présence d'une opératrice sur un poste) et les pannes sont reconstituées
-- à partir de ce journal, ce qui permet à la tablette de travailler hors
-- ligne et de tout renvoyer plus tard dans l'ordre.
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    uuid TEXT UNIQUE NOT NULL,
    poste_id INTEGER NOT NULL REFERENCES postes(id),
    operator_id INTEGER REFERENCES operators(id),
    type TEXT NOT NULL CHECK (type IN (
        'connexion', 'deconnexion', 'couette', 'panne_debut', 'panne_fin',
        'changement_of', 'qualite')),
    ts TEXT NOT NULL,            -- UTC, ISO 8601
    of_number TEXT,
    defect_id INTEGER REFERENCES defects(id),
    cancelled INTEGER NOT NULL DEFAULT 0,
    cancelled_by TEXT,
    received_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_poste_ts ON events(poste_id, ts);

-- Cadence attendue (couettes par heure) de chaque poste, avec historique :
-- une nouvelle valeur s'applique à partir de "depuis", les rendements
-- d'avant restent calculés avec l'ancienne.
CREATE TABLE IF NOT EXISTS cadences (
    id INTEGER PRIMARY KEY,
    poste_id INTEGER NOT NULL REFERENCES postes(id),
    valeur REAL NOT NULL,
    depuis TEXT NOT NULL,        -- UTC, ISO 8601
    par TEXT NOT NULL,
    saisi_le TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cadences ON cadences(poste_id, depuis);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    # Les quarts. "fin" avant "debut" = le quart passe minuit.
    # "pause" en minutes, retirée du temps de présence au prorata.
    "quarts": [
        {"nom": "Matin", "debut": "05:00", "fin": "13:00", "pause": 30},
        {"nom": "Après-midi", "debut": "13:00", "fin": "21:00", "pause": 30},
        {"nom": "Nuit", "debut": "21:00", "fin": "05:00", "pause": 30},
    ],
    # Affiche à l'opératrice le nombre de couettes faites dans son quart.
    "afficher_compteur": True,
    # Délai (secondes) pendant lequel l'opératrice peut annuler une couette
    # comptée par erreur.
    "delai_annulation": 60,
    "fuseau": "Europe/Paris",
}

DEFAULT_DEFECTS = [
    "Défaut tissage",
    "Taches",
    "Couture mammut",
    "Point sauté",
    "Défaut étiquette",
]


def db_path():
    return current_app.config["DB_PATH"]


def get_db():
    if "db" not in g:
        conn = sqlite3.connect(db_path(), timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, json.dumps(value)),
        )
    if conn.execute("SELECT COUNT(*) FROM postes").fetchone()[0] == 0:
        for i in range(1, 5):
            conn.execute(
                "INSERT INTO postes (name, token) VALUES (?, ?)",
                (f"Poste {i}", new_token()),
            )
    if conn.execute("SELECT COUNT(*) FROM defects").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO defects (label) VALUES (?)", [(d,) for d in DEFAULT_DEFECTS]
        )
    conn.commit()
    conn.close()


def new_token():
    return secrets.token_urlsafe(9)


def get_settings():
    rows = get_db().execute("SELECT key, value FROM settings").fetchall()
    settings = dict(DEFAULT_SETTINGS)
    settings.update({r["key"]: json.loads(r["value"]) for r in rows})
    return settings


def set_setting(key, value):
    db = get_db()
    db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )
    db.commit()
