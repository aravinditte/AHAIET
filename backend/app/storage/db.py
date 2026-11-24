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
    conn = connect(db_path)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))")
        applied = {r[0] for r in conn.execute("SELECT version FROM schema_version")}
        for version, sql in MIGRATIONS:
            if version not in applied:
                conn.executescript(sql)
                conn.execute("INSERT INTO schema_version(version) VALUES (?)", (version,))
        for p in PROFILES:
            conn.execute("INSERT OR IGNORE INTO language_profiles(id,name,script,status,notes) VALUES (?,?,?,?,?)", p)
        conn.commit()
    finally:
        conn.close()
def db_ok(db_path: Path) -> bool:
    try:
        conn = connect(db_path); conn.execute("SELECT 1"); conn.close(); return True
    except Exception:
        return False
