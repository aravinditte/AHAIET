"""Verified reference retrieval over the imported corpus.

Trust levels, kept distinct (AHAIET-001/002):
- exact: the normalized source (diacritics significant) equals a stored
  passage's normalized source in the SAME language profile. Verified
  only when exactly ONE passage identity matches.
- normalized: only the diacritic-insensitive keys are equal. Verified
  only when exactly one passage identity matches AND every candidate
  sharing that key has the same vocalized source form — otherwise the
  pointing may distinguish meaning and the match is ambiguous.
- ambiguous_match: multiple passage identities share a key (or a
  diacritic-insensitive key spans differing vocalized forms). NO
  translation is returned as verified; the candidate list (references
  + editions) is returned with reason="ambiguous_match".
- normalized_variant: keys differ but word overlap is high. CANDIDATE
  ONLY — never a verified match, never a translation.

Two separate booleans are reported on every result: text_match (the
text matched a stored key) and passage_identity_verified (the match
identifies one passage unambiguously).

Search never crosses language profiles. Variant shortlisting uses the
passage_tokens inverted index (migration v4, populated by the corpus
importer) with a candidate cap before Jaccard scoring (AHAIET-014) —
never a full-corpus scan.

Cache invalidation across processes (AHAIET-013): lookup results are
memoised in an in-process LRU keyed by (database, corpus revision,
profile, normalized key). The corpus revision lives in the corpus_meta
table and is bumped by the importer in ITS process, so an import in a
separate process invalidates cached hits/misses in the API process.
"""
from __future__ import annotations
import sqlite3
import threading
from collections import OrderedDict
from pathlib import Path
from app.services.language.normalize import normalize, normalize_nodiac, tokens
from app.storage import db as store

VARIANT_OVERLAP_THRESHOLD = 0.8
VARIANT_SHORTLIST_CAP = 50

_LOOKUP_CACHE_MAX = 512
_lookup_cache: "OrderedDict[tuple[str, int, str, str], dict]" = OrderedDict()
_lookup_cache_lock = threading.Lock()


def invalidate_lookup_cache() -> None:
    """Drop every memoised lookup result (same-process fast path; the
    corpus revision in the database covers other processes)."""
    with _lookup_cache_lock:
        _lookup_cache.clear()


def corpus_revision(db_path: Path) -> int:
    """Durable corpus revision from the corpus_meta table (0 when the
    table or row is absent, e.g. a database created before the
    revision counter existed and never re-imported)."""
    if not Path(db_path).exists():
        return 0
    try:
        conn = store.connect(db_path)
        try:
            row = conn.execute(
                "SELECT value FROM corpus_meta WHERE key='revision'").fetchone()
            return int(row["value"]) if row else 0
        finally:
            conn.close()
    except Exception:
        return 0


