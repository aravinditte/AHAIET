"""Retention maintenance: delete aged uploads and processing records.

What this removes, once it is older than the configured retention
period (Settings.retention_days, AHAIET_RETENTION_DAYS):
- upload files stored directly in Settings.storage_dir (the derived
  scratch files in storage_dir/tmp are removed with their parents'
  sweep only when the tmp file itself is old — scratch is normally
  cleaned by the request path already);
- rows in the `history` table (created_at older than the cutoff);
- rows in the `jobs` table (created_at older than the cutoff), whose
  result_json can contain recognised source text and translations;
- rows in the `translation_cache` table (created_at older than cutoff).

Usage:
    python -m app.maintenance              # perform the sweep
    python -m app.maintenance --dry-run    # report counts, delete nothing
    python -m app.maintenance --days 7     # override the retention period

The command prints a JSON report of counts and reclaimed bytes —
metadata only, never file contents, source text, or translations.

Secure deletion, honestly: with Settings.secure_delete_overwrite
(AHAIET_SECURE_DELETE_OVERWRITE=1) each upload file's bytes are
overwritten with zeros and fsynced before unlinking. On a modern
filesystem (journaling, copy-on-write, SSD wear levelling) neither
plain unlink nor overwrite-before-unlink can guarantee the bytes are
unrecoverable; both only remove the directory entry (and, for the
overwrite, the current content of that file's blocks as far as the
filesystem honours it). The operator who needs stronger guarantees
should use full-disk encryption and its key destruction. This is
stated plainly rather than dressed up as "secure erase".
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import Settings, settings as default_settings
from app.storage import db as store


def _cutoff(days: int, now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)) - timedelta(days=days)


def _delete_file(path: Path, overwrite: bool) -> int:
    """Delete one file, optionally overwriting its bytes first.
    Returns the file size in bytes (0 when already gone)."""
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return 0
    if overwrite and size > 0:
        try:
            with path.open("r+b") as fh:
                remaining = size
                zeros = b"\x00" * 65536
                while remaining > 0:
                    chunk = zeros[: min(remaining, len(zeros))]
                    fh.write(chunk)
                    remaining -= len(chunk)
                fh.flush()
                os.fsync(fh.fileno())
        except OSError:
            # If the overwrite fails we still unlink: retention must not
            # silently keep data it was asked to remove.
            pass
    path.unlink(missing_ok=True)
    return size


def _sweep_uploads(settings: Settings, cutoff: datetime, dry_run: bool) -> tuple[int, int]:
    storage = Path(settings.storage_dir)
    if not storage.exists():
        return 0, 0
    count, reclaimed = 0, 0
    cutoff_ts = cutoff.timestamp()
    candidates: list[Path] = []
    for entry in storage.iterdir():
        if entry.is_file():
            candidates.append(entry)
    tmp_dir = Path(settings.temp_dir)
    if tmp_dir.exists():
        for entry in tmp_dir.iterdir():
            if entry.is_file():
                candidates.append(entry)
    for path in candidates:
        try:
            if path.stat().st_mtime >= cutoff_ts:
                continue
        except FileNotFoundError:
            continue
        count += 1
        if dry_run:
            try:
                reclaimed += path.stat().st_size
            except FileNotFoundError:
                pass
        else:
            reclaimed += _delete_file(path, settings.secure_delete_overwrite)
    return count, reclaimed


def _sweep_table(settings: Settings, table: str, cutoff: datetime, dry_run: bool) -> int:
    db_path = Path(settings.db_path)
    if not db_path.exists():
        return 0
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    conn = store.connect(db_path)
    try:
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,)).fetchone()
        if not exists:
            return 0
        count = conn.execute(
            f"SELECT COUNT(*) c FROM {table} WHERE created_at < ?",
            (cutoff_str,)).fetchone()["c"]
        if count and not dry_run:
            conn.execute(f"DELETE FROM {table} WHERE created_at < ?", (cutoff_str,))
            conn.commit()
        return int(count)
    finally:
        conn.close()


def run_retention(settings: Settings, dry_run: bool = False,
                  days: int | None = None, now: datetime | None = None) -> dict:
    """Perform (or, with dry_run, only report) one retention sweep.

    `days` overrides Settings.retention_days for this run. `now` exists
    so tests can pin the clock; production callers leave it None.
    Returns a metadata-only report dict.
    """
    retention_days = settings.retention_days if days is None else days
    cutoff = _cutoff(retention_days, now)
    uploads, reclaimed = _sweep_uploads(settings, cutoff, dry_run)
    report = {
        "dry_run": dry_run,
        "retention_days": retention_days,
        "cutoff_utc": cutoff.strftime("%Y-%m-%d %H:%M:%S"),
        "uploads_deleted": uploads,
        "bytes_reclaimed": reclaimed,
        "history_deleted": _sweep_table(settings, "history", cutoff, dry_run),
        "jobs_deleted": _sweep_table(settings, "jobs", cutoff, dry_run),
        "translation_cache_deleted": _sweep_table(settings, "translation_cache", cutoff, dry_run),
        "secure_delete_overwrite": settings.secure_delete_overwrite,
    }
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Retention sweep: delete uploads and processing records "
                    "older than the retention period.")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be deleted; delete nothing")
    ap.add_argument("--days", type=int, default=None,
                    help="retention period in days (default: AHAIET_RETENTION_DAYS / 30)")
    args = ap.parse_args(argv)
    report = run_retention(default_settings, dry_run=args.dry_run, days=args.days)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
