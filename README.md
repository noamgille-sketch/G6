# G6 Guard

Scanner heuristique, en mode utilisateur, pour repérer sur **ta propre machine** les
traces classiques d'un cheat FiveM (DLL injectée, module manuellement mappé,
driver kernel vulnérable, autorun suspect, plugin ASI ajouté en douce, etc.),
avec un petit dashboard web local pour consulter l'historique des scans.

## Ce que ce n'est PAS

Ce n'est pas Echo AC. Echo AC (comme la plupart des vrais anticheats commerciaux)
tourne en partie en **kernel mode** via un driver signé, s'intègre au moteur du
jeu, et dispose d'une base de signatures mise à jour côté serveur en continu.
Un outil user-mode qui tourne à côté du jeu ne peut pas voir tout ce qu'un
kernel driver voit, et un cheat suffisamment sophistiqué (surtout un cheat
kernel-mode via BYOVD bien fait) peut se planquer d'un scanner comme celui-ci.

Ce que fait ce projet : appliquer les heuristiques publiques les plus fiables
(module non backé par un fichier = mapping manuel, driver sur liste noire de
vulnérabilités connues, DLL supprimée du disque juste après injection, fichier
apparu dans le dossier plugins FiveM depuis le dernier scan...) pour te donner
un signal utile, pas une garantie à 100 %.

## Comment ça détecte

| Check | Fichier | Ce qu'il regarde |
|---|---|---|
| `cheat_scan` | `g6_anticheat/checks/cheat_scan.py` | **Identifie le cheat par son nom** : process, fichiers et dossiers correspondant à une famille connue (voir plus bas) |
| `processes` | `g6_anticheat/checks/processes.py` | Noms de process / lignes de commande matchant des mots-clés connus (injector, loader, spoofer, hwid...), process lancés depuis Temp/Downloads pendant que le jeu tourne |
| `memory` | `g6_anticheat/checks/memory.py` | **Windows only.** Modules "fantômes" (DLL chargée en mémoire mais supprimée du disque) et mémoire exécutable privée non backée par un fichier (signature classique du manual mapping) dans `FiveM_GTAProcess.exe` / `GTA5.exe` |
| `drivers` | `g6_anticheat/checks/drivers.py` | **Windows only.** Drivers kernel chargés qui matchent la liste noire de drivers vulnérables (technique BYOVD), + drivers chargés hors de `System32\drivers` |
| `autoruns` | `g6_anticheat/checks/autoruns.py` | **Windows only.** Clés Run/RunOnce et dossiers Startup pour des entrées suspectes |
| `filesystem` | `g6_anticheat/checks/filesystem.py` | Bureau/Téléchargements/Documents/Temp pour des noms de fichiers suspects + hash SHA256 contre une liste noire locale |
| `fivem_integrity` | `g6_anticheat/checks/fivem_integrity.py` | Dossier `%LOCALAPPDATA%\FiveM\FiveM.app\plugins` : baseline au premier scan, alerte si un `.asi`/`.dll` apparaît ou change ensuite |
| `network` | `g6_anticheat/checks/network.py` | Connexions sortantes du process du jeu (informatif seulement, pas de blocklist IP fiable disponible) |

Chaque finding a une sévérité (`INFO` / `LOW` / `MEDIUM` / `HIGH` / `CRITICAL`),
le score de risque du scan est la somme des sévérités plafonnée à 100.

Les checks marqués **Windows only** sont automatiquement skip (avec la raison
affichée dans le dashboard) sur un autre OS.

## Verdict et identification du cheat

À la fin de chaque scan, tu as un verdict en clair :

| Verdict | Ce que ça veut dire |
|---|---|
| **CHEAT DETECTE** | Un cheat connu a été identifié **par son nom** (Eulen, RedEngine...). Le ou les noms sont affichés. |
| **SUSPECT** | Soit un nom trop commun a matché (à confirmer à la main), soit aucun nom connu mais des comportements typiques de cheat (code injecté, driver détourné). Un cheat renommé ou privé donne exactement ce résultat. |
| **LEGIT** | Aucun cheat connu et aucun comportement suspect. |

Important sur "LEGIT" : ça veut dire *rien trouvé par ces vérifications*, pas
*cette personne est innocente*. Un cheat kernel-mode bien fait peut passer
sous le radar d'un scan user-mode.

### Comment il identifie le cheat

`data/cheat_signatures.json` liste les familles connues (Eulen, RedEngine,
Desudo, Skript.gg, Hydro, TZX, Brutan, Lumia, Susano, Impulse, Cherax, Stand,
Kiddions, Paragon, Absolute, KDMapper, Xenos, Cheat Engine...) avec, pour
chacune, les artefacts qui la trahissent.

Deux niveaux de correspondance, pour éviter les accusations à tort :

- `filename_contains` / `folder_contains` → **sous-chaîne**, réservé aux noms de
  marque distinctifs (`eulen`, `redengine`). Match = preuve forte → CHEAT DETECTE.
- `filename_exact` / `process_exact` / `folder_exact` → **nom complet**, pour les
  noms courts et communs (`stand.exe`, `impulse.dll`). Match = SUSPECT, à confirmer.

