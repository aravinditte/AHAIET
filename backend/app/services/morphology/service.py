"""Morphological lookup backed by the imported morphhb corpus words.

Two strictly separate adapters:
- Hebrew adapter: searches corpus_words of biblical_hebrew passages and
  only word rows whose own language flag is Hebrew.
- Aramaic adapter: searches corpus_words of biblical_aramaic passages and
  only word rows whose own language flag is Aramaic (morphhb marks
  Aramaic words with an 'A' morph-code prefix, Hebrew with 'H').
Hebrew data is never used to analyse an Aramaic word and vice versa.
Words absent from the imported corpus return status 'not_found' — tags
are never fabricated.
"""
from __future__ import annotations
from pathlib import Path
from app.core.errors import UnavailableError
from app.services.language.normalize import normalize_nodiac
from app.storage import db as store

_WORD_LANG = {"biblical_hebrew": "hebrew", "biblical_aramaic": "aramaic"}

def corpus_available(db_path: Path) -> bool:
    if not Path(db_path).exists():
        return False
    conn = store.connect(db_path)
    try:
        if not conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='corpus_words'").fetchone():
            return False
        return conn.execute("SELECT COUNT(*) c FROM corpus_words").fetchone()["c"] > 0
    finally:
        conn.close()

def _lookup_words(db_path: Path, text: str, language_profile: str) -> list[dict]:
    word_lang = _WORD_LANG[language_profile]
    conn = store.connect(db_path)
    try:
        out = []
        for surface in text.split():
            key = normalize_nodiac(surface)
            rows = conn.execute(
                "SELECT cw.surface, cw.lemma, cw.strongs, cw.morph_code, cw.word_language, "
                "rp.reference, rp.source_edition FROM corpus_words cw "
                "JOIN reference_passages rp ON rp.id = cw.passage_id "
                "WHERE cw.language_profile=? AND cw.word_language=? AND cw.surface_nodiac=? "
                "ORDER BY cw.passage_id, cw.position LIMIT 5",
                (language_profile, word_lang, key)).fetchall()
            if rows:
                out.append({"word": surface, "status": "found",
                            "entries": [dict(r) for r in rows]})
            else:
                out.append({"word": surface, "status": "not_found", "entries": [],
                            "note": "Not present in the imported corpus word index for this profile; no analysis was fabricated."})
        return out
    finally:
        conn.close()

def analyze_hebrew(db_path: Path, text: str) -> dict:
    return {"language_profile": "biblical_hebrew", "adapter": "morphhb_hebrew",
            "words": _lookup_words(db_path, text, "biblical_hebrew")}

def analyze_aramaic(db_path: Path, text: str) -> dict:
    return {"language_profile": "biblical_aramaic", "adapter": "morphhb_aramaic",
            "words": _lookup_words(db_path, text, "biblical_aramaic")}

def analyze(db_path: Path, text: str, language_profile: str) -> dict:
    if language_profile not in _WORD_LANG:
        from app.core.errors import ValidationAppError
        raise ValidationAppError("unsupported_language",
                                 f"Morphology is available only for biblical_hebrew and biblical_aramaic, not '{language_profile}'.")
    if not corpus_available(db_path):
        raise UnavailableError("corpus_unavailable",
            "No corpus word index is imported, so morphological analysis cannot run.",
            "Import the corpus first: python -m app.corpus.import_morphhb (see docs/DATASETS.md), then retry.")
    if language_profile == "biblical_hebrew":
        return analyze_hebrew(db_path, text)
    return analyze_aramaic(db_path, text)

def status(db_path: Path) -> dict:
    avail = corpus_available(db_path)
    return {"status": "available" if avail else "unavailable",
            "reason": None if avail else "Corpus word index is empty; import the corpus (docs/DATASETS.md)."}
