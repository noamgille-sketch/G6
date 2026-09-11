"""Production entry point (gunicorn wsgi:app).

Unlike `python dashboard/app.py`, which is meant for local use, this
refuses to start unless accounts are configured. Deploying an open
dashboard to a public URL would expose every scan result to anyone who
guesses the address, so it fails loudly instead.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from g6_anticheat import auth, db
from dashboard.app import app

if not auth.auth_configured():
    raise SystemExit(
        "\nG6 Guard refuse de démarrer : aucun compte configuré.\n\n"
        "Sans compte, ce dashboard serait accessible à tout le monde sur Internet.\n\n"
        "Ajoute une de ces deux variables d'environnement chez ton hébergeur :\n\n"
        "  G6_ACCOUNTS=ton_pseudo:ton_mot_de_passe,collegue:son_mot_de_passe\n"
        "      (simple ; les mots de passe restent visibles dans les réglages\n"
        "       de l'hébergeur, donc utilises-en un que tu n'utilises nulle part ailleurs)\n\n"
        "  G6_USERS={\"ton_pseudo\": \"pbkdf2:sha256:...\"}\n"
        "      (plus sûr ; génère la valeur avec : python manage.py hash-password)\n"
    )

if not os.environ.get("G6_SECRET_KEY"):
    print(
        "ATTENTION : G6_SECRET_KEY n'est pas défini. Une clé aléatoire est "
        "utilisée, donc chaque redémarrage déconnectera tout le monde. "
        "Génère-la avec : python manage.py secret-key",
        file=sys.stderr,
    )

db.init_db()
