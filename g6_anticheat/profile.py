"""Scan profiles.

A scan run for yourself ("local") can look at everything. A scan run by
someone else who accepted a verification link ("remote") is deliberately
narrower: it only looks at what is relevant to a FiveM cheat, and it
anonymises anything that could identify the person or their files.

Every privacy decision lives here so it can be read in one place - both
by you and by the person you send the link to.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ScanProfile:
    name: str
    redact_paths: bool
    scan_documents: bool
    include_network: bool
    include_command_lines: bool
    # A baseline only means something across repeated scans of the same
    # machine. A one-shot scan run from a link has nothing to compare to, so
    # it lists what it finds instead.
    use_baseline: bool


LOCAL = ScanProfile(
    name="local",
    redact_paths=False,
    scan_documents=True,
    include_network=True,
    include_command_lines=True,
    use_baseline=True,
)

REMOTE = ScanProfile(
    name="remote",
    redact_paths=True,
    scan_documents=False,
    include_network=False,
    include_command_lines=False,
    use_baseline=False,
)

BY_NAME = {p.name: p for p in (LOCAL, REMOTE)}

# Shown verbatim to the person who opens a verification link, and printed
# by the client before it sends anything. Keep these two lists truthful:
# if you add a check that collects something else, say it here.
PRIVACY_HEADLINE = "Aucune de tes données personnelles n'est lue ni envoyée."

PRIVACY_SUMMARY = (
    "Ce scan cherche uniquement des cheats FiveM. Il regarde des NOMS "
    "(noms de programmes lancés, de fichiers et de dossiers) pour voir si l'un "
    "correspond à un cheat connu. Il n'ouvre aucun fichier et ne lit jamais "
    "le contenu de quoi que ce soit."
)

REMOTE_COLLECTS = [
    "Les noms des programmes en cours d'exécution qui correspondent à un cheat connu",
    "Les noms de fichiers et dossiers de cheats connus dans Téléchargements, Bureau et Temp",
    "Les pilotes système correspondant à la liste des pilotes détournés par les cheats",
    "Les fichiers ajoutés ou modifiés dans le dossier plugins de FiveM",
    "Les traces de code injecté dans le processus FiveM/GTA5 (l'emplacement, pas le contenu)",
    "Le nom de ton système d'exploitation et le pseudo que tu tapes toi-même",
]

REMOTE_NEVER_COLLECTS = [
    "Le contenu d'un fichier, quel qu'il soit - aucun fichier n'est jamais ouvert",
    "Tes documents, photos, vidéos - le dossier Documents n'est même pas parcouru",
    "Tes mots de passe, ton navigateur, ton historique, tes messages",
    "Ton nom d'utilisateur Windows et le nom de ton PC (remplacés par %USERPROFILE%)",
    "Tes connexions réseau, ton adresse IP, les serveurs sur lesquels tu joues",
    "Captures d'écran, frappes clavier, webcam, micro - rien de tout ça",
]
