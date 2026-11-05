"""Lance le serveur pour l'atelier : python run.py

Les tablettes et les PC du réseau se connectent sur http://<IP de ce PC>:8080
"""

import os
import socket

from waitress import serve

from app import create_app

PORT = int(os.environ.get("BORDAGE_PORT", "8080"))


def ip_locale():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    app = create_app()
    print()
    print("  Suivi bordage - serveur démarré")
    print(f"  Sur ce PC        : http://127.0.0.1:{PORT}")
    print(f"  Sur le réseau    : http://{ip_locale()}:{PORT}")
    with app.app_context():
        from db import get_db
        postes = get_db().execute("SELECT name, token FROM postes WHERE active = 1 ORDER BY id").fetchall()
    if postes:
        print()
        print("  Liens des tablettes (à ouvrir sur chaque tablette) :")
        for p in postes:
            print(f"    {p['name']:<10} http://{ip_locale()}:{PORT}/t/{p['token']}")
    print()
    print("  Laisse cette fenêtre ouverte. Pour arrêter : ferme-la.")
    print()
    serve(app, host="0.0.0.0", port=PORT, threads=8)
