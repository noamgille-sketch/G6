"""Remplit une base de démonstration avec 2 semaines de fausse production.

    set BORDAGE_DATA=demo-data      (Windows)   /  export BORDAGE_DATA=demo-data
    python demo.py
    python run.py

Compte créé : admin / demo123. Ne lance pas ce script sur la vraie base.
"""

import os
import random
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from werkzeug.security import generate_password_hash

from app import create_app

if not os.environ.get("BORDAGE_DATA"):
    sys.exit("Définis BORDAGE_DATA vers un dossier de démo, pour ne pas toucher la vraie base.")

app = create_app()
db = sqlite3.connect(app.config["DB_PATH"])
if db.execute("SELECT COUNT(*) FROM events").fetchone()[0]:
    sys.exit("La base de démo contient déjà des données.")

tz = ZoneInfo("Europe/Paris")
random.seed(4)
db.execute("INSERT OR IGNORE INTO users (username, display_name, password_hash, role) VALUES ('admin', 'Admin démo', ?, 'admin')",
           (generate_password_hash("demo123"),))
noms = ["Amandine", "Brigitte", "Chloé", "Delphine", "Émilie", "Fatima", "Gaëlle", "Hélène",
        "Inès", "Josiane", "Karima", "Laura"]
for n in noms:
    db.execute("INSERT INTO operators (name) VALUES (?)", (n,))
ops = [r[0] for r in db.execute("SELECT id FROM operators ORDER BY id")]
postes = [r[0] for r in db.execute("SELECT id FROM postes ORDER BY id")]
defauts = [r[0] for r in db.execute("SELECT id FROM defects ORDER BY id")]
equipes = {"Matin": ops[0:4], "Après-midi": ops[4:8], "Nuit": ops[8:12]}
talent = {o: random.uniform(0.75, 1.1) for o in ops}
quarts = [("Matin", 5, 8), ("Après-midi", 13, 8), ("Nuit", 21, 8)]
now = datetime.now(timezone.utc)
rows = []


def add(poste, op, type_, ts, of=None, defect=None):
    if ts <= now:
        rows.append((str(uuid.uuid4()), poste, op, type_, ts.astimezone(timezone.utc).isoformat(timespec="milliseconds"),
                     of, defect, now.isoformat()))


debut = (now.astimezone(tz) - timedelta(days=14)).date()
of_num = 240100
for j in range(15):
    jour = debut + timedelta(days=j)
    if jour.weekday() >= 5:
        continue
    for nom, h, duree in quarts:
        d0 = datetime(jour.year, jour.month, jour.day, h, tzinfo=tz)
        for poste, op in zip(postes, equipes[nom]):
            t = d0 + timedelta(minutes=random.randint(0, 8))
            fin = d0 + timedelta(hours=duree) - timedelta(minutes=random.randint(0, 10))
            add(poste, op, "connexion", t)
            of_num += 1
            add(poste, op, "changement_of", t + timedelta(minutes=1), of=f"OF{of_num}")
            cycle = 3600 / (12 * talent[op])
            while t < fin:
                t += timedelta(seconds=random.gauss(cycle, cycle * 0.15))
                if random.random() < 0.01:
                    add(poste, op, "panne_debut", t)
                    t += timedelta(minutes=random.randint(5, 40))
                    add(poste, op, "panne_fin", t)
                if random.random() < 0.05:
                    add(poste, op, "qualite", t, defect=random.choice(defauts[:5] + defauts[:2]))
                if random.random() < 0.004:
                    of_num += 1
                    add(poste, op, "changement_of", t, of=f"OF{of_num}")
                if t < fin:
                    add(poste, op, "couette", t)
            add(poste, op, "deconnexion", fin)

for p in postes:
    db.execute("INSERT INTO cadences (poste_id, valeur, depuis, par, saisi_le) VALUES (?, 12, ?, 'démo', ?)",
               (p, (now - timedelta(days=20)).isoformat(), now.isoformat()))
db.executemany("INSERT INTO events (uuid, poste_id, operator_id, type, ts, of_number, defect_id, received_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
db.commit()
print(f"{len(rows)} événements créés. Connexion : admin / demo123")
