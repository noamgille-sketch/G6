import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stats  # noqa: E402

TZ = ZoneInfo("Europe/Paris")
QUARTS = [
    {"nom": "Matin", "debut": "05:00", "fin": "13:00", "pause": 0},
    {"nom": "Après-midi", "debut": "13:00", "fin": "21:00", "pause": 0},
    {"nom": "Nuit", "debut": "21:00", "fin": "05:00", "pause": 0},
]


def t(h, m=0, jour=5):
    return datetime(2026, 11, jour, h, m, tzinfo=TZ)


def ev(type_, ts, op=1, poste=1, **kw):
    return {"type": type_, "ts": ts.astimezone(timezone.utc), "operator_id": op, "poste_id": poste, **kw}


def test_quart_de_nuit_appartient_au_jour_de_debut():
    q = stats.quart_de(t(2), QUARTS, TZ)
    assert q.nom == "Nuit" and q.jour.isoformat() == "2026-11-04"
    assert stats.quart_de(t(5), QUARTS, TZ).nom == "Matin"


def test_rendement_simple():
    # 2 h de présence, 1 panne de 30 min, cadence 10/h -> 15 attendues, 12 faites.
    evs = [ev("connexion", t(6))]
    evs += [ev("couette", t(6, 5 * i + 1)) for i in range(12)]
    evs += [ev("panne_debut", t(7)), ev("panne_fin", t(7, 30)), ev("deconnexion", t(8))]
    lignes = stats.calculer(evs, t(5), t(13), QUARTS, TZ, {1: 10}, 12, maintenant=t(14))
    assert len(lignes) == 1
    l = lignes[0]
    assert l.presence_s == 7200 and l.panne_s == 1800 and l.nb_pannes == 1
    assert l.couettes == 12
    assert round(l.attendu, 3) == 15
    assert round(l.rendement, 1) == 80.0
    assert round(l.disponibilite, 1) == 75.0


def test_pause_au_prorata():
    q = [dict(x, pause=40) for x in QUARTS]
    evs = [ev("connexion", t(5)), ev("deconnexion", t(9))]  # moitié du quart
    l = stats.calculer(evs, t(5), t(13), q, TZ, {}, 12, maintenant=t(14))[0]
    assert l.pause_s == 20 * 60


def test_session_oubliee_coupee_en_fin_de_quart():
    evs = [ev("connexion", t(10)), ev("couette", t(10, 30))]
    lignes = stats.calculer(evs, t(5), t(5, jour=6), QUARTS, TZ, {}, 12, maintenant=t(20))
    assert len(lignes) == 1
    assert lignes[0].presence_s == 3 * 3600  # 10h -> 13h, pas jusqu'à 20h


def test_panne_oubliee_coupee_en_fin_de_quart():
    evs = [ev("connexion", t(12)), ev("panne_debut", t(12)), ev("connexion", t(13), op=2)]
    sessions, pannes = stats.reconstituer(evs, QUARTS, TZ, t(18))
    assert pannes[0].fin == t(13)


def test_changement_operatrice_ferme_la_session():
    evs = [ev("connexion", t(6), op=1), ev("connexion", t(8), op=2), ev("deconnexion", t(9), op=2)]
    lignes = stats.calculer(evs, t(5), t(13), QUARTS, TZ, {}, 12, maintenant=t(14))
    par_op = {l.operator_id: l.presence_s for l in lignes}
    assert par_op == {1: 7200, 2: 3600}


def test_session_a_cheval_sur_deux_quarts_et_couettes_annulees():
    evs = [ev("connexion", t(12)), ev("couette", t(12, 30)), ev("couette", t(13, 30)),
           ev("couette", t(13, 40), cancelled=1), ev("connexion", t(13, 5), op=1), ev("deconnexion", t(14))]
    lignes = stats.calculer(evs, t(5), t(21), QUARTS, TZ, {}, 12, maintenant=t(22))
    par_quart = {l.quart: (l.presence_s, l.couettes) for l in lignes}
    assert par_quart["Matin"] == (3600, 1)
    assert par_quart["Après-midi"] == (55 * 60, 1)


def test_panne_annulee_ignoree():
    evs = [ev("connexion", t(6)), ev("panne_debut", t(7), cancelled=1), ev("deconnexion", t(8))]
    l = stats.calculer(evs, t(5), t(13), QUARTS, TZ, {}, 12, maintenant=t(14))[0]
    assert l.panne_s == 0


def test_session_en_cours():
    evs = [ev("connexion", t(6))]
    sessions, _ = stats.reconstituer(evs, QUARTS, TZ, t(7))
    assert sessions[0].ouvert and sessions[0].fin == t(7)


def test_pas_de_pourcentage_sur_un_temps_trop_court():
    evs = [ev("connexion", t(6)), ev("couette", t(6, 0)), ev("deconnexion", t(6, 1))]
    l = stats.calculer(evs, t(5), t(13), QUARTS, TZ, {}, 12, maintenant=t(14))[0]
    assert l.couettes == 1 and l.rendement is None
