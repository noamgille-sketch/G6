import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BORDAGE_DATA", str(tmp_path))
    from app import create_app
    app = create_app()
    c = app.test_client()
    with c.session_transaction() as s:
        s["csrf"] = "x"
    c.post("/installation", data={"csrf": "x", "username": "admin", "password": "secret1"})
    c.post("/connexion", data={"csrf": "x", "username": "admin", "password": "secret1"})
    with c.session_transaction() as s:
        s["csrf"] = "x"
    c.post("/admin/operatrices", data={"csrf": "x", "action": "ajouter", "texte": "Julie"})
    c.app = app
    return c


def code_poste(client):
    import sqlite3
    db = sqlite3.connect(client.app.config["DB_PATH"])
    return db.execute("SELECT token FROM postes ORDER BY id LIMIT 1").fetchone()[0]


def test_parcours_tablette(client):
    code = code_poste(client)
    etat = client.get(f"/api/t/{code}/etat").get_json()
    op = etat["operatrices"][0]["id"]
    now = datetime.now(timezone.utc)
    ts = lambda s: (now - timedelta(seconds=s)).isoformat()
    events = [
        {"uuid": "a1", "type": "connexion", "ts": ts(600), "operator_id": op},
        {"uuid": "a2", "type": "changement_of", "ts": ts(590), "operator_id": op, "of": "of 123456"},
        {"uuid": "a3", "type": "couette", "ts": ts(500), "operator_id": op},
        {"uuid": "a4", "type": "couette", "ts": ts(400), "operator_id": op},
        {"uuid": "a5", "type": "annulation", "ts": ts(390), "operator_id": op, "ref": "a4"},
        {"uuid": "a6", "type": "qualite", "ts": ts(300), "operator_id": op, "defect_id": etat["defauts"][0]["id"], "decision": "rebut"},
        {"uuid": "a7", "type": "panne_debut", "ts": ts(200), "operator_id": op},
    ]
    r = client.post(f"/api/t/{code}/events", json={"envoye_a": now.isoformat(), "events": events}).get_json()
    assert len(r["acceptes"]) == 7
    # Renvoi après coupure : pas de doublon.
    client.post(f"/api/t/{code}/events", json={"envoye_a": now.isoformat(), "events": events})

    etat = client.get(f"/api/t/{code}/etat").get_json()
    # 1 couette (l'autre annulée) + 1 couette déclarée en défaut
    assert etat["of"] == "OF123456" and etat["panne"] is not None and etat["compteur"] == 2
    if etat["quart"]:
        assert etat["session"]["operator_id"] == op

    d = client.get("/api/tableau?periode=jour").get_json()
    assert d["total"]["couettes"] == 2 and d["total"]["premier_choix"] == 1
    assert d["total"]["defauts"] == 1 and d["total"]["rebut"] == 1 and d["defauts"][0]["rebut"] == 1
    assert d["of"][0]["of"] == "OF123456"
    assert client.get("/api/direct").status_code == 200
    assert client.get("/export.csv?periode=jour").status_code == 200
    assert client.get("/journal").status_code == 200


def test_horloge_tablette_corrigee(client):
    code = code_poste(client)
    op = client.get(f"/api/t/{code}/etat").get_json()["operatrices"][0]["id"]
    faux = datetime.now(timezone.utc) - timedelta(hours=3)  # tablette en retard de 3 h
    client.post(f"/api/t/{code}/events", json={"envoye_a": faux.isoformat(), "events": [
        {"uuid": "b1", "type": "couette", "ts": (faux - timedelta(minutes=1)).isoformat(), "operator_id": op}]})
    import sqlite3
    ts = sqlite3.connect(client.app.config["DB_PATH"]).execute("SELECT ts FROM events WHERE uuid='b1'").fetchone()[0]
    ecart = datetime.now(timezone.utc) - datetime.fromisoformat(ts)
    assert timedelta(seconds=30) < ecart < timedelta(minutes=2)


def test_roles(client):
    client.post("/admin/comptes", data={"csrf": "x", "action": "ajouter", "username": "sc",
                                        "password": "secret2", "role": "supply_chain"})
    client.post("/deconnexion", data={"csrf": "x"})
    with client.session_transaction() as s:
        s["csrf"] = "x"
    client.post("/connexion", data={"csrf": "x", "username": "sc", "password": "secret2"})
    assert client.get("/").status_code == 200
    assert client.get("/admin/reglages").status_code == 403
    assert client.get("/admin/operatrices").status_code == 403


def test_tablette_code_invalide(client):
    assert client.get("/t/nimporte").status_code == 404
    assert client.get("/api/t/nimporte/etat").status_code == 404


def test_cadences(client):
    code = code_poste(client)
    d = client.get("/api/tableau?periode=jour").get_json()
    assert len(d["sans_cadence"]) == 4
    import sqlite3
    pid = sqlite3.connect(client.app.config["DB_PATH"]).execute("SELECT id FROM postes WHERE token=?", (code,)).fetchone()[0]
    from datetime import date
    r = client.post("/cadences", data={"csrf": "x", "poste": pid, "valeur": "12,5", "depuis": (date.today() - timedelta(days=1)).isoformat()})
    assert r.status_code == 302
    assert len(client.get("/api/tableau?periode=jour").get_json()["sans_cadence"]) == 3
    assert "12,5" in client.get("/cadences").get_data(as_text=True)
