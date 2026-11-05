(function () {
  "use strict";
  // Palette catégorielle (ordre fixe, validée daltonisme). Chaque poste
  // garde toujours la même couleur, quel que soit le filtre.
  var PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
  var AUTRE = "#a3a29c";
  var ROUGE = "#d03b3b";
  var couleurs = {};
  (window.POSTES || []).forEach(function (n, i) { couleurs[n] = i < PALETTE.length ? PALETTE[i] : AUTRE; });
  function couleur(nom) { return couleurs[nom] || AUTRE; }

  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.color = "#52514e";
  Chart.defaults.borderColor = "#ebeae5";
  Chart.defaults.plugins.tooltip.backgroundColor = "#1f2a37";
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.maintainAspectRatio = false;
  Chart.defaults.locale = "fr-FR";

  var periode = "jour";
  var graphes = {};

  function $(id) { return document.getElementById(id); }
  function params() {
    var p = new URLSearchParams();
    p.set("periode", periode);
    if (periode === "perso") { p.set("du", $("du").value); p.set("au", $("au").value || $("du").value); }
    if ($("f-quart").value) p.set("quart", $("f-quart").value);
    if ($("f-operatrice").value) p.set("operatrice", $("f-operatrice").value);
    if ($("f-poste").value) p.set("poste", $("f-poste").value);
    return p.toString();
  }
  function duree(s) {
    if (s == null) return "—";
    var m = Math.round(s / 60);
    return m >= 60 ? Math.floor(m / 60) + " h " + ("0" + (m % 60)).slice(-2) : m + " min";
  }
  function pct(v) { return v == null ? "—" : v.toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + " %"; }
  function nb(v) { return v == null ? "—" : v.toLocaleString("fr-FR", { maximumFractionDigits: 1 }); }
  function badge(v) {
    if (v == null) return "—";
    var c = v >= 95 ? "bon" : v >= 80 ? "moyen" : "faible";
    return '<span class="badge ' + c + '">' + pct(v) + "</span>";
  }
  function esc(t) { var d = document.createElement("div"); d.textContent = t == null ? "" : String(t); return d.innerHTML; }
  function heure(iso) { return new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }); }
  function dateHeure(iso) { return new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); }

  // ---------- Postes en direct ----------
  function chargerDirect() {
    fetch("/api/direct", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (d) {
      $("direct-quart").textContent = d.quart ? "· quart " + d.quart : "· hors quart";
      $("direct").innerHTML = d.postes.map(function (p) {
        var cls = p.panne ? "panne" : p.operatrice ? "prod" : "";
        var statut = p.panne ? "⚠ EN PANNE depuis " + heure(p.panne) : p.operatrice ? "● En production" : "○ Libre";
        return '<div class="poste ' + cls + '">' +
          '<div class="titre"><span>' + esc(p.nom) + '</span><span class="statut">' + statut + "</span></div>" +
          '<div class="muted">' + (p.operatrice ? esc(p.operatrice) + " depuis " + heure(p.depuis) : "Personne de connecté") + "</div>" +
          '<div style="display:flex;justify-content:space-between;align-items:end;margin-top:.4rem">' +
          '<div><div class="grand">' + p.couettes + '</div><div class="muted petit">couettes ce quart</div></div>' +
          '<div style="text-align:right"><div>' + badge(p.rendement) + '</div><div class="muted petit">' + esc(p.of || "Pas d'OF") + "</div>" +
          (p.derniere_couette ? '<div class="muted petit">dernière à ' + heure(p.derniere_couette) + "</div>" : "") +
          "</div></div></div>";
      }).join("") || '<div class="vide">Aucun poste actif.</div>';
    }).catch(function () {});
  }

  // ---------- Période et filtres ----------
  function charger() {
    var q = params();
    $("export").href = "/export.csv?" + q;
    fetch("/api/tableau?" + q, { cache: "no-store" }).then(function (r) { return r.json(); }).then(afficher);
  }

  function afficher(d) {
    $("libelle").textContent = d.periode.libelle;
    var alerte = $("alerte-cadence");
    if (d.sans_cadence.length) {
      alerte.style.display = "";
      alerte.innerHTML = "Cadence pas encore renseignée pour : <b>" + d.sans_cadence.map(esc).join(", ") +
        "</b>. Sans cadence, le rendement de ces postes ne peut pas être calculé. " +
        '<a href="/cadences">Renseigner les cadences</a>';
    } else alerte.style.display = "none";
    var t = d.total;
    $("kpis").innerHTML = [
      ["Couettes", nb(t.couettes), "attendues : " + nb(t.attendu)],
      ["Rendement", pct(t.rendement), "réalisé ÷ attendu"],
      ["Cadence réelle", t.cadence == null ? "—" : nb(t.cadence) + " /h", "couettes par heure productive"],
      ["Disponibilité", pct(t.disponibilite), "temps hors panne"],
      ["Pannes", duree(t.panne_s), t.nb_pannes + " panne(s)"],
      ["Défauts qualité", nb(t.defauts), t.taux_defaut == null ? "" : pct(t.taux_defaut) + " des couettes"],
      ["Temps de présence", duree(t.presence_s), "dont pause " + duree(t.pause_s)]
    ].map(function (k) {
      return '<div class="kpi"><div class="etiquette">' + k[0] + '</div><div class="valeur">' + k[1] + '</div><div class="sous">' + k[2] + "</div></div>";
    }).join("");

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

  // Ligne d'objectif à 100 % sur le graphe de rendement.
  var objectif = {
    id: "objectif",
    afterDatasetsDraw: function (c) {
      var x = c.scales.x;
      if (!x || c.config.options.indexAxis !== "y") return;
      var px = x.getPixelForValue(100), ctx = c.ctx;
      ctx.save();
      ctx.strokeStyle = "#52514e"; ctx.setLineDash([4, 4]); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(px, c.chartArea.top); ctx.lineTo(px, c.chartArea.bottom); ctx.stroke();
      ctx.restore();
    }
  };

  function graphRendement(ops) {
    var lignes = ops.filter(function (o) { return o.rendement != null; });
    remplacer("g-rendement", {
      type: "bar",
      data: {
        labels: lignes.map(function (o) { return o.nom; }),
        datasets: [{
          data: lignes.map(function (o) { return o.rendement; }),
          backgroundColor: lignes.map(function (o) { return "#2a78d6"; }),
          borderRadius: 4, borderSkipped: "start", barThickness: 22
        }]
      },
      options: {
        indexAxis: "y",
        plugins: { legend: { display: false }, tooltip: { callbacks: {
          label: function (c) { var o = lignes[c.dataIndex]; return [pct(o.rendement) + " de rendement", o.couettes + " couettes / " + nb(o.attendu) + " attendues"]; }
        } } },
        scales: { x: { beginAtZero: true, suggestedMax: 110, ticks: { callback: function (v) { return v + " %"; } } }, y: { grid: { display: false } } }
      },
      plugins: [objectif]
    });
  }

  function graphProduction(p) {
    $("t-production").textContent = p.par_heure ? "Couettes produites par heure" : "Couettes produites par jour";
    var noms = Object.keys(p.series);
    remplacer("g-production", {
      type: "bar",
      data: {
        labels: p.etiquettes,
        datasets: noms.map(function (n) {
          return { label: n, data: p.series[n], backgroundColor: couleur(n), borderColor: "#fcfcfb", borderWidth: { top: 2 }, borderSkipped: "bottom", borderRadius: 0 };
        })
      },
      options: {
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { display: noms.length > 1, position: "bottom", labels: { boxWidth: 12 } } },
        scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } } }
      }
    });
  }

  function graphTendance(t) {
    var noms = Object.keys(t.series);
    $("c-tendance").style.display = t.etiquettes.length > 1 ? "" : "none";
    if (t.etiquettes.length <= 1) return;
    remplacer("g-tendance", {
      type: "line",
      data: {
        labels: t.etiquettes,
        datasets: noms.map(function (n) {
          return { label: n, data: t.series[n], borderColor: couleur(n), backgroundColor: couleur(n), borderWidth: 2, pointRadius: 4, pointHoverRadius: 6, spanGaps: true, tension: 0 };
        })
      },
      options: {
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } },
                   tooltip: { callbacks: { label: function (c) { return c.dataset.label + " : " + pct(c.raw); } } } },
        scales: { y: { beginAtZero: true, ticks: { callback: function (v) { return v + " %"; } } }, x: { grid: { display: false } } }
      }
    });
  }

  function graphDefauts(defs) {
    remplacer("g-defauts", {
      type: "bar",
      data: { labels: defs.map(function (x) { return x.libelle; }),
              datasets: [{ data: defs.map(function (x) { return x.nombre; }), backgroundColor: "#eb6834", borderRadius: 4, borderSkipped: "start", barThickness: 20 }] },
      options: { indexAxis: "y", plugins: { legend: { display: false } },
                 scales: { x: { beginAtZero: true, ticks: { precision: 0 } }, y: { grid: { display: false } } } }
    });
  }

  function graphPannes(postes) {
    remplacer("g-pannes", {
      type: "bar",
      data: { labels: postes.map(function (p) { return p.nom; }),
              datasets: [{ data: postes.map(function (p) { return Math.round(p.panne_poste_s / 60); }), backgroundColor: ROUGE, borderRadius: 4, borderSkipped: "start", barThickness: 32 }] },
      options: { plugins: { legend: { display: false }, tooltip: { callbacks: {
                   label: function (c) { var p = postes[c.dataIndex]; return duree(p.panne_poste_s) + " · " + p.nb_pannes_poste + " panne(s)"; } } } },
                 scales: { y: { beginAtZero: true, title: { display: true, text: "minutes" }, ticks: { precision: 0 } }, x: { grid: { display: false } } } }
    });
  }

  function table(entetes, lignes) {
    if (!lignes.length) return '<div class="vide">Aucune donnée sur cette période.</div>';
    return "<table><tr>" + entetes.map(function (e) { return '<th class="' + (e[1] || "") + '">' + e[0] + "</th>"; }).join("") + "</tr>" +
      lignes.map(function (l) { return "<tr>" + l.map(function (c, i) { return '<td class="' + (entetes[i][1] || "") + '">' + c + "</td>"; }).join("") + "</tr>"; }).join("") + "</table>";
  }

  function tables(d) {
    var cols = [["Couettes", "n"], ["Attendues", "n"], ["Rendement", "n"], ["Cadence /h", "n"], ["Présence", "n"], ["Pannes", "n"], ["Disponibilité", "n"], ["Défauts", "n"]];
    function valeurs(r) { return [r.couettes, nb(r.attendu), badge(r.rendement), nb(r.cadence), duree(r.presence_s), duree(r.panne_s), pct(r.disponibilite), r.defauts]; }
    $("t-operatrices").innerHTML = table([["Opératrice"]].concat(cols), d.operatrices.map(function (r) {
      return [esc(r.nom)].concat(valeurs(r));
    }));
    $("t-detail").innerHTML = table([["Jour"], ["Quart"], ["Opératrice"], ["Poste"]].concat(cols), d.detail.map(function (r) {
      return [new Date(r.jour + "T12:00").toLocaleDateString("fr-FR"), esc(r.quart), esc(r.operatrice), esc(r.poste)].concat(valeurs(r));
    }));
    $("t-of").innerHTML = table([["OF"], ["Couettes", "n"], ["Postes"], ["Première couette"], ["Dernière couette"]], d.of.map(function (r) {
      return [esc(r.of), r.couettes, esc(r.postes), dateHeure(r.debut), dateHeure(r.fin)];
    }));
  }

  // ---------- Événements ----------
  Array.prototype.forEach.call(document.querySelectorAll("#periodes button"), function (b) {
    b.addEventListener("click", function () {
      Array.prototype.forEach.call(document.querySelectorAll("#periodes button"), function (x) { x.classList.toggle("actif", x === b); });
      periode = b.dataset.p;
      $("perso").classList.toggle("visible", periode === "perso");
      if (periode === "perso") {
        if (!$("du").value) $("du").value = new Date().toISOString().slice(0, 10);
        return;
      }
      charger();
    });
  });
  $("appliquer").addEventListener("click", charger);
  ["f-quart", "f-operatrice", "f-poste"].forEach(function (id) { $(id).addEventListener("change", charger); });

  chargerDirect();
  charger();
  setInterval(chargerDirect, 15000);
  setInterval(function () { if (periode === "quart" || periode === "jour") charger(); }, 60000);
})();
