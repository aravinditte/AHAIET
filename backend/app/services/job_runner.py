"""Background job lifecycle for /api/process (AHAIET-009/010/015/033).

State machine (finite, persisted per transition):
    queued -> running_ocr -> running_translation
           -> completed | partial | failed | cancelled

Design:
- The route persists a `queued` job and commits BEFORE any work runs,
  then returns 202; a bounded ThreadPoolExecutor (Settings.job_workers)
  with a bounded pending queue drives the work. A full queue is a
  structured 503 with retry metadata, never unbounded growth.
- Cancellation is cooperative and best-effort: POST
  /api/jobs/{id}/cancel records the request; the worker honours it
  between stages (a running decoder subprocess is not killed).
- Ownership and recovery (NEW-15): every job records its owning
  worker instance (owner_id) and a heartbeat (heartbeat_at) that the
  worker refreshes while it works. Startup recovery — invoked from
  the FastAPI lifespan, not at import — fails ONLY jobs whose
  heartbeat is older than Settings.job_heartbeat_stale_s (or whose
  heartbeat/creation is older than that threshold), so a second app
  instance sharing the database never kills a live job owned by a
  first instance that is still heartbeating. Recovery failures are
  logged structurally and surfaced on app state, never swallowed.
- OCR deadline (NEW-16): the job path runs OCR in a subprocess
  (app.services.ocr.worker_entry) bounded by the job's remaining
  deadline; on expiry or cancellation the subprocess is terminated
  and the job ends failed (ocr_timeout) or cancelled. Terminal
  states are therefore guaranteed and queue capacity recovers.
- Privacy (AHAIET-015): with Settings.persist_results=False nothing is
  written to SQLite — jobs live in an in-memory store with a TTL
  (Settings.job_result_ttl_s) and vanish on expiry or restart.
  history_enabled is a separate switch governing only the history
  table's metadata rows.
- Expiry: durable jobs carry expires_at; reads report status
  "expired" once it passes (retention sweeps delete the rows).
"""
from __future__ import annotations
import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import BACKEND_ROOT, Settings
from app.core.errors import AppError
from app.storage import db as store

logger = logging.getLogger("ahaiet.jobs")

TERMINAL = ("completed", "partial", "failed", "cancelled")
NON_TERMINAL = ("queued", "running_ocr", "running_translation")


class QueueFullError(AppError):
    def __init__(self, retry_after_s: int = 30):
        super().__init__(503, "job_queue_full",
                         "The background job queue is full, so this job was not accepted.",
                         "Retry after the running jobs finish, or raise AHAIET_JOB_WORKERS.")
        self.retry_after_s = retry_after_s


class JobManager:
    """Owns the executor, the pending bound, and the ephemeral store."""

    def __init__(self, settings: Settings):
        self.settings = settings
        # NEW-15: this instance's worker identity, stamped on every
        # job it creates and heartbeats.
        self.worker_id = uuid.uuid4().hex
        self.stopped = False
        self.executor = ThreadPoolExecutor(max_workers=max(1, settings.job_workers),
                                           thread_name_prefix="ahaiet-job")
        self._pending = threading.BoundedSemaphore(
            max(1, settings.job_workers) * 4)
        self._ephemeral: dict[str, dict] = {}
        self._ephemeral_lock = threading.Lock()

    def shutdown(self) -> None:
        """Graceful executor shutdown (NEW-15), called from the
        FastAPI lifespan exit: no new work is accepted; running jobs
        are not waited on indefinitely."""
        self.stopped = True
        try:
            self.executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:  # older Python without cancel_futures
            self.executor.shutdown(wait=False)

    # -- submission ----------------------------------------------------
    def submit(self, job_id: str, work) -> None:
        if not self._pending.acquire(blocking=False):
            raise QueueFullError()

        def _wrapped():
            try:
                work()
            finally:
                self._pending.release()

        self.executor.submit(_wrapped)

    # -- ephemeral store (persist_results=False) -----------------------
    def ephemeral_put(self, job_id: str, record: dict) -> None:
        with self._ephemeral_lock:
            self._ephemeral[job_id] = record

    def ephemeral_get(self, job_id: str) -> dict | None:
        with self._ephemeral_lock:
            record = self._ephemeral.get(job_id)
            if record is None:
                return None
            if record.get("expires_at_epoch") and time.time() > record["expires_at_epoch"]:
                self._ephemeral.pop(job_id, None)
                return {**record, "status": "expired", "result": None}
            return record

    def ephemeral_update(self, job_id: str, **fields) -> None:
        with self._ephemeral_lock:
            if job_id in self._ephemeral:
                self._ephemeral[job_id].update(fields)