C'est cette distinction qui fait qu'un fichier légitime nommé
`standard_library.dll` ou `understanding_python.exe` ne déclenche rien, alors
qu'un vrai `Stand.exe` est bien remonté.

### Les hashes sont vides, volontairement

Le champ `sha256` de chaque famille est vide au départ. Je n'ai pas voulu livrer
des hashes inventés : ça donnerait un scanner qui a l'air complet et qui ne
détecte rien. Quand tu croises un vrai échantillon, ajoute son hash :

```json
{ "name": "Eulen", "sha256": ["le_vrai_hash_sha256_ici"] }
```

Un match par hash est le seul indicateur traité comme une **certitude**.

### Ce que cette approche ne voit pas

La détection nominative repose sur le fait que le cheat porte son propre nom.
Un cheat renommé en `svchost.exe`, un cheat privé, ou un cheat injecté sans
jamais toucher au disque ne matchera **aucune** famille. C'est précisément le
rôle des autres vérifications (mémoire injectée, modules fantômes, drivers
vulnérables) : elles ne disent pas *quel* cheat, mais elles voient *qu'il y en
a un*. D'où le verdict SUSPECT dans ce cas.

## Liens de vérification (le mode "Echo AC")

Tu peux générer un lien de vérification depuis le dashboard, l'envoyer à
quelqu'un, et récupérer le résultat de son scan chez toi.

1. Sur ton dashboard, remplis "Who is this for?" et clique **Create link**.
2. Envoie le lien généré (`https://ton-adresse/verify/<token>`).
3. La personne ouvre le lien : elle voit une page qui explique exactement ce qui
   est regardé et ce qui ne l'est jamais, puis lance
   `python verify_client.py <le lien>`.
4. Le client scanne, écrit le rapport complet dans un fichier **sur son disque**,
   affiche chaque finding, et n'envoie rien tant qu'elle n'a pas tapé `yes`
   (elle peut aussi utiliser `--dry-run` pour scanner sans jamais envoyer).
5. Le résultat apparaît sur ton dashboard.

Le lien est à usage unique, expire (24h par défaut, réglable), et tu peux le
révoquer à tout moment.

### Ce que le mode "remote" ne collecte pas

Le scan lancé via un lien utilise un profil bridé (`g6_anticheat/profile.py`),
différent de celui que tu lances sur ta propre machine :

| | Ton scan local | Scan via lien |
|---|---|---|
| Dossier Documents | scanné | **exclu** |
| Chemins de fichiers | complets | **anonymisés** (`%USERPROFILE%`, username remplacé) |
| Connexions réseau / IP | listées | **désactivé** |
| Lignes de commande des process | envoyées | **exclues** |
| Contenu des fichiers | jamais | jamais |

Tout ce qui remonte, ce sont des **noms** de process/fichiers/drivers qui
matchent une signature de cheat, plus le nom d'affichage que la personne a tapé
elle-même. Aucun contenu de fichier, aucun screenshot, aucune donnée de
navigateur, jamais.

### Rendre ton dashboard joignable

Deux options : un tunnel temporaire depuis ton PC, ou un hébergement permanent
(voir la section « Mettre le dashboard en ligne » plus bas).

Pour un tunnel rapide (cloudflared, ngrok...) :

```powershell
set G6_PUBLIC_URL=https://ton-tunnel.trycloudflare.com
python dashboard\app.py
```

Une fois hébergé en ligne, `G6_PUBLIC_URL` devient inutile : l'adresse réelle
est détectée automatiquement.

### Ce que ça ne garantit pas

Un scan côté client peut être falsifié par quelqu'un de déterminé (c'est vrai
pour tout anticheat user-mode, et c'est pour ça qu'Echo AC utilise un driver
kernel + des binaires signés). Le serveur recalcule le score à partir des
findings pour qu'un client ne puisse pas s'auto-déclarer "Clean", mais un cheat
suffisamment avancé peut rester invisible du scan lui-même. C'est un outil de
confiance et de triage entre amis, pas une preuve.

## Installation (sur ta machine Windows, celle qui fait tourner FiveM)

