"""Named cheat family matching.

The heuristic checks answer "is something wrong here?". This module
answers "which cheat is it?" by matching observable artifacts (process,
file and folder names, driver names, file hashes) against the families
declared in data/cheat_signatures.json.

Match strength, strongest first:
  CONFIRMED - a file hash matched a known sample. Not falsifiable.
  STRONG    - a distinctive brand token matched (file/folder/process name).
  MODERATE  - an exact but short/common name matched.
"""
import json
import os
from dataclasses import dataclass
from functools import lru_cache

from .config import DATA_DIR

SIGNATURES_PATH = os.path.join(DATA_DIR, "cheat_signatures.json")

CONFIRMED = "CONFIRMED"
STRONG = "STRONG"
MODERATE = "MODERATE"


@dataclass
class CheatMatch:
    family: str
    kind: str
    strength: str
    artifact: str
    where: str

    @property
    def is_conclusive(self) -> bool:
        return self.strength in (CONFIRMED, STRONG)


@lru_cache(maxsize=1)
def load_families() -> list[dict]:
    with open(SIGNATURES_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh).get("families", [])


def _contains_any(haystack: str, tokens: list[str]) -> str | None:
    for token in tokens:
        if token and token.lower() in haystack:
            return token
    return None


def _equals_any(value: str, candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate and candidate.lower() == value:
            return candidate
    return None


def match_name(name: str, where: str) -> CheatMatch | None:
    """Match a file, folder or process name against every known family.

    `where` is a human label for the finding ("process", "fichier", ...).
    """
    if not name:
        return None

    lowered = name.lower()
    stem = os.path.splitext(lowered)[0]

    for family in load_families():
        fam_name = family.get("name", "?")
        kind = family.get("kind", "")

        if where == "process":
            hit = _equals_any(lowered, family.get("process_exact", []))
            if hit:
                return CheatMatch(fam_name, kind, STRONG, name, where)

        hit = _contains_any(lowered, family.get("filename_contains", []))
        if hit:
            return CheatMatch(fam_name, kind, STRONG, name, where)

        hit = _contains_any(lowered, family.get("folder_contains", []))
        if hit:
            return CheatMatch(fam_name, kind, STRONG, name, where)

        hit = _equals_any(lowered, family.get("filename_exact", []))
        if hit:
            return CheatMatch(fam_name, kind, MODERATE, name, where)

        if _equals_any(stem, [os.path.splitext(f)[0] for f in family.get("folder_exact", [])]):
            return CheatMatch(fam_name, kind, MODERATE, name, where)

        hit = _equals_any(lowered, family.get("driver_exact", []))
        if hit:
            return CheatMatch(fam_name, kind, STRONG, name, where)

    return None


def match_hash(digest: str) -> CheatMatch | None:
    if not digest:
        return None
    lowered = digest.lower()
    for family in load_families():
        if lowered in [h.lower() for h in family.get("sha256", [])]:
            return CheatMatch(
                family.get("name", "?"), family.get("kind", ""), CONFIRMED, digest[:16] + "...", "hash"
            )
    return None


def has_hashes() -> bool:
    """True once at least one real sample hash has been added."""
    return any(f.get("sha256") for f in load_families())


def family_count() -> int:
    return len(load_families())
