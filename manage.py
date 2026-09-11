#!/usr/bin/env python3
"""Setup helper for deploying the dashboard.

    python manage.py hash-password        create an account entry
    python manage.py secret-key           generate G6_SECRET_KEY

Both print a value you paste into your host's environment variables.
"""
import getpass
import json
import secrets
import sys

from werkzeug.security import generate_password_hash


def hash_password():
    username = input("Identifiant : ").strip()
    if not username:
        print("Identifiant vide, abandon.")
        return 1

    password = getpass.getpass("Mot de passe : ")
    if len(password) < 10:
        print("\nTrop court. Prends au moins 10 caractères - ce dashboard sera "
              "exposé sur Internet et n'importe qui peut tenter de deviner.")
        return 1
    if password != getpass.getpass("Confirme le mot de passe : "):
        print("Les mots de passe ne correspondent pas.")
        return 1

    entry = {username: generate_password_hash(password)}
    print("\nAjoute cet utilisateur à la variable d'environnement G6_USERS.")
    print("Un seul utilisateur :\n")
    print(f"G6_USERS={json.dumps(entry)}")
    print("\nPlusieurs utilisateurs : fusionne les objets, par exemple")
    print('G6_USERS={"noam": "hash1...", "collegue": "hash2..."}')
    return 0


def secret_key():
    print("Ajoute ceci aux variables d'environnement de ton hébergeur.")
    print("Sans ça, chaque redémarrage déconnecte tout le monde.\n")
    print(f"G6_SECRET_KEY={secrets.token_hex(32)}")
    return 0


COMMANDS = {"hash-password": hash_password, "secret-key": secret_key}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        return 1
    return COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