def bump_corpus_revision(db_path: Path) -> int:
    """Increment the corpus revision inside the caller's database.
    Used by the corpus importer after a successful import."""
    conn = store.connect(db_path)
    try:
        store.migrate(db_path)
        row = conn.execute(
            "SELECT value FROM corpus_meta WHERE key='revision'").fetchone()
        current = int(row["value"]) if row else 0
        new = current + 1
        conn.execute(
            "INSERT INTO corpus_meta(key, value) VALUES ('revision', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(new),))
        conn.commit()
        return new
    finally:
        conn.close()


def _cache_get(key):
    with _lookup_cache_lock:
        value = _lookup_cache.get(key)
        if value is not None:
            _lookup_cache.move_to_end(key)
        return value


def _cache_put(key, value) -> None:
    with _lookup_cache_lock:
        _lookup_cache[key] = value
        _lookup_cache.move_to_end(key)
        while len(_lookup_cache) > _LOOKUP_CACHE_MAX:
            _lookup_cache.popitem(last=False)


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


def _result(match=None, variant=None, candidates=None, reason=None,
            text_match=False, verified=False) -> dict:
    return {"match": match, "variant_candidate": variant,
            "candidates": candidates or [], "reason": reason,
            "text_match": text_match, "passage_identity_verified": verified}


def lookup(db_path: Path, text: str, language_profile: str) -> dict:
    """Look up `text` in one profile's index only.

    Returns {match, variant_candidate, candidates, reason, text_match,
    passage_identity_verified}. `match` is non-None only for a unique,
    unambiguous passage identity."""
    norm = normalize(text)
    revision = corpus_revision(db_path)
    cache_key = (str(db_path), revision, language_profile, norm)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    result = _lookup_uncached(db_path, text, language_profile, norm)
    _cache_put(cache_key, result)
    return result


def _lookup_uncached(db_path: Path, text: str, language_profile: str, norm: str) -> dict:
    nodiac = normalize_nodiac(text)
    conn = store.connect(db_path)
    try:
        # Exact (diacritic-sensitive) key: ALL matching identities.
        rows = conn.execute(
            "SELECT * FROM reference_passages WHERE language_profile=? AND normalized_source=?",
            (language_profile, norm)).fetchall()
        if rows:
            identities = {r["id"] for r in rows}
            if len(identities) == 1:
                return _result(match=_reference_of(rows[0], "exact"),
                               text_match=True, verified=True)
            candidates = [_reference_of(r, "exact") for r in rows]
            return _result(candidates=candidates, reason="ambiguous_match",
                           text_match=True, verified=False)
        # Diacritic-insensitive key: ALL matching identities. Verified
        # only when one identity matches and every row sharing the key
        # carries the same vocalized (normalized) source form.
        rows = conn.execute(
            "SELECT * FROM reference_passages WHERE language_profile=? AND normalized_nodiac_source=?",
            (language_profile, nodiac)).fetchall()
        if rows:
            identities = {r["id"] for r in rows}
            vocalized_forms = {r["normalized_source"] for r in rows}
            if len(identities) == 1 and len(vocalized_forms) == 1:
                return _result(match=_reference_of(rows[0], "normalized"),
                               text_match=True, verified=True)
            candidates = [_reference_of(r, "normalized") for r in rows]
            return _result(candidates=candidates, reason="ambiguous_match",
                           text_match=True, verified=False)
        # Variant detection via the inverted token index: shortlist by
        # shared-token count, cap the shortlist, then Jaccard-score
        # only the shortlist (AHAIET-014).
        query_tokens = set(tokens(text))
        if not query_tokens:
            return _result()
        placeholders = ",".join("?" for _ in query_tokens)
        shortlist = conn.execute(
            f"SELECT passage_id, COUNT(*) shared FROM passage_tokens "
            f"WHERE language_profile=? AND token IN ({placeholders}) "
            f"GROUP BY passage_id ORDER BY shared DESC LIMIT ?",
            (language_profile, *sorted(query_tokens), VARIANT_SHORTLIST_CAP)).fetchall()
        best, best_overlap = None, 0.0
        for item in shortlist:
            cand = conn.execute("SELECT * FROM reference_passages WHERE id=?",
                                (item["passage_id"],)).fetchone()
            if cand is None:
                continue
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
            return _result(variant=ref)
        return _result()
    finally:
        conn.close()


def profile_evidence(db_path: Path, text: str) -> dict:
    """Per-profile lookup summary used for profile choice
    (AHAIET-036): which profiles hold a verified match, an ambiguous
    candidate set, or only a variant for this text."""
    out: dict[str, dict] = {}
    for profile in ("biblical_hebrew", "biblical_aramaic"):
        r = lookup(db_path, text, profile)
        out[profile] = {
            "verified_match": r["match"] is not None,
            "ambiguous_candidates": len(r["candidates"]),
            "variant_candidate": r["variant_candidate"] is not None,
        }
    return out


def status(db_path: Path) -> dict:
    counts = corpus_counts(db_path)
    return {"status": "available" if counts["total"] else "unavailable",
            "passages": counts["total"], "by_language": counts["by_language"], "words": counts["words"],
            "corpus_revision": corpus_revision(db_path),
            "reason": None if counts["total"] else
            "No corpus has been imported. Run the corpus importer (see docs/DATASETS.md) to populate reference_passages."}
