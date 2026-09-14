# G6 Ban Helper

Userscript de navigateur pour le panel de logs de la brigade anticheat
(`staff.unityrp.io/logs`). Il ne bannit **jamais** tout seul — il te fait
gagner le temps de retaper `/ban <ID> 0 cheat` à la main : dès qu'une ligne
de log "anticheat" est identifiée, un bouton (ou une touche) copie la
commande complète dans le presse-papier. Tu passes en jeu, `T`, `Ctrl+V`,
Entrée.

## Installation (2 minutes)

1. Installe l'extension **Tampermonkey** dans ton navigateur (Chrome,
   Firefox, Edge... tous supportés) :
   https://www.tampermonkey.net/
2. Ouvre le fichier
   [`ban-helper.user.js`](./ban-helper.user.js) sur GitHub, clique
   **Raw**.
3. Tampermonkey détecte automatiquement le script et propose de
   l'installer — clique **Installer**.
4. Va sur `https://staff.unityrp.io/logs...` : un petit encart apparaît
   en bas à droite ("🚨 Dernière détection anticheat").

Pour partager avec un collègue de la brigade : envoie-lui simplement le lien
GitHub **Raw** ci-dessus, ou le fichier `.user.js` en pièce jointe. Il n'a
que Tampermonkey à installer, rien côté serveur.

## Utilisation

Trois façons de récupérer la commande de ban, du plus précis au plus
rapide :

1. **Bouton "🚫 Ban" sur la ligne.** Chaque ligne de log identifiée comme
   une détection anticheat reçoit un bouton en bout de ligne. Un clic copie
   `/ban <ID> 0 cheat` dans le presse-papier.
2. **Touche `B` en survolant une ligne.** Pas besoin de viser le bouton :
   passe la souris sur la ligne et appuie sur `B` (configurable).
3. **`Ctrl+Shift+B` — la dernière détection, où que tu sois sur la page.**
   L'encart en bas à droite garde toujours la détection la plus récente en
   mémoire (uniquement celles arrivées *après* le chargement de la page, pas
   les 100 lignes d'historique déjà affichées). Ce raccourci copie sa
   commande immédiatement, avec un bip et un flash visuel à l'arrivée d'une
   nouvelle détection pour que tu ne la rates pas même en faisant autre
   chose sur la page.

Dans tous les cas : un message vert en bas de l'écran confirme ce qui a été
copié, pour être sûr de ne pas coller la mauvaise commande en jeu.

Si l'ID du joueur n'a pas pu être extrait automatiquement de la ligne (ça
arrive sur certains types de détection qui n'affichent pas `[ID]` dans
l'en-tête), le script te le demande via une petite fenêtre avant de générer
la commande — jamais de copie silencieuse d'une commande incomplète.

## Réglages (⚙️ sur l'encart)

- **Modèle de commande** : par défaut `/ban {id} 0 cheat`. Si un jour la
  brigade change de syntaxe (durée, raison...), modifie ce modèle sans
  toucher au code — `{id}` est remplacé par l'ID détecté.
- **Touche de survol** : `b` par défaut.
- **Bip sonore** : activable/désactivable.

Ces réglages sont propres à chaque navigateur/personne (stockés localement
par Tampermonkey), donc chacun peut les adapter à ses habitudes sans
impacter les autres.

## Limites connues

- Ça reste un script de navigateur : il copie la commande, il ne l'envoie
  jamais dans le jeu à ta place (aucune simulation de touches côté jeu —
  plus fiable et sans ambiguïté vis-à-vis des règles anti-macro).
- L'extraction de l'ID repose sur le format `"Nom" ... [1234]` visible dans
  l'en-tête du log. Si le panel change de format d'affichage, le repli
  "saisie manuelle" prend automatiquement le relais.
- Vérifie toujours la date de création du personnage / l'historique du
  joueur comme tu le fais déjà avant de valider le ban — ce script ne
  remplace pas ce jugement, il ne fait que t'éviter de retaper la commande.
