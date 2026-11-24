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
- Startup recovery: jobs left in a non-terminal state by a previous
  process are marked failed with reason worker_restarted
  (recover_orphaned_jobs, called from app startup).
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
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from app.core.config import Settings
from app.core.errors import AppError
from app.storage import db as store

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
        self.executor = ThreadPoolExecutor(max_workers=max(1, settings.job_workers),
                                           thread_name_prefix="ahaiet-job")
        self._pending = threading.BoundedSemaphore(
            max(1, settings.job_workers) * 4)
        self._ephemeral: dict[str, dict] = {}
        self._ephemeral_lock = threading.Lock()

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
    if not settings.persist_results:
        record = {"id": job_id, "upload_id": upload_id,
                  "language_profile": language_profile, "status": "queued",
                  "stage": "queued", "error": None, "result": None,
                  "stage_timings_ms": {}, "cancel_requested": False,
                  "expires_at_epoch": time.time() + settings.job_result_ttl_s}
        manager.ephemeral_put(job_id, record)
        return record
    conn = store.connect(settings.db_path)
    try:
        conn.execute(
            "INSERT INTO jobs(id,upload_id,language_profile,status,stage,expires_at) "
            "VALUES (?,?,?,?,?,?)",
            (job_id, upload_id, language_profile, "queued", "queued", _expires_at(settings)))
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
    """Startup recovery (AHAIET-009): jobs a previous process left in
    a non-terminal state can never finish — mark them failed with the
    reason worker_restarted. Returns the number recovered."""
    if not settings.persist_results:
        return 0
    conn = store.connect(settings.db_path)
    try:
        placeholders = ",".join("?" for _ in NON_TERMINAL)
        cur = conn.execute(
            f"UPDATE jobs SET status='failed', stage='failed', "
            f"error='worker_restarted: the worker process restarted while this job was "
            f"in progress; resubmit the job.', updated_at=datetime('now') "
            f"WHERE status IN ({placeholders})", NON_TERMINAL)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def run_process_job(settings: Settings, manager: JobManager, job_id: str,
                    upload_path, body: dict) -> None:
    """The worker body: OCR, then translation, driving the state
    machine. Runs on the bounded executor, never in a request."""
    from app.core.errors import AppError as _AppError
    from app.services.ocr.service import run_ocr
    from app.services.translation.service import translate_passage as do_translate_passage

    timings: dict = {}
    try:
        update_job(settings, manager, job_id, status="running_ocr", stage="ocr")
        try:
            result = run_ocr(upload_path, settings, body.get("language_profile"),
                             body.get("preprocessing_profile") or "conservative",
                             body.get("psm"), engine=body.get("engine") or "auto",
                             script_profile=body.get("script_profile") or "hebrew_square")
        except _AppError as e:
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
