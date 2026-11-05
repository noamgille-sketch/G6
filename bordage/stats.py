"""Calcul du rendement.

Tout part du journal d'événements des tablettes. On en reconstitue :

* les **sessions** : une opératrice est présente sur un poste depuis qu'elle a
  cliqué sur son nom jusqu'à ce qu'elle quitte, qu'une autre se connecte sur
  le même poste, ou au plus tard jusqu'à la fin du quart où elle a commencé
  (si elle part sans se déconnecter, son temps ne continue pas à courir) ;
* les **pannes** : de « début de panne » à « fin de panne », elles aussi
  arrêtées au plus tard à la fin du quart si personne n'a appuyé sur « fin ».

Pour chaque opératrice, poste et quart :

    temps de présence   = durée des sessions dans le quart
    temps de pause      = pause du quart, au prorata de la présence
    temps de panne      = pannes du poste pendant sa présence
    temps productif     = présence - pause - panne
    couettes attendues  = temps productif (h) x cadence du poste (couettes/h)
                          (la cadence en vigueur à ce moment-là : la changer
                          ne réécrit pas les rendements passés)
    rendement (%)       = couettes réalisées / couettes attendues x 100
    disponibilité (%)   = (présence - pause - panne) / (présence - pause) x 100

Ce module n'utilise ni Flask ni SQLite pour pouvoir être testé seul.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

MAX_SANS_QUART = timedelta(hours=12)
# En dessous de ce temps productif, un pourcentage n'a pas de sens (1 couette
# en 30 secondes ferait des milliers de %) : on n'en affiche pas.
PRODUCTIF_MIN_S = 5 * 60


# --------------------------------------------------------------------------
# Quarts
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Quart:
    jour: date          # jour de début du quart (la nuit appartient au jour où elle commence)
    nom: str
    debut: datetime     # aware
    fin: datetime       # aware
    pause_min: float

    @property
    def duree_s(self):
        return (self.fin - self.debut).total_seconds()

    @property
    def cle(self):
        return (self.jour.isoformat(), self.nom)


def _hm(text):
    h, m = text.split(":")
    return time(int(h), int(m))


def quarts_entre(debut, fin, config, tz):
    """Tous les quarts qui chevauchent [debut, fin[ (datetimes aware)."""
    out = []
    jour = debut.astimezone(tz).date() - timedelta(days=1)
    dernier = fin.astimezone(tz).date()
    while jour <= dernier:
        for q in config:
            d = datetime.combine(jour, _hm(q["debut"]), tzinfo=tz)
            f_jour = jour if _hm(q["fin"]) > _hm(q["debut"]) else jour + timedelta(days=1)
            f = datetime.combine(f_jour, _hm(q["fin"]), tzinfo=tz)
            if d < fin and f > debut:
                out.append(Quart(jour, q["nom"], d, f, float(q.get("pause", 0) or 0)))
        jour += timedelta(days=1)
    out.sort(key=lambda q: q.debut)
    return out


def quart_de(instant, config, tz):
    """Le quart qui contient cet instant, ou None s'il tombe entre deux quarts."""
    for q in quarts_entre(instant, instant + timedelta(seconds=1), config, tz):
        if q.debut <= instant < q.fin:
            return q
    return None


def _limite(instant, config, tz):
    q = quart_de(instant, config, tz)
    return q.fin if q else instant + MAX_SANS_QUART


# --------------------------------------------------------------------------
# Reconstitution des sessions et des pannes
# --------------------------------------------------------------------------

@dataclass
class Intervalle:
    poste_id: int
    debut: datetime
    fin: datetime
    operator_id: int = None
    ouvert: bool = False     # pas encore terminé (en cours)


def reconstituer(events, config, tz, maintenant):
    """events : dicts triés ou non, avec poste_id, operator_id, type, ts (aware).

    Renvoie (sessions, pannes).
    """
    sessions, pannes = [], []
    par_poste = {}
    for e in events:
        par_poste.setdefault(e["poste_id"], []).append(e)

    for poste_id, evs in par_poste.items():
        evs.sort(key=lambda e: e["ts"])
        session = None   # (operator_id, debut)
        panne = None     # debut

        def fermer_session(a):
            nonlocal session
            if session is None:
                return
            op, d = session
            lim = _limite(d, config, tz)
            f = min(a, lim) if a is not None else min(maintenant, lim)
            ouvert = a is None and maintenant < lim
            if f > d:
                sessions.append(Intervalle(poste_id, d, f, op, ouvert))
            session = None

        def fermer_panne(a):
            nonlocal panne
            if panne is None:
                return
            lim = _limite(panne, config, tz)
            f = min(a, lim) if a is not None else min(maintenant, lim)
            ouvert = a is None and maintenant < lim
            if f > panne:
                pannes.append(Intervalle(poste_id, panne, f, None, ouvert))
            panne = None

        for e in evs:
            if e.get("cancelled"):
                continue
            t, ts = e["type"], e["ts"]
            # Une session ou une panne restée ouverte au-delà de la fin de
            # son quart est considérée comme terminée à cette fin.
            if session and ts >= _limite(session[1], config, tz):
                fermer_session(ts)
            if panne is not None and ts >= _limite(panne, config, tz):
                fermer_panne(ts)

            if t == "connexion":
                fermer_session(ts)
                session = (e["operator_id"], ts)
            elif t == "deconnexion":
                fermer_session(ts)
            elif t == "panne_debut":
                if panne is None:
                    panne = ts
            elif t == "panne_fin":
                fermer_panne(ts)
            elif session is None and e.get("operator_id"):
                # Un clic d'une opératrice sans connexion enregistrée (ne
                # devrait pas arriver) : on ouvre une session pour ne pas
                # perdre son temps de présence.
                session = (e["operator_id"], ts)
            elif session and e.get("operator_id") and e["operator_id"] != session[0]:
                fermer_session(ts)
                session = (e["operator_id"], ts)

        fermer_session(None)
        fermer_panne(None)

    return sessions, pannes


def _chevauchement(a_debut, a_fin, b_debut, b_fin):
    d, f = max(a_debut, b_debut), min(a_fin, b_fin)
    return max(0.0, (f - d).total_seconds())


# --------------------------------------------------------------------------
# Agrégats
# --------------------------------------------------------------------------

@dataclass
class Ligne:
    jour: str
    quart: str
    operator_id: int
    poste_id: int
    presence_s: float = 0.0
    pause_s: float = 0.0
    panne_s: float = 0.0
    nb_pannes: int = 0
    couettes: int = 0
    attendu: float = 0.0
    sans_cadence_s: float = 0.0   # temps productif sans cadence renseignée
    defauts: dict = field(default_factory=dict)

    @property
    def productif_s(self):
        return max(0.0, self.presence_s - self.pause_s - self.panne_s)

    @property
    def nb_defauts(self):
        return sum(self.defauts.values())

    @property
    def rendement(self):
        # Pas de pourcentage si une partie du temps n'a pas de cadence : il
        # serait faux.
        if self.attendu <= 0 or self.sans_cadence_s > 0 or self.productif_s < PRODUCTIF_MIN_S:
            return None
        return 100.0 * self.couettes / self.attendu

    @property
    def disponibilite(self):
        base = self.presence_s - self.pause_s
        if base <= 0:
            return None
        return 100.0 * self.productif_s / base

    @property
    def cadence_reelle(self):
        """Couettes par heure productive."""
        if self.productif_s < PRODUCTIF_MIN_S:
            return None
        return self.couettes / (self.productif_s / 3600.0)

    def ajouter(self, autre):
        self.presence_s += autre.presence_s
        self.pause_s += autre.pause_s
        self.panne_s += autre.panne_s
        self.nb_pannes += autre.nb_pannes
        self.couettes += autre.couettes
        self.attendu += autre.attendu
        self.sans_cadence_s += autre.sans_cadence_s
        for k, v in autre.defauts.items():
            self.defauts[k] = self.defauts.get(k, 0) + v


def calculer(events, debut, fin, config, tz, cadence, maintenant=None):
    """Lignes par (jour, quart, opératrice, poste) sur la période [debut, fin[.

    events doit contenir aussi ce qui précède la période (au moins un quart
    avant), pour retrouver les sessions déjà ouvertes à son début.
    cadence : fonction (poste_id, instant) -> couettes/h en vigueur à cet
    instant, ou None si elle n'a pas été renseignée (pas de rendement alors).
    """
    maintenant = maintenant or datetime.now(timezone.utc)
    fin_calc = min(fin, maintenant)
    sessions, pannes = reconstituer(events, config, tz, maintenant)
    quarts = quarts_entre(debut, fin, config, tz)
    lignes = {}

    def ligne(q, op, poste):
        cle = (q.jour.isoformat(), q.nom, op, poste)
        if cle not in lignes:
            lignes[cle] = Ligne(q.jour.isoformat(), q.nom, op, poste)
        return lignes[cle]

    for s in sessions:
        for q in quarts:
            d = max(s.debut, q.debut, debut)
            f = min(s.fin, q.fin, fin_calc)
            if f <= d:
                continue
            l = ligne(q, s.operator_id, s.poste_id)
            presence = (f - d).total_seconds()
            pause = q.pause_min * 60.0 * presence / q.duree_s
            panne = 0.0
            for p in pannes:
                if p.poste_id != s.poste_id:
                    continue
                ch = _chevauchement(d, f, p.debut, p.fin)
                if ch > 0:
                    panne += ch
                    if d <= p.debut < f:
                        l.nb_pannes += 1
            panne = min(panne, presence)
            l.presence_s += presence
            l.pause_s += pause
            l.panne_s += panne
            productif = max(0.0, presence - pause - panne)
            c = cadence(s.poste_id, d)
            if c:
                l.attendu += float(c) * productif / 3600.0
            else:
                l.sans_cadence_s += productif

    for e in events:
        if e.get("cancelled") or e["type"] not in ("couette", "qualite"):
            continue
        if not (debut <= e["ts"] < fin) or not e.get("operator_id"):
            continue
        q = quart_de(e["ts"], config, tz)
        if q is None:
            continue
        l = ligne(q, e["operator_id"], e["poste_id"])
        if e["type"] == "couette":
            l.couettes += 1
        else:
            k = e.get("defect_id")
            l.defauts[k] = l.defauts.get(k, 0) + 1

    return sorted(lignes.values(), key=lambda l: (l.jour, l.quart, l.poste_id))


def regrouper(lignes, cle):
    """Additionne les lignes qui ont la même clé (fonction ligne -> tuple)."""
    out = {}
    for l in lignes:
        k = cle(l)
        if k not in out:
            out[k] = Ligne(l.jour, l.quart, l.operator_id, l.poste_id)
        out[k].ajouter(l)
    return out


def pannes_par_poste(events, debut, fin, config, tz, maintenant=None):
    """Pour chaque poste : temps de panne et nombre de pannes sur la période,
    qu'une opératrice soit connectée ou non."""
    maintenant = maintenant or datetime.now(timezone.utc)
    _, pannes = reconstituer(events, config, tz, maintenant)
    out = {}
    for p in pannes:
        ch = _chevauchement(debut, min(fin, maintenant), p.debut, p.fin)
        if ch <= 0:
            continue
        r = out.setdefault(p.poste_id, {"panne_s": 0.0, "nb": 0, "liste": []})
        r["panne_s"] += ch
        if debut <= p.debut < fin:
            r["nb"] += 1
        r["liste"].append(p)
    return out
