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
dashboard/           app Flask (dashboard web local)
data/signatures.json base de signatures éditable
run_scan.py          CLI pour lancer un scan ponctuel
```
