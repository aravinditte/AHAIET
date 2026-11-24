from __future__ import annotations
import sqlite3
from pathlib import Path

MIGRATIONS: list[tuple[int, str]] = [
    (1, """
CREATE TABLE IF NOT EXISTS language_profiles (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, script TEXT NOT NULL,
  status TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS model_metadata (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, language_profile TEXT,
  status TEXT NOT NULL, artifact_path TEXT, version TEXT, checksum TEXT);
CREATE TABLE IF NOT EXISTS reference_passages (
  id TEXT PRIMARY KEY, language_profile TEXT NOT NULL, source_text TEXT NOT NULL,
  english_text TEXT NOT NULL, edition TEXT NOT NULL, license TEXT NOT NULL, provenance TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS history (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL DEFAULT (datetime('now')),
  upload_id TEXT, language_profile TEXT, status TEXT NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  upload_id TEXT, language_profile TEXT, status TEXT NOT NULL, stage TEXT, error TEXT, result_json TEXT);
"""),
    # Corpus retrieval work: canonical passage fields + word-level morphology
    # index. Added as a new migration; the foundation migration above is
    # never edited.
    (2, """
ALTER TABLE reference_passages ADD COLUMN dialect TEXT NOT NULL DEFAULT '';
ALTER TABLE reference_passages ADD COLUMN script TEXT NOT NULL DEFAULT 'Hebrew';
ALTER TABLE reference_passages ADD COLUMN period TEXT NOT NULL DEFAULT '';
ALTER TABLE reference_passages ADD COLUMN book TEXT NOT NULL DEFAULT '';
ALTER TABLE reference_passages ADD COLUMN reference TEXT NOT NULL DEFAULT '';
ALTER TABLE reference_passages ADD COLUMN source_edition TEXT NOT NULL DEFAULT '';
ALTER TABLE reference_passages ADD COLUMN translation_edition TEXT NOT NULL DEFAULT '';
ALTER TABLE reference_passages ADD COLUMN partition_name TEXT NOT NULL DEFAULT '';
ALTER TABLE reference_passages ADD COLUMN normalized_source TEXT NOT NULL DEFAULT '';
ALTER TABLE reference_passages ADD COLUMN normalized_nodiac_source TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_passages_norm ON reference_passages(language_profile, normalized_source);
CREATE INDEX IF NOT EXISTS idx_passages_nodiac ON reference_passages(language_profile, normalized_nodiac_source);
CREATE TABLE IF NOT EXISTS corpus_words (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  passage_id TEXT NOT NULL, language_profile TEXT NOT NULL,
  position INTEGER NOT NULL, surface TEXT NOT NULL, surface_nodiac TEXT NOT NULL DEFAULT '',
  lemma TEXT NOT NULL DEFAULT '', strongs TEXT NOT NULL DEFAULT '',
  morph_code TEXT NOT NULL DEFAULT '', word_language TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_words_lookup ON corpus_words(language_profile, surface_nodiac);
"""),
    # Hybrid verification / passage / performance work: per-stage timing
    # storage on jobs, and the trained-model translation result cache.
    # Additive only; earlier migrations are never edited.
    (3, """
ALTER TABLE jobs ADD COLUMN stage_timings_json TEXT;
CREATE TABLE IF NOT EXISTS translation_cache (
  cache_key TEXT PRIMARY KEY,
  language_profile TEXT NOT NULL,
  engine TEXT NOT NULL,
  artifact_sha256 TEXT,
  response_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE INDEX IF NOT EXISTS idx_translation_cache_profile ON translation_cache(language_profile, engine);
"""),
    # Remediation work (AHAIET-013/015/016/009): corpus revision counter
    # for cross-process cache invalidation, an inverted token index for
    # variant shortlisting, maintenance run records, and job expiry /
    # cancellation columns. Additive only.
    (4, """
CREATE TABLE IF NOT EXISTS corpus_meta (
  key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS passage_tokens (
  passage_id TEXT NOT NULL, language_profile TEXT NOT NULL, token TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_passage_tokens ON passage_tokens(language_profile, token);
CREATE TABLE IF NOT EXISTS maintenance_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  kind TEXT NOT NULL, dry_run INTEGER NOT NULL DEFAULT 0,
  report_json TEXT, status TEXT NOT NULL DEFAULT 'ok', error TEXT);
ALTER TABLE jobs ADD COLUMN expires_at TEXT;
ALTER TABLE jobs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0;
"""),
]
PROFILES = [
    ("biblical_hebrew", "Biblical Hebrew", "Hebrew", "profile_defined_models_not_provisioned", "Consonantal and vocalized (niqqud) text; cantillation where present."),
    ("biblical_aramaic", "Biblical Aramaic", "Hebrew", "profile_defined_models_not_provisioned", "Biblical Aramaic written in Hebrew script. Script alone does NOT identify it as Hebrew."),
]
def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
def migrate(db_path: Path) -> None:
    """Apply pending migrations, each inside its own explicit
    transaction (AHAIET-018): the migration SQL and its schema_version
    row commit together or roll back together, so an interrupted
    migration never leaves a half-applied schema with no version row.
    executescript is deliberately not used: it implicitly commits any
    open transaction before running."""
    conn = connect(db_path)
    try:
        conn.isolation_level = None  # explicit transaction control
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))")
        applied = {r[0] for r in conn.execute("SELECT version FROM schema_version")}
        for version, sql in MIGRATIONS:
            if version in applied:
                continue
            statements = [st.strip() for st in sql.split(";") if st.strip()]
            try:
                conn.execute("BEGIN IMMEDIATE")
                for st in statements:
                    conn.execute(st)
                conn.execute("INSERT INTO schema_version(version) VALUES (?)", (version,))
                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        conn.execute("BEGIN IMMEDIATE")
        try:
            for p in PROFILES:
                conn.execute("INSERT OR IGNORE INTO language_profiles(id,name,script,status,notes) VALUES (?,?,?,?,?)", p)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
def db_ok(db_path: Path) -> bool:
    try:
        conn = connect(db_path); conn.execute("SELECT 1"); conn.close(); return True
    except Exception:
        return False
