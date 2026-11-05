/* Écran tablette d'un poste de bordage.
 *
 * Chaque appui crée un événement horodaté sur la tablette, rangé dans une
 * file d'attente (localStorage) puis envoyé au serveur. Si le Wi-Fi coupe,
 * la tablette continue de fonctionner et renvoie tout dès que le réseau
 * revient : aucun clic n'est perdu, et l'heure enregistrée reste celle du clic.
 */
(function () {
  "use strict";
  var CODE = window.BORDAGE.code;
  var CLE_ETAT = "bordage:etat:" + CODE;
  var CLE_FILE = "bordage:file:" + CODE;
  var API = "/api/t/" + encodeURIComponent(CODE);
  var app = document.getElementById("app");

  // ---------- Stockage local ----------
  function lire(cle, defaut) {
    try { var v = localStorage.getItem(cle); return v ? JSON.parse(v) : defaut; }
    catch (e) { return defaut; }
  }
  function ecrire(cle, v) { try { localStorage.setItem(cle, JSON.stringify(v)); } catch (e) {} }

  var config = lire(CLE_ETAT + ":config", { operatrices: [], defauts: [], afficher_compteur: true, delai_annulation: 60, quart: null, poste: window.BORDAGE.poste });
  // etat : ce qui est en cours sur ce poste
  var etat = lire(CLE_ETAT, { operator_id: null, panne: null, of: null, compteur: 0, derniere: null, fin_quart: null });
  var file = lire(CLE_FILE, []);
  var enLigne = true;
  var envoiEnCours = false;
  var dernierAppuiCouette = 0;

  function sauver() { ecrire(CLE_ETAT, etat); ecrire(CLE_FILE, file); }

  function uuid() {
    var b = new Uint8Array(16);
    (window.crypto || window.msCrypto).getRandomValues(b);
    b[6] = (b[6] & 15) | 64; b[8] = (b[8] & 63) | 128;
    var h = Array.prototype.map.call(b, function (x) { return (x + 256).toString(16).slice(1); }).join("");
    return h.slice(0, 8) + "-" + h.slice(8, 12) + "-" + h.slice(12, 16) + "-" + h.slice(16, 20) + "-" + h.slice(20);
  }

  function evenement(type, extra) {
    var e = { uuid: uuid(), type: type, ts: new Date().toISOString(), operator_id: etat.operator_id };
    for (var k in extra || {}) e[k] = extra[k];
    file.push(e);
    sauver();
    envoyer();
    return e;
  }

  // ---------- Réseau ----------
  function envoyer() {
    if (envoiEnCours || !file.length) return;
    envoiEnCours = true;
    var paquet = file.slice(0, 200);
    fetch(API + "/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ envoye_a: new Date().toISOString(), events: paquet })
    }).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    }).then(function (rep) {
      var ok = {};
      rep.acceptes.forEach(function (u) { ok[u] = 1; });
      file = file.filter(function (e) { return !ok[e.uuid]; });
      sauver();
      marquerReseau(true);
      envoiEnCours = false;
      if (file.length) envoyer();
    }).catch(function () {
      envoiEnCours = false;
      marquerReseau(false);
    });
  }

  function synchroniser(premiere) {
    fetch(API + "/etat", { cache: "no-store" }).then(function (r) {
      if (r.status === 404) { afficherErreur("Ce lien de poste n'est plus valable. Demande le nouveau lien au service maintenance."); throw null; }
      if (!r.ok) throw new Error(r.status);
      return r.json();
    }).then(function (s) {
      marquerReseau(true);
      config = { operatrices: s.operatrices, defauts: s.defauts, afficher_compteur: s.afficher_compteur,
                 delai_annulation: s.delai_annulation, quart: s.quart, poste: s.poste };
      ecrire(CLE_ETAT + ":config", config);
      // Le serveur fait foi, sauf si des clics attendent encore d'être envoyés.
      if (!file.length) {
        etat.operator_id = s.session ? s.session.operator_id : null;
        etat.panne = s.panne ? s.panne.depuis : null;
        etat.of = s.of;
        etat.compteur = s.compteur;
        etat.fin_quart = s.quart ? s.quart.fin : null;
        sauver();
      }
      if (premiere || !modalOuvert()) rendre();
    }).catch(function (e) { if (e !== null) { marquerReseau(false); if (premiere) rendre(); } });
  }

  function marquerReseau(ok) {
    enLigne = ok;
    var el = document.getElementById("reseau");
    if (el) majReseau(el);
  }
  function majReseau(el) {
    if (enLigne && !file.length) { el.className = "t-reseau"; el.textContent = "● Connecté"; }
    else { el.className = "t-reseau hors"; el.textContent = "● Hors ligne" + (file.length ? " — " + file.length + " clic(s) en attente" : ""); }
  }

  // ---------- Rendu ----------
  function h(tag, attrs, enfants) {
    var el = document.createElement(tag);
    for (var k in attrs || {}) {
      if (k === "onclick") el.addEventListener("click", attrs[k]);
      else if (k === "class") el.className = attrs[k];
      else if (k === "disabled") el.disabled = !!attrs[k];
      else el.setAttribute(k, attrs[k]);
    }
    (enfants || []).forEach(function (c) {
      if (c == null) return;
      el.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
    });
    return el;
  }

  function ic(nom) {
    var NS = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", "ic");
    var use = document.createElementNS(NS, "use");
    use.setAttribute("href", "#i-" + nom);
    svg.appendChild(use);
    return svg;
  }
  function initiale(nom) { return h("span", { class: "t-initiale" }, [(nom || "?").charAt(0).toUpperCase()]); }

  function nomOperatrice(id) {
    for (var i = 0; i < config.operatrices.length; i++) if (config.operatrices[i].id === id) return config.operatrices[i].nom;
    return "?";
  }
  function heure(iso) { var d = new Date(iso); return ("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2); }

  function entete() {
    var reseau = h("span", { id: "reseau" });
    majReseau(reseau);
    var horloge = h("span", { id: "horloge" }, [heure(new Date().toISOString())]);
    return h("div", { class: "t-entete" }, [
      h("img", { src: window.BORDAGE.logo, alt: "Peg groupe" }),
      h("span", { class: "sep" }),
      h("span", { class: "poste-nom" }, [config.poste || window.BORDAGE.poste]),
      h("div", { class: "quart" }, [h("b", {}, [horloge]), h("span", {}, [config.quart ? "Quart " + config.quart.nom : "Hors quart"])]),
      reseau
    ]);
  }

  function rendre() {
    app.innerHTML = "";
    app.appendChild(entete());
    if (etat.operator_id == null) rendreNoms(); else rendrePanel();
  }

  function rendreNoms() {
    app.appendChild(h("div", { class: "t-titre" }, ["Bonjour ! Appuie sur ton prénom"]));
    app.appendChild(h("div", { class: "t-sous" }, ["pour commencer ton poste"]));
    var grille = h("div", { class: "t-noms" });
    if (!config.operatrices.length) grille.appendChild(h("div", { class: "t-titre" }, ["Aucune opératrice enregistrée."]));
    config.operatrices.forEach(function (o) {
      grille.appendChild(h("button", { onclick: function () { connecter(o.id); } }, [initiale(o.nom), h("span", {}, [o.nom])]));
    });
    app.appendChild(grille);
  }

  function rendrePanel() {
    var enPanne = !!etat.panne;
    app.appendChild(h("div", { class: "t-info" }, [
      h("span", { class: "t-qui" }, [initiale(nomOperatrice(etat.operator_id)), nomOperatrice(etat.operator_id)]),
      h("span", { class: "t-puce" }, [ic("of"), etat.of || "Pas d'OF"]),
      h("button", { class: "t-quitter", onclick: deconnecter }, [ic("echange"), "Changer d'opératrice"])
    ]));
    if (enPanne) {
      app.appendChild(h("div", { class: "t-bandeau" }, [ic("alerte"), "PANNE EN COURS depuis " + heure(etat.panne) + " — appuie sur « Fin de panne » quand le poste repart"]));
    }
    var couette = h("button", { class: "t-btn t-couette", id: "btn-couette", disabled: enPanne, onclick: couetteFinie }, [
      h("span", { class: "rond" }, [ic("ok")]),
      "COUETTE TERMINÉE",
      config.afficher_compteur ? h("span", { class: "compteur", id: "compteur" }, [etat.compteur + " couette" + (etat.compteur > 1 ? "s" : "") + " ce quart"]) : null
    ]);
    app.appendChild(h("div", { class: "t-panel" }, [
      couette,
      h("button", { class: "t-btn t-panne-debut", disabled: enPanne, onclick: debutPanne }, [ic("cle"), "Début de panne"]),
      h("button", { class: "t-btn t-panne-fin", disabled: !enPanne, onclick: finPanne }, [ic("lecture"), "Fin de panne"]),
      h("button", { class: "t-btn t-of", onclick: ouvrirOF }, [ic("of"), "Changement d'OF"]),
      h("button", { class: "t-btn t-qualite", onclick: ouvrirQualite }, [ic("alerte"), "Problème qualité"])
    ]));
  }

  function afficherErreur(msg) {
    app.innerHTML = "";
    app.appendChild(h("div", { class: "t-erreur" }, [msg]));
  }

  function toast(msg) {
    var ancien = document.querySelector(".t-toast");
    if (ancien) ancien.remove();
    var t = h("div", { class: "t-toast" }, [ic("ok"), msg]);
    document.body.appendChild(t);
    setTimeout(function () { t.remove(); }, 1800);
  }

  function vibrer() { if (navigator.vibrate) try { navigator.vibrate(60); } catch (e) {} }

  // ---------- Actions ----------
  function connecter(id) {
    etat.operator_id = id;
    evenement("connexion");
    etat.compteur = 0;
    etat.derniere = null;
    sauver();
    rendre();
    synchroniserBientot();
  }

  function deconnecter() {
    if (etat.operator_id != null) evenement("deconnexion");
    etat.operator_id = null;
    etat.derniere = null;
    sauver();
    fermerAnnulation();
    rendre();
  }

  function couetteFinie() {
    var maintenant = Date.now();
    // Évite de compter deux fois un double appui involontaire.
    if (maintenant - dernierAppuiCouette < 1500 || etat.panne) return;
    dernierAppuiCouette = maintenant;
    var e = evenement("couette");
    etat.compteur += 1;
    etat.derniere = { uuid: e.uuid, ts: maintenant };
    sauver();
    vibrer();
    var b = document.getElementById("btn-couette");
    if (b) { b.classList.add("flash"); setTimeout(function () { b.classList.remove("flash"); }, 350); }
    var c = document.getElementById("compteur");
    if (c) c.textContent = etat.compteur + " couette" + (etat.compteur > 1 ? "s" : "") + " ce quart";
    proposerAnnulation();
  }

  var minuterieAnnulation = null;
  function proposerAnnulation() {
    fermerAnnulation();
    if (!config.delai_annulation) return;
    var b = h("button", { class: "t-annuler", id: "annuler", onclick: annulerDerniere }, [ic("annuler"), "Annuler la dernière couette"]);
    document.body.appendChild(b);
    minuterieAnnulation = setTimeout(fermerAnnulation, config.delai_annulation * 1000);
  }
  function fermerAnnulation() {
    clearTimeout(minuterieAnnulation);
    var b = document.getElementById("annuler");
    if (b) b.remove();
  }
  function annulerDerniere() {
    if (!etat.derniere) return fermerAnnulation();
    evenement("annulation", { ref: etat.derniere.uuid });
    etat.compteur = Math.max(0, etat.compteur - 1);
    etat.derniere = null;
    sauver();
    fermerAnnulation();
    toast("Dernière couette annulée");
    rendre();
  }

  function debutPanne() {
    confirmer("Déclarer une panne sur ce poste ?", function () {
      evenement("panne_debut");
      etat.panne = new Date().toISOString();
      sauver();
      fermerAnnulation();
      rendre();
    });
  }
  function finPanne() {
    evenement("panne_fin");
    etat.panne = null;
    sauver();
    toast("Fin de panne enregistrée");
    rendre();
  }

  // ---------- Fenêtres ----------
  function modalOuvert() { return !!document.querySelector(".t-modal"); }
  function fermerModal() { var m = document.querySelector(".t-modal"); if (m) m.remove(); }
  function modal(contenu) {
    fermerModal();
    var m = h("div", { class: "t-modal" }, [h("div", { class: "t-boite" }, contenu)]);
    document.body.appendChild(m);
  }

  function confirmer(question, siOui) {
    modal([
      h("h2", {}, [question]),
      h("div", { class: "t-actions" }, [
        h("button", { class: "annuler", onclick: fermerModal }, ["Non"]),
        h("button", { class: "valider", onclick: function () { fermerModal(); siOui(); } }, ["Oui"])
      ])
    ]);
  }

  function ouvrirOF() {
    var saisie = "";
    var affichage = h("div", { class: "t-saisie" }, [""]);
    // Les OF s'écrivent « OF » suivi de chiffres : seul le numéro est à taper.
    function maj() {
      affichage.innerHTML = "";
      affichage.appendChild(h("span", { class: "prefixe" }, ["OF"]));
      affichage.appendChild(document.createTextNode(saisie));
    }
    var touches = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "C"];
    var pave = h("div", { class: "t-pave" }, touches.map(function (t) {
      return h("button", { onclick: function () {
        if (t === "⌫") saisie = saisie.slice(0, -1);
        else if (t === "C") saisie = "";
        else if (saisie.length < 20) saisie += t;
        maj();
      } }, [t]);
    }));
    modal([
      h("h2", {}, ["Numéro du nouvel OF"]),
      affichage, pave,
      h("div", { class: "t-actions" }, [
        h("button", { class: "annuler", onclick: fermerModal }, ["Annuler"]),
        h("button", { class: "valider", onclick: function () {
          if (!saisie) return;
          var of = "OF" + saisie;
          evenement("changement_of", { of: of });
          etat.of = of;
          sauver();
          fermerModal();
          toast(of + " enregistré");
          rendre();
        } }, ["Valider"])
      ])
    ]);
    maj();
  }

  function ouvrirQualite() {
    modal([
      h("h2", {}, ["Quel défaut qualité ?"]),
      h("div", { class: "t-defauts" }, config.defauts.map(function (d) {
        return h("button", { onclick: function () { choisirDecision(d); } }, [d.libelle]);
      })),
      h("div", { class: "t-actions" }, [h("button", { class: "annuler", onclick: fermerModal }, ["Annuler"])])
    ]);
  }

  // Selon l'ampleur du défaut, la couette part en second choix, est
  // retouchée (et repart en 1er choix) ou va au rebut.
  var DECISIONS = [
    { cle: "second_choix", libelle: "Second choix", classe: "d-second", icone: "couches" },
    { cle: "retouche", libelle: "Retouchée → 1er choix", classe: "d-retouche", icone: "ok" },
    { cle: "rebut", libelle: "Rebut", classe: "d-rebut", icone: "alerte" }
  ];
  function choisirDecision(defaut) {
    modal([
      h("h2", {}, ["« " + defaut.libelle + " » : que devient la couette ?"]),
      h("div", { class: "t-decisions" }, DECISIONS.map(function (dec) {
        return h("button", { class: dec.classe, onclick: function () {
          evenement("qualite", { defect_id: defaut.id, decision: dec.cle });
          fermerModal();
          toast(defaut.libelle + " — " + dec.libelle);
        } }, [ic(dec.icone), dec.libelle]);
      })),
      h("div", { class: "t-actions" }, [h("button", { class: "annuler", onclick: ouvrirQualite }, ["← Retour"])])
    ]);
  }

  // ---------- Boucles ----------
  var synchroTimer = null;
  function synchroniserBientot() { clearTimeout(synchroTimer); synchroTimer = setTimeout(function () { synchroniser(false); }, 1500); }

  setInterval(function () {
    var el = document.getElementById("horloge");
    if (el) el.textContent = heure(new Date().toISOString());
    // Changement de quart : la tablette revient à la liste des noms pour que
    // l'équipe suivante se connecte, et le compteur repart de zéro.
    if (etat.fin_quart && Date.now() >= new Date(etat.fin_quart).getTime()) {
      if (etat.operator_id != null) {
        fermerModal();
        deconnecter();
      }
      etat.fin_quart = null;
      etat.compteur = 0;
      sauver();
      synchroniser(false);
    }
  }, 5000);
  setInterval(envoyer, 5000);
  setInterval(function () { if (!file.length) synchroniser(false); }, 60000);
  window.addEventListener("online", envoyer);

  rendre();
  synchroniser(true);
  envoyer();
})();
