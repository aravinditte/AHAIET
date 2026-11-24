"""SQLite-backed cache for trained-model translation results.

Key: sha256 over (language profile, normalized source, engine, model
artifact hash) — so a retrained model (new artifact hash) never serves
output produced by the old one, and the two language profiles never
share entries.

Rules that must not change:
- Only trained-model (Moses/Marian) outputs are stored here.
- Verified corpus retrieval is NEVER served from this cache; retrieval
  runs live on every request so corpus provenance is always fresh.
- A cache hit is labelled (cached=True) and keeps the original engine
  provenance, so a cached answer is never disguised as a fresh run.
- The cache can be disabled entirely via AHAIET_TRANSLATION_CACHE=0.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

from app.core.config import Settings
from app.services.language.normalize import normalize
from app.storage import db as store


def cache_key(language_profile: str, source_text: str, engine: str,
              artifact_sha256: str | None) -> str:
    material = "\n".join([language_profile, normalize(source_text), engine,
                          artifact_sha256 or ""])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def get(settings: Settings, key: str) -> dict | None:
    # AHAIET-015: with persist_results off, nothing is read from or
    # written to the durable cache — translations are not persisted.
    if not settings.translation_cache_enabled or not settings.persist_results:
        return None
    if not Path(settings.db_path).exists():
        return None
    conn = store.connect(settings.db_path)
    try:
        row = conn.execute("SELECT response_json FROM translation_cache WHERE cache_key=?",
                           (key,)).fetchone()
    except Exception:
        return None
    finally:
        conn.close()
    if row is None:
        return None
    try:
        return json.loads(row["response_json"])
    except Exception:
        return None


def put(settings: Settings, key: str, language_profile: str, engine: str,
        artifact_sha256: str | None, payload: dict) -> None:
    if not settings.translation_cache_enabled or not settings.persist_results:
        return
    conn = store.connect(settings.db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO translation_cache(cache_key, language_profile, engine, "
            "artifact_sha256, response_json) VALUES (?,?,?,?,?)",
            (key, language_profile, engine, artifact_sha256,
             json.dumps(payload, ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()


def clear(settings: Settings) -> int:
    conn = store.connect(settings.db_path)
    try:
        cur = conn.execute("DELETE FROM translation_cache")
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
