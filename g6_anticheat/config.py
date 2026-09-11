import os
import platform

APP_NAME = "G6 Guard"

IS_WINDOWS = platform.system() == "Windows"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "g6guard.sqlite3")
SIGNATURES_PATH = os.path.join(DATA_DIR, "signatures.json")

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