```powershell
git clone <ce repo>
cd G6
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Utilisation

Lancer un scan depuis le terminal :

```powershell
python run_scan.py
```

Lancer le dashboard (historique + détail des findings) :

```powershell
python dashboard\app.py
```

puis ouvrir http://127.0.0.1:5151 — bouton "Run new scan" pour relancer un scan
directement depuis la page.

Conseil d'usage : fais un premier scan "propre" juste après une install saine de
FiveM (ça enregistre la baseline du dossier plugins), puis un scan avant/après
chaque install d'un mod, script, ou outil externe dont tu n'es pas sûr à 100 %.

Pour un scan mémoire (`memory`) et driver (`drivers`) complets, lance le
terminal en Administrateur - certains process/drivers refusent l'accès en
utilisateur standard.

Pour un scan automatique récurrent, ajoute une tâche planifiée Windows qui
lance `python run_scan.py` (Planificateur de tâches -> créer une tâche basique).

## Mettre le dashboard en ligne

### Pourquoi pas Netlify

Netlify héberge des sites statiques et des fonctions serverless en JS/Go. Il
n'exécute pas de serveur Python, et n'a pas de disque persistant pour la base
SQLite. Y déployer ce projet imposerait de réécrire tout le backend en
JavaScript et d'externaliser la base. Les hébergeurs ci-dessous déploient le
projet tel quel depuis GitHub.

### 1. Créer les comptes (obligatoire)

Le dashboard expose tous les résultats de scan. En ligne sans authentification,
n'importe qui trouvant l'URL voit tout et peut générer des liens. `wsgi.py`
**refuse donc de démarrer** si aucun compte n'est configuré.

Sur ton PC, pour toi et ton collègue :

```powershell
python manage.py hash-password     # une fois par personne
python manage.py secret-key
```

Tu obtiens deux valeurs à mettre dans les variables d'environnement de
l'hébergeur (jamais dans le dépôt Git) :

```
G6_USERS={"noam": "pbkdf2:sha256:...", "collegue": "pbkdf2:sha256:..."}
G6_SECRET_KEY=<la valeur générée>
```

### 2. Déployer sur Render

Le fichier `render.yaml` est déjà configuré.

1. Pousse ce dépôt sur GitHub.
2. Sur [render.com](https://render.com) : **New > Blueprint**, sélectionne le dépôt.
3. Render lit `render.yaml`. Renseigne `G6_USERS` et `G6_SECRET_KEY` quand il
   les demande (ils sont marqués `sync: false`, donc jamais versionnés).
4. Tu obtiens une URL `https://g6-guard-xxxx.onrender.com`. C'est ton dashboard.

**Sur la persistance :** `render.yaml` demande un disque de 1 Go monté sur
`/var/g6data`, ce qui nécessite un plan payant (~7 $/mois). Sur le plan
gratuit, supprime le bloc `disk:` et la variable `G6_DB_PATH` : tout fonctionne,
mais la base est effacée à chaque redémarrage — tu perds l'historique des scans
(les liens en cours aussi). Le plan gratuit met aussi le service en veille après
inactivité, donc le premier chargement prend ~30 s.

Le disque est monté sur `/var/g6data` et **pas** sur `data/`, exprès : monter un
volume sur `data/` masquerait les fichiers de signatures livrés avec le code.

### Autres hébergeurs

- **Fly.io** — volume persistant dans l'offre gratuite, mais demande `flyctl` et un Dockerfile.
- **PythonAnywhere** — disque persistant gratuit, configuration via interface web plutôt que git push.
- **Un VPS** — `gunicorn` derrière nginx, contrôle total.

Le `Procfile` fourni fonctionne sur tout hébergeur qui le lit (Railway, Heroku...).

### Variables d'environnement

| Variable | Rôle |
|---|---|
| `G6_USERS` | **Obligatoire en ligne.** Comptes, en JSON |
| `G6_SECRET_KEY` | Signature des sessions. Sans elle, chaque redémarrage déconnecte tout le monde |
| `G6_DB_PATH` | Emplacement de la base (à mettre sur le volume persistant) |
| `G6_PUBLIC_URL` | Force l'adresse des liens générés. Inutile si hébergé |
| `G6_LOCAL=1` | Autorise les cookies en HTTP, pour tester en local |

## Étendre les signatures

Tout est dans `data/signatures.json` :
- `suspicious_process_patterns` / `suspicious_file_name_patterns` : mots-clés
  détectés dans les noms de process/fichiers
- `known_sha256_blocklist` : hash -> label, à toi de l'enrichir si tu tombes
  sur un échantillon
- `vulnerable_driver_blocklist` : liste de départ de drivers vulnérables connus
  (technique BYOVD), non exhaustive

Aucun redémarrage nécessaire, le fichier est relu au prochain scan (le cache
Python est vidé à chaque process `run_scan.py` / dashboard).

## Limites connues (honnêtes)

- Le check `memory` peut donner des faux positifs sur `FiveM_GTAProcess.exe`
  parce que le runtime de script FiveM (Lua/JS/CLR des ressources serveur)
  fait lui-même du JIT en mémoire privée exécutable — c'est documenté dans le
  détail de la finding.
- `known_sha256_blocklist` démarre vide : sans feed de menaces à jour, ce check
  ne vaut que ce que tu y mets.
- Rien ici ne remplace un vrai anticheat kernel-mode côté serveur. Considère ce
  scanner comme un outil de triage personnel, pas une preuve légale ou un
  substitut à Echo AC / EAC / etc.

## Structure du projet

```
g6_anticheat/        package de détection (checks + moteur + stockage sqlite)
  cheats.py          identification des familles de cheats par leurs artefacts
  profile.py         profils local/remote : tout ce qui touche à la vie privée
  privacy.py         anonymisation des chemins
  submission.py      validation des rapports reçus du réseau (rien n'est fait confiance)
dashboard/           app Flask (dashboard + liens de vérification)
data/cheat_signatures.json  familles de cheats nommées (à enrichir)
data/signatures.json        heuristiques génériques
run_scan.py          CLI pour scanner ta propre machine
verify_client.py     client à lancer par la personne qui reçoit un lien
```
