"""Suivi de production des postes de bordage.

* /t/<code>   : écran tablette d'un poste (pas de mot de passe, le lien suffit)
* /           : tableau de bord (chef de prod, supply chain, admin)
* /admin/...  : opératrices, postes, défauts, comptes, réglages
"""

import csv
import io
import os
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from zoneinfo import ZoneInfo

from flask import (Flask, Response, abort, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import stats
from db import close_db, get_db, get_settings, init_db, new_token, set_setting

ICI = os.path.dirname(os.path.abspath(__file__))

ROLES = {
    "admin": "Administrateur",
    "chef_prod": "Chef de production",
    "supply_chain": "Supply chain",
}
TYPES_EVENEMENT = {"connexion", "deconnexion", "couette", "panne_debut",
                   "panne_fin", "changement_of", "qualite"}
LIBELLES_TYPE = {
    "connexion": "Arrivée sur le poste",
    "deconnexion": "Départ du poste",
    "couette": "Couette terminée",
    "panne_debut": "Début de panne",
    "panne_fin": "Fin de panne",
    "changement_of": "Changement d'OF",
    "qualite": "Problème qualité",
}


def normaliser_of(texte):
    """Les OF s'écrivent « OF » suivi de chiffres : OF123456."""
    t = "".join(str(texte or "").split()).upper()
    if t.startswith("OF"):
        t = t[2:]
    t = t.lstrip("-_:")
    return ("OF" + t)[:40] if t else None


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def parse_ts(text):
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _secret_key(data_dir):
    path = os.path.join(data_dir, "secret.key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


def create_app(db_path=None):
    app = Flask(__name__)
    data_dir = os.environ.get("BORDAGE_DATA", os.path.join(ICI, "data"))
    os.makedirs(data_dir, exist_ok=True)
    app.config["DB_PATH"] = db_path or os.path.join(data_dir, "bordage.sqlite3")
    app.config["SECRET_KEY"] = os.environ.get("BORDAGE_SECRET") or _secret_key(data_dir)
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
    init_db(app.config["DB_PATH"])
    app.teardown_appcontext(close_db)

    # ------------------------------------------------------------------
    # Utilitaires communs
    # ------------------------------------------------------------------

    def tz():
        return ZoneInfo(get_settings().get("fuseau", "Europe/Paris"))

    @app.template_filter("duree")
    def duree(secondes):
        if secondes is None:
            return "—"
        m = int(round(secondes / 60))
        return f"{m // 60} h {m % 60:02d}" if m >= 60 else f"{m} min"

    @app.template_filter("heure_locale")
    def heure_locale(text):
        return parse_ts(text).astimezone(tz()).strftime("%d/%m/%Y %H:%M:%S")

    @app.template_filter("jour_local")
    def jour_local(text):
        return parse_ts(text).astimezone(tz()).strftime("%d/%m/%Y")

    @app.context_processor
    def contexte():
        return {"user": g.get("user"), "ROLES": ROLES, "csrf_token": csrf_token}

    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        return session["csrf"]

    @app.before_request
    def charger_utilisateur():
        g.user = None
        uid = session.get("uid")
        if uid:
            g.user = get_db().execute(
                "SELECT * FROM users WHERE id = ? AND active = 1", (uid,)
            ).fetchone()
        # Les formulaires du site sont protégés par un jeton. L'API des
        # tablettes, elle, n'utilise pas de cookie : le code du poste suffit.
        if request.method == "POST" and not request.path.startswith("/api/t/"):
            if request.form.get("csrf") != session.get("csrf"):
                abort(400, "Formulaire expiré, recharge la page.")

    def connecte(*roles):
        def deco(fn):
            @wraps(fn)
            def wrapper(*a, **kw):
                if g.user is None:
                    if _aucun_compte():
                        return redirect(url_for("installation"))
                    return redirect(url_for("connexion", suite=request.path))
                if roles and g.user["role"] not in roles:
                    abort(403)
                return fn(*a, **kw)
            return wrapper
        return deco

    def _aucun_compte():
        return get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0

    def postes(actifs=True):
        q = "SELECT * FROM postes" + (" WHERE active = 1" if actifs else "") + " ORDER BY id"
        return get_db().execute(q).fetchall()

    def operatrices(actives=False):
        q = "SELECT * FROM operators" + (" WHERE active = 1" if actives else "") + " ORDER BY name COLLATE NOCASE"
        return get_db().execute(q).fetchall()

    def defauts(actifs=False):
        q = "SELECT * FROM defects" + (" WHERE active = 1" if actifs else "") + " ORDER BY id"
        return get_db().execute(q).fetchall()

    def charger_events(debut, fin, poste_id=None):
        """Événements de la période, plus un jour avant pour retrouver les
        sessions et pannes déjà en cours au début."""
        sql = "SELECT * FROM events WHERE ts >= ? AND ts < ?"
        args = [iso(debut - timedelta(days=1)), iso(fin)]
        if poste_id:
            sql += " AND poste_id = ?"
            args.append(poste_id)
        rows = get_db().execute(sql + " ORDER BY ts", args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["ts"] = parse_ts(d["ts"])
            out.append(d)
        return out

    def calcul(debut, fin, poste_id=None):
        s = get_settings()
        evs = charger_events(debut, fin, poste_id)
        lignes = stats.calculer(evs, debut, fin, s["quarts"], tz(), cadence_en_vigueur(), utcnow())
        return evs, lignes

    def cadence_en_vigueur():
        """Fonction (poste, instant) -> cadence valable à cet instant."""
        hist = {}
        for r in get_db().execute("SELECT poste_id, valeur, depuis FROM cadences ORDER BY depuis, id"):
            hist.setdefault(r["poste_id"], []).append((parse_ts(r["depuis"]), r["valeur"]))

        def cadence(poste_id, instant):
            valeur = None
            for depuis, v in hist.get(poste_id, []):
                if depuis > instant:
                    break
                valeur = v
            return valeur
        return cadence

    def heure_debut_journee():
        """Une journée de production commence au début du premier quart."""
        qs = get_settings()["quarts"]
        return min(stats._hm(q["debut"]) for q in qs) if qs else stats.time(0, 0)

    def debut_journee(d):
        return datetime.combine(d, heure_debut_journee(), tzinfo=tz())

    def journee_actuelle():
        h0 = heure_debut_journee()
        return (utcnow().astimezone(tz()) - timedelta(hours=h0.hour, minutes=h0.minute)).date()

    # ------------------------------------------------------------------
    # Comptes
    # ------------------------------------------------------------------

    @app.route("/installation", methods=["GET", "POST"])
    def installation():
        if not _aucun_compte():
            return redirect(url_for("connexion"))
        if request.method == "POST":
            nom = request.form.get("username", "").strip().lower()
            mdp = request.form.get("password", "")
            if not nom or len(mdp) < 6:
                flash("Identifiant obligatoire et mot de passe d'au moins 6 caractères.", "erreur")
            else:
                db = get_db()
                db.execute(
                    "INSERT INTO users (username, display_name, password_hash, role) VALUES (?, ?, ?, 'admin')",
                    (nom, request.form.get("display_name", "").strip() or nom,
                     generate_password_hash(mdp)),
                )
                db.commit()
                flash("Compte administrateur créé. Connecte-toi.", "ok")
                return redirect(url_for("connexion"))
        return render_template("installation.html")

    @app.route("/connexion", methods=["GET", "POST"])
    def connexion():
        if _aucun_compte():
            return redirect(url_for("installation"))
        if g.user is not None:
            return redirect(url_for("tableau"))
        if request.method == "POST":
            row = get_db().execute(
                "SELECT * FROM users WHERE username = ? AND active = 1",
                (request.form.get("username", "").strip().lower(),),
            ).fetchone()
            if row and check_password_hash(row["password_hash"], request.form.get("password", "")):
                session.clear()
                session.permanent = True
                session["uid"] = row["id"]
                suite = request.args.get("suite", "")
                return redirect(suite if suite.startswith("/") and not suite.startswith("//") else url_for("tableau"))
            flash("Identifiant ou mot de passe incorrect.", "erreur")
        return render_template("connexion.html")

    @app.route("/deconnexion", methods=["POST"])
    def deconnexion():
        session.clear()
        return redirect(url_for("connexion"))

    @app.route("/mot-de-passe", methods=["GET", "POST"])
    @connecte()
    def mot_de_passe():
        if request.method == "POST":
            if not check_password_hash(g.user["password_hash"], request.form.get("actuel", "")):
                flash("Mot de passe actuel incorrect.", "erreur")
            elif len(request.form.get("nouveau", "")) < 6:
                flash("Le nouveau mot de passe doit faire au moins 6 caractères.", "erreur")
            else:
                db = get_db()
                db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                           (generate_password_hash(request.form["nouveau"]), g.user["id"]))
                db.commit()
                flash("Mot de passe changé.", "ok")
                return redirect(url_for("tableau"))
        return render_template("mot_de_passe.html")

    # ------------------------------------------------------------------
    # Tablette
    # ------------------------------------------------------------------

    def poste_par_code(code):
        p = get_db().execute("SELECT * FROM postes WHERE token = ? AND active = 1", (code,)).fetchone()
        if p is None:
            abort(404, "Ce lien de poste n'existe pas ou a été désactivé.")
        return p

    @app.route("/t/<code>")
    def tablette(code):
        p = poste_par_code(code)
        return render_template("tablette.html", poste=p, code=code)

    @app.route("/api/t/<code>/etat")
    def tablette_etat(code):
        p = poste_par_code(code)
        s = get_settings()
        maintenant = utcnow()
        q = stats.quart_de(maintenant, s["quarts"], tz())
        evs = charger_events(maintenant - timedelta(hours=1), maintenant + timedelta(seconds=1), p["id"])
        sessions, pannes = stats.reconstituer(evs, s["quarts"], tz(), maintenant)
        en_cours = next((x for x in sessions if x.ouvert), None)
        panne = next((x for x in pannes if x.ouvert), None)
        of_row = get_db().execute(
            "SELECT of_number FROM events WHERE poste_id = ? AND type = 'changement_of' "
            "AND cancelled = 0 ORDER BY ts DESC LIMIT 1", (p["id"],)).fetchone()
        compteur = 0
        if en_cours and q:
            compteur = get_db().execute(
                "SELECT COUNT(*) FROM events WHERE poste_id = ? AND operator_id = ? AND type = 'couette' "
                "AND cancelled = 0 AND ts >= ?", (p["id"], en_cours.operator_id, iso(q.debut))).fetchone()[0]
        return jsonify({
            "poste": p["name"],
            "serveur": iso(maintenant),
            "quart": {"nom": q.nom, "fin": iso(q.fin)} if q else None,
            "operatrices": [{"id": o["id"], "nom": o["name"]} for o in operatrices(actives=True)],
            "defauts": [{"id": d["id"], "libelle": d["label"]} for d in defauts(actifs=True)],
            "afficher_compteur": bool(s["afficher_compteur"]),
            "delai_annulation": int(s["delai_annulation"]),
            "session": {"operator_id": en_cours.operator_id, "depuis": iso(en_cours.debut)} if en_cours else None,
            "panne": {"depuis": iso(panne.debut)} if panne else None,
            "of": of_row["of_number"] if of_row else None,
            "compteur": compteur,
        })

    @app.route("/api/t/<code>/events", methods=["POST"])
    def tablette_events(code):
        p = poste_par_code(code)
        data = request.get_json(silent=True) or {}
        maintenant = utcnow()
        # Corrige l'horloge de la tablette : on compare l'heure à laquelle
        # elle dit avoir envoyé le paquet avec l'heure du serveur.
        decalage = timedelta(0)
        try:
            ecart = maintenant - parse_ts(data["envoye_a"])
            if abs(ecart) > timedelta(seconds=2):
                decalage = ecart
        except (KeyError, ValueError, TypeError):
            pass
        s = get_settings()
        db = get_db()
        ops = {o["id"] for o in operatrices()}
        dfs = {d["id"] for d in defauts()}
        acceptes = []
        for e in data.get("events", []):
            uid = str(e.get("uuid", ""))[:64]
            if not uid:
                continue
            try:
                ts = min(parse_ts(e["ts"]) + decalage, maintenant)
            except (KeyError, ValueError, TypeError):
                ts = maintenant
            t = e.get("type")
            if t == "annulation":
                # Annule une couette comptée par erreur, dans le délai permis.
                cible = db.execute(
                    "SELECT * FROM events WHERE uuid = ? AND poste_id = ? AND type = 'couette'",
                    (str(e.get("ref", "")), p["id"])).fetchone()
                if cible and ts - parse_ts(cible["ts"]) <= timedelta(seconds=int(s["delai_annulation"]) + 30):
                    db.execute("UPDATE events SET cancelled = 1, cancelled_by = 'opératrice' WHERE id = ?",
                               (cible["id"],))
                acceptes.append(uid)
                continue
            if t not in TYPES_EVENEMENT:
                acceptes.append(uid)   # inconnu : on l'écarte pour ne pas bloquer la file
                continue
            op = e.get("operator_id")
            op = op if op in ops else None
            defect = e.get("defect_id") if e.get("defect_id") in dfs else None
            of_number = normaliser_of(e.get("of")) if t == "changement_of" else None
            try:
                db.execute(
                    "INSERT INTO events (uuid, poste_id, operator_id, type, ts, of_number, defect_id, received_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (uid, p["id"], op, t, iso(ts), of_number, defect, iso(maintenant)))
            except sqlite3.IntegrityError:
                pass   # déjà reçu (renvoi après une coupure réseau)
            acceptes.append(uid)
        db.commit()
        return jsonify({"acceptes": acceptes})

    # ------------------------------------------------------------------
    # Tableau de bord
    # ------------------------------------------------------------------

    def periode_demandee():
        """(debut, fin, libellé) à partir des paramètres de la requête."""
        s = get_settings()
        z = tz()
        maintenant = utcnow()
        jour_prod = journee_actuelle()

        def bornes(d1, d2):
            return debut_journee(d1), debut_journee(d2 + timedelta(days=1))

        p = request.args.get("periode", "jour")
        if p == "quart":
            q = stats.quart_de(maintenant, s["quarts"], z)
            if q:
                return q.debut, q.fin, f"Quart en cours : {q.nom}"
            p = "jour"
        if p == "hier":
            d = jour_prod - timedelta(days=1)
            return (*bornes(d, d), f"Hier ({d:%d/%m/%Y})")
        if p == "semaine":
            return (*bornes(jour_prod - timedelta(days=6), jour_prod), "7 derniers jours")
        if p == "mois":
            return (*bornes(jour_prod - timedelta(days=29), jour_prod), "30 derniers jours")
        if p == "perso":
            try:
                d1 = date.fromisoformat(request.args["du"])
                d2 = date.fromisoformat(request.args.get("au") or request.args["du"])
                if d2 < d1:
                    d1, d2 = d2, d1
                if (d2 - d1).days > 400:
                    abort(400, "Période trop longue (400 jours maximum).")
                return (*bornes(d1, d2), f"Du {d1:%d/%m/%Y} au {d2:%d/%m/%Y}")
            except (KeyError, ValueError):
                pass
        return (*bornes(jour_prod, jour_prod), f"Aujourd'hui ({jour_prod:%d/%m/%Y})")

    def filtrer(lignes):
        quart = request.args.get("quart") or None
        op = request.args.get("operatrice", type=int)
        poste = request.args.get("poste", type=int)
        return [l for l in lignes
                if (not quart or l.quart == quart)
                and (not op or l.operator_id == op)
                and (not poste or l.poste_id == poste)]

    def resume(l, **extra):
        return {
            "couettes": l.couettes,
            "attendu": round(l.attendu, 1),
            "rendement": None if l.rendement is None else round(l.rendement, 1),
            "disponibilite": None if l.disponibilite is None else round(l.disponibilite, 1),
            "cadence": None if l.cadence_reelle is None else round(l.cadence_reelle, 1),
            "presence_s": round(l.presence_s),
            "pause_s": round(l.pause_s),
            "panne_s": round(l.panne_s),
            "productif_s": round(l.productif_s),
            "nb_pannes": l.nb_pannes,
            "defauts": l.nb_defauts,
            "taux_defaut": round(100.0 * l.nb_defauts / l.couettes, 1) if l.couettes else None,
            "qualite": None if l.qualite is None else round(l.qualite, 1),
            "trs": None if l.trs is None else round(l.trs, 1),
            **extra,
        }

    @app.route("/")
    @connecte()
    def tableau():
        quarts = [q["nom"] for q in get_settings()["quarts"]]
        return render_template("tableau.html", quarts=quarts, postes=postes(actifs=False),
                               operatrices=operatrices())

    @app.route("/api/tableau")
    @connecte()
    def api_tableau():
        debut, fin, libelle = periode_demandee()
        s = get_settings()
        z = tz()
        evs, lignes = calcul(debut, fin)
        lignes = filtrer(lignes)
        noms_op = {o["id"]: o["name"] for o in operatrices()}
        noms_poste = {p["id"]: p["name"] for p in postes(actifs=False)}
        noms_def = {d["id"]: d["label"] for d in defauts()}
        nom_op = lambda i: noms_op.get(i, "(inconnue)")

        total = stats.Ligne("", "", None, None)
        for l in lignes:
            total.ajouter(l)

        par_op = stats.regrouper(lignes, lambda l: l.operator_id)
        par_poste = stats.regrouper(lignes, lambda l: l.poste_id)
        par_jour_poste = stats.regrouper(lignes, lambda l: (l.jour, l.poste_id))
        jours = sorted({l.jour for l in lignes})

        # Événements retenus par les filtres, pour les courbes et les OF.
        quart_f = request.args.get("quart") or None
        op_f = request.args.get("operatrice", type=int)
        poste_f = request.args.get("poste", type=int)

        def retenu(e):
            if not (debut <= e["ts"] < fin) or e["cancelled"]:
                return False
            if op_f and e["operator_id"] != op_f:
                return False
            if poste_f and e["poste_id"] != poste_f:
                return False
            if quart_f:
                q = stats.quart_de(e["ts"], s["quarts"], z)
                if not q or q.nom != quart_f:
                    return False
            return True

        couettes = [e for e in evs if e["type"] == "couette" and retenu(e)]

        # Production dans le temps : par heure sur une journée, sinon par jour.
        par_heure = (fin - debut) <= timedelta(hours=26)
        series, etiquettes = {}, []
        if par_heure:
            t = debut.astimezone(z).replace(minute=0, second=0, microsecond=0)
            while t < fin:
                etiquettes.append(t.strftime("%Hh"))
                t += timedelta(hours=1)
            base = debut.astimezone(z).replace(minute=0, second=0, microsecond=0)
            for e in couettes:
                i = int((e["ts"] - base).total_seconds() // 3600)
                if 0 <= i < len(etiquettes):
                    series.setdefault(noms_poste.get(e["poste_id"], "?"), [0] * len(etiquettes))[i] += 1
        else:
            d = debut.astimezone(z).date()
            jours_tous = []
            while datetime.combine(d, debut.astimezone(z).time(), tzinfo=z) < fin:
                jours_tous.append(d.isoformat())
                etiquettes.append(d.strftime("%d/%m"))
                d += timedelta(days=1)
            for (jour, poste), l in par_jour_poste.items():
                if jour in jours_tous:
                    series.setdefault(noms_poste.get(poste, "?"), [0] * len(jours_tous))[jours_tous.index(jour)] += l.couettes
            jours = jours_tous

        # Rendement jour par jour, par poste (filtrer sur une opératrice pour
        # voir sa courbe à elle) et pour l'ensemble.
        tendance = {}
        if not par_heure:
            for (jour, poste), l in par_jour_poste.items():
                if jour in jours and l.rendement is not None:
                    tendance.setdefault(noms_poste.get(poste, "?"), [None] * len(jours))[jours.index(jour)] = round(l.rendement, 1)

        # Défauts qualité.
        compte_def = {}
        for l in lignes:
            for k, v in l.defauts.items():
                compte_def[k] = compte_def.get(k, 0) + v

        # Production par OF : chaque couette appartient au dernier OF saisi
        # sur son poste avant elle.
        of_courant, par_of = {}, {}
        for e in evs:
            if e["type"] == "changement_of" and not e["cancelled"]:
                of_courant[e["poste_id"]] = e["of_number"]
            elif e["type"] == "couette" and retenu(e):
                of = of_courant.get(e["poste_id"]) or "(sans OF)"
                r = par_of.setdefault(of, {"of": of, "couettes": 0, "postes": set(),
                                           "debut": e["ts"], "fin": e["ts"]})
                r["couettes"] += 1
                r["postes"].add(noms_poste.get(e["poste_id"], "?"))
                r["fin"] = e["ts"]

        pannes_poste = stats.pannes_par_poste(evs, debut, fin, s["quarts"], z, utcnow())

        cad = cadence_en_vigueur()
        sans_cadence = [p["name"] for p in postes() if cad(p["id"], utcnow()) is None]

        return jsonify({
            "sans_cadence": sans_cadence,
            "periode": {"libelle": libelle, "debut": iso(debut), "fin": iso(fin)},
            "total": resume(total),
            "operatrices": sorted(
                [resume(l, id=k, nom=nom_op(k)) for k, l in par_op.items()],
                key=lambda r: -(r["rendement"] or -1)),
            "postes": [
                resume(par_poste[p["id"]] if p["id"] in par_poste else stats.Ligne("", "", None, p["id"]),
                       id=p["id"], nom=p["name"],
                       panne_poste_s=round(pannes_poste.get(p["id"], {}).get("panne_s", 0)),
                       nb_pannes_poste=pannes_poste.get(p["id"], {}).get("nb", 0))
                for p in postes(actifs=False) if not poste_f or p["id"] == poste_f],
            "detail": [resume(l, jour=l.jour, quart=l.quart, operatrice=nom_op(l.operator_id),
                              poste=noms_poste.get(l.poste_id, "?"))
                       for l in sorted(lignes, key=lambda l: (l.jour, l.quart, nom_op(l.operator_id)), reverse=True)],
            "defauts": sorted([{"libelle": noms_def.get(k, "(non précisé)"), "nombre": v}
                               for k, v in compte_def.items()], key=lambda r: -r["nombre"]),
            "production": {"par_heure": par_heure, "etiquettes": etiquettes, "series": series},
            "tendance": {"etiquettes": etiquettes if not par_heure else [], "series": tendance},
            "of": [{"of": r["of"], "couettes": r["couettes"], "postes": ", ".join(sorted(r["postes"])),
                    "debut": iso(r["debut"]), "fin": iso(r["fin"])}
                   for r in sorted(par_of.values(), key=lambda r: r["debut"], reverse=True)],
        })

    @app.route("/api/direct")
    @connecte()
    def api_direct():
        """État actuel de chaque poste."""
        s = get_settings()
        z = tz()
        maintenant = utcnow()
        q = stats.quart_de(maintenant, s["quarts"], z)
        debut = q.debut if q else maintenant - timedelta(hours=8)
        fin = q.fin if q else maintenant
        evs, lignes = calcul(debut, fin)
        sessions, pannes = stats.reconstituer(evs, s["quarts"], z, maintenant)
        noms_op = {o["id"]: o["name"] for o in operatrices()}
        out = []
        for p in postes():
            sess = next((x for x in sessions if x.ouvert and x.poste_id == p["id"]), None)
            pan = next((x for x in pannes if x.ouvert and x.poste_id == p["id"]), None)
            of = next((e["of_number"] for e in reversed(evs)
                       if e["poste_id"] == p["id"] and e["type"] == "changement_of" and not e["cancelled"]), None)
            if of is None:
                r = get_db().execute(
                    "SELECT of_number FROM events WHERE poste_id = ? AND type = 'changement_of' "
                    "AND cancelled = 0 ORDER BY ts DESC LIMIT 1", (p["id"],)).fetchone()
                of = r["of_number"] if r else None
            ligne = None
            if sess:
                ligne = next((l for l in lignes if l.poste_id == p["id"] and l.operator_id == sess.operator_id), None)
            derniere = next((e for e in reversed(evs) if e["poste_id"] == p["id"]
                             and e["type"] == "couette" and not e["cancelled"]), None)
            out.append({
                "id": p["id"], "nom": p["name"],
                "operatrice": noms_op.get(sess.operator_id) if sess else None,
                "depuis": iso(sess.debut) if sess else None,
                "panne": iso(pan.debut) if pan else None,
                "of": of,
                "couettes": ligne.couettes if ligne else 0,
                "rendement": round(ligne.rendement, 1) if ligne and ligne.rendement is not None else None,
                "derniere_couette": iso(derniere["ts"]) if derniere else None,
            })
        return jsonify({"quart": q.nom if q else None, "maintenant": iso(maintenant), "postes": out})

    @app.route("/export.csv")
    @connecte()
    def export_csv():
        debut, fin, libelle = periode_demandee()
        _, lignes = calcul(debut, fin)
        lignes = filtrer(lignes)
        noms_op = {o["id"]: o["name"] for o in operatrices()}
        noms_poste = {p["id"]: p["name"] for p in postes(actifs=False)}
        noms_def = {d["id"]: d["label"] for d in defauts()}
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["Jour", "Quart", "Opératrice", "Poste", "Présence (min)", "Pause (min)",
                    "Panne (min)", "Temps productif (min)", "Nb pannes", "Couettes",
                    "Couettes attendues", "Rendement / performance (%)", "Disponibilité (%)",
                    "Qualité (%)", "TRS (%)", "Couettes/heure", "Défauts qualité", "Détail défauts"])
        fr = lambda x: "" if x is None else f"{x:.1f}".replace(".", ",")
        for l in lignes:
            w.writerow([l.jour, l.quart, noms_op.get(l.operator_id, "?"), noms_poste.get(l.poste_id, "?"),
                        fr(l.presence_s / 60), fr(l.pause_s / 60), fr(l.panne_s / 60), fr(l.productif_s / 60),
                        l.nb_pannes, l.couettes, fr(l.attendu), fr(l.rendement), fr(l.disponibilite),
                        fr(l.qualite), fr(l.trs), fr(l.cadence_reelle), l.nb_defauts,
                        ", ".join(f"{noms_def.get(k, '?')} x{v}" for k, v in l.defauts.items())])
        # BOM pour qu'Excel lise bien les accents.
        return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=rendement-bordage.csv"})

    # ------------------------------------------------------------------
    # Journal : voir et corriger les clics
    # ------------------------------------------------------------------

    @app.route("/journal")
    @connecte()
    def journal():
        debut, fin, libelle = periode_demandee()
        poste = request.args.get("poste", type=int)
        sql = ("SELECT e.*, o.name AS operatrice, p.name AS poste, d.label AS defaut FROM events e "
               "LEFT JOIN operators o ON o.id = e.operator_id JOIN postes p ON p.id = e.poste_id "
               "LEFT JOIN defects d ON d.id = e.defect_id WHERE e.ts >= ? AND e.ts < ?")
        args = [iso(debut), iso(fin)]
        if poste:
            sql += " AND e.poste_id = ?"
            args.append(poste)
        rows = get_db().execute(sql + " ORDER BY e.ts DESC LIMIT 2000", args).fetchall()
        return render_template("journal.html", events=rows, libelle=libelle, LIBELLES=LIBELLES_TYPE,
                               postes=postes(actifs=False), peut_corriger=g.user["role"] in ("admin", "chef_prod"))

    @app.route("/journal/<int:eid>/annuler", methods=["POST"])
    @connecte("admin", "chef_prod")
    def journal_annuler(eid):
        db = get_db()
        e = db.execute("SELECT cancelled FROM events WHERE id = ?", (eid,)).fetchone()
        if e:
            if e["cancelled"]:
                db.execute("UPDATE events SET cancelled = 0, cancelled_by = NULL WHERE id = ?", (eid,))
            else:
                db.execute("UPDATE events SET cancelled = 1, cancelled_by = ? WHERE id = ?",
                           (g.user["display_name"], eid))
            db.commit()
        return redirect(request.form.get("retour") or url_for("journal"))

    # ------------------------------------------------------------------
    # Administration
    # ------------------------------------------------------------------

    LISTES = {
        "operatrices": ("operators", "name", "Opératrices", "Nom affiché sur la tablette"),
        "defauts": ("defects", "label", "Défauts qualité", "Libellé du défaut"),
    }

    @app.route("/admin/<liste>", methods=["GET", "POST"])
    @connecte("admin", "chef_prod")
    def admin_liste(liste):
        if liste not in LISTES:
            abort(404)
        table, col, titre, aide = LISTES[liste]
        db = get_db()
        if request.method == "POST":
            action = request.form.get("action")
            texte = request.form.get("texte", "").strip()[:60]
            iid = request.form.get("id", type=int)
            if action == "ajouter" and texte:
                db.execute(f"INSERT INTO {table} ({col}) VALUES (?)", (texte,))
            elif action == "renommer" and texte and iid:
                db.execute(f"UPDATE {table} SET {col} = ? WHERE id = ?", (texte, iid))
            elif action == "basculer" and iid:
                db.execute(f"UPDATE {table} SET active = 1 - active WHERE id = ?", (iid,))
            db.commit()
            return redirect(url_for("admin_liste", liste=liste))
        rows = db.execute(f"SELECT id, {col} AS texte, active FROM {table} "
                          f"ORDER BY active DESC, {col} COLLATE NOCASE").fetchall()
        return render_template("admin_liste.html", rows=rows, titre=titre, aide=aide, liste=liste)

    @app.route("/admin/postes", methods=["GET", "POST"])
    @connecte("admin")
    def admin_postes():
        db = get_db()
        if request.method == "POST":
            action = request.form.get("action")
            pid = request.form.get("id", type=int)
            if action == "ajouter":
                n = db.execute("SELECT COUNT(*) FROM postes").fetchone()[0] + 1
                db.execute("INSERT INTO postes (name, token) VALUES (?, ?)", (f"Poste {n}", new_token()))
            elif action == "modifier" and pid:
                db.execute("UPDATE postes SET name = ? WHERE id = ?",
                           (request.form.get("nom", "").strip()[:40] or f"Poste {pid}", pid))
            elif action == "nouveau_lien" and pid:
                db.execute("UPDATE postes SET token = ? WHERE id = ?", (new_token(), pid))
            elif action == "basculer" and pid:
                db.execute("UPDATE postes SET active = 1 - active WHERE id = ?", (pid,))
            db.commit()
            return redirect(url_for("admin_postes"))
        return render_template("admin_postes.html", postes=postes(actifs=False))

    @app.route("/cadences", methods=["GET", "POST"])
    @connecte()
    def cadences():
        """Les responsables renseignent la cadence attendue de chaque poste."""
        db = get_db()
        if request.method == "POST":
            pid = request.form.get("poste", type=int)
            try:
                valeur = float(request.form.get("valeur", "").replace(",", "."))
                if not 0 < valeur < 1000:
                    raise ValueError
                jour = date.fromisoformat(request.form.get("depuis", ""))
            except ValueError:
                flash("Saisis une cadence (nombre de couettes par heure) et une date.", "erreur")
                return redirect(url_for("cadences"))
            if db.execute("SELECT 1 FROM postes WHERE id = ?", (pid,)).fetchone():
                db.execute("INSERT INTO cadences (poste_id, valeur, depuis, par, saisi_le) VALUES (?, ?, ?, ?, ?)",
                           (pid, valeur, iso(debut_journee(jour)), g.user["display_name"], iso(utcnow())))
                db.commit()
                flash("Cadence enregistrée.", "ok")
            return redirect(url_for("cadences"))
        cad = cadence_en_vigueur()
        maintenant = utcnow()
        lignes = [{"poste": p, "actuelle": cad(p["id"], maintenant)} for p in postes(actifs=False)]
        hist = db.execute("SELECT c.*, p.name AS poste FROM cadences c JOIN postes p ON p.id = c.poste_id "
                          "ORDER BY c.depuis DESC, c.id DESC LIMIT 200").fetchall()
        return render_template("cadences.html", lignes=lignes, hist=hist, aujourdhui=journee_actuelle().isoformat())

    @app.route("/admin/comptes", methods=["GET", "POST"])
    @connecte("admin")
    def admin_comptes():
        db = get_db()
        if request.method == "POST":
            action = request.form.get("action")
            uid = request.form.get("id", type=int)
            if action == "ajouter":
                nom = request.form.get("username", "").strip().lower()
                mdp = request.form.get("password", "")
                role = request.form.get("role")
                if not nom or len(mdp) < 6 or role not in ROLES:
                    flash("Identifiant, rôle et mot de passe (6 caractères minimum) obligatoires.", "erreur")
                else:
                    try:
                        db.execute("INSERT INTO users (username, display_name, password_hash, role) VALUES (?, ?, ?, ?)",
                                   (nom, request.form.get("display_name", "").strip() or nom,
                                    generate_password_hash(mdp), role))
                        flash(f"Compte « {nom} » créé.", "ok")
                    except sqlite3.IntegrityError:
                        flash("Cet identifiant existe déjà.", "erreur")
            elif action == "mot_de_passe" and uid:
                mdp = request.form.get("password", "")
                if len(mdp) < 6:
                    flash("6 caractères minimum.", "erreur")
                else:
                    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(mdp), uid))
                    flash("Mot de passe réinitialisé.", "ok")
            elif action == "basculer" and uid and uid != g.user["id"]:
                db.execute("UPDATE users SET active = 1 - active WHERE id = ?", (uid,))
            db.commit()
            return redirect(url_for("admin_comptes"))
        rows = db.execute("SELECT * FROM users ORDER BY active DESC, username").fetchall()
        return render_template("admin_comptes.html", comptes=rows)

    @app.route("/admin/reglages", methods=["GET", "POST"])
    @connecte("admin")
    def admin_reglages():
        if request.method == "POST":
            set_setting("afficher_compteur", request.form.get("afficher_compteur") == "1")
            try:
                set_setting("delai_annulation", max(0, min(600, int(request.form.get("delai_annulation", 60)))))
            except ValueError:
                pass
            quarts = []
            for nom, d, f, pause in zip(request.form.getlist("q_nom"), request.form.getlist("q_debut"),
                                        request.form.getlist("q_fin"), request.form.getlist("q_pause")):
                nom = nom.strip()
                if not nom:
                    continue
                try:
                    stats._hm(d), stats._hm(f)
                    quarts.append({"nom": nom[:30], "debut": d, "fin": f, "pause": max(0, float(pause or 0))})
                except ValueError:
                    flash(f"Horaires invalides pour le quart « {nom} ».", "erreur")
            if quarts:
                set_setting("quarts", quarts)
            flash("Réglages enregistrés.", "ok")
            return redirect(url_for("admin_reglages"))
        return render_template("admin_reglages.html", s=get_settings())

    @app.errorhandler(403)
    def interdit(_e):
        return render_template("erreur.html", message="Ton compte n'a pas accès à cette page."), 403

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=8080, debug=True)
