import json
import re
from functools import lru_cache

from .config import SIGNATURES_PATH


@lru_cache(maxsize=1)
def load_signatures():
    with open(SIGNATURES_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def compiled_file_name_patterns():
    sigs = load_signatures()
    return [re.compile(p) for p in sigs.get("suspicious_file_name_patterns", [])]


def process_name_is_suspicious(name: str) -> str | None:
    name_l = name.lower()
    for pattern in load_signatures().get("suspicious_process_patterns", []):
        if pattern.lower() in name_l:
            return pattern
    return None


def file_name_is_suspicious(name: str) -> bool:
    return any(p.search(name) for p in compiled_file_name_patterns())


def sha256_lookup(digest: str) -> str | None:
    return load_signatures().get("known_sha256_blocklist", {}).get(digest.lower())


def driver_is_blocklisted(filename: str) -> bool:
    return filename.lower() in {
        d.lower() for d in load_signatures().get("vulnerable_driver_blocklist", [])
    }


def trusted_driver_dirs():
    return [d.lower() for d in load_signatures().get("trusted_driver_dirs", [])]