def _expires_at(settings: Settings) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=settings.job_result_ttl_s)
            ).strftime("%Y-%m-%d %H:%M:%S")


def create_job(settings: Settings, manager: JobManager, job_id: str,
               upload_id: str, language_profile: str | None) -> dict:
    """Persist (or register) a queued job and commit before returning."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if not settings.persist_results:
        record = {"id": job_id, "upload_id": upload_id,
                  "language_profile": language_profile, "status": "queued",
                  "stage": "queued", "error": None, "result": None,
                  "stage_timings_ms": {}, "cancel_requested": False,
                  "owner_id": manager.worker_id, "heartbeat_at": now,
                  "expires_at_epoch": time.time() + settings.job_result_ttl_s}
        manager.ephemeral_put(job_id, record)
        return record
    conn = store.connect(settings.db_path)
    try:
        conn.execute(
            "INSERT INTO jobs(id,upload_id,language_profile,status,stage,expires_at,"
            "owner_id,heartbeat_at) VALUES (?,?,?,?,?,?,?)",
            (job_id, upload_id, language_profile, "queued", "queued",
             _expires_at(settings), manager.worker_id, now))
        conn.commit()
    finally:
        conn.close()
    return {"id": job_id, "status": "queued", "stage": "queued"}


def update_job(settings: Settings, manager: JobManager, job_id: str, *,
               status: str | None = None, stage: str | None = None,
               error: str | None = None, result: dict | None = None,
               timings: dict | None = None) -> None:
    if not settings.persist_results:
        fields: dict = {}
        if status is not None:
            fields["status"] = status
        if stage is not None:
            fields["stage"] = stage
        if error is not None:
            fields["error"] = error
        if result is not None:
            fields["result"] = result
        if timings is not None:
            fields["stage_timings_ms"] = timings
        manager.ephemeral_update(job_id, **fields)
        return
    conn = store.connect(settings.db_path)
    try:
        sets, params = [], []
        for column, value in (("status", status), ("stage", stage), ("error", error)):
            if value is not None:
                sets.append(f"{column}=?")
                params.append(value)
        if result is not None:
            sets.append("result_json=?")
            params.append(json.dumps(result, ensure_ascii=False))
        if timings is not None:
            sets.append("stage_timings_json=?")
            params.append(json.dumps(timings))
        if sets:
            sets.append("updated_at=datetime('now')")
            conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?",
                         (*params, job_id))
            conn.commit()
    finally:
        conn.close()


def touch_heartbeat(settings: Settings, manager: JobManager, job_id: str) -> None:
    """Refresh the job's heartbeat (NEW-15). Called at every stage
    transition and periodically while the OCR subprocess runs."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if not settings.persist_results:
        manager.ephemeral_update(job_id, heartbeat_at=now)
        return
    conn = store.connect(settings.db_path)
    try:
        conn.execute("UPDATE jobs SET heartbeat_at=? WHERE id=?", (now, job_id))
        conn.commit()
    finally:
        conn.close()


def cancel_requested(settings: Settings, manager: JobManager, job_id: str) -> bool:
    if not settings.persist_results:
        record = manager.ephemeral_get(job_id)
        return bool(record and record.get("cancel_requested"))
    conn = store.connect(settings.db_path)
    try:
        row = conn.execute("SELECT cancel_requested FROM jobs WHERE id=?",
                           (job_id,)).fetchone()
        return bool(row and row["cancel_requested"])
    finally:
        conn.close()


def request_cancel(settings: Settings, manager: JobManager, job_id: str) -> dict | None:
    """Record a cancellation request. Returns the job view, or None
    when the job does not exist. Terminal jobs are returned unchanged."""
    view = get_job(settings, manager, job_id)
    if view is None:
        return None
    if view["status"] in TERMINAL or view["status"] == "expired":
        return view
    if not settings.persist_results:
        manager.ephemeral_update(job_id, cancel_requested=True)
    else:
        conn = store.connect(settings.db_path)
        try:
            conn.execute("UPDATE jobs SET cancel_requested=1, updated_at=datetime('now') WHERE id=?",
                         (job_id,))
            conn.commit()
        finally:
            conn.close()
    view = get_job(settings, manager, job_id)
    return view


def get_job(settings: Settings, manager: JobManager, job_id: str) -> dict | None:
    if not settings.persist_results:
        record = manager.ephemeral_get(job_id)
        if record is None:
            return None
        return {"id": record["id"], "upload_id": record["upload_id"],
                "language_profile": record["language_profile"],
                "status": record["status"], "stage": record["stage"],
                "error": record["error"], "result": record.get("result"),
                "stage_timings_ms": record.get("stage_timings_ms", {}),
                "cancel_requested": bool(record.get("cancel_requested")),
                "ephemeral": True}
    conn = store.connect(settings.db_path)
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    view = dict(row)
    view.pop("result_json", None)
    view.pop("stage_timings_json", None)
    if view.get("expires_at"):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        if view["expires_at"] < now and view["status"] in TERMINAL:
            view["status"] = "expired"
    result = json.loads(row["result_json"]) if row["result_json"] else None
    timings = json.loads(row["stage_timings_json"]) if row["stage_timings_json"] else {}
    view["result"] = result
    view["stage_timings_ms"] = timings
    return view


