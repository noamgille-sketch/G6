import os
import platform

APP_NAME = "G6 Guard"

IS_WINDOWS = platform.system() == "Windows"

import sys

# When packaged by PyInstaller the bundled files are unpacked into a temp
# folder that sys._MEIPASS points at, not next to the executable.
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Signature files ship with the code and are read-only.
DATA_DIR = os.path.join(BASE_DIR, "data")
SIGNATURES_PATH = os.path.join(DATA_DIR, "signatures.json")

# The database is the only thing written at runtime. On a host it belongs on
# a mounted volume, which must NOT be data/ - mounting there would hide the
# signature files shipped in the repo.
DB_PATH = os.environ.get("G6_DB_PATH") or os.path.join(DATA_DIR, "g6guard.sqlite3")

# Process names we treat as "the game" - findings inside these processes
# (injected/manually-mapped modules, suspicious threads) matter most.
GAME_PROCESS_NAMES = {
    "fivem.exe",
    "fivem_gtaprocess.exe",
    "gta5.exe",
    "gta5_enhanced.exe",
    "ragemp.exe",
    "ragemp_v.exe",
}

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
