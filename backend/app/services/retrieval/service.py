"""Verified reference retrieval over the imported corpus.

Trust levels, kept distinct:
- exact: the normalized source (diacritics significant) equals a stored
  passage's normalized source in the SAME language profile.
- normalized: only the diacritic-insensitive keys are equal. Still a
  verified passage identity, labelled as such.
- normalized_variant: keys differ but word overlap is high. This is a
  CANDIDATE ONLY — it is never returned as a verified match and never
  used as a translation.
Search never crosses language profiles: an Aramaic passage is not in the
Hebrew index and vice versa.
"""
from __future__ import annotations
import sqlite3
from pathlib import Path
from app.services.language.normalize import normalize, normalize_nodiac, tokens
from app.storage import db as store

VARIANT_OVERLAP_THRESHOLD = 0.8

def corpus_counts(db_path: Path) -> dict:
    if not Path(db_path).exists():
        return {"total": 0, "by_language": {}}
    conn = store.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT language_profile, COUNT(*) c FROM reference_passages GROUP BY language_profile").fetchall()
        total = conn.execute("SELECT COUNT(*) c FROM reference_passages").fetchone()["c"]
        words = conn.execute("SELECT COUNT(*) c FROM corpus_words").fetchone()["c"] \
            if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='corpus_words'").fetchone() else 0
    finally:
        conn.close()
    return {"total": total, "by_language": {r["language_profile"]: r["c"] for r in rows}, "words": words}

def _reference_of(row: sqlite3.Row, match_type: str) -> dict:
    return {
        "passage_id": row["id"], "reference": row["reference"], "book": row["book"],
        "language_profile": row["language_profile"], "match_type": match_type,
        "source_edition": row["source_edition"], "translation_edition": row["translation_edition"],
        "license": row["license"], "provenance": row["provenance"],
        "source_text": row["source_text"], "english_text": row["english_text"],
    }

def lookup(db_path: Path, text: str, language_profile: str) -> dict:
    """Look up `text` in one profile's index only.
    Returns {match: {...}|None, variant_candidate: {...}|None}."""
    norm = normalize(text)
    nodiac = normalize_nodiac(text)
    conn = store.connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM reference_passages WHERE language_profile=? AND normalized_source=?",
            (language_profile, norm)).fetchone()
        if row is not None:
            return {"match": _reference_of(row, "exact"), "variant_candidate": None}
        row = conn.execute(
            "SELECT * FROM reference_passages WHERE language_profile=? AND normalized_nodiac_source=?",
            (language_profile, nodiac)).fetchone()
        if row is not None:
            return {"match": _reference_of(row, "normalized"), "variant_candidate": None}
        # Variant detection: candidate passages sharing most word tokens.
        query_tokens = set(tokens(text))
        if not query_tokens:
            return {"match": None, "variant_candidate": None}
        best, best_overlap = None, 0.0
        for cand in conn.execute(
                "SELECT * FROM reference_passages WHERE language_profile=?", (language_profile,)):
            cand_tokens = set(tokens(cand["source_text"]))
            if not cand_tokens:
                continue
            overlap = len(query_tokens & cand_tokens) / max(len(query_tokens | cand_tokens), 1)
            if overlap > best_overlap:
                best, best_overlap = cand, overlap
        if best is not None and best_overlap >= VARIANT_OVERLAP_THRESHOLD:
            ref = _reference_of(best, "normalized_variant")
            ref["overlap"] = round(best_overlap, 3)
            ref["warning"] = ("This stored passage is similar but NOT identical to the input; "
                              "it is a variant candidate only and was not used as a translation.")
            return {"match": None, "variant_candidate": ref}
        return {"match": None, "variant_candidate": None}
    finally:
        conn.close()

def status(db_path: Path) -> dict:
    counts = corpus_counts(db_path)
    return {"status": "available" if counts["total"] else "unavailable",
            "passages": counts["total"], "by_language": counts["by_language"], "words": counts["words"],
            "reason": None if counts["total"] else
            "No corpus has been imported. Run the corpus importer (see docs/DATASETS.md) to populate reference_passages."}