def recover_orphaned_jobs(settings: Settings) -> int:
    """Startup recovery (NEW-15): fail ONLY definitely-orphaned jobs.

    A non-terminal job is orphaned when its heartbeat is older than
    Settings.job_heartbeat_stale_s (jobs written before heartbeats
    existed fall back to their updated_at). A live job owned by
    another still-running instance heartbeats regularly and is never
    touched. Errors propagate to the caller (the FastAPI lifespan),
    which logs them structurally and surfaces a degraded flag —
    they are never swallowed here. Returns the number recovered."""
    if not settings.persist_results:
        return 0
    cutoff = (datetime.now(timezone.utc)
              - timedelta(seconds=settings.job_heartbeat_stale_s)
              ).strftime("%Y-%m-%d %H:%M:%S")
    conn = store.connect(settings.db_path)
    try:
        placeholders = ",".join("?" for _ in NON_TERMINAL)
        cur = conn.execute(
            f"UPDATE jobs SET status='failed', stage='failed', "
            f"error='worker_restarted: the owning worker stopped heartbeating "
            f"(stale threshold {settings.job_heartbeat_stale_s}s); resubmit the job.', "
            f"updated_at=datetime('now') "
            f"WHERE status IN ({placeholders}) "
            f"AND COALESCE(heartbeat_at, updated_at) < ?",
            (*NON_TERMINAL, cutoff))
        conn.commit()
        if cur.rowcount:
            logger.warning("recovered %d orphaned job(s) at startup", cur.rowcount)
        return cur.rowcount
    finally:
        conn.close()


_SETTINGS_PATH_FIELDS = ("storage_dir", "db_path", "models_manifest",
                         "datasets_manifest", "corpus_dir", "tessdata_prefix")
_SETTINGS_SCALAR_FIELDS = ("tesseract_cmd", "tesseract_lang",
                           "ocr_confidence_threshold", "ocr_psm", "ocr_timeout_s",
                           "preprocessing_max_bytes", "max_concurrent_ocr",
                           "script_min_test_samples", "upload_max_pixels",
                           "translation_timeout_s", "kraken_cmd")


def _settings_overrides(settings: Settings) -> dict:
    out: dict = {}
    for name in _SETTINGS_PATH_FIELDS:
        value = getattr(settings, name, None)
        out[name] = str(value) if value is not None else None
    for name in _SETTINGS_SCALAR_FIELDS:
        out[name] = getattr(settings, name, None)
    return out


class _OcrWorkerFailed(Exception):
    def __init__(self, code: str, message: str, detail: str | None = None,
                 status: int = 503):
        super().__init__(message)
        self.code, self.message, self.detail, self.status = code, message, detail, status


def _run_ocr_with_deadline(settings: Settings, manager: JobManager, job_id: str,
                           upload_path, body: dict, started: float) -> dict:
    """OCR for the job path (NEW-16): a subprocess bounded by the
    job's remaining deadline. The runner polls: it heartbeats the
    job, honours cancellation, and on deadline expiry terminates the
    subprocess and raises ocr_timeout — the job always reaches a
    terminal state and the executor slot is released."""
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    request_path = settings.temp_dir / f"ocr-job-{job_id}.request.json"
    result_path = settings.temp_dir / f"ocr-job-{job_id}.result.json"
    request_path.write_text(json.dumps({
        "upload_path": str(upload_path),
        "language_profile": body.get("language_profile"),
        "preprocessing_profile": body.get("preprocessing_profile") or "conservative",
        "psm": body.get("psm"),
        "engine": body.get("engine") or "auto",
        "script_profile": body.get("script_profile") or "hebrew_square",
        "settings": _settings_overrides(settings),
    }, ensure_ascii=False), encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BACKEND_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.services.ocr.worker_entry",
             str(request_path), str(result_path)],
            cwd=str(BACKEND_ROOT), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        raise _OcrWorkerFailed("ocr_worker_unavailable",
                               "The OCR worker subprocess could not be started.",
                               str(e)[:300])
    deadline = started + settings.job_deadline_s
    last_heartbeat = 0.0
    try:
        while True:
            rc = proc.poll()
            if rc is not None:
                break
            now = time.monotonic()
            if now - last_heartbeat >= 1.0:
                touch_heartbeat(settings, manager, job_id)
                last_heartbeat = now
            if cancel_requested(settings, manager, job_id):
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise _OcrWorkerFailed("cancelled", "cancelled by request during OCR",
                                       None, status=499)
            if now > deadline:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise _OcrWorkerFailed(
                    "ocr_timeout",
                    "OCR exceeded the per-job deadline and the worker process was "
                    "terminated, so the job ends here instead of occupying a worker "
                    "indefinitely.",
                    f"job_deadline_s={settings.job_deadline_s}", status=504)
            time.sleep(0.05)
    finally:
        request_path.unlink(missing_ok=True)
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception:
        raise _OcrWorkerFailed("ocr_worker_failed",
                               "The OCR worker exited without producing a result.",
                               f"exit code {proc.returncode}")
    finally:
        result_path.unlink(missing_ok=True)
    if payload.get("ok"):
        return payload["result"]
    err = payload.get("error") or {}
    raise _OcrWorkerFailed(err.get("code", "ocr_failed"),
                           err.get("message", "OCR failed."),
                           err.get("detail"), status=err.get("status", 503))


