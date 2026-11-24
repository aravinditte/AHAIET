"""Number-word lookup for the verification checks.

Loads the small documented lexicon in numbers_lexicon.json (same
directory). Lookups use the diacritic-insensitive key form
(normalize_nodiac), so vocalised and consonantal spellings of the same
number word resolve to the same entry. Anything not in the lexicon
returns None — the verification layer reports that as no evidence, never
as a guessed value.
"""
from __future__ import annotations
import json
from pathlib import Path

_LEXICON_PATH = Path(__file__).resolve().parent / "numbers_lexicon.json"
_cache: dict[str, dict[str, dict]] | None = None

# English number words the candidate side of the check recognises.
ENGLISH_NUMBER_WORDS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100, "thousand": 1000,
}


def _load() -> dict[str, dict[str, dict]]:
    global _cache
    if _cache is None:
        _cache = {}
        try:
            data = json.loads(_LEXICON_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {"entries": []}
        from app.services.language.normalize import normalize_nodiac
        for entry in data.get("entries", []):
            profile = entry.get("profile")
            form = entry.get("form")
            if profile and form:
                _cache.setdefault(profile, {})[normalize_nodiac(form)] = entry
    return _cache


def lookup(profile: str, nodiac_token: str) -> dict | None:
    """Return the lexicon entry for a diacritic-insensitive token, or None."""
    return _load().get(profile, {}).get(nodiac_token)
