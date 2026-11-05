(function () {
  "use strict";
  // Palette catégorielle (ordre fixe, validée daltonisme) : chaque poste garde
  // toujours la même couleur, quel que soit le filtre.
  var PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
  var AUTRE = "#a3a29c", BLEU = "#0079c4", ROUGE = "#e80032", NUIT = "#1c3154";
  var couleurs = {};
  (window.POSTES || []).forEach(function (n, i) { couleurs[n] = i < PALETTE.length ? PALETTE[i] : AUTRE; });
  function couleur(nom) { return couleurs[nom] || AUTRE; }

  Chart.defaults.font.family = "Inter, system-ui, sans-serif";
  Chart.defaults.font.size = 12;
  Chart.defaults.color = "#55617a";
  Chart.defaults.borderColor = "#eef1f5";
  Chart.defaults.locale = "fr-FR";
  Chart.defaults.maintainAspectRatio = false;
  Chart.defaults.plugins.tooltip.backgroundColor = NUIT;
  Chart.defaults.plugins.tooltip.padding = 12;
  Chart.defaults.plugins.tooltip.cornerRadius = 8;
  Chart.defaults.plugins.tooltip.titleFont = { weight: "600" };
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
  Chart.defaults.plugins.legend.labels.pointStyle = "rectRounded";
  Chart.defaults.plugins.legend.labels.boxHeight = 8;
  Chart.defaults.plugins.legend.labels.padding = 14;

  var LIBELLES = { quart: "Quart en cours", jour: "Aujourd'hui", hier: "Hier", semaine: "7 derniers jours", mois: "30 derniers jours", perso: "Dates choisies" };
  var periode = "jour";
  var indicateur = "rendement", derniers = null;
  var graphes = {};
  function $(id) { return document.getElementById(id); }

  // ---------- Formats ----------
  function duree(s) {
    if (s == null) return "—";
    var m = Math.round(s / 60);
    return m >= 60 ? Math.floor(m / 60) + " h " + ("0" + (m % 60)).slice(-2) : m + " min";
  }
  function pct(v) { return v == null ? "—" : v.toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + " %"; }
  function nb(v) { return v == null ? "—" : v.toLocaleString("fr-FR", { maximumFractionDigits: 1 }); }
  function niveau(v) { return v == null ? "neutre" : v >= 95 ? "bon" : v >= 80 ? "moyen" : "faible"; }
  function badge(v) { return '<span class="badge ' + niveau(v) + '">' + pct(v) + "</span>"; }
  // Repères usuels du TRS : 85 % et plus = très bon, moins de 65 % = faible.
  function niveauTrs(v) { return v == null ? "neutre" : v >= 85 ? "bon" : v >= 65 ? "moyen" : "faible"; }
  function badgeTrs(v) { return '<span class="badge ' + niveauTrs(v) + '">' + pct(v) + "</span>"; }
  function jaugeTrs(v) { return '<div class="jauge"><i class="' + niveauTrs(v) + '" style="width:' + Math.min(100, Math.max(0, v || 0)) + '%"></i></div>'; }
  function jauge(v) { return '<div class="jauge"><i class="' + niveau(v) + '" style="width:' + Math.min(100, Math.max(0, v || 0)) + '%"></i></div>'; }
  function esc(t) { var d = document.createElement("div"); d.textContent = t == null ? "" : String(t); return d.innerHTML; }
  function heure(iso) { return new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }); }
  function dateHeure(iso) { return new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); }
  function icone(n) { return '<svg class="ic" aria-hidden="true"><use href="#i-' + n + '"/></svg>'; }

  // ---------- Filtres globaux (gardés dans l'adresse de la page) ----------
  function lireAdresse() {
    var p = new URLSearchParams(location.search);
    periode = p.get("periode") || "jour";
    if (p.get("du")) $("du").value = p.get("du");
    if (p.get("au")) $("au").value = p.get("au");
    ["quart", "operatrice", "poste"].forEach(function (k) { if (p.get(k)) $("f-" + k).value = p.get(k); });
  }
  function params() {
    var p = new URLSearchParams();
    p.set("periode", periode);
    if (periode === "perso") { p.set("du", $("du").value); p.set("au", $("au").value || $("du").value); }
    ["quart", "operatrice", "poste"].forEach(function (k) { if ($("f-" + k).value) p.set(k, $("f-" + k).value); });
    return p.toString();
  }
  function majFiltres() {
    Array.prototype.forEach.call(document.querySelectorAll("#periodes button"), function (b) { b.classList.toggle("actif", b.dataset.p === periode); });
    $("perso").classList.toggle("visible", periode === "perso");
    var puces = [];
    [["quart", "Quart"], ["operatrice", "Opératrice"], ["poste", "Poste"]].forEach(function (k) {
      var s = $("f-" + k[0]);
      if (s.value) puces.push('<span class="puce">' + k[1] + " : " + esc(s.options[s.selectedIndex].text) +
        ' <button type="button" data-effacer="' + k[0] + '" title="Retirer">✕</button></span>');
    });
    $("puces").innerHTML = '<span>Filtres appliqués à tous les indicateurs, graphiques et tableaux :</span> <span class="puce" style="padding-right:11px">' +
      esc(LIBELLES[periode]) + "</span>" + puces.join("");
    $("tout-effacer").style.display = (puces.length || periode !== "jour") ? "" : "none";
  }
  $("puces").addEventListener("click", function (e) {
    var k = e.target.getAttribute("data-effacer");
    if (k) { $("f-" + k).value = ""; charger(); }
  });

  // ---------- Postes en direct ----------
  function chargerDirect() {
    fetch("/api/direct", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (d) {
      $("direct-quart").textContent = d.quart ? "· quart " + d.quart : "· hors quart";
      $("direct").innerHTML = d.postes.map(function (p) {
        var cls = p.panne ? "panne" : p.operatrice ? "prod" : "";
        var statut = p.panne ? '<span class="pastille panne">En panne depuis ' + heure(p.panne) + "</span>"
          : p.operatrice ? '<span class="pastille prod">En production</span>' : '<span class="pastille libre">Libre</span>';
        return '<div class="poste ' + cls + '">' +
          '<div class="haut"><span class="nom">' + esc(p.nom) + "</span>" + statut + "</div>" +
          '<div class="qui">' + (p.operatrice ? "<b>" + esc(p.operatrice) + "</b> depuis " + heure(p.depuis) : "Personne de connecté") + "</div>" +
          '<div class="chiffres"><div><div class="grand">' + p.couettes + '</div><div class="legende">couettes ce quart</div></div>' +
          '<div class="droite">' + badge(p.rendement) + "<span>" + esc(p.of || "Pas d'OF") + "</span>" +
          (p.derniere_couette ? "<span>Dernière : " + heure(p.derniere_couette) + "</span>" : "") + "</div></div>" +
          (p.operatrice ? jauge(p.rendement) : "") + "</div>";
      }).join("") || '<div class="vide">Aucun poste actif.</div>';
    }).catch(function () {});
  }

  // ---------- Chargement ----------
  function charger() {
    var q = params();
    history.replaceState(null, "", "?" + q);
    $("export").href = "/export.csv?" + q;
    majFiltres();
    fetch("/api/tableau?" + q, { cache: "no-store" }).then(function (r) { return r.json(); }).then(afficher);
  }

  function afficher(d) {
    derniers = d;
    $("libelle").textContent = d.periode.libelle;
    var alerte = $("alerte-cadence");
    if (d.sans_cadence.length) {
      alerte.style.display = "";
      alerte.innerHTML = icone("alerte") + "<div>Cadence pas encore renseignée pour : <b>" + d.sans_cadence.map(esc).join(", ") +
        "</b>. Sans cadence, le rendement ne peut pas être calculé. " + '<a href="/cadences">Renseigner les cadences →</a></div>';
    } else alerte.style.display = "none";

    var t = d.total;
    function kpi(ic, cl, etiquette, valeur, sous, vedette, extra) {
      return '<div class="kpi' + (vedette ? " vedette" : "") + '"><div class="tete"><i class="' + cl + '">' + icone(ic) + '</i><span class="etiquette">' + etiquette + "</span></div>" +
        '<div class="valeur">' + valeur + '</div><div class="sous">' + sous + "</div>" + (extra || "") + "</div>";
    }
    $("kpis").innerHTML = [
      kpi("activite", "", "TRS", pct(t.trs), "taux de rendement synthétique", true, jaugeTrs(t.trs) +
        '<div class="decompo"><div><span>Disponibilité</span><b>' + pct(t.disponibilite) + "</b></div>" +
        "<div><span>× Performance</span><b>" + pct(t.rendement) + "</b></div>" +
        "<div><span>× Qualité</span><b>" + pct(t.qualite) + "</b></div></div>"),
      kpi("hausse", "", "Rendement", pct(t.rendement), "couettes réalisées ÷ attendues", false, jauge(t.rendement)),
      kpi("couches", "", "Couettes", nb(t.couettes), "attendues : " + nb(t.attendu)),
      kpi("cadence", "n", "Cadence réelle", t.cadence == null ? "—" : nb(t.cadence) + "<small style='font-size:.55em;font-weight:600'> /h</small>", "par heure productive"),
      kpi("cle", "r", "Pannes", duree(t.panne_s), t.nb_pannes + " panne" + (t.nb_pannes > 1 ? "s" : "")),
      kpi("alerte", "r", "Défauts qualité", nb(t.defauts), nb(t.second_choix) + " 2nd choix · " + nb(t.rebut) + " rebut · " + nb(t.retouche) + " retouchée" + (t.retouche > 1 ? "s" : "")),
      kpi("horloge", "n", "Présence", duree(t.presence_s), "dont pause " + duree(t.pause_s))
    ].join("");

    graphRendement(d.operatrices);
    graphProduction(d.production);
    graphTendance(d.tendance);
    graphDefauts(d.defauts);
    graphPannes(d.postes);
    tables(d);
  }

  function remplacer(id, cfg) {
    if (graphes[id]) graphes[id].destroy();
    graphes[id] = new Chart($(id), cfg);
  }
  function vide(id, oui) {
    var c = $(id), parent = c.parentNode, msg = parent.querySelector(".vide");
    c.style.display = oui ? "none" : "";
    if (oui && !msg) parent.insertAdjacentHTML("beforeend", '<div class="vide">Aucune donnée sur cette période.</div>');
    if (!oui && msg) msg.remove();
    return oui;
  }

  var objectif = {
    id: "objectif",
    afterDatasetsDraw: function (c) {
      var x = c.scales.x;
      if (!x || c.config.options.indexAxis !== "y") return;
      var px = x.getPixelForValue(100), ctx = c.ctx;
      ctx.save();
      ctx.strokeStyle = NUIT; ctx.setLineDash([5, 4]); ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(px, c.chartArea.top); ctx.lineTo(px, c.chartArea.bottom); ctx.stroke();
      ctx.restore();
    }
  };

  function graphRendement(ops) {
    var k = indicateur, nomK = k === "trs" ? "TRS" : "rendement";
    var lignes = ops.filter(function (o) { return o[k] != null; }).sort(function (a, b) { return b[k] - a[k]; });
    $("t-indicateur").textContent = k === "trs" ? "TRS" : "Rendement";
    $("a-indicateur").textContent = k === "trs" ? "Disponibilité × performance × qualité" : "Pointillés : objectif 100 %";
    if (vide("g-rendement", !lignes.length)) return;
    remplacer("g-rendement", {
      type: "bar",
      data: { labels: lignes.map(function (o) { return o.nom; }),
        datasets: [{ data: lignes.map(function (o) { return o[k]; }), backgroundColor: BLEU, hoverBackgroundColor: NUIT,
                     borderRadius: 4, borderSkipped: "start", maxBarThickness: 20 }] },
      options: {
        indexAxis: "y",
        plugins: { legend: { display: false }, tooltip: { callbacks: {
          label: function (c) {
            var o = lignes[c.dataIndex];
            return k === "trs"
              ? ["TRS " + pct(o.trs), "Disponibilité " + pct(o.disponibilite), "Performance " + pct(o.rendement), "Qualité " + pct(o.qualite)]
              : [pct(o.rendement) + " de rendement", o.couettes + " couettes / " + nb(o.attendu) + " attendues"];
          } } } },
        scales: { x: { beginAtZero: true, suggestedMax: 110, ticks: { callback: function (v) { return v + " %"; } } },
                  y: { grid: { display: false }, ticks: { color: "#14213a" } } }
      },
      plugins: k === "rendement" ? [objectif] : []
    });
  }
  Array.prototype.forEach.call(document.querySelectorAll("#indicateur button"), function (b) {
    b.addEventListener("click", function () {
      indicateur = b.dataset.i;
      Array.prototype.forEach.call(document.querySelectorAll("#indicateur button"), function (x) { x.classList.toggle("actif", x === b); });
      if (derniers) graphRendement(derniers.operatrices);
    });
  });

  function graphProduction(p) {
    $("t-production").textContent = p.par_heure ? "Couettes produites par heure" : "Couettes produites par jour";
    var noms = Object.keys(p.series).sort();
    if (vide("g-production", !noms.length)) return;
    remplacer("g-production", {
      type: "bar",
      data: { labels: p.etiquettes,
        datasets: noms.map(function (n) {
          return { label: n, data: p.series[n], backgroundColor: couleur(n), borderColor: "#ffffff", borderWidth: { top: 2 }, borderSkipped: "bottom", maxBarThickness: 34 };
        }) },
      options: {
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { display: noms.length > 1, position: "bottom" } },
        scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } } }
      }
    });
  }

  function graphTendance(t) {
    var noms = Object.keys(t.series).sort();
    var montrer = t.etiquettes.length > 1 && noms.length;
    $("c-tendance").style.display = montrer ? "" : "none";
    if (!montrer) return;
    remplacer("g-tendance", {
      type: "line",
      data: { labels: t.etiquettes,
        datasets: noms.map(function (n) {
          return { label: n, data: t.series[n], borderColor: couleur(n), backgroundColor: couleur(n), borderWidth: 2,
                   pointRadius: 4, pointHoverRadius: 6, pointBorderColor: "#fff", pointBorderWidth: 2, spanGaps: true };
        }) },
      options: {
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "bottom" }, tooltip: { callbacks: { label: function (c) { return " " + c.dataset.label + " : " + pct(c.raw); } } } },
        scales: { y: { beginAtZero: true, ticks: { callback: function (v) { return v + " %"; } } }, x: { grid: { display: false } } }
      }
    });
  }

  function graphDefauts(defs) {
    if (vide("g-defauts", !defs.length)) return;
    // Empilé par décision ; ordre choisi pour que deux couleurs voisines
    // restent distinguables pour les daltoniens.
    var series = [["second_choix", "Second choix", "#eb6834"], ["retouche", "Retouchée → 1er choix", "#1baf7a"], ["rebut", "Rebut", "#e34948"]];
    remplacer("g-defauts", {
      type: "bar",
      data: { labels: defs.map(function (x) { return x.libelle; }),
              datasets: series.map(function (s) {
                return { label: s[1], data: defs.map(function (x) { return x[s[0]]; }), backgroundColor: s[2],
                         borderColor: "#ffffff", borderWidth: { right: 2 }, borderSkipped: "start", maxBarThickness: 20 };
              }) },
      options: { indexAxis: "y", interaction: { mode: "index", intersect: false },
                 plugins: { legend: { position: "bottom" } },
                 scales: { x: { stacked: true, beginAtZero: true, ticks: { precision: 0 } },
                           y: { stacked: true, grid: { display: false }, ticks: { color: "#14213a" } } } }
    });
  }

  function graphPannes(postes) {
    remplacer("g-pannes", {
      type: "bar",
      data: { labels: postes.map(function (p) { return p.nom; }),
              datasets: [{ data: postes.map(function (p) { return Math.round(p.panne_poste_s / 60); }), backgroundColor: ROUGE, borderRadius: 4, borderSkipped: "start", maxBarThickness: 46 }] },
      options: { plugins: { legend: { display: false }, tooltip: { callbacks: {
                   label: function (c) { var p = postes[c.dataIndex]; return duree(p.panne_poste_s) + " · " + p.nb_pannes_poste + " panne(s)"; } } } },
                 scales: { y: { beginAtZero: true, ticks: { precision: 0, callback: function (v) { return v + " min"; } } }, x: { grid: { display: false }, ticks: { color: "#14213a" } } } }
    });
  }

  // ---------- Tableaux ----------
  // colonnes : [titre, clé (ou fonction), options] ; options.f = format,
  // n = numérique, filtre = liste déroulante dans la barre du tableau.
  function table(id, colonnes, lignes) {
    var h = '<table data-tableau="' + id + '"><thead><tr>' + colonnes.map(function (c) {
      var o = c[2] || {};
      return "<th" + (o.n ? ' class="n" data-type="n"' : "") + (o.filtre ? ' data-filtre="' + (o.filtre === 1 ? "" : o.filtre) + '"' : "") + ">" + c[0] + "</th>";
    }).join("") + "</tr></thead><tbody>";
    if (!lignes.length) h += '<tr data-vide><td colspan="' + colonnes.length + '" class="vide">Aucune donnée sur cette période.</td></tr>';
    lignes.forEach(function (l) {
      h += "<tr>" + colonnes.map(function (c) {
        var o = c[2] || {}, v = typeof c[1] === "function" ? c[1](l) : l[c[1]];
        var cls = (o.n ? "n" : "") + (o.fort ? " fort" : "");
        var tri = o.n ? ' data-v="' + (v == null ? "" : v) + '"' : (o.tri ? ' data-v="' + esc(v) + '"' : "");
        return '<td class="' + cls + '"' + tri + ">" + (o.f ? o.f(v, l) : esc(v)) + "</td>";
      }).join("") + "</tr>";
    });
    return h + "</tbody></table>";
  }
  var MESURES = [
    ["Couettes", "couettes", { n: 1, f: nb }], ["Attendues", "attendu", { n: 1, f: nb }], ["Rendement", "rendement", { n: 1, f: badge }],
    ["Cadence /h", "cadence", { n: 1, f: nb }], ["Présence", "presence_s", { n: 1, f: duree }], ["Pannes", "panne_s", { n: 1, f: duree }],
    ["Disponibilité", "disponibilite", { n: 1, f: pct }], ["Qualité", "qualite", { n: 1, f: pct }], ["TRS", "trs", { n: 1, f: badgeTrs }],
    ["Défauts", "defauts", { n: 1, f: nb }], ["1er choix", "premier_choix", { n: 1, f: nb }],
    ["2nd choix", "second_choix", { n: 1, f: nb }], ["Rebut", "rebut", { n: 1, f: nb }]
  ];
  function rendre(conteneur, id, colonnes, lignes) {
    $(conteneur).innerHTML = table(id, colonnes, lignes);
    Tables.activer($(conteneur).querySelector("table"));
  }
  function tables(d) {
    rendre("t-operatrices", "par-operatrice", [["Opératrice", "nom", { fort: 1 }]].concat(MESURES), d.operatrices);
    rendre("t-postes", "par-poste", [["Poste", "nom", { fort: 1 }]].concat(MESURES), d.postes);
    rendre("t-detail", "detail-par-quart", [
      ["Jour", "jour", { filtre: "Tous les jours", tri: 1, f: function (v) { return new Date(v + "T12:00").toLocaleDateString("fr-FR", { weekday: "short", day: "2-digit", month: "2-digit" }); } }],
      ["Quart", "quart", { filtre: "Tous les quarts" }], ["Opératrice", "operatrice", { filtre: "Toutes les opératrices", fort: 1 }], ["Poste", "poste", { filtre: "Tous les postes" }]
    ].concat(MESURES), d.detail);
    rendre("t-of", "par-of", [["OF", "of", { fort: 1 }], ["Couettes", "couettes", { n: 1 }], ["Postes", "postes", { filtre: "Tous les postes" }],
      ["Première couette", "debut", { tri: 1, f: dateHeure }], ["Dernière couette", "fin", { tri: 1, f: dateHeure }]], d.of);
  }

  // ---------- Événements ----------
  Array.prototype.forEach.call(document.querySelectorAll("#periodes button"), function (b) {
    b.addEventListener("click", function () {
      periode = b.dataset.p;
      if (periode === "perso") {
        if (!$("du").value) $("du").value = new Date().toISOString().slice(0, 10);
        majFiltres();
        return;
      }
      charger();
    });
  });
  $("appliquer").addEventListener("click", charger);
  ["f-quart", "f-operatrice", "f-poste"].forEach(function (id) { $(id).addEventListener("change", charger); });
  $("tout-effacer").addEventListener("click", function () {
    periode = "jour"; ["f-quart", "f-operatrice", "f-poste"].forEach(function (id) { $(id).value = ""; }); charger();
  });

  lireAdresse();
  chargerDirect();
  charger();
  setInterval(chargerDirect, 15000);
  // Actualise les chiffres du jour, sauf si quelqu'un est en train de taper dans un filtre.
  setInterval(function () {
    var a = document.activeElement;
    if ((periode === "quart" || periode === "jour") && !(a && a.closest && a.closest(".outils"))) charger();
  }, 60000);
})();
