// ==UserScript==
// @name         G6 Ban Helper — staff.unityrp.io
// @namespace    g6-anticheat-brigade
// @version      1.0.0
// @description  Copie en un clic (ou une touche) la commande /ban à partir d'une ligne de log anticheat, sans retaper l'ID à la main.
// @author       Brigade anticheat G6
// @match        https://staff.unityrp.io/logs*
// @grant        GM_setClipboard
// @grant        GM_setValue
// @grant        GM_getValue
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  // ---------------------------------------------------------------------
  // Réglages (persistés dans Tampermonkey, chaque collègue peut les changer
  // depuis le petit ⚙️ du widget flottant sans toucher au code)
  // ---------------------------------------------------------------------
  const store = {
    get(key, fallback) {
      try {
        if (typeof GM_getValue === 'function') return GM_getValue(key, fallback);
      } catch (e) {}
      try {
        const raw = localStorage.getItem('g6bh_' + key);
        return raw === null ? fallback : JSON.parse(raw);
      } catch (e) {
        return fallback;
      }
    },
    set(key, value) {
      try {
        if (typeof GM_setValue === 'function') return GM_setValue(key, value);
      } catch (e) {}
      try {
        localStorage.setItem('g6bh_' + key, JSON.stringify(value));
      } catch (e) {}
    },
  };

  const settings = {
    template: store.get('template', '/ban {id} 0 cheat'),
    hoverKey: store.get('hoverKey', 'b'),
    globalHotkey: store.get('globalHotkey', 'ctrl+shift+b'),
    sound: store.get('sound', true),
  };

  function saveSettings() {
    store.set('template', settings.template);
    store.set('hoverKey', settings.hoverKey);
    store.set('globalHotkey', settings.globalHotkey);
    store.set('sound', settings.sound);
  }

  function buildCommand(id) {
    return settings.template.replace('{id}', id);
  }

  // ---------------------------------------------------------------------
  // Presse-papier
  // ---------------------------------------------------------------------
  function copyToClipboard(text) {
    if (typeof GM_setClipboard === 'function') {
      GM_setClipboard(text);
      return Promise.resolve();
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    // Fallback ultime : textarea invisible + execCommand
    return new Promise((resolve, reject) => {
      try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        resolve();
      } catch (e) {
        reject(e);
      }
    });
  }

  // ---------------------------------------------------------------------
  // Toast de confirmation
  // ---------------------------------------------------------------------
  function toast(message, isError) {
    const el = document.createElement('div');
    el.textContent = message;
    Object.assign(el.style, {
      position: 'fixed',
      bottom: '20px',
      left: '50%',
      transform: 'translateX(-50%)',
      background: isError ? '#c0392b' : '#1f8a4c',
      color: '#fff',
      padding: '10px 16px',
      borderRadius: '8px',
      fontFamily: 'system-ui, sans-serif',
      fontSize: '13px',
      zIndex: 999999,
      boxShadow: '0 4px 14px rgba(0,0,0,.3)',
      transition: 'opacity .25s',
    });
    document.body.appendChild(el);
    setTimeout(() => {
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 300);
    }, 1600);
  }

  function beep() {
    if (!settings.sound) return;
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = 880;
      gain.gain.value = 0.05;
      osc.connect(gain).connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.15);
    } catch (e) {}
  }

  // ---------------------------------------------------------------------
  // Extraction nom + ID depuis le texte de la page
  //   ex: "Walid Miller" 213.walid [7874]
  //
  // Le panel ne rend pas forcément un <table>/<tr> classique (il n'en a
  // aucun sur staff.unityrp.io), donc on ne peut pas se fier à des
  // sélecteurs CSS. À la place on descend l'arbre DOM pour trouver le plus
  // petit élément qui contient encore le motif complet — ça fonctionne
  // quel que soit le balisage réel (div, span, lien...).
  // ---------------------------------------------------------------------
  const WITH_ID_RE = /"([^"]+)"[^"\[\]]*?\[(\d+)\]/g;
  const NAME_ONLY_RE = /"([^"]+)"/g;

  function contextIncludes(el, pattern, maxLevels) {
    let node = el;
    for (let i = 0; i < maxLevels && node; i++) {
      if (pattern.test(node.textContent || '')) return true;
      node = node.parentElement;
    }
    return false;
  }

  // Renvoie les éléments les plus profonds qui contiennent encore, dans
  // leur propre textContent, au moins une correspondance de `regex` —
  // c'est-à-dire qu'aucun de leurs enfants ne matche déjà à lui seul.
  function findInnermostMatches(root, regex) {
    const found = [];
    function test(el) {
      regex.lastIndex = 0;
      return regex.test(el.textContent || '');
    }
    function walk(el) {
      if (el.dataset && el.dataset.g6bhProcessed) return;
      if (!test(el)) return;
      let childMatched = false;
      for (const child of el.children) {
        if (test(child)) {
          childMatched = true;
          walk(child);
        }
      }
      if (!childMatched) found.push(el);
    }
    walk(root);
    return found;
  }

  function matchesOf(el, regex) {
    regex.lastIndex = 0;
    return [...(el.textContent || '').matchAll(regex)].map((m) => ({ name: m[1], id: m[2] || null }));
  }

  // ---------------------------------------------------------------------
  // Action "copier la commande de ban" pour un joueur donné
  // ---------------------------------------------------------------------
  function copyBanFor(player, buttonEl) {
    let id = player.id;
    if (!id) {
      id = window.prompt(
        `ID introuvable automatiquement pour "${player.name}".\nEntre son ID pour générer la commande :`
      );
      if (!id) return;
    }
    const cmd = buildCommand(id.trim());
    copyToClipboard(cmd).then(
      () => {
        toast(`Copié : ${cmd}`);
        if (buttonEl) flashButton(buttonEl);
      },
      () => toast("Échec de la copie dans le presse-papier", true)
    );
  }

  function flashButton(buttonEl) {
    const original = buttonEl.textContent;
    buttonEl.textContent = '✓ Copié';
    buttonEl.style.background = '#1f8a4c';
    setTimeout(() => {
      buttonEl.textContent = original;
      buttonEl.style.background = '';
    }, 900);
  }

  // ---------------------------------------------------------------------
  // Injection du bouton sur chaque ligne de log "anticheat"
  // ---------------------------------------------------------------------
  let hoveredPlayer = null;

  function makeBanButton(player) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = '🚫 Ban';
    btn.title = player.id
      ? `Copier "${buildCommand(player.id)}"`
      : 'ID non détecté — clique pour le saisir';
    Object.assign(btn.style, {
      marginLeft: '10px',
      padding: '2px 8px',
      fontSize: '12px',
      fontWeight: '600',
      color: '#fff',
      background: player.id ? '#e0562f' : '#888',
      border: 'none',
      borderRadius: '6px',
      cursor: 'pointer',
      verticalAlign: 'middle',
    });
    btn.addEventListener('click', (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      copyBanFor(player, btn);
    });
    return btn;
  }

  function attachButton(el, player) {
    el.dataset.g6bhProcessed = '1';
    const btn = makeBanButton(player);
    // insertAdjacentElement plutôt que appendChild : si `el` est un <a>,
    // imbriquer un <button> dedans casserait le clic / la navigation.
    el.insertAdjacentElement('afterend', btn);

    const hoverScope = el.parentElement || el;
    hoverScope.addEventListener('mouseenter', () => (hoveredPlayer = player));
    hoverScope.addEventListener('mouseleave', () => {
      if (hoveredPlayer === player) hoveredPlayer = null;
    });

    notifyNewDetection(player);
  }

  function processRows() {
    // Passe 1 : lignes avec un ID explicite "[1234]".
    findInnermostMatches(document.body, WITH_ID_RE).forEach((el) => {
      if (!contextIncludes(el, /anticheat/i, 8)) return;
      matchesOf(el, WITH_ID_RE).forEach((player) => attachButton(el, player));
    });

    // Passe 2 : lignes anticheat où seul le nom apparaît (ID absent du
    // texte) — on propose quand même un bouton, qui demandera l'ID à la
    // saisie au clic plutôt que de rester invisible.
    findInnermostMatches(document.body, NAME_ONLY_RE).forEach((el) => {
      if (!contextIncludes(el, /d[ée]clench[ée]/i, 4)) return;
      if (!contextIncludes(el, /anticheat/i, 8)) return;
      matchesOf(el, NAME_ONLY_RE).forEach((player) => attachButton(el, player));
    });
  }

  // ---------------------------------------------------------------------
  // Widget flottant : toujours la dernière détection sous la main
  // ---------------------------------------------------------------------
  let widget, widgetLabel, widgetBtn;
  let latestPlayer = null;
  let baselineDone = false;

  function buildWidget() {
    widget = document.createElement('div');
    Object.assign(widget.style, {
      position: 'fixed',
      right: '18px',
      bottom: '18px',
      width: '260px',
      background: '#1e1e24',
      color: '#fff',
      borderRadius: '10px',
      boxShadow: '0 6px 20px rgba(0,0,0,.4)',
      fontFamily: 'system-ui, sans-serif',
      zIndex: 999998,
      overflow: 'hidden',
      border: '1px solid #333',
    });

    const header = document.createElement('div');
    header.textContent = '🚨 Dernière détection anticheat';
    Object.assign(header.style, {
      padding: '8px 10px',
      fontSize: '12px',
      fontWeight: '700',
      background: '#e0562f',
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
    });

    const gear = document.createElement('span');
    gear.textContent = '⚙️';
    gear.style.cursor = 'pointer';
    gear.title = 'Réglages';
    gear.addEventListener('click', openSettings);
    header.appendChild(gear);

    const body = document.createElement('div');
    body.style.padding = '10px';

    widgetLabel = document.createElement('div');
    widgetLabel.textContent = 'En attente d’une détection…';
    Object.assign(widgetLabel.style, { fontSize: '13px', marginBottom: '8px', wordBreak: 'break-word' });

    widgetBtn = document.createElement('button');
    widgetBtn.type = 'button';
    widgetBtn.textContent = `Copier le ban (${settings.globalHotkey})`;
    widgetBtn.disabled = true;
    Object.assign(widgetBtn.style, {
      width: '100%',
      padding: '8px',
      fontSize: '13px',
      fontWeight: '700',
      color: '#fff',
      background: '#555',
      border: 'none',
      borderRadius: '6px',
      cursor: 'not-allowed',
    });
    widgetBtn.addEventListener('click', () => {
      if (latestPlayer) copyBanFor(latestPlayer, widgetBtn);
    });

    body.appendChild(widgetLabel);
    body.appendChild(widgetBtn);
    widget.appendChild(header);
    widget.appendChild(body);
    document.body.appendChild(widget);
  }

  function notifyNewDetection(player) {
    if (!baselineDone) return; // on ignore les 100 lignes déjà présentes au chargement
    latestPlayer = player;
    widgetLabel.textContent = `${player.name}${player.id ? ' — ID ' + player.id : ' — ID inconnu'}`;
    widgetBtn.disabled = false;
    widgetBtn.style.background = '#e0562f';
    widgetBtn.style.cursor = 'pointer';
    widget.style.outline = '2px solid #ffcc00';
    setTimeout(() => (widget.style.outline = 'none'), 1200);
    beep();
  }

  // ---------------------------------------------------------------------
  // Réglages (petit panneau modal)
  // ---------------------------------------------------------------------
  function openSettings() {
    const overlay = document.createElement('div');
    Object.assign(overlay.style, {
      position: 'fixed',
      inset: '0',
      background: 'rgba(0,0,0,.5)',
      zIndex: 1000000,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
    });

    const box = document.createElement('div');
    Object.assign(box.style, {
      background: '#fff',
      color: '#111',
      padding: '18px',
      borderRadius: '10px',
      width: '320px',
      fontFamily: 'system-ui, sans-serif',
      fontSize: '13px',
    });

    box.innerHTML = `
      <h3 style="margin:0 0 10px;font-size:15px;">Réglages — G6 Ban Helper</h3>
      <label style="display:block;margin-bottom:8px;">
        Modèle de commande (<code>{id}</code> remplacé par l'ID)
        <input id="g6bh-template" style="width:100%;box-sizing:border-box;margin-top:4px;padding:4px;" value="${settings.template}">
      </label>
      <label style="display:block;margin-bottom:8px;">
        Touche à presser en survolant une ligne
        <input id="g6bh-hoverkey" style="width:100%;box-sizing:border-box;margin-top:4px;padding:4px;" value="${settings.hoverKey}">
      </label>
      <label style="display:block;margin-bottom:8px;">
        <input id="g6bh-sound" type="checkbox" ${settings.sound ? 'checked' : ''}>
        Bip sonore sur nouvelle détection
      </label>
      <div style="text-align:right;margin-top:10px;">
        <button id="g6bh-close" style="padding:6px 12px;margin-right:6px;">Annuler</button>
        <button id="g6bh-save" style="padding:6px 12px;background:#e0562f;color:#fff;border:none;border-radius:6px;">Enregistrer</button>
      </div>
    `;

    overlay.appendChild(box);
    document.body.appendChild(overlay);

    box.querySelector('#g6bh-close').addEventListener('click', () => overlay.remove());
    overlay.addEventListener('click', (ev) => {
      if (ev.target === overlay) overlay.remove();
    });
    box.querySelector('#g6bh-save').addEventListener('click', () => {
      settings.template = box.querySelector('#g6bh-template').value || '/ban {id} 0 cheat';
      settings.hoverKey = (box.querySelector('#g6bh-hoverkey').value || 'b').toLowerCase();
      settings.sound = box.querySelector('#g6bh-sound').checked;
      saveSettings();
      overlay.remove();
      toast('Réglages enregistrés');
    });
  }

  // ---------------------------------------------------------------------
  // Raccourcis clavier
  // ---------------------------------------------------------------------
  function isTypingContext(ev) {
    const tag = (ev.target && ev.target.tagName) || '';
    return tag === 'INPUT' || tag === 'TEXTAREA' || ev.target.isContentEditable;
  }

  document.addEventListener('keydown', (ev) => {
    if (isTypingContext(ev)) return;

    // Touche de survol (par défaut "b") -> ban de la ligne survolée
    if (!ev.ctrlKey && !ev.metaKey && !ev.altKey && ev.key.toLowerCase() === settings.hoverKey) {
      if (hoveredPlayer) {
        ev.preventDefault();
        copyBanFor(hoveredPlayer, null);
      }
      return;
    }

    // Raccourci global (par défaut Ctrl+Shift+B) -> ban de la dernière détection
    if (ev.ctrlKey && ev.shiftKey && ev.key.toLowerCase() === 'b') {
      ev.preventDefault();
      if (latestPlayer) copyBanFor(latestPlayer, widgetBtn);
      else toast('Aucune nouvelle détection pour le moment', true);
    }
  });

  // ---------------------------------------------------------------------
  // Démarrage
  // ---------------------------------------------------------------------
  function start() {
    buildWidget();
    processRows();
    // Les 100 lignes déjà à l'écran au chargement ne doivent pas spammer
    // le widget/le bip : on active les alertes seulement après ce premier passage.
    baselineDone = true;

    const observer = new MutationObserver(() => {
      clearTimeout(start._t);
      start._t = setTimeout(processRows, 150);
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
