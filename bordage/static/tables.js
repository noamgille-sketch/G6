/* Tableaux filtrables : recherche, filtre par colonne, tri, export.
 *
 * <table data-tableau="nom-unique">
 *   <thead><tr><th data-filtre>Poste</th><th data-type="n">Couettes</th>...</tr></thead>
 *   <tbody><tr><td>Poste 1</td><td data-v="68">68</td>...</tr></tbody>
 * </table>
 *
 * - th[data-filtre]  : une liste déroulante avec les valeurs de la colonne
 * - th[data-type=n]  : tri numérique (td[data-v] donne la valeur brute)
 * - th[data-pas-tri] : colonne non triable (boutons...)
 * Les choix restent en mémoire quand le tableau est redessiné (actualisation).
 */
window.Tables = (function () {
  "use strict";
  var etats = {};
  try { etats = JSON.parse(sessionStorage.getItem("tables") || "{}"); } catch (e) {}
  function sauver() { try { sessionStorage.setItem("tables", JSON.stringify(etats)); } catch (e) {} }

  function sansAccent(t) { return (t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }
  function texte(td) { return (td.textContent || "").trim(); }
  function valeur(td, num) {
    var v = td.hasAttribute("data-v") ? td.getAttribute("data-v") : texte(td);
    if (!num) return sansAccent(v);
    var n = parseFloat(String(v).replace(/\s/g, "").replace(",", "."));
    return isNaN(n) ? -Infinity : n;
  }
  function el(tag, attrs, html) {
    var e = document.createElement(tag);
    for (var k in attrs || {}) e.setAttribute(k, attrs[k]);
    if (html != null) e.innerHTML = html;
    return e;
  }

  function activer(table) {
    var id = table.getAttribute("data-tableau");
    if (!id || !table.tHead || !table.tBodies.length) return;
    var etat = etats[id] || (etats[id] = { q: "", filtres: {}, tri: null });
    var ths = Array.prototype.slice.call(table.tHead.rows[0].cells);
    var corps = table.tBodies[0];
    var lignes = Array.prototype.slice.call(corps.rows).filter(function (r) { return !r.hasAttribute("data-vide"); });
    var bloc = table.closest(".defile") || table;
    var ancien = bloc.parentNode.querySelector('.outils[data-pour="' + id + '"]');
    if (ancien) ancien.remove();
    if (!lignes.length) return;

    var outils = el("div", { class: "outils", "data-pour": id });
    var recherche = el("label", { class: "recherche" },
      '<svg class="ic" aria-hidden="true"><use href="#i-recherche"/></svg>');
    var champ = el("input", { type: "search", placeholder: "Rechercher…", "aria-label": "Rechercher dans le tableau" });
    champ.value = etat.q;
    recherche.appendChild(champ);
    outils.appendChild(recherche);

    var selects = [];
    ths.forEach(function (th, i) {
      if (!th.hasAttribute("data-filtre")) return;
      var nom = th.textContent.trim();
      var valeurs = {};
      lignes.forEach(function (r) { if (r.cells[i]) valeurs[texte(r.cells[i])] = 1; });
      var liste = Object.keys(valeurs).filter(Boolean).sort(function (a, b) { return a.localeCompare(b, "fr", { numeric: true }); });
      if (liste.length < 2 && !etat.filtres[i]) return;
      var s = el("select", { "aria-label": nom });
      s.appendChild(el("option", { value: "" }, (th.getAttribute("data-filtre") || ("Tous : " + nom.toLowerCase()))));
      liste.forEach(function (v) { var o = el("option", {}); o.value = v; o.textContent = v; s.appendChild(o); });
      if (etat.filtres[i] && valeurs[etat.filtres[i]]) s.value = etat.filtres[i];
      else delete etat.filtres[i];
      s.addEventListener("change", function () { if (s.value) etat.filtres[i] = s.value; else delete etat.filtres[i]; appliquer(); });
      selects.push(s);
      outils.appendChild(s);
    });

    var reinit = el("button", { class: "bouton second petit", type: "button", title: "Effacer les filtres de ce tableau" },
      '<svg class="ic" aria-hidden="true"><use href="#i-reinit"/></svg>Effacer');
    reinit.addEventListener("click", function () {
      etat.q = ""; etat.filtres = {}; champ.value = ""; selects.forEach(function (s) { s.value = ""; }); appliquer();
    });
    outils.appendChild(reinit);
    var compte = el("span", { class: "compte" });
    outils.appendChild(compte);
    var exp = el("button", { class: "bouton second petit", type: "button", title: "Télécharger ce tableau (Excel)" },
      '<svg class="ic" aria-hidden="true"><use href="#i-telecharger"/></svg>Excel');
    exp.addEventListener("click", exporter);
    outils.appendChild(exp);
    bloc.parentNode.insertBefore(outils, bloc);

    champ.addEventListener("input", function () { etat.q = champ.value; appliquer(); });

    ths.forEach(function (th, i) {
      if (th.hasAttribute("data-pas-tri")) return;
      th.classList.add("triable");
      th.onclick = function () {
        if (etat.tri && etat.tri.col === i) etat.tri.dir = etat.tri.dir === "asc" ? "desc" : (etat.tri.dir === "desc" ? null : "asc");
        else etat.tri = { col: i, dir: th.getAttribute("data-type") === "n" ? "desc" : "asc" };
        if (etat.tri && !etat.tri.dir) etat.tri = null;
        appliquer();
      };
    });

    var ordreInitial = lignes.slice();

    function appliquer() {
      var q = sansAccent(etat.q.trim());
      var visibles = 0;
      lignes.forEach(function (r) {
        var ok = !q || sansAccent(r.textContent).indexOf(q) !== -1;
        for (var i in etat.filtres) if (ok && (!r.cells[i] || texte(r.cells[i]) !== etat.filtres[i])) ok = false;
        r.style.display = ok ? "" : "none";
        if (ok) visibles++;
      });
      ths.forEach(function (th, i) {
        th.classList.remove("asc", "desc");
        if (etat.tri && etat.tri.col === i) th.classList.add(etat.tri.dir);
      });
      var ordre = ordreInitial.slice();
      if (etat.tri) {
        var c = etat.tri.col, num = ths[c].getAttribute("data-type") === "n", sens = etat.tri.dir === "asc" ? 1 : -1;
        ordre.sort(function (a, b) {
          var x = valeur(a.cells[c], num), y = valeur(b.cells[c], num);
          return (x < y ? -1 : x > y ? 1 : 0) * sens;
        });
      }
      ordre.forEach(function (r) { corps.appendChild(r); });
      var filtre = q || Object.keys(etat.filtres).length;
      compte.textContent = filtre ? visibles + " sur " + lignes.length + " lignes" : lignes.length + " ligne" + (lignes.length > 1 ? "s" : "");
      reinit.style.display = filtre ? "" : "none";
      sauver();
    }

    function exporter() {
      var cols = ths.map(function (th, i) { return th.hasAttribute("data-pas-export") ? -1 : i; }).filter(function (i) { return i >= 0; });
      var csv = [cols.map(function (i) { return ths[i].textContent.trim(); })];
      Array.prototype.forEach.call(corps.rows, function (r) {
        if (r.style.display === "none" || r.hasAttribute("data-vide")) return;
        csv.push(cols.map(function (i) { return r.cells[i] ? texte(r.cells[i]) : ""; }));
      });
      var contenu = "﻿" + csv.map(function (l) {
        return l.map(function (c) { return /[";\n]/.test(c) ? '"' + c.replace(/"/g, '""') + '"' : c; }).join(";");
      }).join("\r\n");
      var a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([contenu], { type: "text/csv;charset=utf-8" }));
      a.download = id + ".csv";
      document.body.appendChild(a); a.click(); a.remove();
    }

    appliquer();
  }

  function tout() { Array.prototype.forEach.call(document.querySelectorAll("table[data-tableau]"), activer); }
  document.addEventListener("DOMContentLoaded", tout);
  return { activer: activer, tout: tout };
})();