def run_process_job(settings: Settings, manager: JobManager, job_id: str,
                    upload_path, body: dict) -> None:
    """The worker body: OCR, then translation, driving the state
    machine. Runs on the bounded executor, never in a request."""
    from app.core.errors import AppError as _AppError
    from app.services.translation.service import translate_passage as do_translate_passage

    timings: dict = {}
    started = time.monotonic()
    try:
        update_job(settings, manager, job_id, status="running_ocr", stage="ocr")
        touch_heartbeat(settings, manager, job_id)
        try:
            result = _run_ocr_with_deadline(settings, manager, job_id,
                                            upload_path, body, started)
        except _OcrWorkerFailed as e:
            if e.code == "cancelled":
                update_job(settings, manager, job_id, status="cancelled",
                           stage="cancelled",
                           error="cancelled by request during OCR", timings=timings)
                _record_history(settings, job_id, body, "cancelled")
                return
            update_job(settings, manager, job_id, status="failed", stage="ocr",
                       error=f"{e.code}: {e.message} {e.detail or ''}".strip(),
                       timings=timings)
            _record_history(settings, job_id, body, "failed")
            return
        timings.update(result.get("stage_timings_ms", {}))
        if cancel_requested(settings, manager, job_id):
            update_job(settings, manager, job_id, status="cancelled", stage="cancelled",
                       error="cancelled by request before translation", timings=timings)
            _record_history(settings, job_id, body, "cancelled")
            return
        update_job(settings, manager, job_id, status="running_translation",
                   stage="translation")
        touch_heartbeat(settings, manager, job_id)
        translation_payload = None
        translation_error = None
        status = "completed"
        try:
            translation_payload = do_translate_passage(
                result["original_ocr_text"], settings, body.get("language_profile"),
                context={"ocr_mean_confidence": result.get("mean_confidence")})
            for k, v in translation_payload.get("stage_timings_ms", {}).items():
                timings[k] = timings.get(k, 0) + v
            pstatus = translation_payload.get("passage_status", "completed")
            if pstatus == "partial":
                status = "partial"
            elif pstatus == "failed":
                # AHAIET-010: all-segments-failed is a terminal failure,
                # never a lingering non-terminal status.
                status = "failed"
                translation_error = "Translation failed for every segment of the passage."
            else:
                status = "completed"
        except _AppError as e:
            translation_error = f"{e.code}: {e.message} {e.detail or ''}".strip()
            status = "failed"
        if cancel_requested(settings, manager, job_id):
            status = "cancelled"
            translation_error = translation_error or "cancelled by request"
        payload = {"ocr": result, "translation": translation_payload,
                   "translation_error": translation_error}
        update_job(settings, manager, job_id, status=status, stage="done",
                   error=translation_error, result=payload, timings=timings)
        _record_history(settings, job_id, body, status)
    except Exception as e:  # the worker must always reach a terminal state
        update_job(settings, manager, job_id, status="failed", stage="failed",
                   error=f"internal_error: {type(e).__name__}", timings=timings)


def _record_history(settings: Settings, job_id: str, body: dict, status: str) -> None:
    """History metadata rows only (ids, profile, status) — never text.
    Governed by history_enabled alone; with persist_results=False no
    rows are written at all (AHAIET-015)."""
    if not settings.history_enabled or not settings.persist_results:
        return
    conn = store.connect(settings.db_path)
    try:
        conn.execute("INSERT INTO history(upload_id,language_profile,status,detail) VALUES (?,?,?,?)",
                     (body.get("upload_id"), body.get("language_profile"), status, None))
        conn.commit()
    finally:
        conn.close()
